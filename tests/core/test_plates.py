"""Unit tests for :mod:`tricca_autopipette.core.plates`.

Covers ``PlateFactory.type_name_for`` -- the inverse of ``create()``, added to
fix a real round-trip bug: ``LocationManager.save_to_json`` used to derive the
saved "type" string from ``location.__class__.__name__.lower()`` (e.g.
"platearray" for a ``PlateArray``), which never matches a registered plate-type
key ("array"), so ``load_from_json`` could never load a plate ``save_to_json``
had just written.

Also covers configurable traversal order, well masks, exhaustion policy, and
the per-position tip presence map on ``TipBox``.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.plates import (
    InvalidPlateTypeError,
    Plate,
    PlateArray,
    PlateExhaustedError,
    PlateFactory,
    PlateParams,
    PlateSingleton,
    TipBox,
)
from tricca_autopipette.core.traversal import TraversalOrder, WellMask
from tricca_autopipette.core.well import StrategyType, Well

ROWS = 8
COLS = 12


def _well(x: float = 1.0) -> Well:
    return Well(
        coor=Coordinate(x=x, y=2.0, z=3.0),
        dip_top=5.0,
        strategy_type=StrategyType.SIMPLE,
    )


def _params(plate_type: str = "array", **kwargs: object) -> PlateParams:
    """Build plate params for a full-size plate, overriding fields as needed.

    `PlateArray._gen_wells` lays columns out in *decreasing* x, and
    `Coordinate` rejects negative values, so the template well starts far
    enough right that a 12-column plate at 9 mm pitch stays on the bed.

    Returns:
        A `PlateParams` for a full `ROWS` x `COLS` plate, with `kwargs`
        overriding any field.
    """
    base: dict[str, object] = {
        "plate_type": plate_type,
        "well_template": _well(x=150.0),
        "num_row": ROWS,
        "num_col": COLS,
        "spacing_row": 9.0,
        "spacing_col": 9.0,
    }
    base.update(kwargs)
    return PlateParams(**base)  # pyright: ignore[reportArgumentType]


# ==================== Factory round-trip ====================


@pytest.mark.parametrize(
    "plate_type", ["array", "singleton", "tipbox", "waste_container"]
)
def test_type_name_for_round_trips_every_registered_type(plate_type: str) -> None:
    params = PlateParams(plate_type=plate_type, well_template=_well())
    plate = PlateFactory.create(params)

    assert PlateFactory.type_name_for(plate) == plate_type


def test_type_name_for_unregistered_type_raises() -> None:
    class NotAPlate:
        pass

    with pytest.raises(InvalidPlateTypeError):
        PlateFactory.type_name_for(NotAPlate())  # type: ignore[arg-type]


# ==================== Traversal order ====================


class TestPlateOrdering:
    """A plate's visiting sequence, and the defaults that preserve behavior."""

    def test_default_sequence_is_row_major_identity(self) -> None:
        """The guarantee that existing protocols are unaffected."""
        plate = PlateArray(_params())
        assert plate.sequence == list(range(ROWS * COLS))

    def test_default_next_walks_wells_in_order(self) -> None:
        plate = PlateArray(_params())
        assert [plate.next() for _ in range(3)] == [
            plate.wells[i].coor for i in range(3)
        ]

    def test_order_accepts_a_preset_name(self) -> None:
        """Config readability: a name, not four axis fields."""
        plate = PlateArray(_params(order="column_from_bottom_right"))
        assert plate.sequence[:3] == [95, 83, 71]

    def test_order_accepts_an_inline_descriptor(self) -> None:
        plate = PlateArray(_params(order={"major": "column"}))
        assert plate.order == TraversalOrder(major="column")

    def test_unknown_order_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown traversal order"):
            _params(order="not_a_real_order")

    def test_next_follows_the_configured_order(self) -> None:
        plate = PlateArray(_params(order="column_from_bottom_right"))
        assert plate.next() == plate.wells[95].coor
        assert plate.next() == plate.wells[83].coor

    def test_current_row_col_track_the_configured_order(self) -> None:
        """`current_*` must describe the well, not the raw cursor."""
        plate = PlateArray(_params(order="column_from_bottom_right"))
        plate.next()  # consume H12; cursor now points at G12
        assert (plate.current_row, plate.current_col) == (6, 11)

    def test_current_row_col_unchanged_for_default_order(self) -> None:
        """The documented examples on `Plate.current_row` still hold."""
        plate = PlateArray(_params())
        plate.curr = 12
        assert (plate.current_row, plate.current_col) == (1, 0)
        plate.curr = 95
        assert (plate.current_row, plate.current_col) == (7, 11)

    def test_get_dip_distance_uses_the_current_well(self) -> None:
        plate = PlateArray(_params(order="column_from_bottom_right"))
        # Well 95 is the first in this order; dip is uniform, but the lookup
        # must not index `wells` with the raw cursor.
        assert plate.get_dip_distance(None) == plate.wells[95].dip_top


# ==================== Masking ====================


class TestPlateMasking:
    """Restricting a plate to a subset of wells."""

    def test_mask_restricts_the_sequence(self) -> None:
        plate = PlateArray(_params(mask=WellMask(include=["A1:D12"])))
        assert plate.sequence == list(range(48))

    def test_mask_preserves_relative_order(self) -> None:
        plate = PlateArray(
            _params(order="column_from_bottom_right", mask=WellMask(include=["A1:D12"]))
        )
        assert plate.sequence[0] == 47  # D12, the first eligible in this order

    def test_next_never_yields_a_masked_well(self) -> None:
        plate = PlateArray(_params(mask=WellMask(exclude=["A1"])))
        visited = {plate.next() for _ in range(ROWS * COLS - 1)}
        assert plate.wells[0].coor not in visited

    def test_noop_mask_leaves_full_sequence(self) -> None:
        plate = PlateArray(_params(mask=WellMask()))
        assert plate.sequence == list(range(ROWS * COLS))

    def test_mask_excluding_everything_raises(self) -> None:
        """A plate that can never yield a well is a config error."""
        with pytest.raises(ValueError, match="excludes every well"):
            PlateArray(_params(mask=WellMask(exclude=["A1:H12"])))


# ==================== Exhaustion ====================


class TestExhaustionPolicy:
    """What happens after every eligible well has been visited."""

    def test_arrays_wrap_by_default(self) -> None:
        """Preserves the historical modulo behavior for sample plates."""
        plate = PlateArray(_params(num_row=1, num_col=3))
        coords = [plate.next() for _ in range(4)]
        assert coords[3] == coords[0]

    def test_wrapping_plate_never_parks_past_the_end(self) -> None:
        plate = PlateArray(_params(num_row=1, num_col=3))
        for _ in range(3):
            plate.next()
        assert plate.curr == 0

    def test_error_policy_raises_when_exhausted(self) -> None:
        plate = PlateArray(_params(num_row=1, num_col=3, on_exhaust="error"))
        for _ in range(3):
            plate.next()
        with pytest.raises(PlateExhaustedError, match="All 3 well"):
            plate.next()

    def test_reset_rewinds(self) -> None:
        plate = PlateArray(_params(num_row=1, num_col=3, on_exhaust="error"))
        for _ in range(3):
            plate.next()
        plate.reset()
        assert plate.next() == plate.wells[0].coor

    def test_singleton_never_exhausts(self) -> None:
        """A reagent bottle has one access point and is reused indefinitely."""
        plate = PlateSingleton(_params("singleton"))
        assert [plate.next() for _ in range(5)] == [plate.wells[0].coor] * 5


# ==================== TipBox presence ====================


class TestTipBoxPresence:
    """Per-position tip tracking, the reason boxes are no longer merged."""

    def test_starts_full(self) -> None:
        box = TipBox(_params("tipbox"))
        assert box.remaining == box.capacity == ROWS * COLS
        assert all(box.present)

    def test_forces_error_on_exhaust(self) -> None:
        """Wrapping would hand back a used tip, so the box overrides it."""
        box = TipBox(_params("tipbox", on_exhaust="wrap"))
        assert box.on_exhaust == "error"

    def test_take_tip_consumes_a_position(self) -> None:
        box = TipBox(_params("tipbox"))
        index, coor = box.take_tip()
        assert index == 0
        assert coor == box.wells[0].coor
        assert box.present[0] is False
        assert box.remaining == ROWS * COLS - 1

    def test_take_tip_follows_the_configured_order(self) -> None:
        box = TipBox(_params("tipbox", order="column_from_bottom_right"))
        assert [box.take_tip()[0] for _ in range(3)] == [95, 83, 71]

    def test_exhaustion_raises_rather_than_reusing(self) -> None:
        """The core safety property: tip 4 of a 3-tip box is an error."""
        box = TipBox(_params("tipbox", num_row=1, num_col=3))
        for _ in range(3):
            box.take_tip()
        assert box.remaining == 0
        with pytest.raises(PlateExhaustedError):
            box.take_tip()

    def test_take_tip_skips_absent_positions(self) -> None:
        box = TipBox(_params("tipbox"))
        box.set_presence([False] * 12 + [True] * (ROWS * COLS - 12))
        assert box.take_tip()[0] == 12

    def test_peek_does_not_consume(self) -> None:
        box = TipBox(_params("tipbox"))
        assert box.peek_tip() == 0
        assert box.remaining == ROWS * COLS

    def test_peek_returns_none_when_empty(self) -> None:
        box = TipBox(_params("tipbox", num_row=1, num_col=1))
        box.take_tip()
        assert box.peek_tip() is None

    def test_reset_tips_refills(self) -> None:
        box = TipBox(_params("tipbox", num_row=1, num_col=3))
        for _ in range(3):
            box.take_tip()
        box.reset_tips()
        assert box.remaining == 3
        assert box.take_tip()[0] == 0

    def test_set_presence_rewinds_cursor(self) -> None:
        """Restoring state must re-scan, not resume from a stale cursor."""
        box = TipBox(_params("tipbox"))
        box.take_tip()
        box.set_presence([True] * (ROWS * COLS))
        assert box.take_tip()[0] == 0

    def test_set_presence_rejects_wrong_length(self) -> None:
        """A mismatched map would misalign consumed positions onto real tips."""
        box = TipBox(_params("tipbox"))
        with pytest.raises(ValueError, match="has 5 entries"):
            box.set_presence([True] * 5)

    def test_consumed_indices_reports_used_positions(self) -> None:
        box = TipBox(_params("tipbox", order="column_from_bottom_right"))
        box.take_tip()
        box.take_tip()
        assert box.consumed_indices() == {95, 83}

    def test_consumed_indices_ignores_masked_positions(self) -> None:
        """Masked positions were never available, so they are not 'consumed'."""
        box = TipBox(_params("tipbox", mask=WellMask(include=["A1:A12"])))
        box.take_tip()
        assert box.consumed_indices() == {0}

    def test_masked_box_capacity_matches_mask(self) -> None:
        box = TipBox(_params("tipbox", mask=WellMask(include=["A1:A12"])))
        assert box.capacity == 12
        assert box.remaining == 12

    def test_boxes_are_independent(self) -> None:
        """The whole point of dropping append_box."""
        first = TipBox(_params("tipbox"))
        second = TipBox(_params("tipbox"))
        first.take_tip()
        assert second.remaining == ROWS * COLS
        assert second.present[0] is True

    def test_append_box_is_gone(self) -> None:
        """Merging boxes destroyed per-box provenance; it must stay removed."""
        assert not hasattr(TipBox(_params("tipbox")), "append_box")


def test_plate_is_abstract() -> None:
    """Plate stays abstract so every subclass defines its own traversal."""
    with pytest.raises(TypeError):
        Plate(_params())  # type: ignore[abstract]


# ==================== PlateParams validation ====================


class TestPlateParamsValidation:
    def test_unregistered_plate_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid plate type"):
            PlateParams(plate_type="not_a_real_type", well_template=_well())

    def test_explicit_none_order_resolves_to_row_major(self) -> None:
        params = PlateParams(
            plate_type="array",
            well_template=_well(),
            order=None,  # pyright: ignore[reportArgumentType]
        )
        assert params.order == TraversalOrder()


# ==================== Plate base-class dunders and helpers ====================


class TestPlateDunders:
    def test_repr(self) -> None:
        plate = PlateArray(_params(num_row=2, num_col=3))
        assert repr(plate) == "PlateArray(rows=2, cols=3, wells=6)"

    def test_iter_yields_wells_in_row_major_order(self) -> None:
        plate = PlateArray(_params(num_row=2, num_col=3))
        assert list(plate) == plate.wells

    def test_getitem_supports_negative_indexing(self) -> None:
        plate = PlateArray(_params(num_row=2, num_col=3))
        assert plate[-1] is plate.wells[-1]
        assert plate[0] is plate.wells[0]


class TestGetWell:
    def test_valid_position_returns_the_well(self) -> None:
        plate = PlateArray(_params(num_row=2, num_col=3))
        assert plate.get_well(1, 2) is plate.wells[1 * 3 + 2]

    def test_out_of_bounds_returns_none(self) -> None:
        plate = PlateArray(_params(num_row=2, num_col=3))
        assert plate.get_well(99, 99) is None


class TestTotalWells:
    def test_matches_well_count(self) -> None:
        plate = PlateArray(_params(num_row=2, num_col=3))
        assert plate.total_wells == 6


class TestGetCoorInvalidPosition:
    def test_out_of_bounds_raises(self) -> None:
        plate = PlateArray(_params(num_row=2, num_col=3))
        with pytest.raises(ValueError, match="is invalid"):
            plate.get_coor(99, 99)


class TestNextWrapsWhenAlreadyPastTheEnd:
    def test_cursor_manually_advanced_past_the_end_still_wraps(self) -> None:
        """Covers the top-of-`next()` wrap reset, distinct from the

        bottom-of-`next()` reset that ordinarily keeps `curr` from ever
        reaching this state in normal use.
        """
        plate = PlateArray(_params(num_row=2, num_col=3))
        plate.curr = len(plate.sequence)  # simulate an already-past-the-end cursor

        first = plate.wells[plate.sequence[0]].coor

        assert plate.next() == first


# ==================== Plate base-class abstract-method bodies ====================


class _AbstractBodyPlate(Plate):
    """A concrete `Plate` whose `get_coor`/`get_dip_distance`/`next` delegate

    to `super()` rather than overriding fully, so the base class's own (if
    normally unreachable) `NotImplementedError` bodies can be exercised --
    the same pattern `test_well.py` uses for `DipStrategy`. Subclasses `Plate`
    directly (not `PlateArray`) so `super()` resolves to `Plate`'s own
    methods rather than a concrete sibling implementation.
    """

    def _gen_wells(
        self,
        start_coor: Coordinate,
        well_template: Well,
        num_row: int,
        num_col: int,
        spacing_row: float,
        spacing_col: float,
    ) -> list[Well]:
        del start_coor, num_row, num_col, spacing_row, spacing_col
        return [well_template]

    def get_coor(self, row: int, col: int) -> Coordinate:
        return super().get_coor(row, col)  # pyright: ignore[reportAbstractUsage]

    def get_dip_distance(self, vol: float | None) -> float:
        return super().get_dip_distance(vol)  # pyright: ignore[reportAbstractUsage]

    def next(self) -> Coordinate:
        return super().next()  # pyright: ignore[reportAbstractUsage]


class _GenWellsPassThrough(Plate):
    """A minimal `Plate` whose `_gen_wells` delegates to `super()`, so the

    abstract base body raises during construction itself.
    """

    def _gen_wells(
        self,
        start_coor: Coordinate,
        well_template: Well,
        num_row: int,
        num_col: int,
        spacing_row: float,
        spacing_col: float,
    ) -> list[Well]:
        return super()._gen_wells(  # pyright: ignore[reportAbstractUsage]
            start_coor, well_template, num_row, num_col, spacing_row, spacing_col
        )

    def get_coor(self, row: int, col: int) -> Coordinate:
        raise NotImplementedError

    def get_dip_distance(self, vol: float | None) -> float:
        raise NotImplementedError

    def next(self) -> Coordinate:
        raise NotImplementedError


class TestPlateAbstractMethodBodies:
    def test_gen_wells_base_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="_gen_wells"):
            _GenWellsPassThrough(_params(num_row=1, num_col=1))

    def test_get_coor_base_raises(self) -> None:
        plate = _AbstractBodyPlate(_params(num_row=1, num_col=1))
        with pytest.raises(NotImplementedError, match="get_coor"):
            plate.get_coor(0, 0)

    def test_get_dip_distance_base_raises(self) -> None:
        plate = _AbstractBodyPlate(_params(num_row=1, num_col=1))
        with pytest.raises(NotImplementedError, match="get_dip_distance"):
            plate.get_dip_distance(0.0)

    def test_next_base_raises(self) -> None:
        plate = _AbstractBodyPlate(_params(num_row=1, num_col=1))
        with pytest.raises(NotImplementedError, match="next"):
            plate.next()


# ==================== PlateFactory registration/creation edges ====================


class _DummyPlate(PlateArray):
    """A throwaway `Plate` subclass, registered/unregistered per-test below."""


class TestPlateFactoryRegistration:
    def test_duplicate_registration_raises(self) -> None:
        PlateFactory.register("pytest_tmp_dup")(_DummyPlate)
        assert PlateFactory._registry["pytest_tmp_dup"] is _DummyPlate

        try:
            with pytest.raises(ValueError, match="already registered"):
                PlateFactory.register("pytest_tmp_dup")(_DummyPlate)
        finally:
            del PlateFactory._registry["pytest_tmp_dup"]


class TestPlateFactoryCreateUnregistered:
    def test_since_unregistered_type_raises(self) -> None:
        """`PlateParams` normally guarantees a registered type; this covers

        the factory's own defensive check for a type deregistered (or
        mutated past validation) after the params were built.
        """
        params = _params(plate_type="array")
        params.plate_type = "not_a_real_type"  # bypasses validate_plate_type

        with pytest.raises(InvalidPlateTypeError):
            PlateFactory.create(params)

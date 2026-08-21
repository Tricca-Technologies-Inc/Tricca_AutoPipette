"""Unit tests for :mod:`tricca_autopipette.core.tipbox_manager`.

The behavior under test here was impossible before: ``TipBox.append_box`` used
to splice extra boxes' well lists into the first box, so there was no way to
count, reset, unload, or persist any single box. Tests that assert boxes stay
independent are guarding against a regression to that design.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_exceptions import (
    NotALocationError,
    NoTipboxError,
    OutOfTipsError,
)
from tricca_autopipette.core.plates import PlateParams, TipBox
from tricca_autopipette.core.tipbox_manager import TipBoxManager
from tricca_autopipette.core.well import StrategyType, Well


def _box(rows: int = 1, cols: int = 3, y: float = 2.0, **kwargs: object) -> TipBox:
    """Build a small tipbox.

    Columns advance in *decreasing* x and `Coordinate` rejects negatives, so
    the template starts far enough right to keep every well on the bed. `y`
    separates boxes that would otherwise sit on top of each other.

    Returns:
        A `TipBox` of `rows` x `cols` tips.
    """
    params: dict[str, object] = {
        "plate_type": "tipbox",
        "well_template": Well(
            coor=Coordinate(x=150.0, y=y, z=3.0),
            dip_top=5.0,
            strategy_type=StrategyType.SIMPLE,
        ),
        "num_row": rows,
        "num_col": cols,
        "spacing_row": 9.0,
        "spacing_col": 9.0,
    }
    params.update(kwargs)
    return TipBox(PlateParams(**params))  # pyright: ignore[reportArgumentType]


@pytest.fixture
def manager() -> TipBoxManager:
    """A manager with two independent 3-tip boxes, a drawn before b.

    The boxes sit at different y so their wells are physically distinct, as
    two real boxes on a deck would be.

    Returns:
        A `TipBoxManager` with boxes `"tips_a"` and `"tips_b"` registered.
    """
    mgr = TipBoxManager()
    mgr.register("tips_a", _box(y=2.0))
    mgr.register("tips_b", _box(y=100.0))
    return mgr


# ==================== Registration ====================


class TestRegistration:
    def test_starts_empty(self) -> None:
        mgr = TipBoxManager()
        assert not mgr.has_boxes()
        assert mgr.names() == []

    def test_draw_order_is_registration_order(self, manager: TipBoxManager) -> None:
        """Config file order decides which box drains first."""
        assert manager.names() == ["tips_a", "tips_b"]

    def test_unregister_removes_one_box(self, manager: TipBoxManager) -> None:
        assert manager.unregister("tips_a") is True
        assert manager.names() == ["tips_b"]

    def test_unregister_unknown_is_false(self, manager: TipBoxManager) -> None:
        assert manager.unregister("nope") is False

    def test_replacing_keeps_position_in_draw_order(
        self, manager: TipBoxManager
    ) -> None:
        """Editing a box's coordinates must not change which drains first."""
        manager.register("tips_a", _box())
        assert manager.names() == ["tips_a", "tips_b"]

    def test_replacing_resets_consumption(self, manager: TipBoxManager) -> None:
        """A re-registered box is a physically different box."""
        manager.next_tip()
        manager.register("tips_a", _box())
        assert manager.remaining == 6

    def test_clear_removes_everything(self, manager: TipBoxManager) -> None:
        manager.clear()
        assert not manager.has_boxes()


# ==================== Drawing ====================


class TestDrawing:
    def test_counts_span_all_boxes(self, manager: TipBoxManager) -> None:
        assert manager.capacity == 6
        assert manager.remaining == 6

    def test_draws_from_the_first_box_first(self, manager: TipBoxManager) -> None:
        name, _box_out, _coor = manager.next_tip()
        assert name == "tips_a"

    def test_exhausts_a_box_before_moving_on(self, manager: TipBoxManager) -> None:
        drawn = [manager.next_tip()[0] for _ in range(6)]
        assert drawn == ["tips_a"] * 3 + ["tips_b"] * 3

    def test_returns_the_supplying_box(self, manager: TipBoxManager) -> None:
        """Boxes may sit at different heights, so dip depth is per-box."""
        for _ in range(3):
            manager.next_tip()
        name, box, _coor = manager.next_tip()
        assert name == "tips_b"
        assert box is manager.boxes["tips_b"]

    def test_coordinates_come_from_the_right_box(self) -> None:
        mgr = TipBoxManager()
        first = _box(cols=1)
        second = _box(cols=1)
        second.wells[0].coor = Coordinate(x=50.0, y=60.0, z=70.0)
        mgr.register("a", first)
        mgr.register("b", second)

        mgr.next_tip()
        _name, _box_out, coor = mgr.next_tip()
        assert coor == Coordinate(x=50.0, y=60.0, z=70.0)

    def test_no_boxes_raises_no_tipbox(self) -> None:
        with pytest.raises(NoTipboxError):
            TipBoxManager().next_tip()

    def test_exhaustion_raises_rather_than_reusing(
        self, manager: TipBoxManager
    ) -> None:
        """The core safety property: no tip is ever handed out twice."""
        for _ in range(6):
            manager.next_tip()
        with pytest.raises(OutOfTipsError) as excinfo:
            manager.next_tip()
        assert excinfo.value.boxes == ["tips_a", "tips_b"]

    def test_every_drawn_coordinate_is_distinct(self, manager: TipBoxManager) -> None:
        coords = [manager.next_tip()[2] for _ in range(6)]
        assert len({(c.x, c.y, c.z) for c in coords}) == 6

    def test_peek_does_not_consume(self, manager: TipBoxManager) -> None:
        assert manager.peek_tip() == ("tips_a", 0)
        assert manager.remaining == 6

    def test_peek_returns_none_when_exhausted(self, manager: TipBoxManager) -> None:
        for _ in range(6):
            manager.next_tip()
        assert manager.peek_tip() is None

    def test_per_box_order_is_respected(self) -> None:
        """Each box may be consumed in its own pattern."""
        mgr = TipBoxManager()
        mgr.register("a", _box(rows=2, cols=2, order="column_major"))
        assert [mgr.next_tip()[1].present.index(False) for _ in range(1)] == [0]
        # column_major on 2x2 visits 0, 2, 1, 3
        assert mgr.boxes["a"].peek_tip() == 2

    def test_unloading_preserves_other_boxes_state(
        self, manager: TipBoxManager
    ) -> None:
        """Impossible under the old merged-box design."""
        manager.next_tip()  # consume one from tips_a
        manager.unregister("tips_b")
        assert manager.remaining == 2

    def test_next_tip_with_name_draws_from_that_box(
        self, manager: TipBoxManager
    ) -> None:
        """A caller can request a specific box instead of registration order."""
        name, box, _coor = manager.next_tip(name="tips_b")
        assert name == "tips_b"
        assert box is manager.boxes["tips_b"]
        assert manager.boxes["tips_a"].remaining == 3

    def test_next_tip_with_unknown_name_raises(self, manager: TipBoxManager) -> None:
        with pytest.raises(NotALocationError):
            manager.next_tip(name="nope")

    def test_next_tip_with_name_exhausted_raises_out_of_tips(
        self, manager: TipBoxManager
    ) -> None:
        for _ in range(3):
            manager.next_tip(name="tips_a")
        with pytest.raises(OutOfTipsError) as excinfo:
            manager.next_tip(name="tips_a")
        assert excinfo.value.boxes == ["tips_a"]


# ==================== Resetting ====================


class TestResetting:
    def test_reset_one_box(self, manager: TipBoxManager) -> None:
        for _ in range(3):
            manager.next_tip()
        manager.reset_tips("tips_a")
        assert manager.remaining == 6
        assert manager.next_tip()[0] == "tips_a"

    def test_reset_one_box_leaves_others(self, manager: TipBoxManager) -> None:
        for _ in range(4):
            manager.next_tip()  # drains a, takes one from b
        manager.reset_tips("tips_a")
        assert manager.boxes["tips_b"].remaining == 2

    def test_reset_all(self, manager: TipBoxManager) -> None:
        for _ in range(5):
            manager.next_tip()
        manager.reset_all()
        assert manager.remaining == 6

    def test_reset_unknown_box_raises(self, manager: TipBoxManager) -> None:
        with pytest.raises(NotALocationError):
            manager.reset_tips("nope")

    def test_set_consumed_declares_partial_state(self, manager: TipBoxManager) -> None:
        manager.set_consumed("tips_a", {0, 1})
        assert manager.boxes["tips_a"].remaining == 1
        assert manager.next_tip()[2] == manager.boxes["tips_a"].wells[2].coor

    def test_set_consumed_is_absolute_not_additive(
        self, manager: TipBoxManager
    ) -> None:
        """Declaring state replaces it, so it can un-consume too."""
        manager.set_consumed("tips_a", {0, 1, 2})
        manager.set_consumed("tips_a", {0})
        assert manager.boxes["tips_a"].remaining == 2

    def test_set_consumed_rejects_out_of_range(self, manager: TipBoxManager) -> None:
        with pytest.raises(ValueError, match="outside tipbox"):
            manager.set_consumed("tips_a", {99})


# ==================== Persistence ====================


class TestPersistence:
    def test_snapshot_restore_round_trip(self, manager: TipBoxManager) -> None:
        manager.next_tip()
        manager.next_tip()
        saved = manager.snapshot()

        rebuilt = TipBoxManager()
        rebuilt.register("tips_a", _box())
        rebuilt.register("tips_b", _box())
        assert rebuilt.restore(saved) == []
        assert rebuilt.remaining == 4
        # The cursor resumes rather than restarting.
        assert rebuilt.next_tip()[2] == manager.boxes["tips_a"].wells[2].coor

    def test_snapshot_records_dimensions(self, manager: TipBoxManager) -> None:
        record = manager.snapshot()["tips_a"]
        assert record["num_row"] == 1
        assert record["num_col"] == 3

    def test_restore_skips_reshaped_box(self, manager: TipBoxManager) -> None:
        """A reindexed map would send the pipette to an empty position."""
        manager.next_tip()
        saved = manager.snapshot()

        rebuilt = TipBoxManager()
        rebuilt.register("tips_a", _box(rows=2, cols=4))
        assert rebuilt.restore(saved) == ["tips_a"]
        assert rebuilt.boxes["tips_a"].remaining == 8

    def test_restore_ignores_unknown_box_names(self, manager: TipBoxManager) -> None:
        """A stale database entry for a removed box is harmless."""
        assert manager.restore({"long_gone": {"num_row": 1, "num_col": 3}}) == []
        assert manager.remaining == 6

    @pytest.mark.parametrize(
        "record",
        [
            "not-a-dict",
            {"num_row": 1, "num_col": 3},  # no presence map
            {"num_row": 1, "num_col": 3, "present": [True]},  # wrong length
            {"num_row": 1, "num_col": 3, "present": "TTT"},  # wrong type
        ],
    )
    def test_restore_rejects_malformed_records(
        self, manager: TipBoxManager, record: Any
    ) -> None:
        """State comes from an external DB and may predate a config change."""
        assert manager.restore({"tips_a": record}) == ["tips_a"]
        assert manager.boxes["tips_a"].remaining == 3

    def test_restore_warns_about_reshaped_box(
        self, manager: TipBoxManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            manager.restore({"tips_a": {"num_row": 9, "num_col": 9, "present": []}})
        assert "tips_a" in caplog.text

    def test_empty_snapshot_restores_cleanly(self) -> None:
        mgr = TipBoxManager()
        assert mgr.restore({}) == []


# ==================== Reporting ====================


class TestDescribe:
    def test_describe_reports_counts_and_next(self, manager: TipBoxManager) -> None:
        manager.next_tip()
        info = manager.describe("tips_a")

        assert info["name"] == "tips_a"
        assert info["capacity"] == 3
        assert info["remaining"] == 2
        assert info["next_index"] == 1
        assert info["next_well"] == "A2"

    def test_describe_names_a_preset_order(self, manager: TipBoxManager) -> None:
        """A named order round-trips as its name, not four axis fields."""
        assert manager.describe("tips_a")["order"] == "row_major"

    def test_describe_falls_back_to_descriptor(self) -> None:
        mgr = TipBoxManager()
        mgr.register("a", _box(order={"row_dir": "bottom_up", "serpentine": True}))
        assert isinstance(mgr.describe("a")["order"], dict)

    def test_describe_compresses_consumed_ranges(self) -> None:
        mgr = TipBoxManager()
        mgr.register("a", _box(rows=1, cols=12))
        for _ in range(3):
            mgr.next_tip()
        assert mgr.describe("a")["consumed_ranges"] == ["A1:A3"]

    def test_describe_next_is_none_when_empty(self, manager: TipBoxManager) -> None:
        for _ in range(3):
            manager.next_tip()
        info = manager.describe("tips_a")
        assert info["next_index"] is None
        assert info["next_well"] is None

    def test_describe_unknown_raises(self, manager: TipBoxManager) -> None:
        with pytest.raises(NotALocationError):
            manager.describe("nope")

    def test_describe_all_follows_draw_order(self, manager: TipBoxManager) -> None:
        assert [d["name"] for d in manager.describe_all()] == ["tips_a", "tips_b"]

    def test_repr_summarizes_pool(self, manager: TipBoxManager) -> None:
        manager.next_tip()
        assert repr(manager) == "TipBoxManager(boxes=2, remaining=5/6)"

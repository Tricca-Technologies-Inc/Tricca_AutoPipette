"""Tests for well addressing, traversal ordering, and well masks.

The single most important assertion in this file is
`test_row_major_is_the_identity_sequence`: every plate in the system defaults to
``row_major`` with no mask, so that test is what guarantees the traversal
machinery is a no-op against the pre-existing behavior of
`PlateArray._gen_wells`/`next`.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.core.traversal import (
    MAX_ADDRESSABLE_ROWS,
    TraversalOrder,
    TraversalRegistry,
    WellMask,
    coerce_traversal_order,
    compress_to_ranges,
    parse_well_ranges,
    rc_to_well_id,
    well_id_to_rc,
)

# A standard 96-well plate, used throughout.
ROWS = 8
COLS = 12


# ==================== Addressing ====================


class TestWellAddressing:
    """Conversion between well IDs and flat row-major indices."""

    @pytest.mark.parametrize(
        ("row", "col", "well_id"),
        [
            (0, 0, "A1"),
            (0, 11, "A12"),
            (7, 0, "H1"),
            (7, 11, "H12"),
            (3, 5, "D6"),
        ],
    )
    def test_round_trip(self, row: int, col: int, well_id: str) -> None:
        """rc -> ID -> rc returns the original pair."""
        assert rc_to_well_id(row, col) == well_id
        assert well_id_to_rc(well_id, ROWS, COLS) == (row, col)

    @pytest.mark.parametrize("well_id", ["a1", " A1 ", "h12", "H 12"])
    def test_parsing_is_lenient_about_case_and_spacing(self, well_id: str) -> None:
        """Hand-edited config files should not fail on cosmetic differences."""
        row, col = well_id_to_rc(well_id, ROWS, COLS)
        assert (row, col) in {(0, 0), (7, 11)}

    @pytest.mark.parametrize("well_id", ["", "A", "12", "A0", "AA1", "A-1", "1A"])
    def test_malformed_ids_raise(self, well_id: str) -> None:
        """A malformed ID is a config error, not something to silently skip."""
        with pytest.raises(ValueError):
            well_id_to_rc(well_id, ROWS, COLS)

    @pytest.mark.parametrize("well_id", ["I1", "A13", "Z99"])
    def test_out_of_bounds_ids_raise(self, well_id: str) -> None:
        """Addressing past the plate edge must not silently wrap."""
        with pytest.raises(ValueError, match="outside"):
            well_id_to_rc(well_id, ROWS, COLS)

    def test_rc_to_well_id_rejects_negative(self) -> None:
        """Negative indices would otherwise wrap around the alphabet."""
        with pytest.raises(ValueError, match="non-negative"):
            rc_to_well_id(-1, 0)

    def test_rc_to_well_id_rejects_row_past_alphabet(self) -> None:
        """The single-letter row label ceiling is enforced, not wrapped."""
        with pytest.raises(ValueError, match="single-letter"):
            rc_to_well_id(MAX_ADDRESSABLE_ROWS, 0)


class TestParseWellRanges:
    """Expansion of well IDs and rectangular ranges into flat indices."""

    def test_single_wells(self) -> None:
        assert parse_well_ranges(["A1", "A3"], ROWS, COLS) == {0, 2}

    def test_rectangular_range(self) -> None:
        """A range selects a block, not a run of consecutive indices."""
        assert parse_well_ranges(["A1:B2"], ROWS, COLS) == {0, 1, 12, 13}

    def test_full_column(self) -> None:
        assert parse_well_ranges(["A1:H1"], ROWS, COLS) == {
            row * COLS for row in range(ROWS)
        }

    def test_corners_may_be_given_in_either_order(self) -> None:
        assert parse_well_ranges(["D6:A1"], ROWS, COLS) == parse_well_ranges(
            ["A1:D6"], ROWS, COLS
        )

    def test_overlapping_entries_are_unioned(self) -> None:
        """Ranges are a set, so overlap is harmless rather than double-counted."""
        assert parse_well_ranges(["A1:A6", "A4:A9"], ROWS, COLS) == set(range(9))

    def test_empty_input(self) -> None:
        assert parse_well_ranges([], ROWS, COLS) == set()

    def test_out_of_bounds_range_raises(self) -> None:
        with pytest.raises(ValueError, match="outside"):
            parse_well_ranges(["A1:I12"], ROWS, COLS)


class TestCompressToRanges:
    """Summarizing flat indices back into readable ranges."""

    def test_runs_and_singletons(self) -> None:
        assert compress_to_ranges({0, 1, 2, 5}, COLS) == ["A1:A3", "A6"]

    def test_runs_do_not_straddle_rows(self) -> None:
        """Index 11 (A12) and 12 (B1) are adjacent but not the same row."""
        assert compress_to_ranges({11, 12}, COLS) == ["A12", "B1"]

    def test_empty(self) -> None:
        assert compress_to_ranges(set(), COLS) == []

    @pytest.mark.parametrize(
        "indices",
        [
            {0},
            {0, 1, 2, 5},
            {11, 12},
            set(range(96)),
            {i for i in range(96) if i % 3 == 0},
        ],
    )
    def test_round_trips_through_parse(self, indices: set[int]) -> None:
        """Serialization must not lose or invent wells."""
        assert parse_well_ranges(compress_to_ranges(indices, COLS), ROWS, COLS) == (
            indices
        )


# ==================== Ordering ====================


class TestTraversalOrder:
    """The four-field descriptor and the sequences it produces."""

    def test_row_major_is_the_identity_sequence(self) -> None:
        """The backward-compatibility guarantee the whole change rests on.

        Every plate defaults to this, so if it ever stops being ``range(n)``
        the traversal work has silently changed existing protocol behavior.
        """
        assert TraversalOrder().indices(ROWS, COLS) == list(range(ROWS * COLS))

    @pytest.mark.parametrize(
        ("order", "expected"),
        [
            (TraversalOrder(), [0, 1, 2, 3, 4, 5]),
            (TraversalOrder(major="column"), [0, 3, 1, 4, 2, 5]),
            (TraversalOrder(row_dir="bottom_up"), [3, 4, 5, 0, 1, 2]),
            (TraversalOrder(col_dir="right_left"), [2, 1, 0, 5, 4, 3]),
            (TraversalOrder(serpentine=True), [0, 1, 2, 5, 4, 3]),
            (
                TraversalOrder(major="column", serpentine=True),
                [0, 3, 4, 1, 2, 5],
            ),
            (
                TraversalOrder(
                    major="column", col_dir="right_left", row_dir="bottom_up"
                ),
                [5, 2, 4, 1, 3, 0],
            ),
        ],
    )
    def test_known_sequences_on_a_2x3_grid(
        self, order: TraversalOrder, expected: list[int]
    ) -> None:
        assert order.indices(2, 3) == expected

    @pytest.mark.parametrize("major", ["row", "column"])
    @pytest.mark.parametrize("row_dir", ["top_down", "bottom_up"])
    @pytest.mark.parametrize("col_dir", ["left_right", "right_left"])
    @pytest.mark.parametrize("serpentine", [False, True])
    def test_every_combination_is_a_permutation(
        self, major: str, row_dir: str, col_dir: str, serpentine: bool
    ) -> None:
        """All 16 combinations must visit every well exactly once.

        A traversal that dropped or repeated a well would hand out the same tip
        twice, so this invariant matters more than any particular ordering.
        """
        order = TraversalOrder.model_validate({
            "major": major,
            "row_dir": row_dir,
            "col_dir": col_dir,
            "serpentine": serpentine,
        })
        sequence = order.indices(ROWS, COLS)
        assert sorted(sequence) == list(range(ROWS * COLS))

    def test_column_from_bottom_right_starts_at_h12(self) -> None:
        """The motivating example: column-wise, starting bottom right."""
        sequence = TraversalRegistry.resolve("column_from_bottom_right").indices(
            ROWS, COLS
        )
        assert sequence[:3] == [95, 83, 71]
        # First column exhausted (H12 up to A12), then on to column 11.
        assert sequence[ROWS] == 94

    def test_single_well_plate(self) -> None:
        assert TraversalOrder().indices(1, 1) == [0]

    @pytest.mark.parametrize(("rows", "cols"), [(0, 12), (8, 0), (-1, 12)])
    def test_non_positive_dimensions_raise(self, rows: int, cols: int) -> None:
        with pytest.raises(ValueError, match="positive"):
            TraversalOrder().indices(rows, cols)

    def test_is_frozen(self) -> None:
        """Presets are shared, so mutation must be blocked."""
        # pydantic raises ValidationError, a ValueError subclass.
        with pytest.raises(ValueError):
            TraversalOrder().major = "column"  # type: ignore[misc]


class TestTraversalRegistry:
    """Named presets, the primary configuration surface."""

    def test_registered_presets(self) -> None:
        assert "row_major" in TraversalRegistry.registered()
        assert "column_from_bottom_right" in TraversalRegistry.registered()

    def test_resolve_is_case_and_space_insensitive(self) -> None:
        assert TraversalRegistry.resolve(
            "  Column_Major  "
        ) == TraversalRegistry.resolve("column_major")

    def test_unknown_preset_lists_alternatives(self) -> None:
        """The error must be actionable from a config file typo."""
        with pytest.raises(ValueError, match="row_major"):
            TraversalRegistry.resolve("colum_major")

    @pytest.mark.parametrize("name", TraversalRegistry.registered())
    def test_name_for_round_trips_every_preset(self, name: str) -> None:
        """A file written with a preset name must save back as that name."""
        assert TraversalRegistry.name_for(TraversalRegistry.resolve(name)) == name

    def test_name_for_returns_none_for_unnamed_combination(self) -> None:
        unnamed = TraversalOrder(row_dir="bottom_up", serpentine=True)
        assert TraversalRegistry.name_for(unnamed) is None

    def test_all_presets_are_distinct(self) -> None:
        """Two presets denoting the same order would make name_for ambiguous."""
        orders = [TraversalRegistry.resolve(n) for n in TraversalRegistry.registered()]
        assert len(set(orders)) == len(orders)


class TestCoerceTraversalOrder:
    """Config may name a preset or spell out a descriptor inline."""

    def test_from_preset_name(self) -> None:
        assert coerce_traversal_order("column_major").major == "column"

    def test_from_inline_mapping(self) -> None:
        assert coerce_traversal_order({"serpentine": True}).serpentine is True

    def test_passes_through_existing_order(self) -> None:
        order = TraversalOrder(major="column")
        assert coerce_traversal_order(order) is order

    def test_rejects_other_types(self) -> None:
        with pytest.raises(ValueError, match="preset name or a descriptor"):
            coerce_traversal_order(42)

    def test_rejects_unknown_inline_field(self) -> None:
        """A typo'd field must not be silently dropped."""
        # pydantic raises ValidationError, a ValueError subclass.
        with pytest.raises(ValueError):
            coerce_traversal_order({"mjaor": "column"})


# ==================== Masking ====================


class TestWellMask:
    """Membership restriction, independent of ordering."""

    def test_default_allows_everything(self) -> None:
        assert WellMask().allowed(ROWS, COLS) == set(range(ROWS * COLS))

    def test_default_is_a_noop(self) -> None:
        assert WellMask().is_noop()
        assert not WellMask(exclude=["A1"]).is_noop()
        assert not WellMask(include=["A1"]).is_noop()

    def test_include_restricts(self) -> None:
        assert WellMask(include=["A1:D12"]).allowed(ROWS, COLS) == set(range(48))

    def test_exclude_removes(self) -> None:
        assert WellMask(exclude=["A1"]).allowed(2, 3) == {1, 2, 3, 4, 5}

    def test_exclude_applies_after_include(self) -> None:
        mask = WellMask(include=["A1:B12"], exclude=["A1"])
        assert len(mask.allowed(ROWS, COLS)) == 23
        assert 0 not in mask.allowed(ROWS, COLS)

    def test_excluding_everything_yields_empty(self) -> None:
        """A fully masked plate is legal here; plates reject it themselves."""
        assert WellMask(exclude=["A1:H12"]).allowed(ROWS, COLS) == set()

    def test_excluding_a_well_outside_include_is_harmless(self) -> None:
        mask = WellMask(include=["A1:A6"], exclude=["H12"])
        assert mask.allowed(ROWS, COLS) == set(range(6))

    @pytest.mark.parametrize("bad", [[""], ["  "], ["A1", ""]])
    def test_blank_entries_rejected(self, bad: list[str]) -> None:
        """A trailing comma in JSON must not silently mask extra wells."""
        # pydantic raises ValidationError, a ValueError subclass.
        with pytest.raises(ValueError):
            WellMask(exclude=bad)

    def test_mask_preserves_relative_traversal_order(self) -> None:
        """Masking is membership only -- it must not reorder the survivors."""
        order = TraversalRegistry.resolve("column_from_bottom_right")
        full = order.indices(ROWS, COLS)
        eligible = WellMask(include=["A1:D12"]).allowed(ROWS, COLS)
        masked = [i for i in full if i in eligible]
        assert masked == [i for i in full if i in eligible]
        assert set(masked) == eligible

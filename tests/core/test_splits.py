"""Unit tests for the ``pipette --splits`` multi-dispense path.

Split into two halves: ``parse_splits_spec`` is pure string parsing and is
tested directly, while ``AutoPipette.resolve_splits``/``pipette_splits`` are
tested against the real ``pipette_with_plates`` fixture (a 1x4 ``plate_a``, a
1x2 tipbox, and a waste container) so validation runs against a real deck.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_exceptions import (
    NotALocationError,
    NoWasteContainerError,
    VolumeCapacityError,
)
from tricca_autopipette.core.pipette_models import TipState
from tricca_autopipette.core.splits import Split, parse_splits_spec


class TestParseSplitsSpec:
    def test_parses_dest_volume_and_well(self) -> None:
        assert parse_splits_spec("plate_a:12@A1;plate_b:8@C3") == [
            Split(dest="plate_a", vol_ul=12.0, well_id="A1"),
            Split(dest="plate_b", vol_ul=8.0, well_id="C3"),
        ]

    def test_well_id_is_optional(self) -> None:
        assert parse_splits_spec("plate_a:12") == [
            Split(dest="plate_a", vol_ul=12.0, well_id=None)
        ]

    def test_whitespace_and_trailing_separators_are_tolerated(self) -> None:
        assert parse_splits_spec(" plate_a : 12 @ A1 ; ") == [
            Split(dest="plate_a", vol_ul=12.0, well_id="A1")
        ]

    @pytest.mark.parametrize(
        ("spec", "match"),
        [
            ("", "Empty --splits"),
            ("   ", "Empty --splits"),
            ("plate_a", "expected 'DEST:VOL'"),
            (":12@A1", "empty destination"),
            ("plate_a:abc", "is not a number"),
            ("plate_a:0", "greater than zero"),
            ("plate_a:-5", "greater than zero"),
        ],
    )
    def test_malformed_specs_raise(self, spec: str, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            parse_splits_spec(spec)


class TestResolveSplits:
    def test_resolves_well_ids_to_row_and_column(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # plate_a is 1x4, so A1..A4 are the addressable wells.
        resolved = pipette_with_plates.resolve_splits(
            20.0, parse_splits_spec("plate_a:12@A1;plate_a:8@A3")
        )

        assert [(t.row, t.col) for t in resolved] == [(0, 0), (0, 2)]

    def test_omitted_well_defers_to_the_plates_traversal_order(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        resolved = pipette_with_plates.resolve_splits(
            20.0, parse_splits_spec("plate_a:20")
        )

        assert (resolved[0].row, resolved[0].col) == (None, None)

    def test_unknown_destination_raises(self, pipette_with_plates: AutoPipette) -> None:
        with pytest.raises(NotALocationError):
            pipette_with_plates.resolve_splits(20.0, parse_splits_spec("nowhere:20@A1"))

    def test_coordinate_destination_raises(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.location_manager.set_coordinate(
            "home", Coordinate(x=0, y=0, z=0)
        )

        with pytest.raises(ValueError, match="is a coordinate, not a plate"):
            pipette_with_plates.resolve_splits(20.0, parse_splits_spec("home:20"))

    def test_well_outside_the_plate_raises(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # plate_a is 1x4; A9 is off the end of it.
        with pytest.raises(ValueError, match="outside a 1x4 plate"):
            pipette_with_plates.resolve_splits(20.0, parse_splits_spec("plate_a:20@A9"))

    def test_leftover_without_a_waste_container_raises_up_front(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # The whole point of checking here rather than after the last split:
        # discovering this mid-run strands a tip holding liquid.
        pipette_with_plates.location_manager.waste_container = None

        with pytest.raises(NoWasteContainerError):
            pipette_with_plates.resolve_splits(20.0, parse_splits_spec("plate_a:12@A1"))

    def test_volume_beyond_syringe_capacity_raises(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # pipette_splits never chunks -- the whole aspirate has to fit at once.
        with pytest.raises(VolumeCapacityError):
            pipette_with_plates.resolve_splits(
                150.0, parse_splits_spec("plate_a:150@A1")
            )


class TestPipetteSplits:
    def test_one_aspirate_then_a_dispense_per_split(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.state.tip_state = TipState.ATTACHED

        with (
            patch.object(
                pipette_with_plates,
                "aspirate_volume",
                wraps=pipette_with_plates.aspirate_volume,
            ) as spy_aspirate,
            patch.object(
                pipette_with_plates,
                "dispense_to",
                wraps=pipette_with_plates.dispense_to,
            ) as spy_dispense,
        ):
            pipette_with_plates.pipette_splits(
                vol_ul=20.0,
                source="plate_a",
                splits=parse_splits_spec("plate_a:12@A1;plate_a:8@A3"),
                tip_end="keep",
            )

        assert spy_aspirate.call_count == 1
        assert spy_aspirate.call_args.args[0] == pytest.approx(20.0)

        targets = spy_dispense.call_args.args[0]
        dispensed = [t.volume for t in targets]
        wells = [(t.row, t.col) for t in targets]
        assert dispensed == pytest.approx([12.0, 8.0])
        assert wells == [(0, 0), (0, 2)]

    def test_a_bad_spec_emits_no_gcode(self, pipette_with_plates: AutoPipette) -> None:
        pipette_with_plates.state.tip_state = TipState.ATTACHED
        pipette_with_plates.get_gcode()  # drain anything buffered by setup

        with pytest.raises(ValueError, match="outside a 1x4 plate"):
            pipette_with_plates.pipette_splits(
                vol_ul=20.0,
                source="plate_a",
                splits=parse_splits_spec("plate_a:12@A1;plate_a:8@A9"),
                tip_end="keep",
            )

        assert pipette_with_plates.get_gcode() == []

    def test_leftover_empties_to_waste_and_disposes_the_tip(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.state.tip_state = TipState.ATTACHED

        with patch.object(
            pipette_with_plates,
            "empty_tip_to_waste",
            wraps=pipette_with_plates.empty_tip_to_waste,
        ) as spy_waste:
            pipette_with_plates.pipette_splits(
                vol_ul=20.0,
                source="plate_a",
                splits=parse_splits_spec("plate_a:12@A1"),
            )

        assert spy_waste.call_count == 1
        assert pipette_with_plates.state.has_liquid is False
        assert pipette_with_plates.state.tip_state == TipState.DETACHED

    def test_oversubscribed_splits_warn_and_the_last_gets_what_is_left(
        self, pipette_with_plates: AutoPipette, caplog: pytest.LogCaptureFixture
    ) -> None:
        pipette_with_plates.state.tip_state = TipState.ATTACHED

        with (
            caplog.at_level(logging.WARNING),
            patch.object(
                pipette_with_plates,
                "_dispense_one",
                wraps=pipette_with_plates._dispense_one,  # pyright: ignore[reportPrivateUsage]
            ) as spy,
        ):
            pipette_with_plates.pipette_splits(
                vol_ul=20.0,
                source="plate_a",
                splits=parse_splits_spec("plate_a:12@A1;plate_a:15@A2"),
                tip_end="keep",
            )

        assert "more than" in caplog.text
        assert [c.args[1] for c in spy.call_args_list] == pytest.approx([12.0, 8.0])

    def test_fully_consumed_aspirate_disposes_the_tip(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.state.tip_state = TipState.ATTACHED

        pipette_with_plates.pipette_splits(
            vol_ul=20.0,
            source="plate_a",
            splits=parse_splits_spec("plate_a:12@A1;plate_a:8@A3"),
            tip_end="waste",
        )

        assert pipette_with_plates.state.has_liquid is False
        assert pipette_with_plates.state.tip_state == TipState.DETACHED

    def test_picks_up_a_tip_when_none_is_attached(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.state.tip_state = TipState.DETACHED

        pipette_with_plates.pipette_splits(
            vol_ul=20.0,
            source="plate_a",
            splits=parse_splits_spec("plate_a:20@A1"),
            tip_end="keep",
        )

        assert pipette_with_plates.state.tip_state == TipState.ATTACHED

    def test_non_positive_volume_raises(self, pipette_with_plates: AutoPipette) -> None:
        with pytest.raises(ValueError, match="Volume must be positive"):
            pipette_with_plates.pipette_splits(
                vol_ul=0.0,
                source="plate_a",
                splits=parse_splits_spec("plate_a:12@A1"),
            )

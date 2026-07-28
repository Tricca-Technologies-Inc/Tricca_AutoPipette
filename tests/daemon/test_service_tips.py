"""Tests for the tip-inventory commands and the ASCII tip map.

These are the operator's tools for reconciling the daemon's record of which
tip positions are occupied with the physical boxes -- Klipper has no notion of
tip occupancy, so nothing else can correct a drift.
"""

from __future__ import annotations

from typing import Any

import pytest

from tricca_autopipette.cli.report_tables import build_tipbox_map
from tricca_autopipette.commands.tap_cmd_parsers import (
    ResetTipsArgs,
    SetTipsArgs,
    TipsArgs,
)
from tricca_autopipette.core.tipbox_manager import TipBoxManager
from tricca_autopipette.daemon.service import AutoPipetteService


def _manager(service: AutoPipetteService) -> TipBoxManager:
    return service._autopipette.location_manager.tipbox_manager


class TestResetTips:
    def test_resets_one_box(self, service_with_plates: AutoPipetteService) -> None:
        manager = _manager(service_with_plates)
        manager.next_tip()

        result = service_with_plates.reset_tips(ResetTipsArgs(name="tipbox"))

        assert result.ok is True
        assert manager.remaining == manager.capacity

    def test_unknown_box_reports_failure(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        result = service_with_plates.reset_tips(ResetTipsArgs(name="nope"))

        assert result.ok is False
        assert "nope" in result.message

    def test_reset_all(self, service_with_plates: AutoPipetteService) -> None:
        manager = _manager(service_with_plates)
        manager.next_tip()

        result = service_with_plates.reset_tips_all()

        assert result.ok is True
        assert manager.remaining == manager.capacity

    def test_reset_all_without_boxes_reports_failure(
        self, service: AutoPipetteService
    ) -> None:
        result = service.reset_tips_all()

        assert result.ok is False


class TestSetTips:
    def test_declares_consumed_positions(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        manager = _manager(service_with_plates)
        capacity = manager.capacity

        result = service_with_plates.set_tips(SetTipsArgs(name="tipbox", ranges=["A1"]))

        assert result.ok is True
        assert manager.remaining == capacity - 1

    def test_available_inverts_the_selection(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """--available names what remains, not what was used."""
        manager = _manager(service_with_plates)

        result = service_with_plates.set_tips(
            SetTipsArgs(name="tipbox", ranges=["A1"], available=True)
        )

        assert result.ok is True
        assert manager.remaining == 1
        assert manager.peek_tip() == ("tipbox", 0)

    def test_is_absolute_not_additive(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """Declaring state replaces it, so it can restore positions too."""
        manager = _manager(service_with_plates)
        capacity = manager.capacity
        service_with_plates.set_tips(SetTipsArgs(name="tipbox", ranges=["A1"]))

        service_with_plates.set_tips(SetTipsArgs(name="tipbox", ranges=[]))

        assert manager.remaining == capacity

    def test_unknown_box_reports_failure(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        result = service_with_plates.set_tips(SetTipsArgs(name="nope", ranges=["A1"]))

        assert result.ok is False

    def test_invalid_range_reports_failure_without_raising(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """A typo'd well must be a message, not a traceback at the prompt."""
        result = service_with_plates.set_tips(
            SetTipsArgs(name="tipbox", ranges=["ZZ99"])
        )

        assert result.ok is False

    def test_out_of_bounds_range_reports_failure(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        result = service_with_plates.set_tips(
            SetTipsArgs(name="tipbox", ranges=["H12"])
        )

        assert result.ok is False


class TestTipsReport:
    def test_reports_all_boxes(self, service_with_plates: AutoPipetteService) -> None:
        result = service_with_plates.tips(TipsArgs())

        assert result.ok is True
        assert result.data is not None
        boxes: list[dict[str, Any]] = result.data["boxes"]
        assert [b["name"] for b in boxes] == ["tipbox"]

    def test_narrows_to_one_box(self, service_with_plates: AutoPipetteService) -> None:
        result = service_with_plates.tips(TipsArgs(name="tipbox"))

        assert result.ok is True
        assert result.data is not None
        assert len(result.data["boxes"]) == 1

    def test_unknown_box_reports_failure(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        result = service_with_plates.tips(TipsArgs(name="nope"))

        assert result.ok is False

    def test_empty_deck_reports_no_boxes(self, service: AutoPipetteService) -> None:
        result = service.tips(TipsArgs())

        assert result.ok is True
        assert result.data is not None
        assert result.data["boxes"] == []

    def test_db_flag_includes_persisted_state(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        result = service_with_plates.tips(TipsArgs(db=True))

        assert result.data is not None
        assert "persisted" in result.data

    def test_db_flag_absent_by_default(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """Avoids a Moonraker round trip on the common path."""
        result = service_with_plates.tips(TipsArgs())

        assert result.data is not None
        assert "persisted" not in result.data


class TestTipMapRendering:
    @pytest.fixture
    def box(self, service_with_plates: AutoPipetteService) -> dict[str, Any]:
        _manager(service_with_plates).next_tip()
        return _manager(service_with_plates).describe("tipbox")

    def test_header_shows_counts_and_order(self, box: dict[str, Any]) -> None:
        header = build_tipbox_map(box).splitlines()[0]

        assert "tipbox" in header
        assert "remaining" in header
        assert "order=" in header

    def test_consumed_positions_are_marked(self, box: dict[str, Any]) -> None:
        rendered = build_tipbox_map(box)

        assert "." in rendered
        assert "O" in rendered

    def test_shows_the_next_position(self, box: dict[str, Any]) -> None:
        assert "next ->" in build_tipbox_map(box)

    def test_row_labels_are_letters(self, box: dict[str, Any]) -> None:
        lines = build_tipbox_map(box).splitlines()
        assert any(line.strip().startswith("A ") for line in lines)

    def test_masked_positions_use_a_distinct_glyph(
        self, service: AutoPipetteService
    ) -> None:
        from tricca_autopipette.core.coordinate import Coordinate
        from tricca_autopipette.core.plates import PlateParams
        from tricca_autopipette.core.traversal import WellMask
        from tricca_autopipette.core.well import StrategyType, Well

        service._autopipette.location_manager.set_plate(
            "masked",
            PlateParams(
                plate_type="tipbox",
                well_template=Well(
                    coor=Coordinate(x=150.0, y=10.0, z=5.0),
                    dip_top=5.0,
                    strategy_type=StrategyType.SIMPLE,
                ),
                num_row=2,
                num_col=4,
                spacing_row=9.0,
                spacing_col=9.0,
                mask=WellMask(include=["A1:A4"]),
            ),
        )

        rendered = build_tipbox_map(_manager(service).describe("masked"))

        assert "x" in rendered
        assert "masked out" in rendered

    def test_drift_against_the_database_is_flagged(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """The 'what it should be updated to' view."""
        manager = _manager(service_with_plates)
        stored = manager.snapshot()["tipbox"]
        manager.next_tip()

        rendered = build_tipbox_map(manager.describe("tipbox"), stored)

        assert "!" in rendered
        assert "differs from database" in rendered

    def test_no_drift_markers_when_states_agree(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        manager = _manager(service_with_plates)
        manager.next_tip()
        stored = manager.snapshot()["tipbox"]

        rendered = build_tipbox_map(manager.describe("tipbox"), stored)

        assert "!" not in rendered

    def test_reshaped_persisted_map_is_not_diffed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """A length mismatch must not raise or misalign the comparison."""
        manager = _manager(service_with_plates)

        rendered = build_tipbox_map(
            manager.describe("tipbox"),
            {"num_row": 99, "num_col": 99, "present": [False] * 3},
        )

        assert "!" not in rendered
        assert "differs from database" not in rendered

    def test_empty_box_says_so(self, service_with_plates: AutoPipetteService) -> None:
        manager = _manager(service_with_plates)
        service_with_plates.set_tips(
            SetTipsArgs(name="tipbox", ranges=[], available=True)
        )

        rendered = build_tipbox_map(manager.describe("tipbox"))

        assert "box empty" in rendered

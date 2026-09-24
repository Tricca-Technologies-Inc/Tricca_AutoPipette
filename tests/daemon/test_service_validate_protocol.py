"""Tests for ``AutoPipetteService.validate_protocol`` (issue #36).

A dry-run replay of a ``.pipette`` file through the exact same per-line
dispatch tables ``_run_protocol_sync`` uses, but wrapped in
``domain_state_snapshot(restore="always")`` (issue #35) for isolation and a
dry-run ``ContextVar`` (see ``test_service_decorators.py`` for the decorator
unit tests) that short-circuits ``require_homed``/``persist_tip_liquid_state``/
``persist_tip_presence``. Unlike a real run, a bad line becomes a recorded
finding instead of aborting the rest of the file -- see
``tests/fixtures/protocols/validate_*.pipette`` for the fixtures exercising
each finding shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.service import AutoPipetteService, CommandResult

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "protocols"


# pyright doesn't model autouse fixtures, so it sees this as never called.
@pytest.fixture(autouse=True)
def _use_fixture_protocols_dir(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", FIXTURES_DIR)


def _findings(result: CommandResult) -> list[dict[str, Any]]:
    """Pull the findings list out of a ``validate_protocol`` result.

    Returns:
        ``result.data["findings"]``, or an empty list if ``data`` is None.
    """
    return result.data["findings"] if result.data else []


class TestFindingsShape:
    def test_returns_command_result_with_findings_list(
        self, service: AutoPipetteService
    ) -> None:
        result = service.validate_protocol("normal.pipette")

        assert result.data is not None
        assert isinstance(result.data["findings"], list)

    def test_clean_file_has_no_findings_and_is_ok(
        self, service: AutoPipetteService
    ) -> None:
        result = service.validate_protocol("normal.pipette")

        assert result.ok is True
        assert result.data == {"findings": []}

    def test_missing_file_raises_file_not_found(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(FileNotFoundError):
            service.validate_protocol("does_not_exist.pipette")


class TestUnhomedMachine:
    def test_gated_commands_run_on_an_unhomed_machine(
        self, service: AutoPipetteService
    ) -> None:
        # `service` starts unhomed (FakeMoonrakerState(homed=False)); a real
        # run of unhomed.pipette raises NotHomedError (see
        # test_service_protocol_run.py) -- validation must not.
        result = service.validate_protocol("unhomed.pipette")

        assert result.ok is True
        assert result.data == {"findings": []}


class TestCatchAndContinue:
    def test_bad_line_becomes_an_error_finding_and_later_lines_still_run(
        self, service: AutoPipetteService
    ) -> None:
        result = service.validate_protocol("validate_missing_location.pipette")

        findings = _findings(result)
        assert len(findings) == 1
        finding = findings[0]
        assert finding["line_number"] == 3
        assert finding["command"] == "move_loc"
        assert finding["severity"] == "error"
        assert "does_not_exist" in finding["message"]
        assert result.ok is False

    def test_unknown_command_is_a_warning_not_an_error(
        self, service: AutoPipetteService
    ) -> None:
        result = service.validate_protocol("validate_unknown_command.pipette")

        findings = _findings(result)
        assert len(findings) == 1
        assert findings[0]["line_number"] == 3
        assert findings[0]["severity"] == "warning"
        assert "Unknown command" in findings[0]["message"]
        # A warning-only file is still reported ok.
        assert result.ok is True


class TestBreakAndSaveLocations:
    def test_break_is_an_info_finding_and_never_blocks(
        self, service: AutoPipetteService
    ) -> None:
        with patch.object(service, "request_breakpoint") as mock_breakpoint:
            result = service.validate_protocol("validate_break_and_save.pipette")

        mock_breakpoint.assert_not_called()
        findings = _findings(result)
        break_findings = [f for f in findings if f["command"] == "break"]
        assert len(break_findings) == 1
        assert break_findings[0]["severity"] == "info"
        assert break_findings[0]["line_number"] == 5

    def test_save_locations_is_skipped_and_writes_no_file(
        self, service: AutoPipetteService, tmp_path: Path
    ) -> None:
        result = service.validate_protocol("validate_break_and_save.pipette")

        findings = _findings(result)
        save_findings = [f for f in findings if f["command"] == "save_locations"]
        assert len(save_findings) == 1
        assert save_findings[0]["severity"] == "info"
        assert not (tmp_path / "validate_scratch.json").exists()


class TestWarningLogCapture:
    def test_shrunk_air_gap_warning_becomes_a_warning_finding(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        result = service_with_plates.validate_protocol(
            "validate_shrunk_air_gap.pipette"
        )

        findings = _findings(result)
        warning_findings = [f for f in findings if f["severity"] == "warning"]
        assert len(warning_findings) == 1
        assert warning_findings[0]["line_number"] == 8
        assert warning_findings[0]["command"] == "aspirate"
        assert "pre_air_gap reduced from 5.0" in warning_findings[0]["message"]
        # The line itself still dispatched successfully -- a warning isn't
        # an error.
        assert result.ok is True


class TestIsolation:
    def test_never_writes_or_uploads_gcode(self, service: AutoPipetteService) -> None:
        gcode_manager = service.gcode_manager
        with (
            patch.object(gcode_manager, "write_gcode_file") as spy_write,
            patch.object(service, "upload_and_execute_gcode") as spy_upload,
        ):
            service.validate_protocol("normal.pipette")

        spy_write.assert_not_called()
        spy_upload.assert_not_called()
        assert gcode_manager.is_batch_mode is False

    def test_never_persists_to_moonraker_db(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        service_with_plates.client = FakeWebSocketClient()  # type: ignore[assignment]
        moonraker_state = service_with_plates.moonraker_state
        assert isinstance(moonraker_state, FakeMoonrakerState)

        service_with_plates.validate_protocol("next_tip_then_switch.pipette")

        assert moonraker_state.saved_states == []
        assert moonraker_state.saved_tip_presence == []

    def test_domain_state_is_rolled_back_after_a_successful_dry_run(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        tipbox_manager = (
            service_with_plates._autopipette.location_manager.tipbox_manager
        )
        location_manager = service_with_plates._autopipette.location_manager
        autopipette = service_with_plates._autopipette
        pre_tip_snapshot = tipbox_manager.snapshot()
        pre_cursors = location_manager.snapshot_cursors()
        pre_tip_state = autopipette.state.tip_state
        pre_has_liquid = autopipette.state.has_liquid
        pre_liquid = autopipette.active_liquid

        service_with_plates.validate_protocol("next_tip_then_switch.pipette")

        assert tipbox_manager.snapshot() == pre_tip_snapshot
        assert location_manager.snapshot_cursors() == pre_cursors
        assert autopipette.state.tip_state == pre_tip_state
        assert autopipette.state.has_liquid == pre_has_liquid
        assert autopipette.active_liquid == pre_liquid

    def test_domain_state_is_rolled_back_even_after_a_compile_time_error(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        tipbox_manager = (
            service_with_plates._autopipette.location_manager.tipbox_manager
        )
        pre_tip_snapshot = tipbox_manager.snapshot()

        service_with_plates.validate_protocol("compile_fail.pipette")

        assert tipbox_manager.snapshot() == pre_tip_snapshot

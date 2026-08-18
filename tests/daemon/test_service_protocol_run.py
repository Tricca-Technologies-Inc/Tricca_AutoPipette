"""Tests for ``AutoPipetteService``'s typed protocol-file dispatch (Phase 2 of

the ports-and-adapters migration -- see CLAUDE.md). Covers the per-line
dispatch table (``_dispatch_protocol_line``) and the full run loop
(``_run_protocol_sync``/``start_run``/``_run_protocol``), using the fixture
``.pipette`` files under ``tests/fixtures/protocols/``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.daemon.service import AutoPipetteService, ProtocolAbortedError

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "protocols"


# pyright doesn't model autouse fixtures, so it sees this as never called.
@pytest.fixture(autouse=True)
def _use_fixture_protocols_dir(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", FIXTURES_DIR)


def _set_homed(service: AutoPipetteService, homed: bool) -> None:
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    service.moonraker_state.set_homed(homed)


class TestDispatchProtocolLine:
    def test_dispatches_a_migrated_command(self, service: AutoPipetteService) -> None:
        _set_homed(service, True)

        result = service._dispatch_protocol_line("move 10 20 5")

        assert result.ok is True

    def test_semicolon_comment_line_falls_back_to_legacy_and_is_a_noop(
        self, service: AutoPipetteService
    ) -> None:
        # cmd2 treats ';' as a statement terminator by default, so lines
        # like "; some note" (used as ad hoc comments in some committed
        # protocols) parse as an empty statement rather than an error --
        # the legacy fallback must preserve that tolerance exactly.
        result = service._dispatch_protocol_line("; a comment-ish line")

        assert result.ok is True

    def test_unrecognized_command_reports_ok_false_without_raising(
        self, service: AutoPipetteService
    ) -> None:
        # Mirrors the "reset 96wellplate" typo present in several real
        # committed protocol files -- "reset" has never been a real
        # command, but the run must not abort because of it (an ok=False
        # result is reported, not an exception).
        result = service._dispatch_protocol_line("reset some_plate")

        assert result.ok is False
        assert "Unknown command" in result.message

    def test_break_continues_when_operator_proceeds(
        self, service: AutoPipetteService
    ) -> None:
        with patch.object(service, "request_breakpoint", return_value=True):
            result = service._dispatch_protocol_line("break")

        assert result.ok is True

    def test_break_raises_protocol_aborted_when_operator_aborts(
        self, service: AutoPipetteService
    ) -> None:
        with (
            patch.object(service, "request_breakpoint", return_value=False),
            pytest.raises(ProtocolAbortedError),
        ):
            service._dispatch_protocol_line("break")


class TestRunProtocolSync:
    def test_successful_run_uploads_combined_gcode(
        self, service: AutoPipetteService
    ) -> None:
        _set_homed(service, True)
        gcode_manager = service.gcode_manager

        with patch.object(
            gcode_manager, "write_gcode_file", wraps=gcode_manager.write_gcode_file
        ) as spy_write:
            service._run_protocol_sync("normal.pipette")

        spy_write.assert_called_once()
        gcode_arg = spy_write.call_args.args[0]
        assert any("G1" in line for line in gcode_arg)  # move_to emits G1
        assert any("G4" in line for line in gcode_arg)  # wait emits a dwell (G4)
        # Regression guard for the GCodeManager.batch_mode() bug fixed
        # alongside this phase: batch mode must be back off afterward, or
        # every subsequent command would silently just buffer forever.
        assert gcode_manager.is_batch_mode is False

    def test_unhomed_gated_command_raises_and_leaves_batch_mode_off(
        self, service: AutoPipetteService
    ) -> None:
        # moonraker_state starts unhomed per the `service` fixture.
        with pytest.raises(NotHomedError, match="not homed"):
            service._run_protocol_sync("unhomed.pipette")

        assert service.gcode_manager.is_batch_mode is False

    def test_break_abort_raises_protocol_aborted(
        self, service: AutoPipetteService
    ) -> None:
        _set_homed(service, True)

        with (
            patch.object(service, "request_breakpoint", return_value=False),
            pytest.raises(ProtocolAbortedError),
        ):
            service._run_protocol_sync("breakpoint.pipette")

    def test_break_continue_runs_remaining_lines(
        self, service: AutoPipetteService
    ) -> None:
        _set_homed(service, True)
        gcode_manager = service.gcode_manager

        with (
            patch.object(service, "request_breakpoint", return_value=True),
            patch.object(
                gcode_manager, "write_gcode_file", wraps=gcode_manager.write_gcode_file
            ) as spy_write,
        ):
            service._run_protocol_sync("breakpoint.pipette")

        gcode_arg = spy_write.call_args.args[0]
        assert any("G4" in line for line in gcode_arg)  # the post-break wait


class TestStartRunAndRunProtocol:
    def test_full_async_flow_reports_error_status_for_unhomed_run(
        self, service: AutoPipetteService
    ) -> None:
        async def _go() -> None:
            await service.start_run("unhomed.pipette")
            for _ in range(200):
                if service.get_status().status != "running":
                    return
                await asyncio.sleep(0.01)
            pytest.fail("run never left 'running' status")

        asyncio.run(_go())

        status = service.get_status()
        assert status.status == "error"
        assert "not homed" in status.message

    def test_missing_protocol_file_raises_file_not_found(
        self, service: AutoPipetteService
    ) -> None:
        async def _go() -> None:
            with pytest.raises(FileNotFoundError):
                await service.start_run("does_not_exist.pipette")

        asyncio.run(_go())


class TestProtocolsAreASharedLocalUnion:
    """``protocols/`` is a union category (issue #68): a local-only file must

    be just as runnable/listable as a shared one, and a same-named local file
    must win over the shared one.
    """

    def test_local_only_protocol_is_listed(
        self, service: AutoPipetteService, tmp_path: Path
    ) -> None:
        (tmp_path / "local_only.pipette").write_text("wait 1\n")
        with patch.object(DefaultPaths, "DIR_LOCAL_PROTOCOL", tmp_path):
            names = {entry["filename"] for entry in service.list_protocols()}

        assert "local_only.pipette" in names
        assert "normal.pipette" in names  # the shared fixture still shows up

    def test_local_only_protocol_is_runnable(
        self, service: AutoPipetteService, tmp_path: Path
    ) -> None:
        _set_homed(service, True)
        (tmp_path / "local_only.pipette").write_text("move 10 20 5\n")

        with patch.object(DefaultPaths, "DIR_LOCAL_PROTOCOL", tmp_path):
            result = service.run_protocol_blocking("local_only.pipette")

        assert result.ok is True

    def test_local_file_with_the_same_name_wins(
        self, service: AutoPipetteService, tmp_path: Path
    ) -> None:
        _set_homed(service, True)
        # The shared "normal.pipette" fixture moves; a same-named local file
        # with different content must be the one actually executed.
        (tmp_path / "normal.pipette").write_text("wait 1\n")

        with (
            patch.object(DefaultPaths, "DIR_LOCAL_PROTOCOL", tmp_path),
            patch.object(service.gcode_manager, "write_gcode_file") as spy_write,
        ):
            service.run_protocol_blocking("normal.pipette")

        gcode_arg = spy_write.call_args.args[0]
        assert not any("G1" in line for line in gcode_arg)  # no move emitted

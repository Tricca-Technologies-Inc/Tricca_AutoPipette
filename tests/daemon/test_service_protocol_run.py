"""Tests for ``AutoPipetteService``'s typed protocol-file dispatch (Phase 2 of

the ports-and-adapters migration -- see CLAUDE.md). Covers the per-line
dispatch table (``_dispatch_protocol_line``) and the full run loop
(``_run_protocol_sync``/``start_run``/``_run_protocol``), using the fixture
``.pipette`` files under ``tests/fixtures/protocols/``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_exceptions import NotALocationError, NotHomedError
from tricca_autopipette.core.pipette_models import TipState
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


class TestDomainStateSnapshotRollback:
    """Issue #35: a compile-time protocol failure must roll the deck model

    back to exactly its pre-run state -- tip presence, traversal cursors, and
    tip/liquid state -- including writing the restored values back through to
    Moonraker's database, since the persist decorators already wrote the
    (now-rolled-back) corrupted values before the failure. A runtime failure
    (after G-code has already uploaded) must NOT roll anything back.
    """

    def test_compile_time_failure_restores_tip_presence_and_cursor(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        tipbox_manager = (
            service_with_plates._autopipette.location_manager.tipbox_manager
        )
        location_manager = service_with_plates._autopipette.location_manager
        pre_run_tip_snapshot = tipbox_manager.snapshot()
        pre_run_cursors = location_manager.snapshot_cursors()

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync("compile_fail.pipette")

        assert tipbox_manager.snapshot() == pre_run_tip_snapshot
        assert location_manager.snapshot_cursors() == pre_run_cursors

    def test_compile_time_failure_restores_pipette_state(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        autopipette = service_with_plates._autopipette
        pre_run_tip_state = autopipette.state.tip_state
        pre_run_has_liquid = autopipette.state.has_liquid
        pre_run_liquid = autopipette.active_liquid

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync("compile_fail.pipette")

        assert autopipette.state.tip_state == pre_run_tip_state
        assert autopipette.state.has_liquid == pre_run_has_liquid
        assert autopipette.active_liquid == pre_run_liquid

    def test_compile_time_failure_makes_no_db_writes(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        # persist_tip_presence/persist_tip_liquid_state defer their DB
        # writes while gcode_manager.is_batch_mode is true, so an aborted
        # batch never wrote anything through in the first place -- there's
        # nothing for a rollback to undo in the database.
        _set_homed(service_with_plates, True)
        moonraker_state = service_with_plates.moonraker_state
        assert isinstance(moonraker_state, FakeMoonrakerState)

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync("compile_fail.pipette")

        assert moonraker_state.saved_tip_presence == []
        assert moonraker_state.saved_states == []

    def test_successful_run_flushes_final_state_exactly_once(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.client = FakeWebSocketClient()  # type: ignore[assignment]
        moonraker_state = service_with_plates.moonraker_state
        assert isinstance(moonraker_state, FakeMoonrakerState)

        # Two lines that each advance tip/liquid state -- if per-line
        # persistence weren't deferred, this would write twice.
        service_with_plates._run_protocol_sync("next_tip_then_switch.pipette")

        assert len(moonraker_state.saved_tip_presence) == 1
        assert len(moonraker_state.saved_states) == 1
        tipbox_manager = (
            service_with_plates._autopipette.location_manager.tipbox_manager
        )
        assert moonraker_state.saved_tip_presence[-1] == tipbox_manager.snapshot()
        assert moonraker_state.saved_states[-1] == (
            TipState.ATTACHED.value,
            False,
            "methanol",
        )

    def test_runtime_failure_after_upload_leaves_state_advanced(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.client = FakeWebSocketClient()  # type: ignore[assignment]
        tipbox_manager = (
            service_with_plates._autopipette.location_manager.tipbox_manager
        )
        pre_run_tip_snapshot = tipbox_manager.snapshot()

        with (
            patch.object(
                service_with_plates,
                "upload_and_execute_gcode",
                side_effect=RuntimeError("moonraker rejected the upload"),
            ),
            pytest.raises(RuntimeError, match="moonraker rejected"),
        ):
            service_with_plates._run_protocol_sync("tip_then_upload_fails.pipette")

        assert tipbox_manager.snapshot() != pre_run_tip_snapshot
        assert service_with_plates._autopipette.state.tip_state == TipState.ATTACHED

    def test_successful_run_leaves_advanced_state_in_place(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.client = FakeWebSocketClient()  # type: ignore[assignment]
        tipbox_manager = (
            service_with_plates._autopipette.location_manager.tipbox_manager
        )
        pre_run_tip_snapshot = tipbox_manager.snapshot()

        service_with_plates._run_protocol_sync("tip_then_upload_fails.pipette")

        assert tipbox_manager.snapshot() != pre_run_tip_snapshot
        assert service_with_plates._autopipette.state.tip_state == TipState.ATTACHED

    def test_restore_failure_does_not_mask_the_original_exception(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        # A failure inside _restore()'s own in-memory restore logic (e.g. a
        # corrupted tipbox record) must not replace the real compile-time
        # error the caller is supposed to see. (DB writes are deferred
        # during batch mode and rollback no longer touches the database at
        # all, so the injection point is the in-memory tipbox restore.)
        _set_homed(service_with_plates, True)
        tipbox_manager = (
            service_with_plates._autopipette.location_manager.tipbox_manager
        )

        with (
            patch.object(
                tipbox_manager,
                "restore",
                side_effect=RuntimeError("corrupted tipbox record"),
            ),
            pytest.raises(NotALocationError),
        ):
            service_with_plates._run_protocol_sync("compile_fail.pipette")

    def test_reconfigured_tipbox_is_fully_restored_to_its_original_object(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        # Full membership restore (issue #36 review) brings back the exact
        # original 1x2 tipbox object -- a same-name reconfiguration mid-run
        # is undone entirely, not merely detected and left as the (wrong)
        # replacement.
        _set_homed(service_with_plates, True)
        location_manager = service_with_plates._autopipette.location_manager
        tipbox_manager = location_manager.tipbox_manager
        original_tipbox = tipbox_manager.boxes["tipbox"]
        assert location_manager.locations_dir is not None
        (location_manager.locations_dir / "reconfigured_tipbox.json").write_text(
            json.dumps({
                "plates": [
                    {
                        "name": "tipbox",
                        "type": "tipbox",
                        "x": 150.0,
                        "y": 20.0,
                        "z": 5.0,
                        "num_row": 1,
                        "num_col": 1,
                        "spacing_col": 9.0,
                        "dip_top": 5.0,
                    }
                ]
            }),
            encoding="utf-8",
        )

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync(
                "rollback_reconfigured_tipbox.pipette"
            )

        assert tipbox_manager.boxes["tipbox"] is original_tipbox
        assert tipbox_manager.boxes["tipbox"].present == [True, True]

    def test_tipbox_registered_mid_run_is_fully_unregistered(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        location_manager = service_with_plates._autopipette.location_manager
        tipbox_manager = location_manager.tipbox_manager
        assert location_manager.locations_dir is not None
        (location_manager.locations_dir / "new_tipbox_b.json").write_text(
            json.dumps({
                "plates": [
                    {
                        "name": "tipbox_b",
                        "type": "tipbox",
                        "x": 250.0,
                        "y": 20.0,
                        "z": 5.0,
                        "num_row": 1,
                        "num_col": 1,
                        "spacing_col": 9.0,
                        "dip_top": 5.0,
                    }
                ]
            }),
            encoding="utf-8",
        )

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync("rollback_new_tipbox.pipette")

        # tipbox_b did not exist when the pre-run snapshot was taken, so
        # rolling back to "exactly its pre-enter snapshot" means it must be
        # gone entirely, not merely reset to full while still registered.
        assert "tipbox_b" not in tipbox_manager.boxes
        assert not location_manager.has_location("tipbox_b")

    def test_plate_reloaded_smaller_mid_run_is_fully_restored_to_its_original_object(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        location_manager = service_with_plates._autopipette.location_manager
        original_plate_a = location_manager.locations["plate_a"]

        # A prior, successful run leaves plate_a's cursor at 2.
        service_with_plates._run_protocol_sync("advance_plate_a.pipette")
        assert location_manager.locations["plate_a"].curr == 2  # type: ignore[union-attr]

        # plate_a is then reloaded with only one well.
        assert location_manager.locations_dir is not None
        (location_manager.locations_dir / "smaller_plate_a.json").write_text(
            json.dumps({
                "plates": [
                    {
                        "name": "plate_a",
                        "type": "array",
                        "x": 150.0,
                        "y": 20.0,
                        "z": 5.0,
                        "num_row": 1,
                        "num_col": 1,
                        "dip_top": 5.0,
                    }
                ]
            }),
            encoding="utf-8",
        )

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync("rollback_smaller_plate.pipette")

        # Full membership restore brings back the exact original (4-well)
        # plate_a object, with its cursor restored to this run's own
        # pre-run value (2, unchanged from before this run started) --
        # not corrupted, and not merely reset to the differently-shaped
        # replacement's own 0.
        assert location_manager.locations["plate_a"] is original_plate_a
        assert location_manager.locations["plate_a"].curr == 2  # type: ignore[union-attr]

    def test_plate_registered_mid_run_is_fully_unregistered(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        location_manager = service_with_plates._autopipette.location_manager
        assert location_manager.locations_dir is not None
        (location_manager.locations_dir / "new_plate_b.json").write_text(
            json.dumps({
                "plates": [
                    {
                        "name": "plate_b",
                        "type": "array",
                        "x": 250.0,
                        "y": 20.0,
                        "z": 5.0,
                        "num_row": 1,
                        "num_col": 4,
                        "dip_top": 5.0,
                    }
                ]
            }),
            encoding="utf-8",
        )

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync("rollback_new_plate.pipette")

        # plate_b did not exist when the pre-run snapshot was taken, so
        # rolling back to "exactly its pre-enter snapshot" means it must be
        # gone entirely.
        assert not location_manager.has_location("plate_b")

    def test_del_loc_is_rolled_back_on_compile_time_failure(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        location_manager = service_with_plates._autopipette.location_manager
        assert location_manager.has_location("waste")

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync("rollback_after_del_loc.pipette")

        assert location_manager.has_location("waste")

    def test_rollback_does_not_leak_gcode_into_the_next_run(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        # switch_liquid buffers a G-code comment ahead of whatever command
        # comes next in the same run. On a compile-time failure nothing
        # physically happened, so neither that comment nor the rollback's
        # own restoring switch_liquid call may survive to prefix a later,
        # unrelated run's uploaded G-code.
        _set_homed(service_with_plates, True)
        autopipette = service_with_plates._autopipette

        with pytest.raises(NotALocationError):
            service_with_plates._run_protocol_sync("switch_liquid_then_fail.pipette")

        assert autopipette.get_gcode() == []


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

"""Cancel while a run is still being prepared (issue #184).

A protocol compiles to G-code before anything moves. A Cancel in that window
has no print for Moonraker to cancel, so tapd itself must make sure the
prepared job never starts, right up to the hand-off to Moonraker.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.service import AutoPipetteService, RunStatus

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "protocols"


# pyright doesn't model autouse fixtures, so it sees this as never called.
@pytest.fixture(autouse=True)
def _use_fixture_protocols_dir(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", FIXTURES_DIR)


@pytest.fixture
def ready(service_with_plates: AutoPipetteService) -> AutoPipetteService:
    assert isinstance(service_with_plates.moonraker_state, FakeMoonrakerState)
    service_with_plates.moonraker_state.set_homed(True)
    service_with_plates.client = FakeWebSocketClient()  # type: ignore[assignment]
    return service_with_plates


async def _wait_until(condition: Any) -> None:
    for _ in range(300):
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition never became true")


def _moonraker_cancels(service: AutoPipetteService) -> list[dict[str, Any]]:
    client = service.client
    assert isinstance(client, FakeWebSocketClient)
    return [r for r in client.sent_requests if r["method"] == "printer.print.cancel"]


def test_cancel_while_preparing_never_starts_the_job(
    ready: AutoPipetteService,
) -> None:
    tipbox_manager = ready._autopipette.location_manager.tipbox_manager
    before = tipbox_manager.snapshot()
    compiling = threading.Event()
    release = threading.Event()
    real_dispatch = ready._dispatch_protocol_line

    def slow_dispatch(line: str) -> Any:
        result = real_dispatch(line)
        compiling.set()
        release.wait(5)
        return result

    async def go() -> None:
        with (
            patch.object(ready, "_dispatch_protocol_line", side_effect=slow_dispatch),
            patch.object(ready, "upload_and_execute_gcode") as upload,
        ):
            await ready.start_run("three_tips.pipette")
            await asyncio.to_thread(compiling.wait, 5)
            await ready.cancel_run()
            release.set()
            await _wait_until(lambda: ready.get_status().status != "running")
            upload.assert_not_called()

    asyncio.run(go())

    status = ready.get_status()
    assert status.status == "error"
    assert status.message == "Protocol cancelled before it started"
    assert _moonraker_cancels(ready) == []
    # Nothing ran, so the tips the compile took are put back.
    assert tipbox_manager.snapshot() == before


def test_cancel_during_the_hand_off_cancels_the_started_print(
    ready: AutoPipetteService,
) -> None:
    uploading = threading.Event()
    release = threading.Event()

    def slow_upload(*_: Any, **__: Any) -> str:
        uploading.set()
        release.wait(5)
        return "gcodes/x.gcode"

    async def go() -> None:
        with patch.object(ready, "upload_and_execute_gcode", side_effect=slow_upload):
            await ready.start_run("normal.pipette")
            await asyncio.to_thread(uploading.wait, 5)
            cancel = asyncio.create_task(ready.cancel_run())
            await asyncio.sleep(0.05)
            # The cancel waits for the upload rather than racing it.
            assert _moonraker_cancels(ready) == []
            release.set()
            await cancel

    asyncio.run(go())

    assert len(_moonraker_cancels(ready)) == 1


def test_cancel_after_the_job_started_goes_to_moonraker(
    ready: AutoPipetteService,
) -> None:
    async def go() -> None:
        with patch.object(ready, "upload_and_execute_gcode") as upload:
            await ready.start_run("normal.pipette")
            await _wait_until(lambda: upload.called)
            await asyncio.sleep(0.05)
            await ready.cancel_run()

    asyncio.run(go())

    assert len(_moonraker_cancels(ready)) == 1


def test_a_new_run_does_not_inherit_a_cancel(ready: AutoPipetteService) -> None:
    ready._cancel_requested = True

    async def go() -> None:
        with patch.object(ready, "upload_and_execute_gcode") as upload:
            await ready.start_run("normal.pipette")
            await _wait_until(lambda: upload.called)

    asyncio.run(go())


class TestStarted:
    def test_a_new_run_has_not_started(self, ready: AutoPipetteService) -> None:
        async def go() -> RunStatus:
            with patch.object(ready, "upload_and_execute_gcode"):
                return await ready.start_run("normal.pipette")

        assert asyncio.run(go()).started is False

    def test_printing_marks_the_run_started(self, service: AutoPipetteService) -> None:
        service._current = RunStatus(status="running", run_id="r1", filename="a")

        asyncio.run(service._apply_print_state_change("printing"))

        assert service.get_status().started is True
        assert service.get_status().to_dict()["started"] is True

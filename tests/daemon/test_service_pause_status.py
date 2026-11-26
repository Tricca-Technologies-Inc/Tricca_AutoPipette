"""Run status while Klipper has the print paused.

A ``break`` or an empty tipbox puts ``M117 <reason>`` then ``PAUSE`` in the
G-code. When Klipper reports ``print_stats.state == "paused"`` the run stays
active (config stays locked) and shows the reason from the display message,
so the kiosk and ``tap`` can offer Resume.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.daemon.service import AutoPipetteService, RunStatus


@pytest.fixture
def pushes(service: AutoPipetteService) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    service.set_broadcast_callback(
        lambda method, params: (
            seen.append(params) if method == "notify_run_status" else None
        )
    )
    return seen


def _running(service: AutoPipetteService) -> None:
    service._current = RunStatus(
        status="running", message="Running a.pipette", run_id="r1", filename="a.pipette"
    )


def test_a_pause_shows_the_reason_and_keeps_the_run_locked(
    service: AutoPipetteService, pushes: list[dict[str, Any]]
) -> None:
    _running(service)

    asyncio.run(service._apply_print_state_change("paused", "Out of tips: reload tb"))

    status = service.get_status()
    assert status.paused is True
    assert status.config_locked is True
    assert status.message == "Paused: Out of tips: reload tb"
    assert pushes[-1]["paused"] is True


def test_a_pause_with_no_message_says_how_to_continue(
    service: AutoPipetteService,
) -> None:
    _running(service)

    asyncio.run(service._apply_print_state_change("paused", ""))

    assert service.get_status().message == "Paused: press Resume to continue"


def test_printing_again_clears_the_pause(service: AutoPipetteService) -> None:
    _running(service)
    asyncio.run(service._apply_print_state_change("paused", "x"))

    asyncio.run(service._apply_print_state_change("printing", ""))

    status = service.get_status()
    assert status.paused is False
    assert status.message == "Running a.pipette"


def test_the_display_message_is_read_for_a_pause(service: AutoPipetteService) -> None:
    state = cast("FakeMoonrakerState", service.moonraker_state)
    state.print_message = "ignored"
    state.display_message = "Protocol break: press Resume to continue"
    seen: list[tuple[str, str]] = []

    async def record(new_state: str, message: str = "") -> None:
        await asyncio.sleep(0)
        seen.append((new_state, message))

    service._apply_print_state_change = record  # type: ignore[method-assign]
    service._loop = asyncio.new_event_loop()
    try:
        service._handle_print_state_change("paused")
        service._loop.run_until_complete(asyncio.sleep(0.05))
    finally:
        service._loop.close()

    assert seen == [("paused", "Protocol break: press Resume to continue")]

"""Real-browser coverage of the Run page's run controls and progress.

While a protocol runs, the Run button becomes Pause (Resume once paused)
beside Cancel, and the page and shows how far through its G-code the print is, from
Klipper's `virtual_sdcard.progress`, with an estimate of the time left.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Dialog, Page, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer

from tricca_autopipette.daemon.service import RunStatus


def _push(
    plane: LiveControlPlane, *, paused: bool = False, progress: float | None = None
) -> None:
    plane.service._current = RunStatus(
        status="running",
        message="Running a.pipette",
        run_id="r1",
        filename="a.pipette",
        paused=paused,
        progress=progress,
    )
    plane.service._broadcast_status()


def test_controls_are_disabled_with_no_run(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)

    expect(page.locator("#runBtn")).to_be_disabled()
    expect(page.locator("#cancelBtn")).to_be_disabled()


def test_pause_then_resume(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    page.goto(live_kiosk_server.url)
    _push(live_control_plane)
    expect(page.locator("#runBtnLabel")).to_have_text("Pause")

    with page.expect_request("**/run/pause"):
        page.click("#runBtn")

    _push(live_control_plane, paused=True)
    expect(page.locator("#runBtnLabel")).to_have_text("Resume")
    with page.expect_request("**/run/resume"):
        page.click("#runBtn")


def test_cancel_asks_first(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    page.goto(live_kiosk_server.url)
    _push(live_control_plane)
    asked: list[str] = []

    def accept(dialog: Dialog) -> None:
        asked.append(dialog.message)
        dialog.accept()

    page.once("dialog", accept)
    with page.expect_request("**/run/cancel"):
        page.click("#cancelBtn")

    assert "not an emergency stop" in asked[0]


def test_progress_shows_percent_and_time_left(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    page.clock.install()
    page.goto(live_kiosk_server.url)
    label = page.locator("#progressLabel")

    _push(live_control_plane, progress=0.1)
    expect(label).to_have_text("10%")

    page.clock.fast_forward(10_000)
    _push(live_control_plane, progress=0.2)

    # 10 s for 10 %, so 80 s for the 80 % left.
    expect(label).to_have_text("20% · ~1m 20s left")
    expect(page.locator("#progressBar")).to_have_attribute("value", "20")


def test_paused_time_is_not_counted(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    page.clock.install()
    page.goto(live_kiosk_server.url)
    label = page.locator("#progressLabel")
    _push(live_control_plane, progress=0.1)
    expect(label).to_have_text("10%")

    _push(live_control_plane, progress=0.1, paused=True)
    expect(page.locator("#runBtnLabel")).to_have_text("Resume")
    page.clock.fast_forward(60_000)
    _push(live_control_plane, progress=0.1)
    expect(page.locator("#runBtnLabel")).to_have_text("Pause")
    page.clock.fast_forward(10_000)
    _push(live_control_plane, progress=0.2)

    expect(label).to_have_text("20% · ~1m 20s left")

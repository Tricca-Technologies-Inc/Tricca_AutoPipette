"""Real-browser coverage of the paused-run banner in `app.js`.

A `break` or an empty tipbox pauses the print in Klipper; the daemon's
`notify_run_status` then carries `paused` and the reason. The banner shows
on every tab and offers Resume and Cancel.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer

from tricca_autopipette.daemon.service import RunStatus

ACTIVE = re.compile(r"\bactive\b")


def _push_paused(plane: LiveControlPlane, message: str) -> None:
    plane.service._current = RunStatus(
        status="running",
        message=message,
        run_id="r1",
        filename="a.pipette",
        paused=True,
    )
    plane.service._broadcast_status()


def test_a_paused_run_shows_the_reason_and_resumes(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    page.goto(live_kiosk_server.url)
    banner = page.locator("#breakpointBanner")
    expect(banner).not_to_have_class(ACTIVE)

    _push_paused(live_control_plane, "Paused: Out of tips: reload tipbox, then Resume")

    expect(banner).to_have_class(ACTIVE)
    expect(page.locator("#breakpointMsg")).to_have_text(
        "Paused: Out of tips: reload tipbox, then Resume"
    )
    with page.expect_request("**/run/resume"):
        page.click("#pauseResumeBtn")


def test_cancel_cancels_the_run(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    page.goto(live_kiosk_server.url)
    _push_paused(live_control_plane, "Paused: press Resume to continue")
    expect(page.locator("#breakpointBanner")).to_have_class(ACTIVE)

    with page.expect_request("**/run/cancel"):
        page.click("#pauseCancelBtn")

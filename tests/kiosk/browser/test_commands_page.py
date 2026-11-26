"""Real-browser coverage of the Commands page (`commands.js`).

The operator types one command, as in `tap` or a protocol file, and the
page shows the daemon's answer. The daemon decides what's allowed; the
page only disables Send while a protocol runs.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer

from tricca_autopipette.daemon.service import RunStatus


def _open(page: Page, url: str) -> None:
    page.goto(url)
    page.click(".tab-btn[data-page=commands]")


def test_a_command_shows_its_result(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open(page, live_kiosk_server.url)

    page.fill("#commandInput", "vol_to_mm 10")
    page.click("#commandSendBtn")

    entry = page.locator(".command-result").first
    expect(entry).to_contain_text("> vol_to_mm 10")
    expect(entry).to_contain_text("mm")
    expect(entry).not_to_have_class("command-result error")


def test_a_refusal_shows_as_an_error(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open(page, live_kiosk_server.url)

    page.fill("#commandInput", "gcode_print hi")
    page.press("#commandInput", "Enter")

    entry = page.locator(".command-result").first
    expect(entry).to_have_class("command-result error")
    expect(entry).to_contain_text("can't be run from the kiosk")


def test_not_homed_shows_the_daemons_reason(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open(page, live_kiosk_server.url)

    page.fill("#commandInput", "move 1 2 3")
    page.click("#commandSendBtn")

    expect(page.locator(".command-result").first).to_contain_text("home")


def test_send_is_disabled_while_a_protocol_runs(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    _open(page, live_kiosk_server.url)
    page.fill("#commandInput", "vol_to_mm 10")
    expect(page.locator("#commandSendBtn")).to_be_enabled()

    live_control_plane.service._current = RunStatus(
        status="running", message="Running a.pipette", filename="a.pipette"
    )
    live_control_plane.service._broadcast_status()

    expect(page.locator("#commandSendBtn")).to_be_disabled()
    expect(page.locator("#commandLock")).to_be_visible()

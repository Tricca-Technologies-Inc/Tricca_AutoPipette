"""Real-browser coverage of `run.js`: protocol list/selection, and the
run-status pipeline it shares with `app.js`'s status pill (ADR-0003 /
issue #78).

The run test below is the other named gap from issue #78 beyond `tips.js`'s
toggle math: "the client-side WebSocket message handling." It drives a real
`/run` POST through the real daemon and checks the real `notify_run_status`
push lands on *both* app.js's shared pill and run.js's own status card --
proof the two independently-subscribed listeners (`App.onStatus`) both
actually receive it, not just one. It stops at "running": nothing in this
fake-Moonraker-backed test setup ever fires a print-completion event (see
`tests/fakes/fake_moonraker_state.py`), so a "done" transition isn't
reachable here yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_kiosk_server import LiveKioskServer


def test_empty_protocol_list_shows_a_placeholder(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    del protocols_dir  # exists (redirected), just empty
    page.goto(live_kiosk_server.url)

    expect(page.locator("#protocolList")).to_contain_text("No .pipette files found")


def test_selecting_a_protocol_enables_run_and_shows_its_name(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
    page.goto(live_kiosk_server.url)
    expect(page.locator(".protocol-item")).to_have_count(1)

    page.click(".protocol-item")

    expect(page.locator("#selectionName")).to_have_text("a")
    expect(page.locator("#runBtn")).to_be_enabled()


def test_running_a_protocol_updates_the_shared_pill_and_the_run_page_card(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
    page.goto(live_kiosk_server.url)
    page.click(".protocol-item")

    page.click("#runBtn")

    # app.js's shared status pill (visible regardless of active tab)...
    expect(page.locator("#statusPillLabel")).to_have_text("Running")
    # ...and run.js's own detailed status card -- both driven by the same
    # real notify_run_status push, relayed over the real /ws/status socket.
    expect(page.locator("#statusState")).to_have_text("Running")
    expect(page.locator("#runBtn")).to_be_disabled()


def test_a_failed_run_shows_the_error_label_and_icon_on_both_widgets(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    # `next_tip` is a homed-gated command (see `require_homed` in
    # daemon/service.py); this fixture's fake Moonraker state starts
    # unhomed, so it raises `NotHomedError` synchronously and the daemon
    # reports the run as "error" without needing a real print-completion
    # event -- the one non-"running" status this fake-backed setup can
    # reach (see this file's module docstring).
    (protocols_dir / "a.pipette").write_text("next_tip\n")
    page.goto(live_kiosk_server.url)
    page.click(".protocol-item")

    page.click("#runBtn")

    expect(page.locator("#statusPillLabel")).to_have_text("Error")
    expect(page.locator("#statusState")).to_have_text("Error")
    expect(page.locator("#statusIcon")).to_have_text("✕")

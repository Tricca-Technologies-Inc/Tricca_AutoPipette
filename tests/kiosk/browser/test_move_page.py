"""Real-browser coverage of `move.js` (issue #86).

Covers the client-side wiring a `TestClient`-based test can't honestly
exercise: real DOM class toggling driven by a real `/ws/status` push (the
not-homed banner, live position fields), and the click -> fetch -> render
round trip for the step selector, D-pad, and named-location dropdown. The
`/move`/`/move_loc`/`/move_rel`/`/locations` routes' own status-code/error
mapping is already covered at the HTTP level in `tests/kiosk/test_move.py`;
this file only adds what a browser is needed to prove.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright")

from fakes.fake_websocket_client import FakeWebSocketClient
from playwright.sync_api import Page, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer

ACTIVE = re.compile(r"\bactive\b")


def test_move_tab_shows_not_homed_banner_by_default(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    # live_control_plane's plain `service` starts unhomed (see
    # tests/conftest.py) -- the banner should reflect that immediately,
    # before any toolhead push has ever arrived.
    page.goto(live_kiosk_server.url)
    page.click('.tab-btn[data-page="move"]')

    expect(page.locator("#moveNotHomedBanner")).to_have_class(ACTIVE)


def test_toolhead_update_hides_banner_and_populates_live_position(
    page: Page,
    live_kiosk_server_with_moonraker: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    assert isinstance(live_control_plane.service.client, FakeWebSocketClient)
    page.goto(live_kiosk_server_with_moonraker.url)
    page.click('.tab-btn[data-page="move"]')
    expect(page.locator("#moveNotHomedBanner")).to_have_class(ACTIVE)

    live_control_plane.service.client.trigger_notification(
        "notify_status_update",
        [{"toolhead": {"position": [12.5, 34.0, 5.25, 0.0], "homed_axes": "xyz"}}, 1.0],
    )

    expect(page.locator("#moveNotHomedBanner")).not_to_have_class(ACTIVE)
    expect(page.locator("#moveXLive")).to_have_text("12.500")
    expect(page.locator("#moveYLive")).to_have_text("34.000")
    expect(page.locator("#moveZLive")).to_have_text("5.250")
    # The (unfocused) editable field is populated from the live push too.
    expect(page.locator("#moveXInput")).to_have_value("12.500")


def test_editing_a_focused_field_is_not_clobbered_by_a_live_update(
    page: Page,
    live_kiosk_server_with_moonraker: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    assert isinstance(live_control_plane.service.client, FakeWebSocketClient)
    page.goto(live_kiosk_server_with_moonraker.url)
    page.click('.tab-btn[data-page="move"]')

    page.click("#moveXInput")
    page.fill("#moveXInput", "99")
    live_control_plane.service.client.trigger_notification(
        "notify_status_update",
        [{"toolhead": {"position": [1.0, 2.0, 3.0, 0.0], "homed_axes": "xyz"}}, 1.0],
    )

    # The live push still updates the small grey read-only label...
    expect(page.locator("#moveXLive")).to_have_text("1.000")
    # ...but leaves the focused, in-progress edit alone.
    expect(page.locator("#moveXInput")).to_have_value("99")


def test_step_selector_is_mutually_exclusive(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)
    page.click('.tab-btn[data-page="move"]')
    expect(page.locator('.step-btn[data-step="1"]')).to_have_class(ACTIVE)

    page.click('.step-btn[data-step="10"]')

    expect(page.locator('.step-btn[data-step="10"]')).to_have_class(ACTIVE)
    expect(page.locator('.step-btn[data-step="1"]')).not_to_have_class(ACTIVE)
    expect(page.locator("#dpadStepLabel")).to_have_text("10 mm")


def test_dpad_click_when_not_homed_shows_the_real_daemon_error(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    # Proves the click -> POST /move_rel -> error-feedback round trip end
    # to end against the real (unhomed) daemon, not a mocked fetch.
    page.goto(live_kiosk_server.url)
    page.click('.tab-btn[data-page="move"]')

    page.click(".dpad-xplus")

    expect(page.locator("#moveJogFeedback")).to_have_class(re.compile(r"\berror\b"))
    expect(page.locator("#moveJogFeedback")).to_contain_text(re.compile(r"home", re.I))


def test_location_dropdown_lists_locations_and_shows_rowcol_for_a_plate(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server_with_plates.url)
    page.click('.tab-btn[data-page="move"]')

    expect(page.locator("#moveLocSelect option")).to_have_count(4)  # placeholder + 3
    expect(page.locator("#moveLocRowCol")).to_be_hidden()

    page.select_option("#moveLocSelect", "tipbox")

    expect(page.locator("#moveLocRowCol")).to_be_visible()

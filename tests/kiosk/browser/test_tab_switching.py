"""Real-browser coverage of `app.js`: the tab switcher and connection
indicator (ADR-0003 / issue #78).

`App.registerPage`/`App.switchTo` is the mechanism every current and future
kiosk page hangs its lifecycle hooks off of -- a regression here (a page
stuck active, or `onShow` never firing on switch) silently breaks every
page, not just one, which is why it gets its own file rather than living
inside `test_run_page.py`/`test_tips_toggle.py`.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_kiosk_server import LiveKioskServer

ACTIVE = re.compile(r"\bactive\b")
LIVE = re.compile(r"\blive\b")


def test_run_tab_is_active_on_load(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    # A full reload always lands on Run, never a persisted tab -- see
    # app.js's `initTabBar` docstring.
    page.goto(live_kiosk_server.url)

    expect(page.locator('.tab-btn[data-page="run"]')).to_have_class(ACTIVE)
    expect(page.locator("#page-run")).to_have_class(ACTIVE)
    expect(page.locator("#page-tips")).not_to_have_class(ACTIVE)


def test_clicking_tips_switches_pages_and_fires_its_onshow(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server_with_plates.url)

    page.click('.tab-btn[data-page="tips"]')

    expect(page.locator('.tab-btn[data-page="tips"]')).to_have_class(ACTIVE)
    expect(page.locator("#page-tips")).to_have_class(ACTIVE)
    expect(page.locator('.tab-btn[data-page="run"]')).not_to_have_class(ACTIVE)
    expect(page.locator("#page-run")).not_to_have_class(ACTIVE)
    # tips.js's onShow (loadTips) actually ran -- a real `GET /tips`
    # rendered the box, not just the tab/page classes flipping.
    expect(page.locator('.tipbox-card[data-box="tipbox"]')).to_be_visible()


def test_clicking_back_to_run_restores_it(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)
    page.click('.tab-btn[data-page="tips"]')

    page.click('.tab-btn[data-page="run"]')

    expect(page.locator("#page-run")).to_have_class(ACTIVE)
    expect(page.locator("#page-tips")).not_to_have_class(ACTIVE)


def test_status_websocket_connects(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)

    expect(page.locator("#connDot")).to_have_class(LIVE)
    expect(page.locator("#connLabel")).to_have_text("live")


def test_losing_the_socket_shows_reconnecting(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    # app.js's onclose handler (connectWS) has never been exercised --
    # killing the real server drops the real socket, the same event a
    # network blip would fire.
    page.goto(live_kiosk_server.url)
    expect(page.locator("#connDot")).to_have_class(LIVE)

    live_kiosk_server.stop()

    expect(page.locator("#connDot")).not_to_have_class(LIVE)
    expect(page.locator("#connLabel")).to_have_text("reconnecting")

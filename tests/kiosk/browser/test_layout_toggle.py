"""Real-browser coverage of `layout.js`: the header's touch/desktop switch.

The kiosk defaults to the 5" touch layout; the switch adds `desktop-mode`
to `<html>` (which `style-desktop.css` keys on) and remembers the choice.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_kiosk_server import LiveKioskServer

DESKTOP = re.compile(r"\bdesktop-mode\b")


def test_touch_is_the_default_and_the_switch_is_remembered(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)
    html = page.locator("html")
    expect(html).not_to_have_class(DESKTOP)

    page.click("#layoutToggleBtn")
    expect(html).to_have_class(DESKTOP)
    expect(page.locator("#layoutToggleLabel")).to_have_text("Touch")

    page.reload()
    expect(html).to_have_class(DESKTOP)

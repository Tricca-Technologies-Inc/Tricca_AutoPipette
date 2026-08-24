"""Opt-in kiosk screenshot capture -- for a Claude session's own visual
review of a UI change (ADR-0003), not an automated test.

Deliberately not named `test_*.py`: it reuses this directory's fixtures
(`live_kiosk_server_with_plates`, `pytest-playwright`'s `page`) but plain
`pytest`'s directory-glob collection never picks it up, so it never runs by
accident. Run it explicitly, naming this file:

    pytest tests/kiosk/browser/capture_screenshot.py \
        --capture-page=tips --capture-out=/tmp/tips.png

`--capture-page` selects an entry from `PAGES` below -- add one there for a
new page/state rather than a new script.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page
from support.live_kiosk_server import LiveKioskServer

PAGES: dict[str, Callable[[Page], None]] = {
    "run": lambda page: None,  # loaded active by default, nothing to do
    "move": lambda page: page.click('.tab-btn[data-page="move"]'),
    "tips": lambda page: page.click('.tab-btn[data-page="tips"]'),
}


def test_capture(
    page: Page,
    live_kiosk_server_with_plates: LiveKioskServer,
    pytestconfig: pytest.Config,
) -> None:
    """Load `--capture-page` and save a full-page screenshot to `--capture-out`.

    Uses `live_kiosk_server_with_plates` (a tipbox/waste/plate wired up)
    regardless of which page is requested, so any page can render its full
    state -- there's no cost to the extra backend data for a page that
    doesn't use it.
    """
    name = pytestconfig.getoption("capture_page")
    if not name:
        pytest.skip("pass --capture-page=<name> to run this (see PAGES)")
    if name not in PAGES:
        pytest.fail(f"Unknown --capture-page {name!r}; choices: {sorted(PAGES)}")

    page.goto(live_kiosk_server_with_plates.url)
    PAGES[name](page)
    page.wait_for_timeout(200)  # let the just-triggered render settle

    out = Path(str(pytestconfig.getoption("capture_out")))
    page.screenshot(path=out, full_page=True)
    print(f"\nSaved {name!r} screenshot to {out}")

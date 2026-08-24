"""Real-browser coverage of `deck.js`: the Deck page's spatial tiles and
tap interactions (issue #87).

Drives the real rendered page against `live_kiosk_server_with_plates`'s
tipbox ("tipbox", 1x2, both positions present by default -- see
`tests/conftest.py`'s `_add_tipbox_waste_and_plate`), waste container
("waste"), and 4-well plate ("plate_a"), the same fixture
`test_tips_toggle.py`/`test_tab_switching.py` already use.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_kiosk_server import LiveKioskServer

ACTIVE = re.compile(r"\bactive\b")
SELECTED = re.compile(r"\bselected\b")


def _goto_deck(page: Page, server: LiveKioskServer) -> None:
    page.goto(server.url)
    page.click('.tab-btn[data-page="deck"]')


def test_every_registered_location_gets_a_tile(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    _goto_deck(page, live_kiosk_server_with_plates)

    expect(page.locator('.deck-tile[data-name="tipbox"]')).to_be_visible()
    expect(page.locator('.deck-tile[data-name="waste"]')).to_be_visible()
    expect(page.locator('.deck-tile[data-name="plate_a"]')).to_be_visible()


def test_a_tile_is_positioned_from_its_real_mm_coordinates(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    # tipbox sits at x=10, y=10 (tests/conftest.py). toPercent's formula
    # (deck.js): leftPct = 100 + x/400*100, topPct = y/400*100.
    _goto_deck(page, live_kiosk_server_with_plates)

    tile = page.locator('.deck-tile[data-name="tipbox"]')
    assert tile.evaluate("el => el.style.left") == "102.5%"
    assert tile.evaluate("el => el.style.top") == "2.5%"


def test_tipbox_tile_embeds_an_occupancy_mini_grid_from_tips_data(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    _goto_deck(page, live_kiosk_server_with_plates)

    grid = page.locator('.deck-tile[data-name="tipbox"] .deck-mini-grid')
    expect(grid.locator(".deck-mini-cell")).to_have_count(2)
    # Both positions present by default (see fixture docstring above).
    expect(grid.locator(".deck-mini-cell.present")).to_have_count(2)


def test_non_tipbox_tiles_have_no_mini_grid(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    _goto_deck(page, live_kiosk_server_with_plates)

    expect(page.locator('.deck-tile[data-name="waste"] .deck-mini-grid')).to_have_count(
        0
    )


def test_tapping_a_tile_shows_its_name_type_and_coordinates(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    _goto_deck(page, live_kiosk_server_with_plates)

    page.click('.deck-tile[data-name="waste"]')

    info = page.locator("#deckInfo")
    expect(info).to_contain_text("waste")
    expect(info).to_contain_text("WasteContainer")
    expect(info).to_contain_text("50")


def test_tapping_a_tile_marks_it_selected(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    _goto_deck(page, live_kiosk_server_with_plates)

    page.click('.deck-tile[data-name="waste"]')

    expect(page.locator('.deck-tile[data-name="waste"]')).to_have_class(SELECTED)
    # Selection is exclusive -- only the tapped tile carries it.
    expect(page.locator('.deck-tile[data-name="tipbox"]')).not_to_have_class(SELECTED)


def test_tapping_a_tipbox_tile_switches_to_the_tips_tab(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    _goto_deck(page, live_kiosk_server_with_plates)

    page.click('.deck-tile[data-name="tipbox"]')

    expect(page.locator('.tab-btn[data-page="tips"]')).to_have_class(ACTIVE)
    expect(page.locator("#page-tips")).to_have_class(ACTIVE)
    expect(page.locator('.tipbox-card[data-box="tipbox"]')).to_be_visible()


def test_tapping_a_non_tipbox_tile_stays_on_the_deck_tab(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    _goto_deck(page, live_kiosk_server_with_plates)

    page.click('.deck-tile[data-name="waste"]')

    expect(page.locator("#page-deck")).to_have_class(ACTIVE)

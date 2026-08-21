"""Real-browser coverage of `tips.js`'s tap-to-toggle math (ADR-0003).

Issue #78 named this the riskiest untested piece: `toggleCell` recomputes a
tipbox's *entire* consumed-well-id set from `present`/`eligible` and posts
it wholesale to `/tips/set` (since `config.set_tips` replaces a box's whole
state, not one cell). A regression here silently misreports or corrupts the
daemon's tip-presence record. This drives a real click against the real
rendered grid and checks the round trip against `GET /tips`, not just the
client-side class toggle -- a client-only assertion could pass while
`toggleCell`'s posted range list was wrong.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_kiosk_server import LiveKioskServer

PRESENT = re.compile(r"\bpresent\b")


def _get_json(url: str) -> Any:
    """GET `url` and parse the JSON body. Stdlib stand-in for `requests.get`.

    Returns:
        The parsed JSON body.
    """
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def test_tapping_a_present_cell_marks_it_consumed_end_to_end(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server_with_plates.url)
    page.click('.tab-btn[data-page="tips"]')

    card = page.locator('.tipbox-card[data-box="tipbox"]')
    cell_a1 = card.locator('.tip-cell[data-index="0"]')
    expect(cell_a1).to_have_class(PRESENT)  # box starts full (see test_main.py)

    cell_a1.click()

    # tips.js's toggleCell always calls loadTips() in a `finally`, which
    # tears down and rebuilds the grid -- re-querying via the locator (not
    # holding the old element handle) is what lets this wait past that
    # rebuild instead of racing it.
    expect(card.locator('.tip-cell[data-index="0"]')).not_to_have_class(PRESENT)
    expect(card.locator('.tip-cell[data-index="1"]')).to_have_class(PRESENT)

    # The client-side class flip alone can't distinguish "toggled the right
    # cell" from "toggled the wrong one and re-rendered anyway" -- confirm
    # against the server's own record, the same `GET /tips` tips.js itself
    # polls after every toggle.
    listing = _get_json(f"{live_kiosk_server_with_plates.url}/tips")
    assert listing["data"]["boxes"][0]["present"] == [False, True]


def test_tapping_again_restores_it(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server_with_plates.url)
    page.click('.tab-btn[data-page="tips"]')
    card = page.locator('.tipbox-card[data-box="tipbox"]')
    cell_a1 = card.locator('.tip-cell[data-index="0"]')

    cell_a1.click()
    expect(card.locator('.tip-cell[data-index="0"]')).not_to_have_class(PRESENT)
    card.locator('.tip-cell[data-index="0"]').click()
    expect(card.locator('.tip-cell[data-index="0"]')).to_have_class(PRESENT)

    listing = _get_json(f"{live_kiosk_server_with_plates.url}/tips")
    assert listing["data"]["boxes"][0]["present"] == [True, True]


def test_a_rejected_set_reverts_the_optimistic_toggle(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    # `toggleCell`'s optimistic update (flip the cell, then POST) has a
    # revert branch for exactly this case -- untested until now, since the
    # two tests above only ever exercise a `/tips/set` that succeeds.
    page.route(
        "**/tips/set",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"ok": false, "message": "rejected", "data": null}',
        ),
    )
    page.goto(live_kiosk_server_with_plates.url)
    page.click('.tab-btn[data-page="tips"]')
    card = page.locator('.tipbox-card[data-box="tipbox"]')
    cell_a1 = card.locator('.tip-cell[data-index="0"]')
    expect(cell_a1).to_have_class(PRESENT)

    cell_a1.click()

    expect(card.locator('.tip-cell[data-index="0"]')).to_have_class(PRESENT)

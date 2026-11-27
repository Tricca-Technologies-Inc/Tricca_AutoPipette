"""Number fields open a number pad on the touchscreen keyboard (issue #237)."""

from __future__ import annotations

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_kiosk_server import LiveKioskServer


def test_every_number_input_asks_for_a_number_pad(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)
    # Settings builds its liquid fields in JS; render them before looking.
    page.click('.tab-btn[data-page="settings"]')
    expect(page.locator(".settings-liquid input").first).to_be_attached()

    modes = page.locator('input[type="number"]').evaluate_all(
        "els => els.map(el => [el.id || el.closest('[data-key]')?.dataset.key,"
        " el.inputMode])"
    )

    assert {"moveXInput", "moveYInput", "moveZInput", "calMassInput"} <= {
        name for name, _ in modes
    }
    assert [m for m in modes if m[1] not in {"decimal", "numeric"}] == []
    # Well row/col are whole numbers.
    assert dict(modes)["moveLocRow"] == "numeric"
    assert dict(modes)["moveLocCol"] == "numeric"

"""Real-browser coverage of `settings.js` (issue #33 slice c, ADR-0003).

Every write lands in a per-test scratch local root, never the session's.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_kiosk_server import LiveKioskServer

from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths


@pytest.fixture
def local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Scratch local roots, with the active system profile copied in.

    Returns:
        The scratch local root.
    """
    local = tmp_path / "local"
    (local / "system").mkdir(parents=True)
    shutil.copy2(
        DefaultPaths.DIR_LOCAL_SYSTEM / DefaultFilenames.CONFIG_SYSTEM,
        local / "system",
    )
    for attr, category in (
        ("DIR_LOCAL_SYSTEM", "system"),
        ("DIR_LOCAL_LIQUIDS", "liquids"),
        ("DIR_LOCAL_PIPETTE", "pipettes"),
        ("DIR_LOCAL_GANTRY", "gantry"),
    ):
        monkeypatch.setattr(DefaultPaths, attr, local / category)
    return local


def _settings(server: LiveKioskServer) -> Any:
    with urllib.request.urlopen(f"{server.url}/settings", timeout=5) as response:
        return json.load(response)["data"]


def _open_settings(page: Page, server: LiveKioskServer) -> None:
    page.goto(server.url)
    page.click('.tab-btn[data-page="settings"]')
    expect(page.locator("#settingsGantry")).to_be_visible()


@pytest.mark.usefixtures("local")
def test_fields_disable_with_the_reason_while_a_run_is_active(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
    _open_settings(page, live_kiosk_server)
    field = page.locator('#settingsGantry [data-key="speed_xy"] input')
    expect(field).to_be_enabled()

    request = urllib.request.Request(
        f"{live_kiosk_server.url}/run",
        data=json.dumps({"filename": "a.pipette"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=5).close()

    expect(page.locator("#settingsLockBanner")).to_be_visible()
    expect(page.locator("#settingsLockBanner")).to_contain_text(
        "Locked while a protocol is running"
    )
    expect(field).to_be_disabled()
    expect(page.locator("#page-settings button:enabled")).to_have_count(0)


def test_an_out_of_bounds_high_risk_value_is_refused(
    page: Page, live_kiosk_server: LiveKioskServer, local: Path
) -> None:
    _open_settings(page, live_kiosk_server)
    row = page.locator('#settingsPipette [data-key="syringe.max_volume_ul"]')

    row.locator("input").fill("5000")
    row.get_by_role("button", name="Save").click()

    expect(row.locator(".move-feedback")).to_contain_text("Out of range")
    expect(row.get_by_role("button", name="Confirm")).to_have_count(0)
    assert not (local / "pipettes").exists()


@pytest.mark.usefixtures("local")
def test_a_high_risk_edit_needs_confirming_then_asks_for_a_home(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)
    row = page.locator('#settingsGantry [data-key="speed_z"]')

    row.locator("input").fill("9000")
    row.get_by_role("button", name="Save").click()
    row.get_by_role("button", name="Confirm").click()

    expect(row.locator(".move-feedback")).to_have_text("Saved.")
    expect(page.locator("#settingsHomeBanner")).to_be_visible()
    gantry = _settings(live_kiosk_server)["gantry"]["fields"]
    assert next(f for f in gantry if f["key"] == "speed_z")["value"] == 9000.0  # ruff:ignore[float-equality-comparison]


@pytest.mark.usefixtures("local")
def test_a_low_risk_liquid_edit_round_trips(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)
    row = page.locator(
        '.settings-liquid[data-liquid="water"] [data-key="viscosity_cP"]'
    )

    row.locator("input").fill("1.7")
    row.locator("input").press("Enter")

    expect(row.locator(".move-feedback")).to_have_text("Saved.")
    water = next(
        r
        for r in _settings(live_kiosk_server)["liquids"]["loaded"]
        if r["name"] == "water"
    )
    viscosity = next(f for f in water["fields"] if f["key"] == "viscosity_cP")
    assert viscosity["value"] == 1.7  # ruff:ignore[float-equality-comparison]

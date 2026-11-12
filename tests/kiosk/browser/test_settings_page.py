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


def test_switch_error_shows_http_failure_detail(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)
    page.route(
        "**/settings/switch_system",
        lambda route: route.fulfill(
            status=500, json={"detail": "Gantry configuration is invalid"}
        ),
    )

    page.locator("#settingsSystem").get_by_role("button", name="Switch").click()

    expect(page.locator("#settingsSystem .move-feedback")).to_have_text(
        "Gantry configuration is invalid"
    )


@pytest.mark.usefixtures("local")
def test_fields_disable_with_the_reason_while_a_run_is_active(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text("break\n")
    _open_settings(page, live_kiosk_server)
    field = page.locator(
        '.settings-liquid[data-liquid="water"] [data-key="viscosity_cP"] input'
    )
    expect(field).to_be_enabled()

    request = urllib.request.Request(
        f"{live_kiosk_server.url}/run",
        data=json.dumps({"filename": "a.pipette"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=5).close()

    try:
        expect(page.locator("#settingsLockBanner")).to_be_visible()
        expect(page.locator("#settingsLockBanner")).to_contain_text(
            "Locked while a protocol is running"
        )
        expect(field).to_be_disabled()
        expect(page.locator("#page-settings button:enabled")).to_have_count(0)
    finally:
        expect(page.locator("#bpAbortBtn")).to_be_visible()
        page.click("#bpAbortBtn")


def test_system_components_are_visible_but_not_independently_editable(
    page: Page, live_kiosk_server: LiveKioskServer, local: Path
) -> None:
    _open_settings(page, live_kiosk_server)
    settings = _settings(live_kiosk_server)
    expect(page.locator("#settingsPipette")).to_contain_text(
        settings["pipette"]["name"]
    )
    max_volume = next(
        f for f in settings["pipette"]["fields"] if f["key"] == "syringe.max_volume_ul"
    )
    expect(
        page.locator('#settingsPipette [data-key="syringe.max_volume_ul"]')
    ).to_contain_text(f"{max_volume['value']:g}")
    expect(page.locator("#settingsGantry")).to_contain_text("speed_xy")
    expect(
        page.locator(
            "#settingsPipette input, #settingsPipette select, #settingsPipette button"
        )
    ).to_have_count(0)
    expect(
        page.locator(
            "#settingsGantry input, #settingsGantry select, #settingsGantry button"
        )
    ).to_have_count(0)
    expect(
        page.locator("#settingsLiquids select, #settingsLiquids button")
    ).to_have_count(0)
    expect(page.locator("#settingsLiquidSelect, #settingsPipetteSelect")).to_have_count(
        0
    )
    expect(page.locator("#settingsSystemSelect")).to_be_enabled()
    assert not (local / "pipettes").exists()


def test_switch_system_updates_read_only_components(
    page: Page, live_kiosk_server: LiveKioskServer, local: Path
) -> None:
    for name in ("Tyson100_system.json", "Tyson_main.json"):
        shutil.copy2(DefaultPaths.DIR_CONFIG_SYSTEM / name, local / "system" / name)
    shutil.copy2(
        DefaultPaths.DIR_CONFIG_LOCATIONS / "Tyson100_locations.json", local.parent
    )
    _open_settings(page, live_kiosk_server)

    page.locator("#settingsSystemSelect").select_option("Tyson100_system.json")
    page.locator("#settingsSystem").get_by_role("button", name="Switch").click()
    expect(page.locator("#settingsPipette")).to_contain_text("TysonP100")
    expect(page.locator('#settingsGantry [data-key="speed_xy"]')).to_contain_text(
        "39000"
    )
    expect(page.locator("#settingsHomeBanner")).to_be_visible()
    assert _settings(live_kiosk_server)["system_profile"] == "Tyson100_system.json"


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

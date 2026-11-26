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

from playwright.sync_api import Locator, Page, expect
from support.live_control_plane import LiveControlPlane
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


def _start_run(server: LiveKioskServer, protocols_dir: Path) -> None:
    (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
    request = urllib.request.Request(
        f"{server.url}/run",
        data=json.dumps({"filename": "a.pipette"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=5).close()


_WATER_VISCOSITY = '.settings-liquid[data-liquid="water"] [data-key="viscosity_cP"]'


@pytest.mark.usefixtures("local")
def test_fields_disable_with_the_reason_while_a_run_is_active(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    _open_settings(page, live_kiosk_server)
    field = page.locator(f"{_WATER_VISCOSITY} input")
    expect(field).to_be_enabled()

    _start_run(live_kiosk_server, protocols_dir)

    expect(page.locator("#settingsLockBanner")).to_be_visible()
    expect(page.locator("#settingsLockBanner")).to_contain_text(
        "Locked while a protocol is running"
    )
    expect(field).to_be_disabled()
    expect(page.locator("#settingsLiquidSelect")).to_be_disabled()
    expect(page.locator('#settingsLiquids button:text-is("Load")')).to_be_disabled()
    expect(
        page.locator('#settingsLiquids button:text-is("Unload")').first
    ).to_be_disabled()
    expect(page.locator("#page-settings button:enabled")).to_have_count(0)


@pytest.mark.usefixtures("local")
def test_pipette_and_gantry_values_are_shown_read_only(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)
    settings = _settings(live_kiosk_server)
    speed_xy = next(f for f in settings["gantry"]["fields"] if f["key"] == "speed_xy")

    expect(page.locator("#settingsPipette")).to_contain_text(
        settings["pipette"]["name"]
    )
    expect(page.locator('#settingsGantry [data-key="speed_xy"]')).to_contain_text(
        f"{speed_xy['value']:g}"
    )
    for panel in ("#settingsPipette", "#settingsGantry"):
        controls = page.locator(f"{panel} input, {panel} select, {panel} button")
        expect(controls).to_have_count(0)


def test_switching_the_system_profile_asks_for_a_home(
    page: Page, live_kiosk_server: LiveKioskServer, local: Path
) -> None:
    other = json.loads((local / "system" / DefaultFilenames.CONFIG_SYSTEM).read_text())
    other["pipette"] = "default_p100"
    (local / "system" / "other.json").write_text(json.dumps(other))
    _open_settings(page, live_kiosk_server)

    page.locator("#settingsSystemSelect").select_option("other.json")
    page.locator("#settingsSystem").get_by_role("button", name="Switch").click()

    expect(page.locator("#settingsHomeBanner")).to_be_visible()
    expect(page.locator("#pipettePill")).to_contain_text("default_p100")
    assert _settings(live_kiosk_server)["system_profile"] == "other.json"


@pytest.mark.usefixtures("local")
def test_the_header_pill_switches_the_pipette_from_any_tab(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)
    pill = page.locator("#pipettePill")
    expect(pill).to_contain_text("p100_vertical")

    pill.click()
    page.locator("#pipetteSwitcher").get_by_role("button", name="default_p100").click()

    expect(pill).to_contain_text("default_p100")
    assert _settings(live_kiosk_server)["pipette"]["file"] == "default_p100.json"


@pytest.mark.usefixtures("local")
def test_the_header_pill_is_disabled_while_a_run_is_active(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    page.goto(live_kiosk_server.url)
    expect(page.locator("#pipettePill")).to_be_enabled()

    _start_run(live_kiosk_server, protocols_dir)

    expect(page.locator("#pipettePill")).to_be_disabled()


@pytest.mark.usefixtures("local")
def test_a_low_risk_liquid_edit_round_trips(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)
    row = page.locator(_WATER_VISCOSITY)

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


@pytest.mark.usefixtures("local")
def test_the_header_pill_follows_a_swap_made_elsewhere(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)
    pill = page.locator("#pipettePill")
    expect(pill).to_contain_text("p100_vertical")

    # As `tap load_pipette` would: straight to the daemon, not via the pill.
    request = urllib.request.Request(
        f"{live_kiosk_server.url}/settings/load_pipette",
        data=json.dumps({"filename": "default_pipette.json"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=5).close()

    expect(pill).to_contain_text("default_pipette")


@pytest.mark.usefixtures("local")
def test_a_pill_swap_rerenders_the_open_settings_page(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)
    speed = page.locator('#settingsPipette [data-key="syringe.speed_dispense"]')
    expect(speed).to_contain_text("50")

    page.click("#pipettePill")
    page.locator("#pipetteSwitcher").get_by_role(
        "button", name="default_pipette"
    ).click()

    expect(speed).to_contain_text("25")


def _loaded_names(server: LiveKioskServer) -> list[str]:
    return [r["name"] for r in _settings(server)["liquids"]["loaded"]]


def _unload_button(page: Page, liquid: str) -> Locator:
    return page.locator(f'.settings-liquid[data-liquid="{liquid}"]').get_by_role(
        "button", name="Unload"
    )


def _load(page: Page, filename: str) -> None:
    page.locator("#settingsLiquidSelect").select_option(filename)
    page.locator("#settingsLiquids").get_by_role(
        "button", name="Load", exact=True
    ).click()


def test_loading_a_liquid_file_adds_its_card(
    local: Path, page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    (local / "liquids").mkdir()
    (local / "liquids" / "oil.json").write_text(
        json.dumps({"name": "oil", "viscosity_cP": 30.0})
    )
    _open_settings(page, live_kiosk_server)

    _load(page, "oil.json")

    expect(page.locator('.settings-liquid[data-liquid="oil"]')).to_be_visible()
    assert "oil" in _loaded_names(live_kiosk_server)


def test_loading_an_already_loaded_file_rereads_it(
    local: Path, page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)
    viscosity = page.locator(f"{_WATER_VISCOSITY} input")
    expect(viscosity).to_have_value("1")
    # An edit on disk, as an operator would make in the local config repo.
    water = json.loads((DefaultPaths.DIR_CONFIG_LIQUIDS / "water.json").read_text())
    water["viscosity_cP"] = 2.5
    (local / "liquids").mkdir()
    (local / "liquids" / "water.json").write_text(json.dumps(water))

    _load(page, "water.json")

    expect(viscosity).to_have_value("2.5")


@pytest.mark.usefixtures("local")
def test_unloading_a_liquid_removes_its_card(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)

    _unload_button(page, "serum").click()

    expect(page.locator('.settings-liquid[data-liquid="serum"]')).to_have_count(0)
    assert "serum" not in _loaded_names(live_kiosk_server)


@pytest.mark.usefixtures("local")
def test_the_active_liquid_cannot_be_unloaded(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_settings(page, live_kiosk_server)

    expect(_unload_button(page, "water")).to_be_disabled()
    expect(_unload_button(page, "serum")).to_be_enabled()


@pytest.mark.usefixtures("local")
def test_a_refused_unload_shows_the_daemons_message(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    _open_settings(page, live_kiosk_server)
    # Made active elsewhere (as `tap switch_liquid` would) after the page drew.
    live_control_plane.service.switch_liquid("serum")

    _unload_button(page, "serum").click()

    card = page.locator('.settings-liquid[data-liquid="serum"]')
    expect(card.locator(".move-feedback").first).to_contain_text(
        "'serum' is the active liquid"
    )
    assert "serum" in _loaded_names(live_kiosk_server)

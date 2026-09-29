"""Real-browser coverage of `calibrate.js` (issue #26, ADR-0003).

A commit writes to a per-test scratch local ``pipettes/`` root, never the
session's.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_models import TipState


@pytest.fixture
def local_pipettes(
    live_control_plane_with_plates: LiveControlPlane,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Home the daemon, put a tip on, and isolate the local pipettes root.

    Returns:
        The scratch local ``pipettes/`` directory.
    """
    monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_PIPETTE", tmp_path / "pipettes")
    service = live_control_plane_with_plates.service
    service.moonraker_state.set_homed(True)  # type: ignore[union-attr]
    service._autopipette.state.tip_state = TipState.ATTACHED
    return tmp_path / "pipettes"


def _open(page: Page, server: LiveKioskServer) -> None:
    page.goto(server.url)
    page.click('.tab-btn[data-page="calibrate"]')
    expect(page.locator('#calSourceSelect option[value="plate_a"]')).to_be_attached()


def test_a_whole_calibration_through_the_wizard(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer, local_pipettes: Path
) -> None:
    _open(page, live_kiosk_server_with_plates)
    page.select_option("#calSourceSelect", "plate_a")
    page.select_option("#calDestSelect", "plate_a")
    page.fill("#calVolumesInput", "20, 40")
    page.click("#calStartBtn")

    for i, mass in enumerate(("0.0195", "0.0402")):
        expect(page.locator("#calStepTitle")).to_contain_text(f"Point {i + 1} of 2")
        page.click("#calDispenseBtn")
        expect(page.locator("#calRecordRow")).to_be_visible()
        page.fill("#calMassInput", mass)
        page.click("#calRecordBtn")

    expect(page.locator("#calStepTitle")).to_have_text("All 2 points measured")
    page.click("#calPreviewBtn")
    expect(page.locator("#calFit")).to_contain_text("New")
    expect(page.locator("#calFit")).to_contain_text("Current")
    page.click("#calCommitBtn")

    expect(page.locator("#calFeedback")).to_contain_text("Saved 2-point calibration")
    expect(page.locator("#calSetup")).to_be_visible()
    saved = json.loads((local_pipettes / "p100_vertical.json").read_text())
    assert saved["syringe"]["calibration_volumes"] == pytest.approx([19.5, 40.2])


@pytest.mark.usefixtures("local_pipettes")
def test_a_refused_start_shows_the_reason_and_stays_on_setup(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer
) -> None:
    _open(page, live_kiosk_server_with_plates)
    page.select_option("#calSourceSelect", "plate_a")
    page.select_option("#calDestSelect", "plate_a")
    page.fill("#calVolumesInput", "500, 600")
    page.click("#calStartBtn")

    expect(page.locator("#calFeedback")).to_contain_text("Need at least 2 target")
    expect(page.locator("#calFeedback")).to_have_class("move-feedback error")
    expect(page.locator("#calSetup")).to_be_visible()
    expect(page.locator("#calSession")).to_be_hidden()


@pytest.mark.usefixtures("local_pipettes")
def test_the_wizard_is_locked_while_a_run_is_active(
    page: Page, live_kiosk_server_with_plates: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
    _open(page, live_kiosk_server_with_plates)
    expect(page.locator("#calStartBtn")).to_be_enabled()

    request = urllib.request.Request(
        f"{live_kiosk_server_with_plates.url}/run",
        data=json.dumps({"filename": "a.pipette"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(request, timeout=5).close()

    expect(page.locator("#calLockBanner")).to_be_visible()
    expect(page.locator("#calStartBtn")).to_be_disabled()
    expect(page.locator("#page-calibrate button:enabled")).to_have_count(0)

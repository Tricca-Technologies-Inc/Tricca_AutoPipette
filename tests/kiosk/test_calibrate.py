"""Kiosk calibration wizard routes (issue #26).

Each route forwards one ``calibrate.*`` RPC's `CommandResult` as-is, over a
real control plane. A commit writes to a per-test scratch local root.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.live_control_plane import LiveControlPlane

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_models import TipState
from tricca_autopipette.daemon.service import RunStatus


@pytest.fixture
def ready(
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


_START = {"source": "plate_a", "dest": "plate_a", "volumes_ul": [20.0, 40.0]}


def test_a_whole_session_through_the_routes(
    kiosk_client_with_plates: TestClient, ready: Path
) -> None:
    client = kiosk_client_with_plates
    assert client.post("/calibrate/start", json=_START).json()["ok"]
    for mass in (0.0195, 0.0402):
        assert client.post("/calibrate/dispense").json()["ok"]
        assert client.post("/calibrate/record", json={"mass_g": mass}).json()["ok"]

    preview = client.post("/calibrate/preview").json()
    commit = client.post("/calibrate/commit").json()

    assert preview["data"]["fit"]["volumes_ul"] == pytest.approx([19.5, 40.2])
    assert commit["ok"], commit["message"]
    saved = json.loads((ready / "p100_vertical.json").read_text())
    assert saved["syringe"]["calibration_volumes"] == pytest.approx([19.5, 40.2])
    assert client.get("/calibrate").json()["data"] == {"active": False}


def test_an_unhomed_start_is_a_409_with_the_reason(
    kiosk_client_with_plates: TestClient,
) -> None:
    response = kiosk_client_with_plates.post("/calibrate/start", json=_START)

    assert response.status_code == 409
    assert "not homed" in response.json()["detail"]


@pytest.mark.usefixtures("ready")
def test_refused_while_a_run_is_active(
    kiosk_client_with_plates: TestClient,
    live_control_plane_with_plates: LiveControlPlane,
) -> None:
    live_control_plane_with_plates.service._current = RunStatus(
        status="running", filename="a.pipette"
    )

    body = kiosk_client_with_plates.post("/calibrate/start", json=_START).json()

    assert body["ok"] is False
    assert body["data"] == {"reason": "run_active"}


@pytest.mark.usefixtures("ready")
def test_abort(kiosk_client_with_plates: TestClient) -> None:
    kiosk_client_with_plates.post("/calibrate/start", json=_START)

    assert kiosk_client_with_plates.post("/calibrate/abort").json()["ok"]

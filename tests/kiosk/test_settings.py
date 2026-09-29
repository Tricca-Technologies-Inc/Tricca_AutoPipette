"""Kiosk Settings page routes (issue #33 slice c).

Each route forwards one ``config.*`` RPC's `CommandResult` as-is, over a real
control plane. Writes go to a per-test scratch local root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from support.live_control_plane import LiveControlPlane

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.service import RunStatus


@pytest.fixture
def local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the union categories' local roots at a scratch dir.

    Returns:
        The scratch local root.
    """
    local = tmp_path / "local"
    for attr, category in (
        ("DIR_LOCAL_LIQUIDS", "liquids"),
        ("DIR_LOCAL_PIPETTE", "pipettes"),
        ("DIR_LOCAL_GANTRY", "gantry"),
    ):
        monkeypatch.setattr(DefaultPaths, attr, local / category)
    return local


def _liquid_field(body: dict[str, Any], liquid: str, key: str) -> dict[str, Any]:
    row = next(r for r in body["data"]["liquids"]["loaded"] if r["name"] == liquid)
    return next(f for f in row["fields"] if f["key"] == key)


def _set(client: TestClient, field: dict[str, Any], value: object) -> dict[str, Any]:
    return client.post(
        "/settings/set",
        json={
            "category": field["category"],
            "filename": field["filename"],
            "key_path": field["key_path"],
            "value": value,
        },
    ).json()


class TestSettingsRoutes:
    def test_get_reports_the_sections(self, kiosk_client: TestClient) -> None:
        body = kiosk_client.get("/settings").json()

        assert body["ok"] is True
        assert {"pipette", "gantry", "liquids", "system_profiles"} <= set(body["data"])

    @pytest.mark.usefixtures("local")
    def test_a_low_risk_edit_round_trips(self, kiosk_client: TestClient) -> None:
        field = _liquid_field(kiosk_client.get("/settings").json(), "water", "viscosity_cP")

        assert _set(kiosk_client, field, 1.7)["ok"] is True

        after = _liquid_field(kiosk_client.get("/settings").json(), "water", "viscosity_cP")
        assert after["value"] == 1.7  # ruff:ignore[float-equality-comparison]

    def test_an_out_of_bounds_edit_is_refused_with_the_reason(
        self, kiosk_client: TestClient, local: Path
    ) -> None:
        body = kiosk_client.get("/settings").json()
        field = next(
            f
            for f in body["data"]["pipette"]["fields"]
            if f["key"] == "syringe.max_volume_ul"
        )

        result = _set(kiosk_client, field, 99999)

        assert result["ok"] is False
        assert "outside the allowed range" in result["message"]
        assert not (local / "pipettes").exists()

    def test_a_write_during_a_run_is_refused_as_run_active(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        live_control_plane.service._current = RunStatus(
            status="running", filename="a.pipette"
        )

        result = kiosk_client.post(
            "/settings/set",
            json={
                "category": "liquids",
                "filename": "water.json",
                "key_path": "viscosity_cP",
                "value": 2,
            },
        ).json()

        assert result["ok"] is False
        assert result["data"] == {"reason": "run_active"}

    def test_unload_then_load_a_liquid(self, kiosk_client: TestClient) -> None:
        unloaded = kiosk_client.post("/settings/unload_liquid", json={"name": "methanol"})
        assert unloaded.json()["ok"] is True

        loaded = kiosk_client.post(
            "/settings/load_liquid", json={"filename": "methanol.json"}
        )

        assert loaded.json()["ok"] is True
        names = [
            r["name"]
            for r in kiosk_client.get("/settings").json()["data"]["liquids"]["loaded"]
        ]
        assert "methanol" in names

    def test_load_pipette(self, kiosk_client: TestClient) -> None:
        result = kiosk_client.post(
            "/settings/load_pipette", json={"filename": "default_pipette.json"}
        ).json()

        assert result["ok"] is True
        assert "init" in result["message"]

    def test_switch_system_to_an_unknown_profile_is_refused(
        self, kiosk_client: TestClient
    ) -> None:
        result = kiosk_client.post(
            "/settings/switch_system", json={"filename": "nope.json"}
        ).json()

        assert result["ok"] is False
        assert "nope.json" in result["message"]

    def test_the_status_stream_carries_config_locked(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')

        with kiosk_client.websocket_connect("/ws/status") as ws:
            assert ws.receive_json()["config_locked"] is False
            kiosk_client.post("/run", json={"filename": "a.pipette"})

            assert ws.receive_json()["config_locked"] is True

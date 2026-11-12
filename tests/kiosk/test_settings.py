"""Kiosk Settings page routes (issue #33 slice c).

Each route forwards one ``config.*`` RPC's `CommandResult` as-is, over a real
control plane. Writes go to a per-test scratch local root.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from support.live_control_plane import LiveControlPlane

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_models import GantryKinematics, LiquidProfile
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
    def test_check_tyson_prime_protocol_with_its_setup(
        self,
        kiosk_client: TestClient,
        local: Path,
        protocols_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        system = local / "system"
        system.mkdir(parents=True)
        for name in ("Tyson100_system.json", "Tyson_main.json"):
            shutil.copy2(DefaultPaths.DIR_CONFIG_SYSTEM / name, system / name)
        shutil.copy2(
            DefaultPaths.DIR_CONFIG_LOCATIONS / "Tyson100_locations.json",
            local.parent,
        )
        monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_SYSTEM", system)
        source = (
            DefaultPaths.DIR_REPO_ROOT
            / "protocols/Tyson/kit_making/prime/panel_a/prime_making_a_10.pipette"
        )
        shutil.copy2(source, protocols_dir / source.name)

        response = kiosk_client.post("/validate", json={"filename": source.name})

        assert response.status_code == 200
        result = response.json()
        assert result["ok"], result["data"]["findings"]

    def test_failed_switch_restores_active_configuration_and_deck(
        self, kiosk_client: TestClient, local: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        system = local / "system"
        system.mkdir(parents=True)
        shutil.copy2(DefaultPaths.DIR_LOCAL_SYSTEM / "default_system.json", system)
        (system / "broken.json").write_text(
            json.dumps({
                "gantry": "Tyson_gantry",
                "pipette": "TysonP100",
                "liquids": "Tyson100_liquids",
                "locations": "missing_deck",
            })
        )
        monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_SYSTEM", system)
        before = kiosk_client.get("/settings").json()["data"]
        before_deck = kiosk_client.get("/locations").json()
        with pytest.raises(ValueError):
            Coordinate(x=-1, y=0, z=0)

        result = kiosk_client.post(
            "/settings/switch_system", json={"filename": "broken.json"}
        ).json()

        assert not result["ok"]
        assert "missing_deck" in result["message"]
        after = kiosk_client.get("/settings").json()["data"]
        assert after["system_profile"] == before["system_profile"]
        assert after["pipette"] == before["pipette"]
        assert after["gantry"] == before["gantry"]
        assert kiosk_client.get("/locations").json() == before_deck
        with pytest.raises(ValueError):
            Coordinate(x=-1, y=0, z=0)

    @pytest.mark.parametrize(
        ("size", "profile"),
        [
            ("100", "Tyson100_system.json"),
            ("1000", "Tyson1000_system.json"),
            ("100", "Tyson_main.json"),
        ],
    )
    def test_switch_to_tyson_profile_loads_its_components(
        self,
        kiosk_client: TestClient,
        live_control_plane: LiveControlPlane,
        local: Path,
        monkeypatch: pytest.MonkeyPatch,
        size: str,
        profile: str,
    ) -> None:
        system = local / "system"
        system.mkdir(parents=True)
        for name in {"Tyson_main.json", profile}:
            shutil.copy2(DefaultPaths.DIR_CONFIG_SYSTEM / name, system / name)
        shutil.copy2(
            DefaultPaths.DIR_CONFIG_LOCATIONS / f"Tyson{size}_locations.json",
            local.parent,
        )
        monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_SYSTEM", system)

        result = kiosk_client.post(
            "/settings/switch_system", json={"filename": profile}
        )

        assert result.status_code == 200
        assert result.json()["ok"], result.json()
        settings = kiosk_client.get("/settings").json()["data"]
        assert settings["pipette"]["name"] == f"TysonP{size}"
        gantry = json.loads(
            (DefaultPaths.DIR_CONFIG_GANTRY / "Tyson_gantry.json").read_text()
        )
        service = live_control_plane.service
        assert service._autopipette.gantry == GantryKinematics.model_validate(gantry)
        field = next(f for f in settings["gantry"]["fields"] if f["key"] == "speed_xy")
        assert field["value"] == gantry["speed_xy"]
        assert field["category"] == "gantry"
        assert field["filename"] == "Tyson_gantry.json"
        liquid = json.loads(
            (DefaultPaths.DIR_CONFIG_LIQUIDS / f"Tyson{size}_liquids.json").read_text()
        )
        assert service._autopipette.system_config.liquids["water"] == (
            LiquidProfile.model_validate(liquid)
        )
        water = next(x for x in settings["liquids"]["loaded"] if x["name"] == "water")
        speed = next(f for f in water["fields"] if f["key"] == "speed_aspirate")
        assert speed["value"] == liquid["speed_aspirate"]
        assert speed["filename"] == f"Tyson{size}_liquids.json"
        locations = kiosk_client.get("/locations").json()
        assert locations["ok"]
        assert any(loc["name"] == "tipbox" for loc in locations["data"]["locations"])
        assert _set(kiosk_client, speed, 25)["ok"]
        updated = _liquid_field(
            kiosk_client.get("/settings").json(), "water", "speed_aspirate"
        )
        assert updated["value"] == 25
        assert updated["filename"] == f"Tyson{size}_liquids.json"
        assert (local / "liquids" / f"Tyson{size}_liquids.json").exists()

    def test_get_reports_the_sections(self, kiosk_client: TestClient) -> None:
        body = kiosk_client.get("/settings").json()

        assert body["ok"] is True
        assert {"pipette", "gantry", "liquids", "system_profiles"} <= set(body["data"])

    @pytest.mark.usefixtures("local")
    def test_a_low_risk_edit_round_trips(self, kiosk_client: TestClient) -> None:
        field = _liquid_field(
            kiosk_client.get("/settings").json(), "water", "viscosity_cP"
        )

        assert _set(kiosk_client, field, 1.7)["ok"] is True

        after = _liquid_field(
            kiosk_client.get("/settings").json(), "water", "viscosity_cP"
        )
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
        unloaded = kiosk_client.post(
            "/settings/unload_liquid", json={"name": "methanol"}
        )
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

"""Live configuration changes in the running daemon (issue #33, slice b).

Every test runs against a scratch copy of the repo's ``config/`` tree as the
shared root and a scratch local root (with its own ``system/``), both under
``tmp_path`` -- nothing here reads or writes the real ``~/.config``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.commands.tap_cmd_parsers import (
    HomeArgs,
    LoadLocationsArgs,
    MoveArgs,
)
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.daemon.service import (
    AutoPipetteService,
    CommandResult,
    RunStatus,
)

REPO_CONFIG = DefaultPaths.DIR_CONFIG

_CATEGORY_ATTRS = {
    "system": ("DIR_CONFIG_SYSTEM", "DIR_LOCAL_SYSTEM"),
    "gantry": ("DIR_CONFIG_GANTRY", "DIR_LOCAL_GANTRY"),
    "pipettes": ("DIR_CONFIG_PIPETTE", "DIR_LOCAL_PIPETTE"),
    "liquids": ("DIR_CONFIG_LIQUIDS", "DIR_LOCAL_LIQUIDS"),
    "locations": ("DIR_CONFIG_LOCATIONS", "DIR_LOCAL_LOCATIONS"),
    "plates": ("DIR_CONFIG_PLATES", "DIR_LOCAL_PLATES"),
}


@pytest.fixture
def local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated shared/local roots, with the default system profile seeded.

    Returns:
        The scratch local root.
    """
    shared = tmp_path / "shared"
    local = tmp_path / "local"
    shutil.copytree(REPO_CONFIG, shared)
    (local / "system").mkdir(parents=True)
    shutil.copy2(
        shared / "system" / DefaultFilenames.CONFIG_SYSTEM,
        local / "system" / DefaultFilenames.CONFIG_SYSTEM,
    )
    for category, (shared_attr, local_attr) in _CATEGORY_ATTRS.items():
        monkeypatch.setattr(DefaultPaths, shared_attr, shared / category)
        monkeypatch.setattr(DefaultPaths, local_attr, local / category)
    return local


@pytest.fixture
def svc(local: Path, tmp_path: Path) -> AutoPipetteService:
    """A homed, unconnected service built from the isolated roots.

    Returns:
        The service.
    """
    service = AutoPipetteService(
        config_system=local / "system" / DefaultFilenames.CONFIG_SYSTEM,
        config_gantry=None,
        config_pipette=None,
        config_locations=None,
        config_liquids=None,
        connect_websocket=False,
    )
    service.gcode_manager.gcode_path = tmp_path
    service.moonraker_state = FakeMoonrakerState(homed=True)  # type: ignore[assignment]
    return service


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestHotReload:
    def test_liquid_edit_takes_effect_on_the_active_liquid(
        self, svc: AutoPipetteService
    ) -> None:
        result = svc.set_config_value("liquids", "water.json", "speed_aspirate", 42.0)

        assert result.ok, result.message
        assert svc._autopipette.syringe.speed_aspirate == 42.0  # ruff:ignore[float-equality-comparison]

    def test_system_edit_takes_effect(self, svc: AutoPipetteService) -> None:
        result = svc.set_config_value(
            "system", DefaultFilenames.CONFIG_SYSTEM, "gantry.speed_xy", 1234.0
        )

        assert result.ok, result.message
        assert svc._autopipette.gantry.speed_xy == 1234.0  # ruff:ignore[float-equality-comparison]

    def test_active_pipette_edit_takes_effect(self, svc: AutoPipetteService) -> None:
        result = svc.set_config_value(
            "pipettes", "p100_vertical.json", "syringe.max_volume_ul", 90.0
        )

        assert result.ok, result.message
        assert svc._autopipette.syringe.max_volume_ul == 90.0  # ruff:ignore[float-equality-comparison]


class TestForcedRehome:
    def test_editing_the_active_pipette_requires_homing_again(
        self, svc: AutoPipetteService
    ) -> None:
        svc.set_config_value(
            "pipettes", "p100_vertical.json", "syringe.max_volume_ul", 90.0
        )

        with pytest.raises(NotHomedError):
            svc.move(MoveArgs(x=1.0, y=1.0, z=1.0))

    def test_editing_the_gantry_requires_homing_again(
        self, svc: AutoPipetteService
    ) -> None:
        svc.set_config_value(
            "system", DefaultFilenames.CONFIG_SYSTEM, "gantry.speed_xy", 1234.0
        )

        with pytest.raises(NotHomedError):
            svc.move(MoveArgs(x=1.0, y=1.0, z=1.0))

    def test_editing_a_liquid_or_an_inactive_pipette_keeps_homing(
        self, svc: AutoPipetteService
    ) -> None:
        svc.set_config_value("liquids", "water.json", "speed_aspirate", 42.0)
        svc.set_config_value(
            "pipettes", "default_pipette.json", "syringe.max_volume_ul", 90.0
        )

        assert svc.move(MoveArgs(x=1.0, y=1.0, z=1.0)).ok

    def test_init_restores_homing(self, svc: AutoPipetteService) -> None:
        svc.set_config_value(
            "pipettes", "p100_vertical.json", "syringe.max_volume_ul", 90.0
        )

        svc.init()

        assert svc.move(MoveArgs(x=1.0, y=1.0, z=1.0)).ok

    def test_homing_one_axis_does_not_restore_homing(
        self, svc: AutoPipetteService
    ) -> None:
        svc.set_config_value(
            "pipettes", "p100_vertical.json", "syringe.max_volume_ul", 90.0
        )

        svc.home(HomeArgs(motors="x"))

        with pytest.raises(NotHomedError):
            svc.move(MoveArgs(x=1.0, y=1.0, z=1.0))


def _p1000(local: Path) -> None:
    data = json.loads((REPO_CONFIG / "pipettes" / "p100_vertical.json").read_text())
    data["name"] = "P1000"
    data["syringe"]["max_volume_ul"] = 1000.0
    _write_json(local / "pipettes" / "p1000.json", data)


class TestLoadPipette:
    def test_swaps_the_active_pipette_and_requires_homing(
        self, svc: AutoPipetteService, local: Path
    ) -> None:
        _p1000(local)

        result = svc.load_pipette("p1000.json")

        assert result.ok, result.message
        assert svc._autopipette.pipette_model.name == "P1000"
        assert svc._autopipette.syringe.max_volume_ul == 1000.0  # ruff:ignore[float-equality-comparison]
        with pytest.raises(NotHomedError):
            svc.move(MoveArgs(x=1.0, y=1.0, z=1.0))

    def test_swapped_pipette_survives_a_later_edit(
        self, svc: AutoPipetteService, local: Path
    ) -> None:
        _p1000(local)
        svc.load_pipette("p1000.json")

        svc.set_config_value("liquids", "water.json", "speed_aspirate", 42.0)

        assert svc._autopipette.pipette_model.name == "P1000"

    def test_missing_file_is_refused(self, svc: AutoPipetteService) -> None:
        result = svc.load_pipette("nope.json")

        assert not result.ok
        assert svc._autopipette.pipette_model.name == "P100_Vertical"


class TestSwitchSystem:
    def test_switches_profile_repoints_active_and_requires_homing(
        self, svc: AutoPipetteService, local: Path
    ) -> None:
        _p1000(local)
        _write_json(
            local / "system" / "murphy_1000.json",
            {"extends": DefaultFilenames.CONFIG_SYSTEM, "pipette": "p1000"},
        )

        result = svc.switch_system("murphy_1000.json")

        assert result.ok, result.message
        assert svc._autopipette.pipette_model.name == "P1000"
        assert (local / "system" / "active.json").resolve().name == "murphy_1000.json"
        with pytest.raises(NotHomedError):
            svc.move(MoveArgs(x=1.0, y=1.0, z=1.0))

    def test_summary_names_the_active_and_available_profiles(
        self, svc: AutoPipetteService, local: Path
    ) -> None:
        _write_json(local / "system" / "other.json", {"extends": "default_system.json"})
        svc.switch_system("other.json")

        data = svc.system_summary().data

        assert data is not None
        assert data["system_profile"] == "other.json"
        assert data["system_profiles"] == ["default_system.json", "other.json"]

    def test_unknown_profile_is_refused_and_nothing_changes(
        self, svc: AutoPipetteService
    ) -> None:
        result = svc.switch_system("nope.json")

        assert not result.ok
        assert svc.move(MoveArgs(x=1.0, y=1.0, z=1.0)).ok


class TestLiquidMembership:
    def test_unload_then_load(self, svc: AutoPipetteService) -> None:
        assert svc.unload_liquid("methanol").ok
        assert "methanol" not in svc._autopipette.system_config.liquids

        assert svc.load_liquid("methanol.json").ok
        assert "methanol" in svc._autopipette.system_config.liquids

    def test_unloaded_liquid_stays_unloaded_after_a_reload(
        self, svc: AutoPipetteService
    ) -> None:
        svc.unload_liquid("methanol")

        svc.set_config_value("liquids", "water.json", "speed_aspirate", 42.0)

        assert "methanol" not in svc._autopipette.system_config.liquids

    def test_the_active_liquid_cannot_be_unloaded(
        self, svc: AutoPipetteService
    ) -> None:
        result = svc.unload_liquid("water")

        assert not result.ok
        assert "water" in svc._autopipette.system_config.liquids

    def test_unknown_liquid_is_refused(self, svc: AutoPipetteService) -> None:
        assert not svc.unload_liquid("nope").ok


class TestRunLock:
    @pytest.fixture
    def running(self, svc: AutoPipetteService) -> AutoPipetteService:
        svc._current = RunStatus(status="running", filename="a.pipette")
        return svc

    @pytest.mark.parametrize(
        ("method", "args"),
        [
            ("set_config_value", ("liquids", "water.json", "speed_aspirate", 42.0)),
            ("load_pipette", ("p100_vertical.json",)),
            ("switch_system", (DefaultFilenames.CONFIG_SYSTEM,)),
            ("unload_liquid", ("methanol",)),
        ],
    )
    def test_config_changes_are_refused_with_a_reason(
        self,
        running: AutoPipetteService,
        local: Path,
        method: str,
        args: tuple[object, ...],
    ) -> None:
        result: CommandResult = getattr(running, method)(*args)

        assert not result.ok
        assert result.data == {"reason": "run_active"}
        assert "a.pipette" in result.message
        assert not (local / "liquids").exists()
        assert "methanol" in running._autopipette.system_config.liquids

    def test_status_reports_the_lock(self, running: AutoPipetteService) -> None:
        assert running.get_status().config_locked

    def test_idle_status_is_unlocked(self, svc: AutoPipetteService) -> None:
        assert not svc.get_status().config_locked


_TIPBOX = {
    "name": "box",
    "type": "tipbox",
    "x": 100,
    "y": 20,
    "z": 5,
    "dip_top": 5.0,
    "num_row": 2,
    "num_col": 5,
    "spacing_row": 9.0,
    "spacing_col": 9.0,
}


class TestLocationsHotReload:
    @pytest.fixture
    def deck(self, svc: AutoPipetteService, local: Path) -> None:
        _write_json(
            local / "locations" / "deck.json",
            {
                "coordinates": [
                    {"name": "home", "x": 1, "y": 2, "z": 3},
                    {"name": "gone", "x": 1, "y": 2, "z": 3},
                ],
                "plates": [_TIPBOX],
            },
        )
        assert svc.load_locations(LoadLocationsArgs("deck.json", False)).ok

    @pytest.mark.usefixtures("deck")
    def test_editing_a_loaded_file_updates_the_deck(
        self, svc: AutoPipetteService
    ) -> None:
        result = svc.set_config_value("locations", "deck.json", "coordinates.0.x", 5)

        assert result.ok, result.message
        home = svc._autopipette.location_manager.locations["home"]
        assert isinstance(home, Coordinate)
        assert home.x == 5

    @pytest.mark.usefixtures("deck")
    def test_tip_consumption_survives_a_reload(self, svc: AutoPipetteService) -> None:
        manager = svc._autopipette.location_manager.tipbox_manager
        manager.set_consumed("box", {0, 1, 2})
        before = manager.snapshot()

        svc.set_config_value("locations", "deck.json", "plates.0.z", 6)

        assert manager.snapshot() == before

    @pytest.mark.usefixtures("deck")
    def test_an_entry_removed_from_the_file_leaves_the_deck(
        self, svc: AutoPipetteService, local: Path
    ) -> None:
        path = local / "locations" / "deck.json"
        data = json.loads(path.read_text())
        data["coordinates"] = data["coordinates"][:1]
        _write_json(path, data)

        svc.set_config_value("locations", "deck.json", "coordinates.0.x", 5)

        assert not svc._autopipette.location_manager.has_location("gone")

    def test_system_locations_edit_rebuilds_the_deck(
        self, svc: AutoPipetteService, local: Path
    ) -> None:
        _write_json(
            local / "locations" / "bench.json",
            {"coordinates": [{"name": "bench", "x": 1, "y": 2, "z": 3}]},
        )

        result = svc.set_config_value(
            "system", DefaultFilenames.CONFIG_SYSTEM, "locations", "bench.json"
        )

        assert result.ok, result.message
        assert svc._autopipette.location_manager.has_location("bench")

    def test_system_switch_loads_the_new_profiles_deck(
        self, svc: AutoPipetteService, local: Path
    ) -> None:
        _write_json(
            local / "locations" / "bench.json",
            {"coordinates": [{"name": "bench", "x": 1, "y": 2, "z": 3}]},
        )
        _write_json(
            local / "system" / "other.json",
            {"extends": DefaultFilenames.CONFIG_SYSTEM, "locations": "bench.json"},
        )

        assert svc.switch_system("other.json").ok

        assert svc._autopipette.location_manager.has_location("bench")

    def test_editing_a_file_that_is_not_loaded_leaves_the_deck_alone(
        self, svc: AutoPipetteService
    ) -> None:
        names = svc._autopipette.location_manager.get_all_names()

        result = svc.set_config_value(
            "locations", "examples_deck.json", "plates.0.z", 6
        )

        assert result.ok, result.message
        assert svc._autopipette.location_manager.get_all_names() == names

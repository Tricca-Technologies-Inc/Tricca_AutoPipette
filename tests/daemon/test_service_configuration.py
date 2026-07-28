"""Unit tests for ``AutoPipetteService``'s configuration commands (Phase 1 of

the ports-and-adapters migration, ConfigurationCommands group -- see
CLAUDE.md). Only the state-mutating commands are covered here: the
read-only reporting commands (``list_liquids``, ``ls``) were deliberately
not migrated (see the module docstring on ``ConfigurationCommands``) and
have no service-layer equivalent to test.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.commands.tap_cmd_parsers import (
    CoorArgs,
    DelLocArgs,
    PlateArgs,
    ResetPlateArgs,
    SetArgs,
)
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths
from tricca_autopipette.core.plates import Plate
from tricca_autopipette.daemon.service import AutoPipetteService


def _plate_args(**overrides: object) -> PlateArgs:
    defaults: dict[str, object] = {
        "name": "my_plate",
        "plate_type": "array",
        "num_row": 8,
        "num_col": 12,
        "x": 100.0,
        "y": 200.0,
        "z": 10.0,
        "dip_top": 2.0,
        "dip_btm": None,
        "dip_func": "simple",
        "well_diameter": None,
        "spacing_row": 9.0,
        "spacing_col": 9.0,
    }
    defaults.update(overrides)
    return PlateArgs(**defaults)  # type: ignore[arg-type]


class TestSwitchLiquid:
    def test_switches_and_returns_liquid_details(
        self, service: AutoPipetteService
    ) -> None:
        result = service.switch_liquid("methanol")

        assert result.ok is True
        assert service._autopipette.active_liquid == "methanol"
        assert result.data is not None
        assert result.data["viscosity_cP"] == pytest.approx(0.59)

    def test_unknown_liquid_raises_value_error(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            service.switch_liquid("not_a_real_liquid")


class TestLoadLiquid:
    def test_loads_existing_profile(self, service: AutoPipetteService) -> None:
        result = service.load_liquid("water.json")

        assert result.ok is True
        assert result.data is not None
        assert result.data["name"] == "water"

    def test_missing_file_raises_file_not_found(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(FileNotFoundError):
            service.load_liquid("does_not_exist.json")


class TestSet:
    def test_speed_factor(self, service: AutoPipetteService) -> None:
        result = service.set(SetArgs(var="SPEED_FACTOR", value=150.0))

        assert result.ok is True
        assert "150.0" in result.message

    def test_velocity_max(self, service: AutoPipetteService) -> None:
        result = service.set(SetArgs(var="velocity_max", value=5000.0))

        assert result.ok is True

    def test_accel_max(self, service: AutoPipetteService) -> None:
        result = service.set(SetArgs(var="ACCEL_MAX", value=3000.0))

        assert result.ok is True

    def test_unknown_variable_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.set(SetArgs(var="NOT_A_VAR", value=1.0))

        assert result.ok is False
        assert "Unknown variable" in result.message


class TestCoor:
    def test_creates_a_coordinate(self, service: AutoPipetteService) -> None:
        result = service.coor(CoorArgs(name="bench", x=1.0, y=2.0, z=3.0))

        assert result.ok is True
        location = service._autopipette.location_manager.locations["bench"]
        assert isinstance(location, Coordinate)
        assert location.x == pytest.approx(1.0)
        assert location.y == pytest.approx(2.0)
        assert location.z == pytest.approx(3.0)


class TestPlate:
    def test_creates_an_array_plate(self, service: AutoPipetteService) -> None:
        result = service.plate(_plate_args())

        assert result.ok is True
        loc_mgr = service._autopipette.location_manager
        assert loc_mgr.has_location("my_plate")
        assert "my_plate" in loc_mgr.get_plate_names()

    def test_creates_a_tipbox_and_registers_it(
        self, service: AutoPipetteService
    ) -> None:
        result = service.plate(
            _plate_args(name="tips", plate_type="tipbox", num_row=1, num_col=2)
        )

        assert result.ok is True
        assert service._autopipette.location_manager.tipboxes is not None


class TestResetPlate:
    def test_unknown_location_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.reset_plate(ResetPlateArgs(name="nope"))

        assert result.ok is False
        assert "not found" in result.message

    def test_non_plate_location_is_a_noop(self, service: AutoPipetteService) -> None:
        service.coor(CoorArgs(name="bench", x=1.0, y=2.0, z=3.0))

        result = service.reset_plate(ResetPlateArgs(name="bench"))

        assert result.ok is False
        assert "not a plate" in result.message

    def test_resets_a_plate(self, service: AutoPipetteService) -> None:
        service.plate(_plate_args())
        loc_mgr = service._autopipette.location_manager
        plate = loc_mgr.locations["my_plate"]
        assert isinstance(plate, Plate)
        plate.curr = 5

        result = service.reset_plate(ResetPlateArgs(name="my_plate"))

        assert result.ok is True
        assert plate.curr == 0


class TestResetPlates:
    def test_no_plates_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.reset_plates()

        assert result.ok is False

    def test_resets_all_plates(self, service: AutoPipetteService) -> None:
        service.plate(_plate_args(name="plate_a"))
        service.plate(_plate_args(name="plate_b"))
        loc_mgr = service._autopipette.location_manager
        plate_a = loc_mgr.locations["plate_a"]
        plate_b = loc_mgr.locations["plate_b"]
        assert isinstance(plate_a, Plate)
        assert isinstance(plate_b, Plate)
        plate_a.curr = 3
        plate_b.curr = 7

        result = service.reset_plates()

        assert result.ok is True
        assert "2 plate" in result.message
        assert plate_a.curr == 0
        assert plate_b.curr == 0


class TestDelLoc:
    def test_unknown_location_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.del_loc(DelLocArgs(name="nope"))

        assert result.ok is False

    def test_deletes_a_location(self, service: AutoPipetteService) -> None:
        service.coor(CoorArgs(name="bench", x=1.0, y=2.0, z=3.0))

        result = service.del_loc(DelLocArgs(name="bench"))

        assert result.ok is True
        assert not service._autopipette.location_manager.has_location("bench")


class TestClearLocs:
    def test_no_locations_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.clear_locs()

        assert result.ok is False

    def test_clears_all_locations(self, service: AutoPipetteService) -> None:
        service.coor(CoorArgs(name="bench", x=1.0, y=2.0, z=3.0))
        service.plate(_plate_args())

        result = service.clear_locs()

        assert result.ok is True
        assert len(service._autopipette.location_manager.locations) == 0


class TestSaveAndLoadLocations:
    def test_round_trips_through_a_real_file(self, service: AutoPipetteService) -> None:
        # The `service` fixture points location_manager.locations_dir at
        # tmp_path, so this writes a real file without touching the repo's
        # config/locations/.
        loc_mgr = service._autopipette.location_manager
        filename = "round_trip.json"

        service.coor(CoorArgs(name="bench", x=1.0, y=2.0, z=3.0))
        service.plate(_plate_args())

        save_result = service.save_locations(filename)
        assert save_result.ok is True
        assert (loc_mgr.locations_dir / filename).exists()

        service.clear_locs()
        load_result = service.load_locations(filename)

        assert load_result.ok is True
        assert loc_mgr.has_location("bench")
        assert loc_mgr.has_location("my_plate")

    def test_load_missing_file_raises_file_not_found(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(FileNotFoundError):
            service.load_locations("does_not_exist_at_all.json")


def test_default_filenames_sanity() -> None:
    # Guards the assumption in TestLoadLiquid that water.json is real.
    assert (DefaultPaths.DIR_CONFIG_LIQUIDS / "water.json").exists()
    assert DefaultFilenames.CONFIG_LIQUIDS

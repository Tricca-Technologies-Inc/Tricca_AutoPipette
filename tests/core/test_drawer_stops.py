"""Named drawer stops in locations files, and deck locations linked to them (#142)."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from tricca_autopipette.core.location_manager import Drawer, LocationManager
from tricca_autopipette.core.pipette_exceptions import DrawerNotAtStopError
from tricca_autopipette.daemon.moonraker_state import AxisConfig, PlateAxis

KLIPPER = AxisConfig(
    plates=(
        PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),
        PlateAxis("plate2", "V", 0.0, 350.0, (0.0, 120.0, 350.0)),
    ),
    z_safe=0.0,
    park_tol=0.1,
)


def drawer_file() -> dict[str, Any]:
    # The addendum's D38/D40 example, with real deck geometry.
    return {
        "drawers": {
            "plate2": {
                "stops": {"load": 350, "cover": 300, "work_a": 0, "work_b": 120},
                "pipetting": ["work_a", "work_b"],
            }
        },
        "coordinates": [
            {"name": "bench", "x": 1, "y": 2, "z": 3},
            {
                "name": "probe",
                "x": 4,
                "y": 5,
                "z": 6,
                "drawer": "plate2",
                "stop": "work_b",
            },
        ],
        "plates": [
            {
                "name": "sample_plate",
                "drawer": "plate2",
                "stop": "work_a",
                "type": "array",
                "x": 10,
                "y": 10,
                "z": 5,
                "num_row": 2,
                "num_col": 3,
            }
        ],
    }


def manager_with(data: dict[str, Any], source: str = "deck.json") -> LocationManager:
    manager = LocationManager()
    manager.apply_locations_data(data, source=source)
    return manager


class TestParse:
    def test_good_file_loads_drawers_and_links(self) -> None:
        manager = manager_with(drawer_file())

        assert manager.drawers["plate2"].stops == {
            "load": 350.0,
            "cover": 300.0,
            "work_a": 0.0,
            "work_b": 120.0,
        }
        assert manager.drawers["plate2"].pipetting == ("work_a", "work_b")
        assert manager.drawer_links == {
            "probe": ("plate2", "work_b"),
            "sample_plate": ("plate2", "work_a"),
        }

    def test_file_without_drawers_has_none(self) -> None:
        data = drawer_file()
        del data["drawers"]
        for entry in [*data["coordinates"], *data["plates"]]:
            entry.pop("drawer", None)
            entry.pop("stop", None)

        manager = manager_with(data)

        assert manager.drawers == {}
        assert manager.drawer_links == {}

    @pytest.mark.parametrize(
        ("drawers", "message"),
        [
            ([], "'drawers' must be an object"),
            ({"plate2": {"pipetting": []}}, "needs a 'stops' object"),
            ({"plate2": {"stops": {"a": "far"}}}, "stop 'a' must be a number"),
            ({"plate2": {"stops": {"a": True}}}, "stop 'a' must be a number"),
            (
                {"plate2": {"stops": {"a": 0}, "pipetting": ["b"]}},
                "pipetting stop 'b' is not one of its stops",
            ),
        ],
    )
    def test_malformed_drawer_is_rejected(self, drawers: Any, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            manager_with({"drawers": drawers})

    def test_link_needs_both_drawer_and_stop(self) -> None:
        data = drawer_file()
        del data["plates"][0]["stop"]

        with pytest.raises(ValueError, match="both 'drawer' and 'stop'"):
            manager_with(data)

    def test_dangling_stop_is_rejected(self) -> None:
        data = drawer_file()
        data["plates"][0]["stop"] = "work_z"

        with pytest.raises(ValueError, match=r"'work_z'.*doesn't define"):
            manager_with(data)

    def test_link_to_non_pipetting_stop_is_rejected(self) -> None:
        data = drawer_file()
        data["plates"][0]["stop"] = "load"

        with pytest.raises(ValueError, match="'load' is not a pipetting stop"):
            manager_with(data)

    def test_link_to_drawer_from_another_file_resolves(self) -> None:
        data = drawer_file()
        drawers = {"drawers": data.pop("drawers")}
        manager = manager_with(drawers, source="drawers.json")

        manager.apply_locations_data(data, source="deck.json")

        assert manager.drawer_links["sample_plate"] == ("plate2", "work_a")

    def test_redefining_a_drawer_rechecks_existing_links(self) -> None:
        manager = manager_with(drawer_file())
        before = copy.deepcopy(manager.drawers)

        with pytest.raises(ValueError, match=r"'work_b'.*doesn't define"):
            manager.apply_locations_data(
                {
                    "drawers": {
                        "plate2": {"stops": {"work_a": 0}, "pipetting": ["work_a"]}
                    }
                },
                source="other.json",
            )
        assert manager.drawers == before


class TestAdditiveLoad:
    def test_failed_load_leaves_deck_untouched(self) -> None:
        manager = manager_with(drawer_file())
        bad = drawer_file()
        bad["drawers"]["plate1"] = {"stops": {"a": 0}, "pipetting": ["nope"]}
        bad["coordinates"].append({"name": "new", "x": 0, "y": 0, "z": 0})

        with pytest.raises(ValueError):
            manager.apply_locations_data(bad, source="bad.json")

        assert set(manager.drawers) == {"plate2"}
        assert not manager.has_location("new")

    def test_second_file_adds_drawers(self) -> None:
        manager = manager_with(drawer_file())

        manager.apply_locations_data(
            {"drawers": {"plate1": {"stops": {"in": 0}, "pipetting": ["in"]}}},
            source="more.json",
        )

        assert set(manager.drawers) == {"plate1", "plate2"}

    def test_duplicate_drawer_is_last_load_wins_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = manager_with(drawer_file())
        override = {
            "drawers": {
                "plate2": {
                    "stops": {"work_a": 1, "work_b": 121},
                    "pipetting": ["work_a", "work_b"],
                }
            }
        }

        with caplog.at_level(logging.WARNING):
            manager.apply_locations_data(override, source="override.json")

        assert manager.drawers["plate2"].stops == {"work_a": 1.0, "work_b": 121.0}
        assert "plate2" in caplog.text
        assert "override.json" in caplog.text
        assert "deck.json" in caplog.text

    def test_replace_wipes_drawers_and_links(self) -> None:
        manager = manager_with(drawer_file())

        manager.apply_locations_data(
            {"coordinates": [{"name": "x", "x": 0, "y": 0, "z": 0}]}, replace=True
        )

        assert manager.drawers == {}
        assert manager.drawer_links == {}

    def test_load_from_json_reads_drawers(self, tmp_path: Path) -> None:
        (tmp_path / "deck.json").write_text(json.dumps(drawer_file()))
        manager = LocationManager(tmp_path)

        manager.load_from_json("deck.json")

        assert isinstance(manager.drawers["plate2"], Drawer)


def discovered(axes: AxisConfig = KLIPPER) -> LocationManager:
    manager = LocationManager()
    manager.set_axis_config(axes)
    return manager


class TestKlipperValidation:
    def test_good_file_passes(self) -> None:
        manager = discovered()

        manager.apply_locations_data(drawer_file(), source="deck.json")

        assert "plate2" in manager.drawers

    def test_unknown_drawer_is_rejected(self) -> None:
        data = drawer_file()
        data["drawers"]["plate9"] = data["drawers"].pop("plate2")
        for entry in [*data["coordinates"], *data["plates"]]:
            entry.pop("drawer", None)
            entry.pop("stop", None)

        with pytest.raises(ValueError, match="'plate9' is not a plate Klipper knows"):
            discovered().apply_locations_data(data)

    def test_out_of_range_stop_is_rejected(self) -> None:
        data = drawer_file()
        data["drawers"]["plate2"]["stops"]["load"] = 360

        with pytest.raises(ValueError, match="'load' at 360 mm is outside its travel"):
            discovered().apply_locations_data(data)

    def test_pipetting_stop_off_the_safe_list_is_rejected(self) -> None:
        data = drawer_file()
        data["drawers"]["plate2"]["stops"]["work_b"] = 200

        with pytest.raises(
            ValueError, match=r"'work_b' at 200 mm is not within 0.1 mm"
        ):
            discovered().apply_locations_data(data)

    def test_pipetting_stop_within_park_tol_passes(self) -> None:
        data = drawer_file()
        data["drawers"]["plate2"]["stops"]["work_b"] = 120.05

        discovered().apply_locations_data(data)

    def test_non_pipetting_stop_need_not_be_tip_safe(self) -> None:
        # "cover" at 300 mm isn't on Klipper's list, and needn't be.
        discovered().apply_locations_data(drawer_file())

    def test_machine_without_plates_rejects_a_drawers_block(self) -> None:
        with pytest.raises(ValueError, match="no plates configured in Klipper"):
            discovered(AxisConfig()).apply_locations_data(drawer_file())

    def test_machine_without_plates_still_loads_plain_decks(self) -> None:
        manager = discovered(AxisConfig())

        manager.apply_locations_data({
            "coordinates": [{"name": "a", "x": 0, "y": 0, "z": 0}]
        })

        assert manager.has_location("a")

    def test_before_discovery_the_block_is_kept_and_rechecked_on_connect(
        self,
    ) -> None:
        data = drawer_file()
        data["drawers"]["plate2"]["stops"]["work_b"] = 200
        manager = manager_with(data)

        problems = manager.set_axis_config(KLIPPER)

        assert "plate2" in manager.drawers
        assert len(problems) == 1
        assert "'work_b' at 200 mm" in problems[0]


def write_deck(directory: Path, data: dict[str, Any], name: str = "deck.json") -> Path:
    # The same formatting `write_json_atomic` uses, so bytes can be compared.
    path = directory / name
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


class TestPersistence:
    def test_save_round_trips_byte_for_byte(self, tmp_path: Path) -> None:
        data = drawer_file()
        data["drawers"]["plate2"]["note"] = "front left"  # unknown keys survive
        original = write_deck(tmp_path, data).read_bytes()
        manager = LocationManager(tmp_path)
        manager.load_from_json("deck.json")

        manager.save_to_json("deck.json")

        assert (tmp_path / "deck.json").read_bytes() == original

    def test_reload_source_picks_up_edited_stops_and_dropped_drawers(
        self, tmp_path: Path
    ) -> None:
        data = drawer_file()
        data["drawers"]["plate1"] = {"stops": {"in": 0}, "pipetting": ["in"]}
        write_deck(tmp_path, data)
        manager = LocationManager(tmp_path)
        manager.load_from_json("deck.json")

        del data["drawers"]["plate1"]
        data["drawers"]["plate2"]["stops"]["cover"] = 310
        write_deck(tmp_path, data)
        assert manager.reload_source("deck.json") is True

        assert set(manager.drawers) == {"plate2"}
        assert manager.drawers["plate2"].stops["cover"] == pytest.approx(310)

    def test_reload_source_of_a_drawers_only_file(self, tmp_path: Path) -> None:
        write_deck(tmp_path, {"drawers": drawer_file()["drawers"]}, "drawers.json")
        manager = LocationManager(tmp_path)
        manager.load_from_json("drawers.json")

        assert manager.reload_source("drawers.json") is True

    def test_membership_restore_undoes_drawer_and_link_changes(self) -> None:
        manager = manager_with(drawer_file())
        snapshot = manager.snapshot_membership()

        manager.clear()
        manager.restore_membership(snapshot)

        assert set(manager.drawers) == {"plate2"}
        assert manager.drawer_links["sample_plate"] == ("plate2", "work_a")

    def test_relinking_by_hand_drops_the_link(self) -> None:
        manager = manager_with(drawer_file())

        manager.set_coordinate("probe", manager.get_coordinate("bench"))

        assert "probe" not in manager.drawer_links


class TestDrawerModel:
    def test_unlinked_location_needs_no_drawer(self) -> None:
        manager = manager_with(drawer_file())

        manager.get_coordinate("bench")

    def test_linked_location_with_unknown_position_is_refused(self) -> None:
        manager = manager_with(drawer_file())

        with pytest.raises(DrawerNotAtStopError, match="unknown position"):
            manager.get_coordinate("sample_plate")

    def test_linked_location_with_drawer_elsewhere_is_refused(self) -> None:
        manager = discovered()
        manager.apply_locations_data(drawer_file())
        manager.set_drawer_position("plate2", 350)

        with pytest.raises(
            DrawerNotAtStopError,
            match=r"'sample_plate' needs drawer 'plate2' at stop 'work_a'.*at 350 mm",
        ):
            manager.get_coordinate("sample_plate")

    def test_linked_location_with_drawer_at_its_stop_is_allowed(self) -> None:
        manager = discovered()
        manager.apply_locations_data(drawer_file())
        manager.seed_drawer_positions({"plate2": 120.08})  # within park_tol

        manager.get_coordinate("probe")

    def test_seeding_replaces_the_model(self) -> None:
        manager = manager_with(drawer_file())
        manager.set_drawer_position("plate2", 0)

        manager.seed_drawer_positions({})

        with pytest.raises(DrawerNotAtStopError, match="unknown position"):
            manager.get_coordinate("sample_plate")

    def test_link_to_undefined_drawer_is_refused(self) -> None:
        data = drawer_file()
        del data["drawers"]
        manager = manager_with(data)
        manager.set_drawer_position("plate2", 0)

        with pytest.raises(DrawerNotAtStopError, match="not defined"):
            manager.get_coordinate("sample_plate")

    def test_drawer_rejected_by_klipper_is_refused(self) -> None:
        data = drawer_file()
        data["drawers"]["plate2"]["stops"]["work_b"] = 200
        manager = manager_with(data)
        manager.set_axis_config(KLIPPER)
        manager.set_drawer_position("plate2", 200)

        with pytest.raises(DrawerNotAtStopError, match=r"not within 0.1 mm"):
            manager.get_coordinate("probe")

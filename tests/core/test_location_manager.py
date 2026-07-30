"""Unit tests for :mod:`tricca_autopipette.core.location_manager`.

This class previously had no direct unit tests -- coverage was indirect, via
``tests/daemon/test_service_configuration.py``. These focus on the load
semantics: additive merge, single-location unload, duplicate-name handling, and
the guarantee that a failed load leaves the existing deck untouched.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.location_manager import LocationManager
from tricca_autopipette.core.plates import PlateParams, TipBox
from tricca_autopipette.core.well import StrategyType, Well


@pytest.fixture
def locations_dir(tmp_path: Path) -> Path:
    """A scratch locations directory, so tests never touch the real config."""
    return tmp_path


@pytest.fixture
def manager(locations_dir: Path) -> LocationManager:
    return LocationManager(locations_dir)


def _write(directory: Path, name: str, payload: dict[str, Any]) -> str:
    """Write a locations file and return its filename."""
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")
    return name


def _coord_file(names: list[str]) -> dict[str, Any]:
    return {
        "coordinates": [
            {"name": name, "x": 10.0 + i, "y": 20.0, "z": 5.0}
            for i, name in enumerate(names)
        ]
    }


def _tipbox_entry(name: str, cols: int = 3, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": name,
        "type": "tipbox",
        "x": 150.0,
        "y": 20.0,
        "z": 5.0,
        "num_row": 1,
        "num_col": cols,
        "spacing_col": 9.0,
        "dip_top": 5.0,
    }
    entry.update(extra)
    return entry


# ==================== Additive loading ====================


class TestAdditiveLoading:
    def test_load_is_additive_by_default(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """The headline change: groups compose instead of replacing."""
        _write(locations_dir, "a.json", _coord_file(["bench", "rack"]))
        _write(locations_dir, "b.json", _coord_file(["sink"]))

        manager.load_from_json("a.json")
        manager.load_from_json("b.json")

        assert sorted(manager.get_all_names()) == ["bench", "rack", "sink"]

    def test_replace_clears_first(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        _write(locations_dir, "b.json", _coord_file(["sink"]))

        manager.load_from_json("a.json")
        manager.load_from_json("b.json", replace=True)

        assert manager.get_all_names() == ["sink"]

    def test_load_group_composes_in_order(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        _write(locations_dir, "b.json", _coord_file(["sink"]))

        manager.load_group(["a.json", "b.json"])

        assert sorted(manager.get_all_names()) == ["bench", "sink"]

    def test_load_group_is_atomic(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """One bad file must not leave a half-built deck."""
        _write(locations_dir, "a.json", _coord_file(["bench"]))

        with pytest.raises(FileNotFoundError):
            manager.load_group(["a.json", "missing.json"])

        assert manager.get_all_names() == []

    def test_empty_file_loads_cleanly(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """config/locations/default_locations.json is literally `{}`."""
        _write(locations_dir, "empty.json", {})
        manager.load_from_json("empty.json")

        assert manager.get_all_names() == []


# ==================== Failure is non-destructive ====================


class TestFailedLoadPreservesState:
    def test_missing_file_leaves_deck_intact(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """Regression: load used to clear() before checking the file existed."""
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        manager.load_from_json("a.json")

        with pytest.raises(FileNotFoundError):
            manager.load_from_json("nope.json")

        assert manager.get_all_names() == ["bench"]

    def test_invalid_json_leaves_deck_intact(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        manager.load_from_json("a.json")
        (locations_dir / "bad.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid JSON"):
            manager.load_from_json("bad.json")

        assert manager.get_all_names() == ["bench"]

    def test_malformed_entry_leaves_deck_intact(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """Validation happens before any entry is applied, not per-entry."""
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        manager.load_from_json("a.json")
        _write(
            locations_dir,
            "partial.json",
            {
                "coordinates": [
                    {"name": "good", "x": 1.0, "y": 2.0, "z": 3.0},
                    {"name": "bad", "x": 1.0, "y": 2.0},  # missing z
                ]
            },
        )

        with pytest.raises(ValueError, match="Invalid coordinate"):
            manager.load_from_json("partial.json")

        assert manager.get_all_names() == ["bench"]

    def test_replace_load_that_fails_keeps_old_deck(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """Even the destructive mode validates before clearing."""
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        manager.load_from_json("a.json")

        with pytest.raises(FileNotFoundError):
            manager.load_from_json("nope.json", replace=True)

        assert manager.get_all_names() == ["bench"]

    def test_non_object_json_rejected(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        (locations_dir / "list.json").write_text("[1, 2]", encoding="utf-8")

        with pytest.raises(ValueError, match="must contain a JSON object"):
            manager.load_from_json("list.json")

    def test_entry_without_name_rejected(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """Names are identifiers, so a nameless entry is unusable."""
        _write(locations_dir, "x.json", {"coordinates": [{"x": 1, "y": 2, "z": 3}]})

        with pytest.raises(ValueError, match="needs a non-empty 'name'"):
            manager.load_from_json("x.json")


# ==================== Duplicate names ====================


class TestDuplicateNames:
    def test_last_load_wins(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(
            locations_dir,
            "a.json",
            {"coordinates": [{"name": "bench", "x": 1.0, "y": 1.0, "z": 1.0}]},
        )
        _write(
            locations_dir,
            "b.json",
            {"coordinates": [{"name": "bench", "x": 9.0, "y": 9.0, "z": 9.0}]},
        )

        manager.load_from_json("a.json")
        manager.load_from_json("b.json")

        assert manager.get_coordinate("bench") == Coordinate(x=9.0, y=9.0, z=9.0)

    def test_duplicate_warns_naming_both_sources(
        self,
        manager: LocationManager,
        locations_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Silently retargeting a pipetting step would be dangerous."""
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        _write(locations_dir, "b.json", _coord_file(["bench"]))

        manager.load_from_json("a.json")
        with caplog.at_level(logging.WARNING):
            manager.load_from_json("b.json")

        assert "bench" in caplog.text
        assert "a.json" in caplog.text
        assert "b.json" in caplog.text

    def test_no_warning_without_collision(
        self,
        manager: LocationManager,
        locations_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        _write(locations_dir, "b.json", _coord_file(["sink"]))

        manager.load_from_json("a.json")
        with caplog.at_level(logging.WARNING):
            manager.load_from_json("b.json")

        assert "overwrites" not in caplog.text

    def test_source_is_recorded(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(locations_dir, "deck_a.json", _coord_file(["bench"]))
        manager.load_from_json("deck_a.json")

        assert manager.source_of("bench") == "deck_a.json"

    def test_source_is_none_for_interactive_locations(
        self, manager: LocationManager
    ) -> None:
        manager.set_coordinate("adhoc", Coordinate(x=1.0, y=2.0, z=3.0))
        assert manager.source_of("adhoc") is None


# ==================== Unloading ====================


class TestUnload:
    def test_unload_removes_one_location(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(locations_dir, "a.json", _coord_file(["bench", "rack"]))
        manager.load_from_json("a.json")

        assert manager.unload("bench") is True
        assert manager.get_all_names() == ["rack"]

    def test_unload_unknown_returns_false(self, manager: LocationManager) -> None:
        assert manager.unload("nope") is False

    def test_unload_clears_provenance(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(locations_dir, "a.json", _coord_file(["bench"]))
        manager.load_from_json("a.json")
        manager.unload("bench")

        assert manager.source_of("bench") is None

    def test_unload_one_tipbox_keeps_the_others(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """The capability the old merged-box design made impossible."""
        _write(
            locations_dir,
            "tips.json",
            {"plates": [_tipbox_entry("tips_a"), _tipbox_entry("tips_b")]},
        )
        manager.load_from_json("tips.json")
        manager.tipbox_manager.next_tip()

        assert manager.unload("tips_a") is True
        assert manager.tipbox_manager.names() == ["tips_b"]
        assert manager.tipbox_manager.remaining == 3

    def test_unload_waste_container_clears_reference(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(
            locations_dir,
            "w.json",
            {
                "plates": [
                    {
                        "name": "bin",
                        "type": "waste_container",
                        "x": 10.0,
                        "y": 20.0,
                        "z": 5.0,
                        "dip_top": 5.0,
                    }
                ]
            },
        )
        manager.load_from_json("w.json")
        assert manager.waste_container is not None

        manager.unload("bin")
        assert manager.waste_container is None

    def test_waste_container_is_not_aliased_under_a_second_name(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """A waste container used to be filed under its name *and* the literal
        key ``"waste_container"``.

        That inflated `ls`, wrote the container twice on save, and made
        ``del_loc waste_container`` raise KeyError -- ``remove_location``
        popped the alias key and then popped ``name`` (the same key) again.
        """
        _write(
            locations_dir,
            "w.json",
            {
                "plates": [
                    {
                        "name": "bin",
                        "type": "waste_container",
                        "x": 10.0,
                        "y": 20.0,
                        "z": 5.0,
                        "dip_top": 5.0,
                    }
                ]
            },
        )
        manager.load_from_json("w.json")

        assert manager.get_all_names() == ["bin"]
        # Formerly a KeyError rather than a clean "no such location".
        assert manager.unload("waste_container") is False
        assert manager.has_location("bin")

    def test_waste_container_saves_as_one_entry(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """The alias made save_to_json emit two plates for one container."""
        _write(
            locations_dir,
            "w.json",
            {
                "plates": [
                    {
                        "name": "bin",
                        "type": "waste_container",
                        "x": 10.0,
                        "y": 20.0,
                        "z": 5.0,
                        "dip_top": 5.0,
                    }
                ]
            },
        )
        manager.load_from_json("w.json")
        manager.save_to_json("out.json")

        saved = json.loads((locations_dir / "out.json").read_text(encoding="utf-8"))
        assert [p["name"] for p in saved["plates"]] == ["bin"]

    def test_a_coordinate_may_be_named_waste_container(
        self, manager: LocationManager
    ) -> None:
        """The alias silently clobbered any user location with that name."""
        manager.set_coordinate("waste_container", Coordinate(x=1.0, y=2.0, z=3.0))
        manager.set_plate(
            "bin",
            PlateParams(
                plate_type="waste_container",
                well_template=Well(
                    coor=Coordinate(x=10.0, y=20.0, z=5.0),
                    dip_top=5.0,
                    strategy_type=StrategyType.SIMPLE,
                ),
            ),
        )

        assert isinstance(manager.locations["waste_container"], Coordinate)
        assert manager.waste_container is manager.locations["bin"]


# ==================== Traversal, masks, and tip state ====================


class TestPlateOptions:
    def test_order_loads_from_a_preset_name(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(
            locations_dir,
            "t.json",
            {
                "plates": [
                    _tipbox_entry("tips", cols=12, order="column_from_bottom_right")
                ]
            },
        )
        manager.load_from_json("t.json")

        box = manager.locations["tips"]
        assert isinstance(box, TipBox)
        assert box.sequence[0] == 11

    def test_mask_loads(self, manager: LocationManager, locations_dir: Path) -> None:
        _write(
            locations_dir,
            "t.json",
            {"plates": [_tipbox_entry("tips", cols=12, mask={"include": ["A1:A6"]})]},
        )
        manager.load_from_json("t.json")

        box = manager.locations["tips"]
        assert isinstance(box, TipBox)
        assert box.capacity == 6

    def test_partially_used_tipbox_loads(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """An operator can declare a half-used box in the config."""
        _write(
            locations_dir,
            "t.json",
            {"plates": [_tipbox_entry("tips", cols=12, tips={"consumed": ["A1:A3"]})]},
        )
        manager.load_from_json("t.json")

        assert manager.tipbox_manager.remaining == 9
        assert manager.tipbox_manager.peek_tip() == ("tips", 3)

    def test_tips_on_a_non_tipbox_rejected(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(
            locations_dir,
            "t.json",
            {
                "plates": [
                    {
                        "name": "plate",
                        "type": "array",
                        "x": 150.0,
                        "y": 20.0,
                        "z": 5.0,
                        "num_row": 1,
                        "num_col": 3,
                        "dip_top": 5.0,
                        "tips": {"consumed": ["A1"]},
                    }
                ]
            },
        )

        with pytest.raises(ValueError, match="not a tipbox"):
            manager.load_from_json("t.json")

    def test_invalid_order_name_names_the_plate(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(
            locations_dir,
            "t.json",
            {"plates": [_tipbox_entry("tips", order="sideways")]},
        )

        with pytest.raises(ValueError, match="Invalid plate 'tips'"):
            manager.load_from_json("t.json")


# ==================== Save round-trip ====================


class TestSaveRoundTrip:
    def test_traversal_options_survive_a_round_trip(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """Dropping these on save is the same class of bug as 'platearray'."""
        _write(
            locations_dir,
            "t.json",
            {
                "plates": [
                    _tipbox_entry(
                        "tips",
                        cols=12,
                        order="column_from_bottom_right",
                        mask={"include": ["A1:A6"]},
                    )
                ]
            },
        )
        manager.load_from_json("t.json")
        manager.save_to_json("out.json")

        reloaded = LocationManager(locations_dir)
        reloaded.load_from_json("out.json")

        original = manager.locations["tips"]
        restored = reloaded.locations["tips"]
        assert isinstance(original, TipBox)
        assert isinstance(restored, TipBox)
        assert restored.order == original.order
        assert restored.sequence == original.sequence

    def test_consumed_tips_survive_a_round_trip(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        _write(locations_dir, "t.json", {"plates": [_tipbox_entry("tips", cols=12)]})
        manager.load_from_json("t.json")
        for _ in range(3):
            manager.tipbox_manager.next_tip()

        manager.save_to_json("out.json")
        reloaded = LocationManager(locations_dir)
        reloaded.load_from_json("out.json")

        assert reloaded.tipbox_manager.remaining == 9

    def test_default_plate_saves_without_traversal_noise(
        self, manager: LocationManager, locations_dir: Path
    ) -> None:
        """A file that used no traversal options round-trips unchanged."""
        _write(
            locations_dir,
            "t.json",
            {
                "plates": [
                    {
                        "name": "plate",
                        "type": "array",
                        "x": 150.0,
                        "y": 20.0,
                        "z": 5.0,
                        "num_row": 1,
                        "num_col": 3,
                        "dip_top": 5.0,
                    }
                ]
            },
        )
        manager.load_from_json("t.json")
        manager.save_to_json("out.json")

        saved = json.loads((locations_dir / "out.json").read_text(encoding="utf-8"))
        entry = saved["plates"][0]
        assert "order" not in entry
        assert "mask" not in entry
        assert "on_exhaust" not in entry

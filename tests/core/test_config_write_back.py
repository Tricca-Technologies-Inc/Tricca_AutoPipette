"""Config write-back (issue #33, slice a).

Every test runs against a scratch copy of the repo's real ``config/`` tree as
the *shared* root and an empty scratch *local* root, both under ``tmp_path``
via monkeypatched `DefaultPaths` -- nothing here reads or writes the real
``~/.config`` or the repo's ``config/``.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tricca_autopipette.core.config_writer import set_config_value
from tricca_autopipette.core.location_manager import LocationManager
from tricca_autopipette.core.pipette_constants import DefaultPaths

REPO_CONFIG = DefaultPaths.DIR_CONFIG

_CATEGORY_ATTRS = {
    "system": ("DIR_CONFIG_SYSTEM", "DIR_LOCAL_SYSTEM"),
    "gantry": ("DIR_CONFIG_GANTRY", "DIR_LOCAL_GANTRY"),
    "pipettes": ("DIR_CONFIG_PIPETTE", "DIR_LOCAL_PIPETTE"),
    "liquids": ("DIR_CONFIG_LIQUIDS", "DIR_LOCAL_LIQUIDS"),
    "locations": ("DIR_CONFIG_LOCATIONS", "DIR_LOCAL_LOCATIONS"),
    "plates": ("DIR_CONFIG_PLATES", "DIR_LOCAL_PLATES"),
}


@dataclass
class Roots:
    """The scratch shared/local roots a test runs against."""

    shared: Path
    local: Path


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Roots:
    shared = tmp_path / "shared"
    local = tmp_path / "local"
    shutil.copytree(REPO_CONFIG, shared)
    local.mkdir()
    for category, (shared_attr, local_attr) in _CATEGORY_ATTRS.items():
        monkeypatch.setattr(DefaultPaths, shared_attr, shared / category)
        monkeypatch.setattr(DefaultPaths, local_attr, local / category)
    return Roots(shared, local)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_files(category: str) -> list[str]:
    return sorted(p.name for p in (REPO_CONFIG / category).glob("*.json"))


class TestLocationsRoundTrip:
    @pytest.mark.parametrize("filename", _repo_files("locations"))
    def test_load_then_save_reproduces_the_file(
        self, roots: Roots, filename: str
    ) -> None:
        manager = LocationManager()
        manager.load_from_json(filename)

        manager.save_to_json(filename)

        saved = roots.local / "locations" / filename
        assert _read(saved) == _read(roots.shared / "locations" / filename)

    def test_template_references_and_unknown_keys_survive(self, roots: Roots) -> None:
        deck = {
            "coordinates": [{"name": "home", "x": 1, "y": 2, "z": 3, "note": "hi"}],
            "plates": [
                {
                    "name": "p",
                    "plate_file": "96_well_standard.json",
                    "x": 150,
                    "y": 20,
                    "z": 5,
                    "operator_label": "rack 2",
                }
            ],
        }
        (roots.local / "locations").mkdir()
        (roots.local / "locations" / "deck.json").write_text(json.dumps(deck))
        manager = LocationManager()
        manager.load_from_json("deck.json")

        manager.save_to_json("out.json")

        assert _read(roots.local / "locations" / "out.json") == deck

    def test_tipbox_tips_block_reflects_current_consumption(self, roots: Roots) -> None:
        manager = LocationManager()
        manager.load_from_json("examples_deck.json")
        manager.tipbox_manager.set_consumed("example_tipbox", {0, 1})

        manager.save_to_json("out.json")

        saved = _read(roots.local / "locations" / "out.json")
        tipbox = next(p for p in saved["plates"] if p["name"] == "example_tipbox")
        assert tipbox["tips"] == {"consumed": ["A1:A2"]}


class TestSetConfigValue:
    def test_shared_only_file_is_copied_into_local_then_edited(
        self, roots: Roots
    ) -> None:
        shared_file = roots.shared / "liquids" / "water.json"
        shared_before = shared_file.read_bytes()

        written = set_config_value("liquids", "water.json", "density_g_ml", 1.2)

        assert written == roots.local / "liquids" / "water.json"
        expected = {**json.loads(shared_before), "density_g_ml": 1.2}
        assert _read(written) == expected
        assert list(_read(written)) == list(expected)  # key order kept
        assert shared_file.read_bytes() == shared_before

    @pytest.mark.parametrize(
        ("category", "filename", "key_path", "value"),
        [
            ("liquids", "water.json", "density_g_ml", "dense"),
            ("gantry", "default_gantry.json", "speed_xy", -5),
            ("pipettes", "default_pipette.json", "syringe", "nope"),
            ("locations", "examples_deck.json", "plates.0.num_row", "two"),
            ("plates", "96_well_standard.json", "num_col", "twelve"),
        ],
    )
    def test_write_that_would_not_load_is_rejected_and_nothing_is_written(
        self, roots: Roots, category: str, filename: str, key_path: str, value: Any
    ) -> None:
        with pytest.raises(ValueError, match="would not load"):
            set_config_value(category, filename, key_path, value)

        assert not (roots.local / category / filename).exists()

    @pytest.mark.parametrize(
        ("category", "filename", "key_path"),
        [
            ("liquids", "water.json", "speed_aspirat"),
            ("gantry", "default_gantry.json", "sped_xy"),
            ("pipettes", "default_pipette.json", "syringe.max_volum_ul"),
        ],
    )
    def test_new_key_the_model_does_not_define_is_rejected(
        self, roots: Roots, category: str, filename: str, key_path: str
    ) -> None:
        with pytest.raises(ValueError, match="Unknown key"):
            set_config_value(category, filename, key_path, 1.0)

        assert not (roots.local / category / filename).exists()

    def test_existing_key_the_model_does_not_define_stays_editable(
        self, roots: Roots
    ) -> None:
        water = {**_read(roots.shared / "liquids" / "water.json"), "note": "old"}
        (roots.local / "liquids").mkdir()
        (roots.local / "liquids" / "water.json").write_text(json.dumps(water))

        written = set_config_value("liquids", "water.json", "note", "new")

        assert _read(written)["note"] == "new"

    def test_rejected_write_leaves_an_existing_local_file_untouched(
        self, roots: Roots
    ) -> None:
        local_file = set_config_value("liquids", "water.json", "density_g_ml", 1.2)
        before = local_file.read_bytes()

        with pytest.raises(ValueError, match="would not load"):
            set_config_value("liquids", "water.json", "density_g_ml", "dense")

        assert local_file.read_bytes() == before


class TestSystemWrites:
    @pytest.fixture
    def system_dir(self, roots: Roots) -> Path:
        system_dir = roots.local / "system"
        system_dir.mkdir()
        shutil.copy(roots.shared / "system" / "default_system.json", system_dir)
        return system_dir

    def test_extends_is_preserved_not_flattened(self, system_dir: Path) -> None:
        child = {"extends": "default_system.json", "network": {"hostname": "a"}}
        (system_dir / "child.json").write_text(json.dumps(child))

        set_config_value("system", "child.json", "network.hostname", "rig7")

        assert _read(system_dir / "child.json") == {
            "extends": "default_system.json",
            "network": {"hostname": "rig7"},
        }

    def test_unloadable_system_write_is_rejected(self, system_dir: Path) -> None:
        before = (system_dir / "default_system.json").read_bytes()

        with pytest.raises(ValueError, match="would not load"):
            set_config_value("system", "default_system.json", "pipette", "no_such")

        assert (system_dir / "default_system.json").read_bytes() == before

    def test_writes_through_the_active_symlink(self, system_dir: Path) -> None:
        (system_dir / "active.json").symlink_to("default_system.json")

        set_config_value("system", "active.json", "system_name", "Rig 7")

        assert (system_dir / "active.json").is_symlink()
        assert _read(system_dir / "default_system.json")["system_name"] == "Rig 7"

    def test_new_top_level_key_the_model_lacks_is_rejected(
        self, system_dir: Path
    ) -> None:
        with pytest.raises(ValueError, match="systm_name"):
            set_config_value("system", "default_system.json", "systm_name", "x")

    def test_new_known_keys_are_accepted(self, system_dir: Path) -> None:
        set_config_value("system", "default_system.json", "locations", "a.json")
        set_config_value("system", "default_system.json", "liquids.water", {})
        set_config_value(
            "system", "default_system.json", "liquids.water.speed_aspirate", 5.0
        )

        saved = _read(system_dir / "default_system.json")
        assert saved["liquids"] == {"water": {"speed_aspirate": 5.0}}

    def test_new_key_in_a_system_liquid_override_is_checked(
        self, system_dir: Path
    ) -> None:
        set_config_value("system", "default_system.json", "liquids.water", {})

        with pytest.raises(ValueError, match="speed_aspirat"):
            set_config_value(
                "system", "default_system.json", "liquids.water.speed_aspirat", 5.0
            )

    def test_never_reads_the_shared_system_template(self, roots: Roots) -> None:
        with pytest.raises(FileNotFoundError):
            set_config_value("system", "default_system.json", "system_name", "x")


class TestRejectedArguments:
    def test_path_like_filename_is_rejected(self, roots: Roots) -> None:
        with pytest.raises(ValueError, match="bare filename"):
            set_config_value("liquids", "../liquids/water.json", "name", "x")

    def test_missing_intermediate_key_is_rejected(self, roots: Roots) -> None:
        with pytest.raises(ValueError, match="no_such"):
            set_config_value("pipettes", "default_pipette.json", "no_such.x", 1)

    def test_protocols_are_not_a_config_category(self, roots: Roots) -> None:
        with pytest.raises(ValueError, match="category"):
            set_config_value("protocols", "a.pipette", "x", 1)


_ALL_FILES = [
    (category, filename)
    for category in ("system", "gantry", "pipettes", "liquids", "locations", "plates")
    for filename in _repo_files(category)
]


class TestRoundTripFidelity:
    """Load every file under config/, save it through the writer, reload."""

    @pytest.mark.parametrize(("category", "filename"), _ALL_FILES)
    def test_no_op_write_reproduces_every_file(
        self, roots: Roots, category: str, filename: str
    ) -> None:
        shared_file = roots.shared / category / filename
        original = _read(shared_file)
        if category == "system":  # system/ is local-only; start from a copy
            (roots.local / "system").mkdir()
            shutil.copy(shared_file, roots.local / "system")
        if not original:  # e.g. an empty locations file: nothing to set
            pytest.skip(f"{filename} has no keys")
        key = next(iter(original))

        written = set_config_value(category, filename, key, original[key])

        assert _read(written) == original


class TestHighRiskBounds:
    """Pipette and gantry fields refuse an out-of-bounds edit (#33 slice c)."""

    @pytest.fixture
    def system(self, roots: Roots) -> dict[str, Any]:
        (roots.local / "system").mkdir()
        shutil.copy2(
            roots.shared / "system" / "default_system.json", roots.local / "system"
        )
        return _read(roots.shared / "system" / "default_system.json")

    def test_an_out_of_bounds_pipette_value_is_refused_and_nothing_written(
        self, roots: Roots
    ) -> None:
        with pytest.raises(ValueError, match="max_volume_ul"):
            set_config_value(
                "pipettes", "p100_vertical.json", "syringe.max_volume_ul", 5000.0
            )

        assert not (roots.local / "pipettes" / "p100_vertical.json").exists()

    def test_an_in_bounds_pipette_value_is_written(self, roots: Roots) -> None:
        path = set_config_value(
            "pipettes", "p100_vertical.json", "syringe.max_volume_ul", 90.0
        )

        assert _read(path)["syringe"]["max_volume_ul"] == 90.0  # ruff:ignore[float-equality-comparison]

    def test_a_gantry_file_value_is_bounded(self, roots: Roots) -> None:
        with pytest.raises(ValueError, match="accel_z"):
            set_config_value("gantry", "default_gantry.json", "accel_z", 1e9)

    @pytest.mark.usefixtures("system")
    def test_gantry_bounds_apply_through_a_system_file_too(self) -> None:
        with pytest.raises(ValueError, match="speed_xy"):
            set_config_value("system", "default_system.json", "gantry.speed_xy", 5e5)

    def test_a_whole_block_write_is_checked_field_by_field(
        self, system: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError, match="speed_z"):
            set_config_value(
                "system",
                "default_system.json",
                "gantry",
                {**system["gantry"], "speed_z": 1e9},
            )

    def test_low_risk_liquid_fields_have_no_bounds(self, roots: Roots) -> None:
        path = set_config_value("liquids", "water.json", "speed_aspirate", 5000.0)

        assert _read(path)["speed_aspirate"] == 5000.0  # ruff:ignore[float-equality-comparison]

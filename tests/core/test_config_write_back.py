"""Config write-back (issue #33, slice a).

Every test runs against a scratch copy of the repo's real ``config/`` tree as
the *shared* root and an empty scratch *local* root, both under ``tmp_path``
via monkeypatched `DefaultPaths` -- nothing here reads or writes the real
``~/.config`` or the repo's ``config/``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

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


class Roots:
    """The scratch shared/local roots a test runs against."""

    def __init__(self, shared: Path, local: Path) -> None:
        self.shared = shared
        self.local = local


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

    def test_tipbox_tips_block_reflects_current_consumption(
        self, roots: Roots
    ) -> None:
        manager = LocationManager()
        manager.load_from_json("examples_deck.json")
        manager.tipbox_manager.set_consumed("example_tipbox", {0, 1})

        manager.save_to_json("out.json")

        saved = _read(roots.local / "locations" / "out.json")
        tipbox = next(p for p in saved["plates"] if p["name"] == "example_tipbox")
        assert tipbox["tips"] == {"consumed": ["A1:A2"]}

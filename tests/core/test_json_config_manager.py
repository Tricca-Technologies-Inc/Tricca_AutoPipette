"""Tests for system-config inheritance and the ``locations`` section.

``extends`` exists so a per-protocol system config carries only what differs --
usually just ``locations`` -- instead of duplicating gantry, network, and
pipette settings that would then drift out of sync with the machine's.

These tests write scratch config files into the real ``config/system/``
directory (there is no injection point for it -- `JsonConfigManager` resolves
against `DefaultPaths.DIR_CONFIG_SYSTEM` at call time) and remove them
afterwards, so filenames are prefixed to avoid colliding with real configs.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tricca_autopipette.core.json_config_manager import JsonConfigManager
from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_models import LocationsConfig

PREFIX = "pytest_tmp_"

#: Every shape the ``locations`` key accepts, and the source list it becomes.
_NORMALIZATION_CASES: list[tuple[Any, list[Any]]] = [
    (None, []),
    ({}, []),
    ("deck.json", ["deck.json"]),
    ([], []),
    (["a.json", "b.json"], ["a.json", "b.json"]),
    ({"plates": []}, [{"plates": []}]),
]


@pytest.fixture
def write_system_config() -> Iterator[Any]:
    """Write scratch system configs, cleaning them up afterwards."""
    written: list[Path] = []

    def _write(name: str, payload: dict[str, Any]) -> str:
        filename = f"{PREFIX}{name}"
        path = DefaultPaths.DIR_CONFIG_SYSTEM / filename
        path.write_text(json.dumps(payload), encoding="utf-8")
        written.append(path)
        return filename

    yield _write

    for path in written:
        path.unlink(missing_ok=True)


class TestExtends:
    def test_child_inherits_parent_fields(self, write_system_config: Any) -> None:
        """The point of extends: don't copy machine settings per protocol."""
        write_system_config(
            "parent.json",
            {
                "system_name": "Machine",
                "gantry": {"speed_xy": 1234.0},
                "pipette": "p100_vertical",
                "network": {"hostname": "bench.local", "port": "7125"},
            },
        )
        child = write_system_config(
            "child.json", {"extends": f"{PREFIX}parent.json", "system_name": "Protocol"}
        )

        config = JsonConfigManager().load_system_config(child)

        assert config.system_name == "Protocol"  # child wins
        # inherited; exact JSON round-trip of a literal, not a computed value
        assert config.gantry.speed_xy == 1234.0  # ruff:ignore[float-equality-comparison]
        assert config.network["hostname"] == "bench.local"  # inherited

    def test_child_overrides_parent(self, write_system_config: Any) -> None:
        write_system_config(
            "parent.json", {"gantry": {"speed_xy": 1000.0}, "pipette": "p100_vertical"}
        )
        child = write_system_config(
            "child.json",
            {"extends": f"{PREFIX}parent.json", "gantry": {"speed_xy": 9999.0}},
        )

        config = JsonConfigManager().load_system_config(child)

        # Exact JSON round-trip of a literal, not a computed value.
        assert config.gantry.speed_xy == 9999.0  # ruff:ignore[float-equality-comparison]

    def test_multi_level_chain(self, write_system_config: Any) -> None:
        write_system_config("a.json", {"system_name": "A", "pipette": "p100_vertical"})
        write_system_config(
            "b.json", {"extends": f"{PREFIX}a.json", "gantry": {"speed_z": 42.0}}
        )
        child = write_system_config("c.json", {"extends": f"{PREFIX}b.json"})

        config = JsonConfigManager().load_system_config(child)

        assert config.system_name == "A"
        # Exact JSON round-trip of a literal, not a computed value.
        assert config.gantry.speed_z == 42.0  # ruff:ignore[float-equality-comparison]

    def test_nearest_ancestor_wins(self, write_system_config: Any) -> None:
        """A grandparent must not override the parent."""
        write_system_config("a.json", {"system_name": "grandparent"})
        write_system_config(
            "b.json", {"extends": f"{PREFIX}a.json", "system_name": "parent"}
        )
        child = write_system_config("c.json", {"extends": f"{PREFIX}b.json"})

        config = JsonConfigManager().load_system_config(child)

        assert config.system_name == "parent"

    def test_cycle_raises_rather_than_recursing(self, write_system_config: Any) -> None:
        write_system_config("x.json", {"extends": f"{PREFIX}y.json"})
        write_system_config("y.json", {"extends": f"{PREFIX}x.json"})

        with pytest.raises(ValueError, match="Cyclic 'extends'"):
            JsonConfigManager().load_system_config(f"{PREFIX}x.json")

    def test_self_reference_raises(self, write_system_config: Any) -> None:
        child = write_system_config("self.json", {"extends": f"{PREFIX}self.json"})

        with pytest.raises(ValueError, match="Cyclic 'extends'"):
            JsonConfigManager().load_system_config(child)

    def test_missing_parent_raises(self, write_system_config: Any) -> None:
        child = write_system_config("orphan.json", {"extends": "does_not_exist.json"})

        with pytest.raises(FileNotFoundError):
            JsonConfigManager().load_system_config(child)

    def test_non_string_extends_raises(self, write_system_config: Any) -> None:
        child = write_system_config("bad.json", {"extends": ["a.json"]})

        with pytest.raises(ValueError, match="must be a filename string"):
            JsonConfigManager().load_system_config(child)

    def test_extends_key_is_not_leaked_into_config(
        self, write_system_config: Any
    ) -> None:
        write_system_config("parent.json", {"pipette": "p100_vertical"})
        child = write_system_config("child.json", {"extends": f"{PREFIX}parent.json"})

        config = JsonConfigManager().load_system_config(child)

        assert not hasattr(config, "extends")

    def test_config_without_extends_still_loads(self) -> None:
        """The existing default config must be unaffected."""
        config = JsonConfigManager().load_system_config()
        assert config.system_name == "TAP-Tyson"


class TestLocationsSection:
    def test_absent_locations_is_empty(self) -> None:
        """Preserves today's boot: fall back to default_locations.json."""
        config = JsonConfigManager().load_system_config()
        assert config.locations.is_empty()

    def test_filename_string(self, write_system_config: Any) -> None:
        child = write_system_config(
            "loc.json", {"pipette": "p100_vertical", "locations": "deck_a.json"}
        )

        config = JsonConfigManager().load_system_config(child)

        assert config.locations.sources == ["deck_a.json"]

    def test_inline_payload(self, write_system_config: Any) -> None:
        payload = {"coordinates": [{"name": "bench", "x": 1, "y": 2, "z": 3}]}
        child = write_system_config(
            "loc.json", {"pipette": "p100_vertical", "locations": payload}
        )

        config = JsonConfigManager().load_system_config(child)

        assert config.locations.sources == [payload]

    def test_mixed_list(self, write_system_config: Any) -> None:
        """A shared deck file plus a protocol-specific inline override."""
        inline: dict[str, Any] = {"plates": []}
        child = write_system_config(
            "loc.json",
            {"pipette": "p100_vertical", "locations": ["standard_deck.json", inline]},
        )

        config = JsonConfigManager().load_system_config(child)

        assert config.locations.sources == ["standard_deck.json", inline]

    def test_locations_are_inherited_through_extends(
        self, write_system_config: Any
    ) -> None:
        write_system_config(
            "parent.json", {"pipette": "p100_vertical", "locations": "shared.json"}
        )
        child = write_system_config("child.json", {"extends": f"{PREFIX}parent.json"})

        config = JsonConfigManager().load_system_config(child)

        assert config.locations.sources == ["shared.json"]

    def test_child_locations_replace_parent(self, write_system_config: Any) -> None:
        """The whole point: inherit the machine, override the deck."""
        write_system_config(
            "parent.json", {"pipette": "p100_vertical", "locations": "shared.json"}
        )
        child = write_system_config(
            "child.json",
            {"extends": f"{PREFIX}parent.json", "locations": "assay_a.json"},
        )

        config = JsonConfigManager().load_system_config(child)

        assert config.locations.sources == ["assay_a.json"]

    def test_invalid_locations_type_raises(self, write_system_config: Any) -> None:
        child = write_system_config(
            "loc.json", {"pipette": "p100_vertical", "locations": 42}
        )

        with pytest.raises(ValueError, match="must be a filename, an object"):
            JsonConfigManager().load_system_config(child)


class TestLocationsConfigNormalization:
    """`LocationsConfig` accepts three shapes; all normalize to a source list."""

    @pytest.mark.parametrize(("value", "expected"), _NORMALIZATION_CASES)
    def test_normalization(self, value: Any, expected: list[Any]) -> None:
        assert LocationsConfig.model_validate(value).sources == expected

    def test_default_construction_is_empty(self) -> None:
        """An empty mapping must not become one empty inline source."""
        assert LocationsConfig().sources == []
        assert LocationsConfig().is_empty()

    def test_round_trips_through_dump(self) -> None:
        original = LocationsConfig.model_validate(["a.json", {"plates": []}])
        assert (
            LocationsConfig.model_validate(original.model_dump()).sources
            == original.sources
        )

"""Tests for ``JsonConfigManager``: loading, merging, and gap-fill coverage.

``extends`` exists so a per-protocol system config carries only what differs --
usually just ``locations`` -- instead of duplicating gantry, network, and
pipette settings that would then drift out of sync with the machine's.

These tests write scratch config files into the real ``config/system/``,
``config/gantry/``, ``config/pipettes/``, and ``config/liquids/`` directories
(there is no injection point for them -- `JsonConfigManager` resolves against
`DefaultPaths.DIR_CONFIG_*` at call time) and remove them afterwards, so
filenames are prefixed to avoid colliding with real configs. The handful of
tests that need a *missing* directory (`_load_default_pipettes`/
`_load_default_liquids`'s "directory not found" branches, and the
`_load_default_gantry` `FileNotFoundError`) monkeypatch the relevant
`DefaultPaths.DIR_CONFIG_*` constant to an isolated `tmp_path` instead, since
that can't be expressed by adding scratch files to a directory that already
exists and already has real defaults in it.
"""

from __future__ import annotations

import itertools
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tricca_autopipette.core.json_config_manager import (
    MAX_EXTENDS_DEPTH,
    JsonConfigManager,
)
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


def _scratch_writer(directory: Path) -> Iterator[Any]:
    """Shared body for the ``write_*_config`` fixtures below.

    Yields a ``(name, payload) -> filename`` writer that prefixes each
    filename and tracks it for cleanup once the test using it finishes.
    """
    written: list[Path] = []

    def _write(name: str, payload: dict[str, Any]) -> str:
        filename = f"{PREFIX}{name}"
        path = directory / filename
        path.write_text(json.dumps(payload), encoding="utf-8")
        written.append(path)
        return filename

    yield _write

    for path in written:
        path.unlink(missing_ok=True)


@pytest.fixture
def write_system_config() -> Iterator[Any]:
    """Write scratch system configs, cleaning them up afterwards."""
    yield from _scratch_writer(DefaultPaths.DIR_CONFIG_SYSTEM)


@pytest.fixture
def write_gantry_config() -> Iterator[Any]:
    """Write scratch gantry configs, cleaning them up afterwards."""
    yield from _scratch_writer(DefaultPaths.DIR_CONFIG_GANTRY)


@pytest.fixture
def write_pipette_config() -> Iterator[Any]:
    """Write scratch pipette configs, cleaning them up afterwards."""
    yield from _scratch_writer(DefaultPaths.DIR_CONFIG_PIPETTE)


@pytest.fixture
def write_liquid_config() -> Iterator[Any]:
    """Write scratch liquid configs, cleaning them up afterwards."""
    yield from _scratch_writer(DefaultPaths.DIR_CONFIG_LIQUIDS)


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


class TestGetSystemConfig:
    def test_raises_without_a_loaded_config(self) -> None:
        with pytest.raises(RuntimeError, match="No system configuration loaded"):
            JsonConfigManager().get_system_config()

    def test_returns_the_loaded_config(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        assert manager.get_system_config() is manager.system_config


class TestLoadConfigs:
    """``load_configs`` only dynamically re-loads gantry/pipette/liquids when

    their filename differs from the module's own default constant --
    otherwise ``load_system_config`` alone already covered it.
    """

    def test_default_filenames_load_only_the_system_config(self) -> None:
        manager = JsonConfigManager()

        config = manager.load_configs()

        assert config is manager.system_config

    def test_custom_gantry_filename_triggers_a_dynamic_load(
        self, write_gantry_config: Any
    ) -> None:
        gantry_name = write_gantry_config("gantry.json", {"speed_xy": 4242.0})
        manager = JsonConfigManager()

        manager.load_configs(fn_gantry=gantry_name)

        assert manager.system_config is not None
        # Exact JSON round-trip of a literal, not a computed value.
        assert manager.system_config.gantry.speed_xy == 4242.0  # ruff:ignore[float-equality-comparison]

    def test_custom_pipette_filename_triggers_a_dynamic_load(
        self, write_pipette_config: Any
    ) -> None:
        pipette_name = write_pipette_config(
            "pipette.json", {"name": "Custom", "syringe": {}, "servo": {}}
        )
        manager = JsonConfigManager()

        manager.load_configs(fn_pipette=pipette_name)

        assert manager.system_config is not None
        assert manager.system_config.pipette.name == "Custom"

    def test_custom_liquids_filename_triggers_a_dynamic_load(
        self, write_liquid_config: Any
    ) -> None:
        liquid_name = write_liquid_config("liquid.json", {"name": "extra_liquid"})
        manager = JsonConfigManager()

        manager.load_configs(fn_liquids=liquid_name)

        assert manager.system_config is not None
        assert "extra_liquid" in manager.system_config.liquids


class TestLoadSystemConfigMissingFile:
    def test_missing_top_level_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="System config not found"):
            JsonConfigManager().load_system_config(f"{PREFIX}does_not_exist.json")


class TestPipetteResolution:
    def test_unknown_pipette_reference_raises(self, write_system_config: Any) -> None:
        child = write_system_config(
            "bad_pipette.json", {"pipette": "not_a_real_pipette"}
        )

        with pytest.raises(ValueError, match="Unknown pipette"):
            JsonConfigManager().load_system_config(child)

    def test_inline_full_pipette_config_is_used_directly(
        self, write_system_config: Any
    ) -> None:
        inline_pipette: dict[str, Any] = {
            "name": "InlinePipette",
            "syringe": {},
            "servo": {},
        }
        child = write_system_config("inline_pipette.json", {"pipette": inline_pipette})

        config = JsonConfigManager().load_system_config(child)

        assert config.pipette.name == "InlinePipette"


class TestLiquidMerging:
    def test_user_only_liquid_is_added_alongside_defaults(
        self, write_system_config: Any
    ) -> None:
        child = write_system_config(
            "extra_liquid.json",
            {
                "pipette": "p100_vertical",
                "liquids": {"my_custom_liquid": {"name": "my_custom_liquid"}},
            },
        )

        config = JsonConfigManager().load_system_config(child)

        assert "my_custom_liquid" in config.liquids
        assert "water" in config.liquids  # defaults are still present


class TestExtendsDepthGuard:
    def test_chain_deeper_than_max_depth_raises(self, write_system_config: Any) -> None:
        # Build a straight (acyclic) chain one link longer than
        # MAX_EXTENDS_DEPTH, so the depth guard trips rather than the cycle
        # guard. The file the last link's `extends` points to is never
        # actually read (the guard fires before that read), so it need not
        # exist.
        names = [
            write_system_config(f"depth_{i}.json", {})
            for i in range(MAX_EXTENDS_DEPTH + 1)
        ]
        for child_name, parent_name in itertools.pairwise(names):
            path = DefaultPaths.DIR_CONFIG_SYSTEM / child_name
            path.write_text(json.dumps({"extends": parent_name}))
        last_path = DefaultPaths.DIR_CONFIG_SYSTEM / names[-1]
        last_path.write_text(json.dumps({"extends": "unreachable.json"}))

        with pytest.raises(ValueError, match="deeper than"):
            JsonConfigManager().load_system_config(names[0])


class TestExtendsValidation:
    def test_non_string_extends_in_an_ancestor_raises(
        self, write_system_config: Any
    ) -> None:
        write_system_config("mid.json", {"extends": 123})
        child = write_system_config("child.json", {"extends": f"{PREFIX}mid.json"})

        with pytest.raises(ValueError, match="must be a filename string"):
            JsonConfigManager().load_system_config(child)


class TestReadSystemFile:
    def test_invalid_json_raises_value_error(self) -> None:
        path = DefaultPaths.DIR_CONFIG_SYSTEM / f"{PREFIX}invalid.json"
        path.write_text("{not valid json")
        try:
            with pytest.raises(ValueError, match="Invalid JSON"):
                JsonConfigManager().load_system_config(path.name)
        finally:
            path.unlink(missing_ok=True)

    def test_non_object_json_raises_value_error(self) -> None:
        path = DefaultPaths.DIR_CONFIG_SYSTEM / f"{PREFIX}array.json"
        path.write_text("[1, 2, 3]")
        try:
            with pytest.raises(ValueError, match="must contain a JSON object"):
                JsonConfigManager().load_system_config(path.name)
        finally:
            path.unlink(missing_ok=True)


class TestLoadGantry:
    def test_raises_without_a_loaded_system_config(self) -> None:
        with pytest.raises(RuntimeError, match="No system config loaded"):
            JsonConfigManager().load_gantry()

    def test_missing_file_raises(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        with pytest.raises(FileNotFoundError, match="Gantry config not found"):
            manager.load_gantry(f"{PREFIX}does_not_exist.json")

    def test_invalid_json_raises_value_error(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        path = DefaultPaths.DIR_CONFIG_GANTRY / f"{PREFIX}invalid.json"
        path.write_text("{not valid json")
        try:
            with pytest.raises(ValueError, match="Invalid JSON"):
                manager.load_gantry(path.name)
        finally:
            path.unlink(missing_ok=True)

    def test_validation_failure_raises_value_error(
        self, write_gantry_config: Any
    ) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        name = write_gantry_config("bad.json", {"speed_xy": -1.0})  # gt=0 violated

        with pytest.raises(ValueError, match="Gantry config validation failed"):
            manager.load_gantry(name)

    def test_success_updates_the_active_gantry(self, write_gantry_config: Any) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        name = write_gantry_config("fast.json", {"speed_xy": 9999.0})

        gantry = manager.load_gantry(name)

        # Exact JSON round-trip of a literal, not a computed value.
        assert gantry.speed_xy == 9999.0  # ruff:ignore[float-equality-comparison]
        assert manager.system_config is not None
        assert manager.system_config.gantry is gantry


class TestLoadPipette:
    def test_raises_without_a_loaded_system_config(self) -> None:
        with pytest.raises(RuntimeError, match="No system config loaded"):
            JsonConfigManager().load_pipette()

    def test_missing_file_raises(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        with pytest.raises(FileNotFoundError, match="Pipette config not found"):
            manager.load_pipette(f"{PREFIX}does_not_exist.json")

    def test_invalid_json_raises_value_error(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        path = DefaultPaths.DIR_CONFIG_PIPETTE / f"{PREFIX}invalid.json"
        path.write_text("{not valid json")
        try:
            with pytest.raises(ValueError, match="Invalid JSON"):
                manager.load_pipette(path.name)
        finally:
            path.unlink(missing_ok=True)

    def test_validation_failure_raises_value_error(
        self, write_pipette_config: Any
    ) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        name = write_pipette_config("bad.json", {"syringe": {}, "servo": {}})  # no name

        with pytest.raises(ValueError, match="Pipette config validation failed"):
            manager.load_pipette(name)

    def test_success_updates_the_active_pipette(
        self, write_pipette_config: Any
    ) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        name = write_pipette_config(
            "custom.json", {"name": "Custom", "syringe": {}, "servo": {}}
        )

        pipette = manager.load_pipette(name)

        assert pipette.name == "Custom"
        assert manager.system_config is not None
        assert manager.system_config.pipette is pipette


class TestLoadLiquid:
    def test_raises_without_a_loaded_system_config(self) -> None:
        with pytest.raises(RuntimeError, match="No system config loaded"):
            JsonConfigManager().load_liquid()

    def test_missing_file_raises(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        with pytest.raises(FileNotFoundError, match="Liquid config not found"):
            manager.load_liquid(f"{PREFIX}does_not_exist.json")

    def test_invalid_json_raises_value_error(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        path = DefaultPaths.DIR_CONFIG_LIQUIDS / f"{PREFIX}invalid.json"
        path.write_text("{not valid json")
        try:
            with pytest.raises(ValueError, match="Invalid JSON"):
                manager.load_liquid(path.name)
        finally:
            path.unlink(missing_ok=True)

    def test_validation_failure_raises_value_error(
        self, write_liquid_config: Any
    ) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        name = write_liquid_config("bad.json", {})  # missing required "name"

        with pytest.raises(ValueError, match="Liquid config validation failed"):
            manager.load_liquid(name)

    def test_success_adds_the_liquid_without_activating_it(
        self, write_liquid_config: Any
    ) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()
        name = write_liquid_config("acetone.json", {"name": "acetone"})

        liquid = manager.load_liquid(name)

        assert liquid.name == "acetone"
        assert manager.system_config is not None
        assert manager.system_config.liquids["acetone"] is liquid


class TestSwitchLiquid:
    def test_raises_without_a_loaded_system_config(self) -> None:
        with pytest.raises(RuntimeError, match="No system config loaded"):
            JsonConfigManager().switch_liquid("water")

    def test_unknown_liquid_raises_value_error(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        with pytest.raises(ValueError, match="not loaded"):
            manager.switch_liquid("not_a_real_liquid")

    def test_known_liquid_returns_its_profile(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        profile = manager.switch_liquid("water")

        assert profile.name == "water"


class TestGetActiveLiquidName:
    def test_always_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            JsonConfigManager().get_active_liquid_name()


class TestListAvailablePipettes:
    def test_lists_real_default_pipette_file_stems(self) -> None:
        pipettes = JsonConfigManager().list_available_pipettes()

        assert pipettes == sorted(pipettes)
        assert "p100_vertical" in pipettes

    def test_missing_directory_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            DefaultPaths, "DIR_CONFIG_PIPETTE", tmp_path / "does_not_exist"
        )

        assert JsonConfigManager().list_available_pipettes() == []


class TestListAvailableLiquids:
    def test_no_config_loaded_returns_empty_list(self) -> None:
        assert JsonConfigManager().list_available_liquids() == []

    def test_loaded_config_returns_sorted_liquid_names(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        liquids = manager.list_available_liquids()

        assert liquids == sorted(liquids)
        assert "water" in liquids


class TestHasLiquid:
    def test_no_config_loaded_returns_false(self) -> None:
        assert JsonConfigManager().has_liquid("water") is False

    def test_loaded_config_reports_presence(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        assert manager.has_liquid("water") is True
        assert manager.has_liquid("not_a_real_liquid") is False


class TestGetCurrentConfig:
    def test_raises_without_a_loaded_config(self) -> None:
        with pytest.raises(RuntimeError, match="No system config loaded"):
            JsonConfigManager().get_current_config()

    def test_returns_the_loaded_config(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        assert manager.get_current_config() is manager.system_config


class TestGetMergedSyringeParamsErrors:
    """The happy path is covered incidentally by `AutoPipette` fixtures --

    only the two guard branches need direct coverage here.
    """

    def test_raises_without_a_loaded_config(self) -> None:
        with pytest.raises(RuntimeError, match="No system config loaded"):
            JsonConfigManager().get_merged_syringe_params("water")

    def test_unknown_liquid_raises_value_error(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        with pytest.raises(ValueError, match="not found"):
            manager.get_merged_syringe_params("not_a_real_liquid")


class TestLoadDefaultGantry:
    def test_missing_default_file_raises_file_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(DefaultPaths, "DIR_CONFIG_GANTRY", tmp_path)

        with pytest.raises(FileNotFoundError, match="Default gantry"):
            JsonConfigManager()._load_default_gantry()


class TestLoadDefaultPipettes:
    def test_missing_directory_returns_empty_and_warns(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            DefaultPaths, "DIR_CONFIG_PIPETTE", tmp_path / "does_not_exist"
        )

        with caplog.at_level(logging.WARNING):
            result = JsonConfigManager()._load_default_pipettes()

        assert result == {}
        assert any("not found" in r.message for r in caplog.records)

    def test_a_malformed_file_is_skipped_and_logged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (tmp_path / "good.json").write_text(
            json.dumps({"name": "Good", "syringe": {}, "servo": {}})
        )
        (tmp_path / "bad.json").write_text("{not valid json")
        monkeypatch.setattr(DefaultPaths, "DIR_CONFIG_PIPETTE", tmp_path)

        with caplog.at_level(logging.ERROR):
            result = JsonConfigManager()._load_default_pipettes()

        assert set(result) == {"good"}
        assert any("bad.json" in r.message for r in caplog.records)


class TestLoadDefaultLiquids:
    def test_missing_directory_returns_empty_and_warns(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            DefaultPaths, "DIR_CONFIG_LIQUIDS", tmp_path / "does_not_exist"
        )

        with caplog.at_level(logging.WARNING):
            result = JsonConfigManager()._load_default_liquids()

        assert result == {}
        assert any("not found" in r.message for r in caplog.records)

    def test_a_malformed_file_is_skipped_and_logged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (tmp_path / "good.json").write_text(json.dumps({"name": "good_liquid"}))
        (tmp_path / "bad.json").write_text("{not valid json")
        monkeypatch.setattr(DefaultPaths, "DIR_CONFIG_LIQUIDS", tmp_path)

        with caplog.at_level(logging.ERROR):
            result = JsonConfigManager()._load_default_liquids()

        assert set(result) == {"good_liquid"}
        assert any("bad.json" in r.message for r in caplog.records)


class TestRepr:
    def test_reflects_unloaded_state(self) -> None:
        assert repr(JsonConfigManager()) == "JsonConfigManager(system_loaded=False)"

    def test_reflects_loaded_state(self) -> None:
        manager = JsonConfigManager()
        manager.load_system_config()

        assert repr(manager) == "JsonConfigManager(system_loaded=True)"

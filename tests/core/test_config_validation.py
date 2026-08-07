"""Unit tests for ``core/config_validation.py``'s ``validate_config_files``.

Monkeypatches the module's ``DIR_CONFIG_*``/``CONFIG_SYSTEM`` constants to a
``tmp_path`` tree rather than touching the repo's real ``config/`` directory,
so these tests can freely create missing files, wrong-type paths (a
directory where a file is expected), etc.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from tricca_autopipette.core import config_validation


@pytest.fixture
def config_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Redirect every ``DIR_CONFIG_*`` constant into an isolated ``tmp_path`` tree.

    Returns:
        Mapping of config kind (``"system"``/``"gantry"``/``"pipette"``/
        ``"locations"``/``"liquids"``) to its (already-created, empty)
        directory under ``tmp_path``.
    """
    dirs = {
        "system": tmp_path / "system",
        "gantry": tmp_path / "gantry",
        "pipette": tmp_path / "pipettes",
        "locations": tmp_path / "locations",
        "liquids": tmp_path / "liquids",
    }
    for directory in dirs.values():
        directory.mkdir()
    monkeypatch.setattr(config_validation, "DIR_CONFIG_SYSTEM", dirs["system"])
    monkeypatch.setattr(config_validation, "DIR_CONFIG_GANTRY", dirs["gantry"])
    monkeypatch.setattr(config_validation, "DIR_CONFIG_PIPETTE", dirs["pipette"])
    monkeypatch.setattr(config_validation, "DIR_CONFIG_LOCATIONS", dirs["locations"])
    monkeypatch.setattr(config_validation, "DIR_CONFIG_LIQUIDS", dirs["liquids"])
    monkeypatch.setattr(config_validation, "CONFIG_SYSTEM", "default_system.json")
    return dirs


def _validate(**overrides: str | None) -> None:
    defaults: dict[str, str | None] = {
        "config_system": None,
        "config_gantry": None,
        "config_pipette": None,
        "config_locations": None,
        "config_liquids": None,
    }
    defaults.update(overrides)
    config_validation.validate_config_files(**defaults)  # type: ignore[arg-type]


class TestSystemConfig:
    def test_missing_default_system_file_raises(
        self, config_dirs: dict[str, Path]
    ) -> None:
        with pytest.raises(FileNotFoundError, match=re.escape("default_system.json")):
            _validate()

    def test_default_system_file_present_passes(
        self, config_dirs: dict[str, Path]
    ) -> None:
        (config_dirs["system"] / "default_system.json").write_text("{}")

        _validate()  # must not raise

    def test_explicit_system_filename_resolves_under_the_system_dir(
        self, config_dirs: dict[str, Path]
    ) -> None:
        (config_dirs["system"] / "custom.json").write_text("{}")

        _validate(config_system="custom.json")  # must not raise

    def test_missing_explicit_system_file_raises(
        self, config_dirs: dict[str, Path]
    ) -> None:
        with pytest.raises(FileNotFoundError, match=re.escape("missing.json")):
            _validate(config_system="missing.json")

    def test_system_path_that_is_a_directory_raises_value_error(
        self, config_dirs: dict[str, Path]
    ) -> None:
        (config_dirs["system"] / "a_directory.json").mkdir()

        with pytest.raises(ValueError, match="not a file"):
            _validate(config_system="a_directory.json")


@pytest.mark.parametrize(
    ("kwarg", "dir_key"),
    [
        ("config_gantry", "gantry"),
        ("config_pipette", "pipette"),
        ("config_locations", "locations"),
        ("config_liquids", "liquids"),
    ],
)
class TestOptionalConfigs:
    def test_none_is_skipped_entirely(
        self, config_dirs: dict[str, Path], kwarg: str, dir_key: str
    ) -> None:
        (config_dirs["system"] / "default_system.json").write_text("{}")
        # The optional dir stays empty -- if validation tried to check it
        # anyway, this would raise.

        _validate(**{kwarg: None})  # must not raise

    def test_missing_named_file_raises(
        self, config_dirs: dict[str, Path], kwarg: str, dir_key: str
    ) -> None:
        (config_dirs["system"] / "default_system.json").write_text("{}")

        with pytest.raises(FileNotFoundError, match=re.escape("nope.json")):
            _validate(**{kwarg: "nope.json"})

    def test_present_named_file_passes(
        self, config_dirs: dict[str, Path], kwarg: str, dir_key: str
    ) -> None:
        (config_dirs["system"] / "default_system.json").write_text("{}")
        (config_dirs[dir_key] / "present.json").write_text("{}")

        _validate(**{kwarg: "present.json"})  # must not raise

    def test_path_that_is_a_directory_raises_value_error(
        self, config_dirs: dict[str, Path], kwarg: str, dir_key: str
    ) -> None:
        (config_dirs["system"] / "default_system.json").write_text("{}")
        (config_dirs[dir_key] / "a_directory.json").mkdir()

        with pytest.raises(ValueError, match="not a file"):
            _validate(**{kwarg: "a_directory.json"})


class TestLogging:
    def test_logs_info_for_every_validated_file(
        self,
        config_dirs: dict[str, Path],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (config_dirs["system"] / "default_system.json").write_text("{}")
        (config_dirs["gantry"] / "g.json").write_text("{}")

        with caplog.at_level(logging.INFO):
            _validate(config_gantry="g.json")

        messages = [r.message for r in caplog.records]
        assert any("default_system.json" in m for m in messages)
        assert any("g.json" in m for m in messages)

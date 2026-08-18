"""Unit tests for ``core/config_validation.py``'s ``validate_config_files``.

Monkeypatches `DefaultPaths`' ``DIR_CONFIG_*``/``DIR_LOCAL_*`` constants to a
``tmp_path`` tree rather than touching the repo's real ``config/``/local-root
directories, so these tests can freely create missing files, wrong-type paths
(a directory where a file is expected), etc.

``config_system`` isn't covered here -- it's no longer this function's
concern (issue #68); see ``tests/daemon/test_main.py``'s coverage of
``resolve_system_config`` instead.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from tricca_autopipette.core import config_validation
from tricca_autopipette.core.pipette_constants import DefaultPaths


@pytest.fixture
def config_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    """Redirect every relevant shared/local `DefaultPaths` dir into ``tmp_path``.

    Returns:
        Mapping of config kind (``"gantry"``/``"pipette"``/``"locations"``/
        ``"liquids"``) to its (already-created, empty) shared directory under
        ``tmp_path``. The matching local dirs are also redirected (to a
        sibling, never-created directory), so `LocalConfigRoots.resolve`'s
        "missing local root is empty" fallback is exercised the same way it
        would be in production.
    """
    dirs = {
        "gantry": tmp_path / "gantry",
        "pipette": tmp_path / "pipettes",
        "locations": tmp_path / "locations",
        "liquids": tmp_path / "liquids",
    }
    for directory in dirs.values():
        directory.mkdir()
    monkeypatch.setattr(DefaultPaths, "DIR_CONFIG_GANTRY", dirs["gantry"])
    monkeypatch.setattr(DefaultPaths, "DIR_CONFIG_PIPETTE", dirs["pipette"])
    monkeypatch.setattr(DefaultPaths, "DIR_CONFIG_LOCATIONS", dirs["locations"])
    monkeypatch.setattr(DefaultPaths, "DIR_CONFIG_LIQUIDS", dirs["liquids"])
    monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_GANTRY", tmp_path / "local_gantry")
    monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_PIPETTE", tmp_path / "local_pipettes")
    monkeypatch.setattr(
        DefaultPaths, "DIR_LOCAL_LOCATIONS", tmp_path / "local_locations"
    )
    monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_LIQUIDS", tmp_path / "local_liquids")
    return dirs


def _validate(**overrides: str | None) -> None:
    defaults: dict[str, str | None] = {
        "config_gantry": None,
        "config_pipette": None,
        "config_locations": None,
        "config_liquids": None,
    }
    defaults.update(overrides)
    config_validation.validate_config_files(**defaults)  # type: ignore[arg-type]


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
        # The dir stays empty -- if validation tried to check it anyway,
        # this would raise.
        _validate(**{kwarg: None})  # must not raise

    def test_missing_named_file_raises(
        self, config_dirs: dict[str, Path], kwarg: str, dir_key: str
    ) -> None:
        with pytest.raises(FileNotFoundError, match=re.escape("nope.json")):
            _validate(**{kwarg: "nope.json"})

    def test_present_named_file_passes(
        self, config_dirs: dict[str, Path], kwarg: str, dir_key: str
    ) -> None:
        (config_dirs[dir_key] / "present.json").write_text("{}")

        _validate(**{kwarg: "present.json"})  # must not raise

    def test_path_that_is_a_directory_raises_value_error(
        self, config_dirs: dict[str, Path], kwarg: str, dir_key: str
    ) -> None:
        (config_dirs[dir_key] / "a_directory.json").mkdir()

        with pytest.raises(ValueError, match="not a file"):
            _validate(**{kwarg: "a_directory.json"})


class TestLogging:
    def test_logs_info_for_every_validated_file(
        self,
        config_dirs: dict[str, Path],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        (config_dirs["gantry"] / "g.json").write_text("{}")

        with caplog.at_level(logging.INFO):
            _validate(config_gantry="g.json")

        messages = [r.message for r in caplog.records]
        assert any("g.json" in m for m in messages)

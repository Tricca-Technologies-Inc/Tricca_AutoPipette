"""Unit tests for the ``tap`` entry point, ``cli/main.py``.

Covers argument parsing only, matching the seam ``tests/daemon/test_main.py``
uses for ``tapd``'s ``parse_arguments``.
"""

from __future__ import annotations

import importlib.metadata

import pytest

from tricca_autopipette.cli import main as main_module


class TestParseArguments:
    def test_version_flag_prints_installed_package_version_and_exits(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.argv", ["tap", "--version"])

        with pytest.raises(SystemExit) as exc_info:
            main_module.parse_arguments()

        assert exc_info.value.code == 0
        installed_version = importlib.metadata.version("tricca-autopipette")
        assert installed_version in capsys.readouterr().out

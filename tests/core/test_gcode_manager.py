"""Unit tests for :class:`tricca_autopipette.core.gcode_manager.GCodeManager`."""

from __future__ import annotations

from pathlib import Path

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.gcode_manager import GCodeManager


@pytest.fixture
def gcode_manager(tmp_path: Path, autopipette: AutoPipette) -> GCodeManager:
    return GCodeManager(tmp_path, autopipette)


class TestImmediateMode:
    def test_write_gcode_file_creates_file_under_temp_dir(
        self, gcode_manager: GCodeManager, tmp_path: Path
    ) -> None:
        path = gcode_manager.write_gcode_file(["G28\n", "G1 X10 Y10\n"], "test.gcode")

        assert path == tmp_path / "temp" / "test.gcode"
        contents = path.read_text(encoding="utf-8")
        assert "G28" in contents
        assert "G1 X10 Y10" in contents

    def test_write_gcode_file_prepends_header_when_requested(
        self, gcode_manager: GCodeManager
    ) -> None:
        path = gcode_manager.write_gcode_file(
            ["G28\n"], "with_header.gcode", append_header=True
        )

        contents = path.read_text(encoding="utf-8")
        assert "AutoPipette Configuration" in contents

    def test_write_gcode_file_auto_generates_filename(
        self, gcode_manager: GCodeManager
    ) -> None:
        path = gcode_manager.write_gcode_file(["G28\n"])

        assert path.exists()
        assert path.suffix == ".gcode"


class TestBatchMode:
    def test_add_gcode_outside_batch_mode_raises_runtime_error(
        self, gcode_manager: GCodeManager
    ) -> None:
        assert gcode_manager.is_batch_mode is False

        with pytest.raises(RuntimeError, match="batch mode"):
            gcode_manager.add_gcode(["G28\n"])

    def test_batch_mode_accumulates_across_multiple_calls(
        self, gcode_manager: GCodeManager
    ) -> None:
        with gcode_manager.batch_mode():
            assert gcode_manager.is_batch_mode is True
            gcode_manager.add_gcode(["G28\n"])
            gcode_manager.add_gcode(["G1 X10 Y10\n"])

        # batch_mode()'s context manager turns batch mode back off on exit
        # (so a command issued right after the `with` block goes back to
        # immediate mode) but does NOT clear the buffer -- the caller is
        # expected to call get_buffer()/clear_buffer() explicitly.
        assert gcode_manager.is_batch_mode is False
        assert gcode_manager.get_buffer() == ["G28\n", "\n", "G1 X10 Y10\n", "\n"]

    def test_exiting_batch_mode_returns_to_immediate_mode(
        self, gcode_manager: GCodeManager
    ) -> None:
        # Regression test: batch_mode()'s `finally` used to be a bare
        # `pass`, so is_batch_mode stayed True forever after the first use
        # anywhere in the process -- every later command would silently
        # accumulate into the buffer instead of actually uploading.
        with gcode_manager.batch_mode():
            gcode_manager.add_gcode(["G28\n"])
        gcode_manager.clear_buffer()

        with pytest.raises(RuntimeError, match="batch mode"):
            gcode_manager.add_gcode(["G1 X10 Y10\n"])

    def test_get_buffer_does_not_clear(self, gcode_manager: GCodeManager) -> None:
        with gcode_manager.batch_mode():
            gcode_manager.add_gcode(["G28\n"])

        first = gcode_manager.get_buffer()
        second = gcode_manager.get_buffer()
        assert first == second == ["G28\n", "\n"]

    def test_clear_buffer_empties_it(self, gcode_manager: GCodeManager) -> None:
        with gcode_manager.batch_mode():
            gcode_manager.add_gcode(["G28\n"])

        gcode_manager.clear_buffer()

        assert gcode_manager.get_buffer() == []

    def test_start_batch_clears_any_prior_buffer(
        self, gcode_manager: GCodeManager
    ) -> None:
        with gcode_manager.batch_mode():
            gcode_manager.add_gcode(["G28\n"])

        gcode_manager.start_batch()

        assert gcode_manager.get_buffer() == []

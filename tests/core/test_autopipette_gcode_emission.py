"""Characterization test: the exact G-code text ``AutoPipette`` emits.

Pins the byte-for-byte output of every G-code emission site in
``core/autopipette.py`` as the file ``GCodeManager.write_gcode_file`` would
write it (each buffered entry ``rstrip("\\n")`` + ``"\\n"``), so migrating
those sites onto ``core/gcode_commands.py``'s ``GCodeCommands`` builders
(issue #30) provably changes nothing a Klipper machine would receive.

The golden file was captured from the hand-built f-string emitters before
that migration -- it is the independent source of truth here, not a
recomputation of what the builders do. One deliberate edit since: the old
``move_pipette_stepper`` emitted ``SPEED=`` before ``MOVE=`` while every
other ``MANUAL_STEPPER`` site emitted ``MOVE=`` first; the builder has one
fixed parameter order, so those two lines now read ``MOVE= SPEED=``.
Klipper parses extended parameters by name, so the machine sees no change.

A second deliberate edit, issue #29, *does* change what the machine sees:
``STOP_ON_ENDSTOP`` moved from Klipper's deprecated numeric aliases to the
documented strings (``1`` -> ``home``, ``-1`` -> ``inverted_home``, ``2`` ->
``try_home``, per ``klippy/extras/manual_stepper.py``'s own alias map), and
the homing/``clear_syringe`` distance moved from the volume-derived
``vol_to_steps(2 * max_volume_ul)`` (``499.034...``) to
``2 * max_travel_mm`` (``120.0`` for the shared 60 mm configs).

The comparison is exact on everything except the *value* of each number,
which is checked with ``math.isclose(rel_tol=1e-9)``. Stepper distances come
from the volume converter's numpy polyfit, whose last few float digits vary
with the numpy build and the platform's BLAS (x86 vs arm64 CI differ in
e.g. ``499.03429068615003`` vs ``499.0342906861499``) -- noise far below
anything a stepper can resolve, and not what this test guards. Each
number's *shape* (integer vs decimal) still has to match exactly, so a
formatting change like ``S100`` -> ``S100.0`` is still caught.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from pathlib import Path

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate

GOLDEN = Path(__file__).parents[1] / "fixtures" / "gcode" / "autopipette_emission.gcode"


_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def _as_written(entries: Sequence[str]) -> str:
    return "".join(entry.rstrip("\n") + "\n" for entry in entries)


def _split_numbers(text: str) -> tuple[str, list[float]]:
    """Split G-code text into a number-free skeleton and its numbers.

    Returns:
        The text with each number replaced by ``<int>``/``<dec>``, and the
        numbers themselves in order.
    """
    skeleton = _NUMBER.sub(lambda m: "<dec>" if m.group(1) else "<int>", text)
    return skeleton, [float(m.group(0)) for m in _NUMBER.finditer(text)]


def test_every_emission_site_emits_unchanged_gcode(
    pipette_with_plates: AutoPipette,
) -> None:
    ap = pipette_with_plates
    ap.get_gcode()  # drain anything buffered by setup

    ap.init_pipette()
    ap.set_coor_sys("relative")
    ap.set_speed_factor(150)
    ap.set_max_velocity(5000)
    ap.set_max_accel(3000)
    ap.home_x()
    ap.home_y()
    ap.home_z()
    ap.move_to_z(Coordinate(x=1, y=2, z=3))
    ap.gcode_print("hello world")
    ap.move_pipette_stepper(-4.5)
    ap.clear_syringe()
    ap.pipette(20.0, "plate_a", "plate_a")

    actual_text, actual_numbers = _split_numbers(_as_written(ap.get_gcode()))
    golden_text, golden_numbers = _split_numbers(GOLDEN.read_text(encoding="utf-8"))

    assert actual_text == golden_text
    assert len(actual_numbers) == len(golden_numbers)
    for index, (actual, golden) in enumerate(
        zip(actual_numbers, golden_numbers, strict=True)
    ):
        assert math.isclose(actual, golden, rel_tol=1e-9), (index, actual, golden)

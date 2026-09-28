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
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate

GOLDEN = Path(__file__).parents[1] / "fixtures" / "gcode" / "autopipette_emission.gcode"


def _as_written(entries: Sequence[str]) -> str:
    return "".join(entry.rstrip("\n") + "\n" for entry in entries)


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

    assert _as_written(ap.get_gcode()) == GOLDEN.read_text(encoding="utf-8")

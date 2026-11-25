"""Tests for the park and Z re-home after a tip goes into the waste.

Ported from Scott's Tyson tuning (218227a): after ejecting into the waste
the head parks clear of the deck and homes Z, so a skipped Z step from the
eject doesn't carry into the next transfer. Both are gantry fields.
"""

from __future__ import annotations

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_models import TipState


def _dispose(ap: AutoPipette) -> list[str]:
    """Dispose an attached tip.

    Returns:
        The G-code lines emitted, comments dropped.
    """
    ap.state.tip_state = TipState.ATTACHED
    ap.get_gcode()
    ap.dispose_tip()
    return [line.strip() for line in ap.get_gcode() if not line.startswith(";")]


def _off(ap: AutoPipette) -> list[str]:
    """Dispose with the park and Z home turned off, then turn them back on.

    Returns:
        The G-code lines emitted with both off.
    """
    park = ap.gantry.park_after_dispose
    ap.gantry.park_after_dispose = None
    ap.gantry.home_z_after_dispose = False
    lines = _dispose(ap)
    ap.gantry.park_after_dispose = park
    ap.gantry.home_z_after_dispose = True
    return lines


def test_dispose_parks_then_homes_z_by_default(
    pipette_with_plates: AutoPipette,
) -> None:
    ap = pipette_with_plates
    off = _off(ap)

    lines = _dispose(ap)

    # move_to travels XY, then Z.
    assert lines[: len(off)] == off
    assert [line.split(" F")[0] for line in lines[len(off) :]] == [
        "G1 X150.0 Y150.0",
        "G1 Z0.0",
        "G28 Z",
    ]


def test_the_park_position_is_configurable(pipette_with_plates: AutoPipette) -> None:
    ap = pipette_with_plates
    ap.gantry.park_after_dispose = Coordinate(x=10.0, y=20.0, z=0.0)

    assert _dispose(ap)[-3].startswith("G1 X10.0 Y20.0")


def test_both_can_be_turned_off(pipette_with_plates: AutoPipette) -> None:
    off = _off(pipette_with_plates)

    assert "G28 Z" not in off
    assert not any(line.startswith("G1 X150.0 Y150.0") for line in off)


def test_returning_a_tip_does_not_park(pipette_with_plates: AutoPipette) -> None:
    # No waste container: the tip goes back to its slot, nothing was ejected
    # into the waste, so there is nothing to recover from.
    ap = pipette_with_plates
    ap.next_tip()
    ap.location_manager.waste_container = None
    ap.get_gcode()

    ap.dispose_tip()

    assert "G28 Z" not in [line.strip() for line in ap.get_gcode()]

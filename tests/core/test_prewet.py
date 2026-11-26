"""Tests for the prewet sequence (Scott's Tyson technique, 35841ee/7c53d2c).

With prewet on, the tip draws the pre-gap as an air cushion, dips, runs the
prewet cycles, rises ``syringe.prewet_raise_mm`` above the dip (capped at
Z0) and pushes the cushion out there, clearing what the prewet left in the
tip. It then draws a fresh pre-gap and dips again for the real aspirate. A
prewet volume nobody set is the aspirate volume.
"""

from __future__ import annotations

from typing import Any

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.pipette_models import FluidDisplacement, TipState
from tricca_autopipette.core.plates import Plate

ASP = FluidDisplacement.aspiration
DISP = FluidDisplacement.dispense


def _record(ap: AutoPipette) -> list[tuple[Any, ...]]:
    """Log top-level dip, Z and syringe calls from here on.

    Returns:
        A list filling with ``(name, *args)``, coordinates reduced to Z.
    """
    calls: list[tuple[Any, ...]] = []
    depth = [0]
    for name in ("dip_z_down", "dip_z_return", "move_to_z", "operate_syringe"):
        original = getattr(ap, name)

        def wrapper(*args: Any, _n: str = name, _o: Any = original, **kw: Any) -> Any:
            if not depth[0]:
                calls.append((_n, *(getattr(a, "z", a) for a in args)))
            depth[0] += 1
            try:
                return _o(*args, **kw)
            finally:
                depth[0] -= 1

        setattr(ap, name, wrapper)
    return calls


def _depth(ap: AutoPipette, volume: float) -> tuple[float, float]:
    """Clearance and dip Z for aspirating `volume` from plate_a's A1.

    Returns:
        ``(clear_z, depth)``.
    """
    plate = ap.location_manager.locations["plate_a"]
    assert isinstance(plate, Plate)
    clear = ap.location_manager.get_coordinate("plate_a", 0, 0).z
    return clear, plate.get_dip_distance(volume)


def _aspirate(ap: AutoPipette, **kw: Any) -> list[tuple[Any, ...]]:
    ap.state.tip_state = TipState.ATTACHED
    calls = _record(ap)
    ap.aspirate_volume(
        20.0,
        "plate_a",
        src_row=0,
        src_col=0,
        pre_air_gap_ul=4.0,
        post_air_gap_ul=2.0,
        **kw,
    )
    return calls


def test_prewet_cushions_raises_and_expels_before_the_aspirate(
    pipette_with_plates: AutoPipette,
) -> None:
    ap = pipette_with_plates
    ap.pipette_model.syringe.prewet_raise_mm = 1.0
    clear, depth = _depth(ap, 20.0)

    calls = _aspirate(ap, prewet_cycles=1, prewet_vol_ul=8.0)

    assert calls == [
        ("operate_syringe", ASP, pytest.approx(4.0)),
        ("dip_z_down", clear, depth),
        ("operate_syringe", ASP, pytest.approx(8.0)),
        ("operate_syringe", DISP, pytest.approx(8.0)),
        ("move_to_z", depth - 1.0),
        ("operate_syringe", DISP, pytest.approx(4.0)),
        ("operate_syringe", ASP, pytest.approx(4.0)),
        ("dip_z_down", clear, depth),
        ("operate_syringe", ASP, pytest.approx(20.0)),
        ("dip_z_return", clear),
        ("operate_syringe", ASP, pytest.approx(2.0)),
    ]


def test_the_raise_stops_at_z0(pipette_with_plates: AutoPipette) -> None:
    # The default 30 mm is more than plate_a's dip, so it caps at Z0.
    calls = _aspirate(pipette_with_plates, prewet_cycles=1, prewet_vol_ul=8.0)

    assert ("move_to_z", 0.0) in calls


def test_an_unset_prewet_volume_is_the_aspirate_volume(
    pipette_with_plates: AutoPipette,
) -> None:
    calls = _aspirate(pipette_with_plates, prewet_cycles=2)

    prewets = [c[2] for c in calls if c[0] == "operate_syringe"][1:5]
    assert prewets == pytest.approx([20.0, 20.0, 20.0, 20.0])


def test_no_prewet_leaves_the_aspirate_unchanged(
    pipette_with_plates: AutoPipette,
) -> None:
    calls = _aspirate(pipette_with_plates, prewet_cycles=0)

    assert [c[0] for c in calls] == [
        "operate_syringe",
        "dip_z_down",
        "operate_syringe",
        "dip_z_return",
        "operate_syringe",
    ]


def test_pipette_prewets_each_chunk_with_its_own_volume(
    pipette_with_plates: AutoPipette,
) -> None:
    ap = pipette_with_plates
    ap.state.tip_state = TipState.ATTACHED
    calls = _record(ap)

    ap.pipette(150.0, "plate_a", "plate_a", prewet_cycles=1, tip_end="keep")

    # 98 uL budget: two chunks of 75, each prewet with 75.
    asp = [c[2] for c in calls if c[:2] == ("operate_syringe", ASP)]
    assert asp == pytest.approx([75.0, 75.0, 75.0, 75.0])

"""Tests for ``AutoPipette.dispense_to``, the one dispense path (issue #205).

Each target: hover just above the dispense depth and push out the
post-gap there, dip the rest of the way, dispense, rise and draw a fresh
post-gap. The last target instead pushes out the pre-gap (a full clear)
and draws nothing. Asking for more than the tip holds warns and dispenses
what is left; liquid left after the last target warns and goes to waste.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from tricca_autopipette.core.autopipette import AutoPipette, DispenseTarget
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_exceptions import NoWasteContainerError
from tricca_autopipette.core.pipette_models import FluidDisplacement, TipState
from tricca_autopipette.core.plates import Plate, PlateParams
from tricca_autopipette.core.well import StrategyType, Well

_RECORDED = (
    "dip_z_down",
    "move_to_z",
    "operate_syringe",
    "clear_syringe",
    "dip_z_return",
    "home_pipette_stepper",
    "empty_tip_to_waste",
)


def _record(ap: AutoPipette) -> list[tuple[Any, ...]]:
    """Log the top-level motion calls ``ap`` makes from here on.

    Returns:
        A list that fills with ``(name, *args)`` per call, in call order.
        Coordinates are reduced to their Z. Calls made inside a recorded
        call (``dip_z_down``'s own ``move_to_z``) are left out.
    """
    calls: list[tuple[Any, ...]] = []
    depth = [0]
    for name in _RECORDED:
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


def _filled(ap: AutoPipette, volume: float = 20.0) -> AutoPipette:
    """Aspirate `volume` with a 5 uL pre-gap and 2 uL post-gap.

    Returns:
        The same autopipette, holding the liquid.
    """
    # Travel at Z1, dips to Z20, so hover (Z18) and rise (Z18) are distinct.
    ap.location_manager.set_plate(
        "deep",
        PlateParams(
            plate_type="array",
            well_template=Well(
                coor=Coordinate(x=150.0, y=100.0, z=1.0),
                dip_top=20.0,
                strategy_type=StrategyType.SIMPLE,
            ),
            num_row=1,
            num_col=4,
            spacing_row=0.0,
            spacing_col=9.0,
        ),
    )
    ap.state.tip_state = TipState.ATTACHED
    ap.aspirate_volume(
        volume, "plate_a", src_row=0, src_col=0, pre_air_gap_ul=5.0, post_air_gap_ul=2.0
    )
    ap.get_gcode()
    return ap


def _depths(ap: AutoPipette, volume: float) -> tuple[float, float, float, float]:
    """Travel, hover, dispense and rise Z for a dispense of `volume`.

    Returns:
        ``(travel_z, hover_z, depth, rise_z)`` for ``deep``.
    """
    travel = ap.location_manager.get_coordinate("deep", 0, 1).z
    plate = ap.location_manager.locations["deep"]
    assert isinstance(plate, Plate)
    depth = plate.get_dip_distance(volume)
    model = ap.pipette_model
    return (
        travel,
        max(travel, depth - model.dispense_hover_mm),
        depth,
        max(travel, depth - model.dispense_rise_mm),
    )


DISP = FluidDisplacement.dispense
ASP = FluidDisplacement.aspiration


class TestSequence:
    def test_the_deep_plate_separates_every_height(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        travel, hover, depth, rise = _depths(_filled(pipette_with_plates), 20.0)

        assert (travel, hover, depth, rise) == pytest.approx((1.0, 18.0, 20.0, 18.0))

    def test_one_target_pushes_the_post_gap_at_hover_then_clears(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        ap = _filled(pipette_with_plates)
        travel, hover, depth, _ = _depths(ap, 20.0)
        calls = _record(ap)

        ap.dispense_to([DispenseTarget("deep", 0, 1, None)])

        assert calls == [
            ("dip_z_down", travel, hover),
            ("operate_syringe", DISP, pytest.approx(2.0)),
            ("dip_z_down", travel, depth),
            ("operate_syringe", DISP, pytest.approx(20.0)),
            ("clear_syringe",),
            ("dip_z_return", travel),
            ("home_pipette_stepper",),
        ]
        assert ap.state.has_liquid is False
        assert ap.state.liquid_ul == pytest.approx(0.0)

    def test_every_target_but_the_last_redraws_the_post_gap_on_the_way_up(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        ap = _filled(pipette_with_plates)
        travel, hover, depth, rise = _depths(ap, 12.0)
        _, hover8, depth8, _ = _depths(ap, 8.0)
        calls = _record(ap)

        ap.dispense_to([
            DispenseTarget("deep", 0, 1, 12.0),
            DispenseTarget("deep", 0, 1, 8.0),
        ])

        assert calls == [
            ("dip_z_down", travel, hover),
            ("operate_syringe", DISP, pytest.approx(2.0)),
            ("dip_z_down", travel, depth),
            ("operate_syringe", DISP, pytest.approx(12.0)),
            ("move_to_z", rise),
            ("operate_syringe", ASP, pytest.approx(2.0)),
            ("dip_z_return", travel),
            ("dip_z_down", travel, hover8),
            ("operate_syringe", DISP, pytest.approx(2.0)),
            ("dip_z_down", travel, depth8),
            ("operate_syringe", DISP, pytest.approx(8.0)),
            ("clear_syringe",),
            ("dip_z_return", travel),
            ("home_pipette_stepper",),
        ]


class TestVolumeChecks:
    def test_asking_for_more_than_the_tip_holds_warns_and_dispenses_the_rest(
        self, pipette_with_plates: AutoPipette, caplog: pytest.LogCaptureFixture
    ) -> None:
        ap = _filled(pipette_with_plates)
        calls = _record(ap)

        with caplog.at_level(logging.WARNING):
            ap.dispense_to([DispenseTarget("deep", 0, 1, 30.0)])

        assert "more than" in caplog.text
        dispensed = [c[2] for c in calls if c[:2] == ("operate_syringe", DISP)]
        assert dispensed == pytest.approx([2.0, 20.0])
        assert ap.state.has_liquid is False

    def test_liquid_left_after_the_last_target_warns_and_goes_to_waste(
        self, pipette_with_plates: AutoPipette, caplog: pytest.LogCaptureFixture
    ) -> None:
        ap = _filled(pipette_with_plates)
        calls = _record(ap)

        with caplog.at_level(logging.WARNING):
            ap.dispense_to([DispenseTarget("deep", 0, 1, 12.0)])

        assert "left in the tip" in caplog.text
        assert calls[-1] == ("empty_tip_to_waste",)
        # The one target isn't the last word, so it redraws its post-gap.
        assert ("operate_syringe", ASP, pytest.approx(2.0)) in calls
        assert ap.state.has_liquid is False

    def test_leftover_with_no_waste_container_raises_before_moving(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        ap = _filled(pipette_with_plates)
        ap.location_manager.waste_container = None

        with pytest.raises(NoWasteContainerError):
            ap.dispense_to([DispenseTarget("deep", 0, 1, 12.0)])

        assert ap.get_gcode() == []

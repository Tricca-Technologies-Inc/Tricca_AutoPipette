"""Stage-2 plunger: absolute ``G1 P`` moves from a compile-time model (issue #147).

With ``AutoPipette.plunger`` set (Klipper's bound P axis at stage 2), every
syringe operation becomes an absolute ``G1 P<target>`` bracketed by
``SET_VELOCITY_LIMIT ACCEL=``. The target is the model's position plus the
same signed travel stage 1 sends as a relative ``MANUAL_STEPPER`` move, so
aspiration is negative (D26). Stage 1 (``plunger`` None) is pinned by the
existing golden emission test.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.core.pipette_models import AbsolutePlunger, FluidDisplacement
from tricca_autopipette.core.volume_converter import VolumeConverter


@pytest.fixture
def ap(pipette_with_plates: AutoPipette) -> AutoPipette:
    """A stage-2 pipette at P0 with a 0.5 mm/μL curve (no intercept).

    Returns:
        ``pipette_with_plates`` with its plunger model set.
    """
    pipette_with_plates.volume_converter = VolumeConverter([0.0, 100.0], [0.0, 50.0])
    pipette_with_plates.plunger = AbsolutePlunger("P", -60.0, 0.0, 0.0)
    pipette_with_plates.get_gcode()
    return pipette_with_plates


def _lines(ap: AutoPipette) -> list[str]:
    return [g.rstrip("\n") for g in ap.get_gcode() if not g.startswith(";")]


def _p_moves(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("G1 P")]


class TestAbsoluteTargets:
    def test_transfer_steps_reach_expected_absolute_positions(
        self, ap: AutoPipette
    ) -> None:
        asp = ap.syringe.speed_aspirate * 60
        disp = ap.syringe.speed_dispense * 60

        ap.aspirate_volume(
            40.0, "plate_a", pre_air_gap_ul=10.0, post_air_gap_ul=0.0, prewet_cycles=0
        )
        ap.dispense_volume("plate_a", volume=20.0, empties_tip=False)
        ap.dispense_volume("plate_a")
        lines = _lines(ap)

        assert _p_moves(lines) == [
            f"G1 P-5.0 F{asp}",  # pre-aspirate air gap
            f"G1 P-25.0 F{asp}",  # liquid
            f"G1 P-15.0 F{disp}",  # metered dispense
            f"G1 P0.0 F{disp}",  # dispense the rest: back to the homed zero
        ]
        assert ap.plunger is not None
        assert ap.plunger.position_mm == pytest.approx(0.0)
        assert not any("MANUAL_STEPPER" in line for line in lines)

    def test_return_to_zero_before_aspirating_is_a_move_not_a_rehome(
        self, ap: AutoPipette
    ) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = -3.0

        ap.aspirate_volume(
            10.0, "plate_a", pre_air_gap_ul=0.0, post_air_gap_ul=0.0, prewet_cycles=0
        )

        assert _p_moves(_lines(ap))[:2] == [
            f"G1 P0.0 F{ap.syringe.speed_dispense * 60}",
            f"G1 P-5.0 F{ap.syringe.speed_aspirate * 60}",
        ]

    def test_last_travel_stays_the_unsigned_commanded_travel(
        self, ap: AutoPipette
    ) -> None:
        ap.operate_syringe(FluidDisplacement.aspiration, 30.0)

        assert ap.last_syringe_travel_mm == pytest.approx(15.0)


class TestAccelBracketing:
    def test_each_plunger_move_is_bracketed_and_gantry_accel_restored(
        self, ap: AutoPipette
    ) -> None:
        ap.set_max_accel(1234)
        ap.get_gcode()

        ap.operate_syringe(FluidDisplacement.aspiration, 10.0, accel=150)

        assert _lines(ap) == [
            "SET_VELOCITY_LIMIT ACCEL=150",
            f"G1 P-5.0 F{ap.syringe.speed_aspirate * 60}",
            "SET_VELOCITY_LIMIT ACCEL=1234",
        ]


class TestRefusals:
    def test_aspiration_past_the_lower_limit_is_refused_before_emission(
        self, ap: AutoPipette
    ) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = -50.0

        with pytest.raises(ValueError, match="outside"):
            ap.operate_syringe(FluidDisplacement.aspiration, 30.0)

        assert _lines(ap) == []
        assert ap.plunger.position_mm == pytest.approx(-50.0)

    def test_dispense_past_zero_is_refused_never_a_positive_target(
        self, ap: AutoPipette
    ) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = -5.0

        with pytest.raises(ValueError, match="outside"):
            ap.operate_syringe(FluidDisplacement.dispense, 20.0)

        assert _lines(ap) == []

    def test_positive_target_refused_even_if_klipper_allowed_it(
        self, ap: AutoPipette
    ) -> None:
        ap.plunger = AbsolutePlunger("P", -60.0, 60.0, 0.0)

        with pytest.raises(ValueError, match="outside"):
            ap.operate_syringe(FluidDisplacement.dispense, 2.0)

    def test_float_noise_at_a_limit_is_clamped_not_refused(
        self, ap: AutoPipette
    ) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = -10.0

        ap.operate_syringe(FluidDisplacement.dispense, 20.0 + 1e-9)

        assert _p_moves(_lines(ap)) == [f"G1 P0.0 F{ap.syringe.speed_dispense * 60}"]

    def test_unknown_position_refuses_with_not_homed(self, ap: AutoPipette) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = None

        with pytest.raises(NotHomedError, match="plunger not homed"):
            ap.operate_syringe(FluidDisplacement.aspiration, 10.0)


class TestHomingSetsTheModel:
    def test_g28_p_zeroes_the_model(self, ap: AutoPipette) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = None

        ap.home_pipette_motors("P")

        assert "G28 P" in _lines(ap)
        assert ap.plunger.position_mm == pytest.approx(0.0)

    def test_full_init_zeroes_the_model(self, ap: AutoPipette) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = None

        ap.init_pipette("P")

        assert ap.plunger.position_mm == pytest.approx(0.0)

"""Air gaps drawn while Z moves: coordinated ``G1 Z P`` moves (issue #148).

Opt-in at stage 2 via ``air_gap_rise_mm`` (flag > liquid > pipette > 0). The
pre-aspirate gap is drawn as Z descends from ``rise`` mm above the well's
clearance height (its location Z) to that height; the post-aspirate gap as Z
rises from it back up ``rise`` mm. Larger Z lowers the tip, so "at or above
the clearance height" means Z <= the location's Z.
"""

from __future__ import annotations

import itertools
import re

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.pipette_models import AbsolutePlunger, FluidDisplacement
from tricca_autopipette.core.volume_converter import VolumeConverter

CLEARANCE_Z = 5.0  # plate_a's well Z in the shared fixture
_COORDINATED = re.compile(r"G1 Z(\S+) P(\S+) F(\S+)")


@pytest.fixture
def ap(pipette_with_plates: AutoPipette) -> AutoPipette:
    """A stage-2 pipette at P0 with a 0.5 mm/μL curve.

    Returns:
        ``pipette_with_plates`` with its plunger model set.
    """
    pipette_with_plates.volume_converter = VolumeConverter([0.0, 100.0], [0.0, 50.0])
    pipette_with_plates.plunger = AbsolutePlunger("P", -60.0, 0.0, 0.0)
    pipette_with_plates.get_gcode()
    return pipette_with_plates


def _lines(ap: AutoPipette) -> list[str]:
    return [g.rstrip("\n") for g in ap.get_gcode() if not g.startswith(";")]


def _aspirate(ap: AutoPipette, rise: float | None, **kw: float) -> list[str]:
    ap.aspirate_volume(
        40.0,
        "plate_a",
        0,
        0,
        pre_air_gap_ul=kw.get("pre", 10.0),
        post_air_gap_ul=kw.get("post", 4.0),
        prewet_cycles=0,
        air_gap_rise_mm=rise,
    )
    return _lines(ap)


def _coordinated(lines: list[str]) -> list[tuple[float, float, float]]:
    return [
        (float(m[1]), float(m[2]), float(m[3]))
        for line in lines
        if (m := _COORDINATED.fullmatch(line))
    ]


class TestCoordinatedSegments:
    def test_pre_and_post_gaps_ride_the_z_moves_around_the_aspirate(
        self, ap: AutoPipette
    ) -> None:
        lines = _aspirate(ap, 2.0)

        # 10 μL = 5 mm while descending 3 -> 5; 4 μL = 2 mm while rising 5 -> 3.
        assert [(z, p) for z, p, _ in _coordinated(lines)] == [
            (5.0, -5.0),
            (3.0, -27.0),
        ]
        # The descent to the segment's start is a plain Z move above clearance.
        assert lines.index("G1 Z3.0 F12000.0") < lines.index("G1 Z5.0 P-5.0 F600.0")
        # The liquid itself is still drawn stationary, inside the well.
        assert "G1 P-25.0 F1500.0" in lines

    def test_segment_endpoints_never_go_below_the_clearance_height(
        self, ap: AutoPipette
    ) -> None:
        lines = _aspirate(ap, 2.0)
        z_moves = [line for line in lines if line.startswith("G1 Z")]
        segments = [
            (float(prev.split()[1][1:]), float(m[1]))
            for prev, line in itertools.pairwise(z_moves)
            if (m := _COORDINATED.fullmatch(line))
        ]

        assert len(segments) == 2
        for start, end in segments:
            assert start <= CLEARANCE_Z
            assert end <= CLEARANCE_Z

    def test_plunger_never_exceeds_its_aspirate_speed_or_accel(
        self, ap: AutoPipette
    ) -> None:
        lines = _aspirate(ap, 2.0)
        # Klipper's F is the Z speed here; the plunger moves |dP|/|dZ| times
        # as fast, and accelerates |dP|/|dZ| times as hard.
        pre = lines.index("G1 Z5.0 P-5.0 F600.0")
        post = lines.index("G1 Z3.0 P-27.0 F1500.0")

        assert ap.syringe.speed_aspirate == pytest.approx(600.0 / 60 * 5.0 / 2.0)
        assert lines[pre - 1] == "SET_VELOCITY_LIMIT ACCEL=80.0"  # 200 * 2/5
        assert lines[pre + 1] == f"SET_VELOCITY_LIMIT ACCEL={ap.gantry_accel}"
        assert ap.syringe.speed_aspirate == pytest.approx(1500.0 / 60 * 2.0 / 2.0)
        assert lines[post - 1] == "SET_VELOCITY_LIMIT ACCEL=200.0"

    def test_z_keeps_its_own_speed_when_the_plunger_is_the_short_leg(
        self, ap: AutoPipette
    ) -> None:
        lines = _aspirate(ap, 4.5, pre=1.0, post=0.0)

        # 0.5 mm of plunger over 4.5 mm of Z: Z keeps its normal 12000
        # mm/min, and the accel is the plunger's 200 scaled by 4.5/0.5.
        assert _coordinated(lines) == [(5.0, -0.5, 12000.0)]
        coordinated = lines.index("G1 Z5.0 P-0.5 F12000.0")
        assert lines[coordinated - 1] == "SET_VELOCITY_LIMIT ACCEL=1800.0"

    def test_rise_is_capped_at_the_top_of_z(self, ap: AutoPipette) -> None:
        lines = _aspirate(ap, 50.0, post=0.0)

        assert "G1 Z0.0 F12000.0" in lines
        assert [z for z, _, _ in _coordinated(lines)] == [5.0]


class TestUnchangedWhenOff:
    @pytest.mark.parametrize("rise", [None, 0.0])
    def test_no_rise_draws_air_stationary_as_before(
        self, ap: AutoPipette, rise: float | None
    ) -> None:
        assert ap.syringe.air_gap_rise_mm == pytest.approx(0.0)
        lines = _aspirate(ap, rise)

        assert _coordinated(lines) == []
        assert lines.count("G1 Z5.0 F12000.0") == 3

    def test_stage1_ignores_the_rise(self, pipette_with_plates: AutoPipette) -> None:
        ap = pipette_with_plates
        ap.get_gcode()
        off = _aspirate(ap, 0.0)
        on = _aspirate(ap, 2.0)

        assert on == off

    def test_no_air_gap_means_no_extra_z_moves(self, ap: AutoPipette) -> None:
        lines = _aspirate(ap, 2.0, pre=0.0, post=0.0)

        assert _coordinated(lines) == []
        assert "G1 Z3.0 F12000.0" not in lines


class TestPrecedence:
    def test_liquid_profile_beats_the_pipette_default(self, ap: AutoPipette) -> None:
        ap.system_config.liquids["methanol"].air_gap_rise_mm = 2.0
        ap.switch_liquid("methanol")
        assert ap.syringe.air_gap_rise_mm == pytest.approx(2.0)
        ap.switch_liquid("water")  # water defers to the pipette's 0

        assert ap.syringe.air_gap_rise_mm == pytest.approx(0.0)

    def test_configured_default_applies_when_flag_omitted(
        self, ap: AutoPipette
    ) -> None:
        ap.syringe.air_gap_rise_mm = 2.0

        assert len(_coordinated(_aspirate(ap, None))) == 2

    def test_explicit_zero_turns_a_configured_default_off(
        self, ap: AutoPipette
    ) -> None:
        ap.syringe.air_gap_rise_mm = 2.0

        assert _coordinated(_aspirate(ap, 0.0)) == []

    def test_negative_rise_is_refused(self, ap: AutoPipette) -> None:
        with pytest.raises(ValueError, match="air_gap_rise"):
            _aspirate(ap, -1.0)


class TestLimits:
    def test_coordinated_target_outside_the_limits_emits_nothing(
        self, ap: AutoPipette
    ) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = -58.0

        with pytest.raises(ValueError, match="outside"):
            ap.operate_syringe(
                FluidDisplacement.aspiration, 10.0, z_move=(3.0, CLEARANCE_Z)
            )

        assert _lines(ap) == []
        assert ap.plunger.position_mm == pytest.approx(-58.0)

    def test_a_gap_too_small_to_move_the_plunger_still_moves_z(
        self, ap: AutoPipette
    ) -> None:
        ap.operate_syringe(
            FluidDisplacement.aspiration, 1e-9, z_move=(3.0, CLEARANCE_Z)
        )

        assert _lines(ap) == ["G1 Z5.0 F12000.0"]

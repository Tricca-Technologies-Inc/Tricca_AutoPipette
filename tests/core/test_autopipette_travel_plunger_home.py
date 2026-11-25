"""The stage-2 plunger homes during tip-pickup travel instead of at the source.

Before an aspirate the plunger homes (a dispense-direction move of air) and
then draws the pre-aspirate air gap. With no tip on, the home can ride the
XY and Z legs of the trip to the tipbox: same plunger targets, same order and
direction, same speed/accel caps, only earlier. Anything that would make that
unsafe or the move lengths unknowable falls back to the old sequence.
"""

from __future__ import annotations

import math
import re

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_constants import CoordinateSystem
from tricca_autopipette.core.pipette_models import AbsolutePlunger, TipState
from tricca_autopipette.core.volume_converter import VolumeConverter

_G1 = re.compile(r"G1((?: [XYZP]-?[\d.]+)+) F([\d.]+)")
_ACCEL = re.compile(r"SET_VELOCITY_LIMIT ACCEL=([\d.]+)")


@pytest.fixture
def ap(pipette_with_plates: AutoPipette) -> AutoPipette:
    """A stage-2 pipette at P0 with a 0.5 mm/μL curve.

    Returns:
        ``pipette_with_plates`` with its plunger model set.
    """
    pipette_with_plates.volume_converter = VolumeConverter([0.0, 100.0], [0.0, 50.0])
    pipette_with_plates.plunger = AbsolutePlunger("P", -60.0, 0.0, 0.0)
    pipette_with_plates.state.tip_state = TipState.DETACHED
    pipette_with_plates.get_gcode()
    return pipette_with_plates


def _transfer(ap: AutoPipette, col: int) -> list[str]:
    # A fixed-volume dispense leaves the 10 μL pre-gap (5 mm) in the syringe,
    # so the next transfer's home is a real 5 mm move.
    ap.pipette(
        20.0,
        "plate_a",
        "plate_a",
        disp_vol_ul=20.0,
        src_row=0,
        src_col=col,
        dest_row=0,
        dest_col=3,
        pre_air_gap_ul=10.0,
        post_air_gap_ul=4.0,
        prewet_cycles=0,
    )
    return [g.rstrip("\n") for g in ap.get_gcode() if not g.startswith(";")]


def _words(line: str) -> dict[str, float] | None:
    m = _G1.fullmatch(line)
    if m is None:
        return None
    words = {w[0]: float(w[1:]) for w in m[1].split()}
    words["F"] = float(m[2])
    return words


def _plunger_targets(lines: list[str]) -> list[float]:
    return [w["P"] for line in lines if (w := _words(line)) and "P" in w]


def _turning_points(targets: list[float], start: float) -> list[float]:
    """Collapse runs of same-direction plunger moves to their endpoints.

    Returns:
        The plunger positions at which it reverses (plus the last).
    """
    points: list[float] = []
    pos, direction = start, 0
    for target in targets:
        step = (target > pos) - (target < pos)
        if step and direction and step != direction:
            points.append(pos)
        if step:
            direction = step
        pos = target
    points.append(pos)
    return points


class TestRidesTheTipPickupTravel:
    def test_second_pickup_homes_the_plunger_on_its_travel(
        self, ap: AutoPipette
    ) -> None:
        _transfer(ap, 0)
        assert ap.plunger is not None
        assert ap.plunger.position_mm == pytest.approx(-5.0)

        lines = _transfer(ap, 1)

        # The very first move is the trip to the tipbox, with the plunger
        # homing on it -- before any tip is pressed on.
        first = _words(lines[1])
        assert first is not None
        assert {"X", "Y", "P"} <= first.keys()
        assert first["P"] == pytest.approx(0.0)

    def test_the_aspirate_no_longer_homes_at_the_source(self, ap: AutoPipette) -> None:
        _transfer(ap, 0)
        targets = _plunger_targets(_transfer(ap, 1))

        # Home on the way, pre-gap -5, liquid -15, post-gap -17, dispense -5.
        assert targets == [0.0, -5.0, -15.0, -17.0, -5.0]

    def test_home_is_shared_between_the_xy_and_z_legs(self, ap: AutoPipette) -> None:
        assert ap.plunger is not None
        ap.move_to(Coordinate(x=50.0, y=50.0, z=0.0))  # fully raised
        ap.plunger.position_mm = -5.0
        ap.get_gcode()

        ap.next_tip()
        lines = [g.rstrip("\n") for g in ap.get_gcode() if not g.startswith(";")]

        riding = [w for line in lines if (w := _words(line)) and "P" in w]
        assert len(riding) == 2
        assert {"X", "Y"} <= riding[0].keys() and "Z" not in riding[0]
        assert -5.0 < riding[0]["P"] < 0.0
        assert "Z" in riding[1] and riding[1]["P"] == pytest.approx(0.0)

    def test_plunger_makes_the_same_moves_in_the_same_order(
        self, ap: AutoPipette
    ) -> None:
        _transfer(ap, 0)
        riding = _plunger_targets(_transfer(ap, 1))

        ap.forget_toolhead()  # disables the ride for the next transfer
        ap.location_manager.tipbox_manager.reset_all()  # the fixture box holds 2
        ap.plunger = AbsolutePlunger("P", -60.0, 0.0, -5.0)
        fallback = _plunger_targets(_transfer(ap, 2))

        assert fallback[0] == pytest.approx(0.0)  # the old home, at the source
        assert _turning_points(riding, -5.0) == _turning_points(fallback, -5.0)

    def test_no_move_exceeds_plunger_or_gantry_limits(self, ap: AutoPipette) -> None:
        _transfer(ap, 0)
        gantry, syringe = ap.gantry, ap.syringe

        head = ap.toolhead
        assert head.x is not None and head.y is not None and head.z is not None
        pos = {"X": head.x, "Y": head.y, "Z": head.z, "P": -5.0}
        lines = _transfer(ap, 1)
        accel = ap.gantry_accel
        checked = 0
        for line in lines:
            if (m := _ACCEL.fullmatch(line)) is not None:
                accel = float(m[1])
                continue
            words = _words(line)
            if words is None:
                continue
            carrier_axes = [a for a in "XYZ" if a in words]
            if "P" in words and carrier_axes and all(a in pos for a in carrier_axes):
                length = math.dist(
                    [pos[a] for a in carrier_axes], [words[a] for a in carrier_axes]
                )
                dp = abs(words["P"] - pos["P"])
                cap = gantry.speed_xy if "X" in words else gantry.speed_z
                assert words["F"] <= cap + 1e-6
                assert accel <= ap.gantry_accel + 1e-6
                plunger_speed = words["F"] / 60 * dp / length
                plunger_accel = accel * dp / length
                assert plunger_speed <= syringe.speed_dispense + 1e-3
                assert plunger_accel <= syringe.accel_home + 1e-3
                checked += 1
            pos.update({a: v for a, v in words.items() if a in "XYZP"})
        assert checked == 1


class TestFallsBack:
    def _pickup_lines(self, ap: AutoPipette) -> list[str]:
        ap.next_tip()
        return [g.rstrip("\n") for g in ap.get_gcode() if not g.startswith(";")]

    def _seed(self, ap: AutoPipette) -> None:
        ap.move_to(ap.location_manager.get_coordinate("waste", None, None))
        assert ap.plunger is not None
        ap.plunger.position_mm = -5.0
        ap.get_gcode()

    def test_seeded_case_does_ride(self, ap: AutoPipette) -> None:
        self._seed(ap)
        assert _plunger_targets(self._pickup_lines(ap))

    def test_unknown_position_moves_as_before(self, ap: AutoPipette) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = -5.0

        assert _plunger_targets(self._pickup_lines(ap)) == []

    @pytest.mark.parametrize("state", [TipState.UNKNOWN])
    def test_a_tip_that_might_be_on_moves_as_before(
        self, ap: AutoPipette, state: TipState
    ) -> None:
        self._seed(ap)
        ap.state.tip_state = state

        assert _plunger_targets(self._pickup_lines(ap)) == []

    def test_liquid_in_the_syringe_moves_as_before(self, ap: AutoPipette) -> None:
        self._seed(ap)
        ap.state.has_liquid = True

        assert _plunger_targets(self._pickup_lines(ap)) == []

    @pytest.mark.parametrize(
        ("method", "args"),
        [
            ("home_axis", ()),
            ("home_x", ()),
            ("home_z", ()),
            ("set_coor_sys", (CoordinateSystem.RELATIVE,)),
            ("plates_in", ()),
        ],
        ids=["G28", "G28 X", "G28 Z", "G91", "PLATES_IN"],
    )
    def test_anything_that_could_move_the_head_disables_it(
        self, ap: AutoPipette, method: str, args: tuple[object, ...]
    ) -> None:
        self._seed(ap)
        getattr(ap, method)(*args)
        ap.set_coor_sys(CoordinateSystem.ABSOLUTE)
        ap.get_gcode()

        assert _plunger_targets(self._pickup_lines(ap)) == []

    def test_stage_one_is_untouched(self, ap: AutoPipette) -> None:
        self._seed(ap)
        ap.plunger = None

        assert not any(
            (w := _words(line)) and "P" in w for line in self._pickup_lines(ap)
        )

"""Stage-2 plunger moves that are air only ride travel moves.

Before an aspirate the plunger homes (a dispense-direction move of air) and
draws the pre-aspirate air gap. With no tip on, the home rides the trip to
the tipbox; with a freshly picked-up, still-dry tip, whatever is left (the
gap, and the home if it couldn't ride earlier) rides the trip to the source.
Same plunger targets, order and directions, same speed/accel caps, only
earlier. Anything that would make that unsafe or the move lengths unknowable
falls back to the old sequence.
"""

from __future__ import annotations

import itertools
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
    """A stage-2 pipette at P0 with a 0.5 mm/μL curve, no tip on.

    Returns:
        ``pipette_with_plates`` with its plunger model set.
    """
    pipette_with_plates.volume_converter = VolumeConverter([0.0, 100.0], [0.0, 50.0])
    pipette_with_plates.plunger = AbsolutePlunger("P", -60.0, 0.0, 0.0)
    pipette_with_plates.state.tip_state = TipState.DETACHED
    pipette_with_plates.get_gcode()
    return pipette_with_plates


def _lines(ap: AutoPipette) -> list[str]:
    return [g.rstrip("\n") for g in ap.get_gcode() if not g.startswith(";")]


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
    return _lines(ap)


def _words(line: str) -> dict[str, float] | None:
    m = _G1.fullmatch(line)
    if m is None:
        return None
    words = {w[0]: float(w[1:]) for w in m[1].split()}
    words["F"] = float(m[2])
    return words


def _plunger_targets(lines: list[str]) -> list[float]:
    return [w["P"] for line in lines if (w := _words(line)) and "P" in w]


def _riding(lines: list[str]) -> list[dict[str, float]]:
    """G1 moves that carry the plunger on X, Y or Z.

    Returns:
        Their parsed words, in order.
    """
    return [
        w
        for line in lines
        if (w := _words(line)) and "P" in w and w.keys() & {"X", "Y", "Z"}
    ]


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


class TestRidesTheTravel:
    """On this branch a fixed-volume dispense blows the pre-gap out (P back to
    0), so the gap is what's left to ride: it rides the trip to the source."""

    def test_gap_rides_the_source_trip_after_the_tip_press(
        self, ap: AutoPipette
    ) -> None:
        _transfer(ap, 0)
        lines = _transfer(ap, 1)

        press = next(i for i, line in enumerate(lines) if line.endswith(" F100"))
        riding = [
            (i, w)
            for i, line in enumerate(lines)
            if (w := _words(line)) and "P" in w and w.keys() & {"X", "Y", "Z"}
        ]
        assert riding, "nothing rode the travel"
        assert all(i > press for i, _ in riding)
        assert riding[-1][1]["P"] == pytest.approx(-5.0)

    def test_only_the_liquid_moves_happen_at_the_source(self, ap: AutoPipette) -> None:
        _transfer(ap, 0)
        lines = _transfer(ap, 1)

        stationary = [
            w["P"]
            for line in lines
            if (w := _words(line)) and "P" in w and not w.keys() & {"X", "Y", "Z"}
        ]
        # Liquid -15, post-gap -17; then at the destination: post-gap out
        # -15, liquid out -5, pre-gap blown out 0. No pre-gap at the source.
        assert stationary == [-15.0, -17.0, -15.0, -5.0, 0.0]

    def test_plunger_makes_the_same_moves_in_the_same_order(
        self, ap: AutoPipette, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _transfer(ap, 0)
        riding = _plunger_targets(_transfer(ap, 1))

        def never_ride(*_args: object, **_kwargs: object) -> bool:
            return False

        monkeypatch.setattr(ap, "_travel_with_plunger", never_ride)
        ap.location_manager.tipbox_manager.reset_all()  # the fixture box holds 2
        fallback = _plunger_targets(_transfer(ap, 2))

        assert fallback[0] == pytest.approx(-5.0)  # the old gap, at the source
        assert _turning_points(riding, 0.0) == [-17.0, 0.0]
        assert _turning_points(fallback, 0.0) == [-17.0, 0.0]

    def test_home_and_gap_share_one_trip_when_the_pickup_could_not_ride(
        self, ap: AutoPipette
    ) -> None:
        _transfer(ap, 0)
        assert ap.plunger is not None
        ap.plunger.position_mm = -5.0  # e.g. a dispense that kept its pre-gap
        ap.forget_toolhead()  # pickup trip can't ride; it relearns XYZ there
        lines = _transfer(ap, 1)

        riding = [w["P"] for w in _riding(lines)]
        home_end = riding.index(0.0)
        assert all(a < b for a, b in itertools.pairwise(riding[: home_end + 1]))
        assert all(a > b for a, b in itertools.pairwise(riding[home_end:]))
        assert riding[-1] == pytest.approx(-5.0)

    def test_no_move_exceeds_plunger_or_gantry_limits(self, ap: AutoPipette) -> None:
        _transfer(ap, 0)
        assert ap.plunger is not None
        ap.plunger.position_mm = -5.0  # so the pickup trip carries a home too
        ap.move_to(Coordinate(x=60.0, y=40.0, z=0.0))  # raised: XY and Z legs
        ap.get_gcode()
        pos = {"X": 60.0, "Y": 40.0, "Z": 0.0, "P": -5.0}
        lines = _transfer(ap, 1)
        gantry, syringe = ap.gantry, ap.syringe

        accel = ap.gantry_accel
        checked = 0
        for line in lines:
            if (m := _ACCEL.fullmatch(line)) is not None:
                accel = float(m[1])
                continue
            words = _words(line)
            if words is None:
                continue
            axes = [a for a in "XYZ" if a in words]
            if "P" in words and axes:
                length = math.dist([pos[a] for a in axes], [words[a] for a in axes])
                dp = abs(words["P"] - pos["P"])
                cap = gantry.speed_xy if "X" in words else gantry.speed_z
                assert words["F"] <= cap + 1e-6
                assert accel <= ap.gantry_accel + 1e-6
                homing = words["P"] > pos["P"]
                # Home: speed_dispense/accel_home. Gap: this branch draws it
                # at speed_dispense with the default accel_move.
                a_max = syringe.accel_home if homing else syringe.accel_move
                assert words["F"] / 60 * dp / length <= syringe.speed_dispense + 1e-3
                assert accel * dp / length <= a_max + 1e-3
                checked += 1
            pos.update({a: v for a, v in words.items() if a in "XYZP"})
        assert checked >= 3


class TestSourceTripFallsBack:
    def test_a_tip_that_has_been_dipped_draws_the_gap_at_the_source(
        self, ap: AutoPipette
    ) -> None:
        _transfer(ap, 0)
        ap.next_tip()
        ap.aspirate_volume(5.0, "plate_a", 0, 0, 10.0, 0.0, 0)
        ap.dispense_volume("plate_a", 0, 3)  # empties; tip now wet
        _lines(ap)

        ap.aspirate_volume(5.0, "plate_a", 0, 1, 10.0, 0.0, 0)

        assert _riding(_lines(ap)) == []

    def test_a_tip_put_on_outside_tapd_draws_the_gap_at_the_source(
        self, ap: AutoPipette
    ) -> None:
        ap.move_to(Coordinate(x=60.0, y=40.0, z=5.0))
        ap.state.tip_state = TipState.ATTACHED  # e.g. after a daemon restart
        _lines(ap)

        ap.aspirate_volume(5.0, "plate_a", 0, 0, 10.0, 0.0, 0)

        assert _riding(_lines(ap)) == []


class TestPickupTripFallsBack:
    def _pickup_lines(self, ap: AutoPipette) -> list[str]:
        ap.next_tip()
        return _lines(ap)

    def _seed(self, ap: AutoPipette) -> None:
        ap.move_to(ap.location_manager.get_coordinate("waste", None, None))
        assert ap.plunger is not None
        ap.plunger.position_mm = -5.0
        ap.get_gcode()

    def test_seeded_case_does_ride(self, ap: AutoPipette) -> None:
        self._seed(ap)
        assert _riding(self._pickup_lines(ap))

    def test_unknown_position_moves_as_before(self, ap: AutoPipette) -> None:
        assert ap.plunger is not None
        ap.plunger.position_mm = -5.0

        assert _plunger_targets(self._pickup_lines(ap)) == []

    def test_a_tip_that_might_be_on_moves_as_before(self, ap: AutoPipette) -> None:
        self._seed(ap)
        ap.state.tip_state = TipState.UNKNOWN

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

        assert _plunger_targets(self._pickup_lines(ap)) == []

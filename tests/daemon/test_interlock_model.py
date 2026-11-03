"""``InterlockModel``: Klipper's interlock replayed over emitted G-code (issue #149).

Fed the G-code ``validate_protocol``'s dry run emits, line by line, it answers
what Klipper's interlock (umbrella §6.2, as amended by addendum D39/D45)
would refuse. These cover the rules no protocol command reaches yet (I6, the
stage-2 plunger limits) and the edge semantics; the protocol-level
behaviour is in ``test_service_validate_interlock.py``.
"""

from __future__ import annotations

from tricca_autopipette.daemon.interlock_model import InterlockModel
from tricca_autopipette.daemon.moonraker_state import AxisConfig, PipetteAxis, PlateAxis

AXES = AxisConfig(
    plates=(
        PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),
        PlateAxis("plate2", "V", 0.0, 350.0, (0.0, 120.0, 350.0)),
    ),
    z_safe=0.0,
    park_tol=0.1,
    pipette=PipetteAxis("P", 2, -60.0, 0.0),
)


def homed(**plates: float) -> InterlockModel:
    return InterlockModel(
        AXES,
        z=0.0,
        plates={"plate1": 0.0, "plate2": 0.0, **plates},
        plunger_homed=True,
    )


class TestTipDescent:
    def test_allowed_with_every_plate_at_a_tip_safe_position(self) -> None:
        assert homed(plate2=120.05).check(["G1 Z5\n"]) == []

    def test_refused_with_a_plate_off_its_tip_safe_positions(self) -> None:
        assert homed(plate2=200.0).check(["G1 X1 Y2\n", "G1 Z5\n"]) == [
            (
                "error",
                "Klipper will refuse this (I2): plate2 not at a tip-safe "
                "position (200 mm).",
            )
        ]

    def test_relative_descent_counts(self) -> None:
        model = homed(plate2=200.0)
        assert model.check(["G91\n", "G1 Z3\n", "G90\n"])[0][1].startswith(
            "Klipper will refuse this (I2)"
        )

    def test_rising_or_staying_above_z_safe_is_not_checked(self) -> None:
        model = homed(plate2=200.0)
        assert model.check(["G1 Z0\n", "G1 X5\n"]) == []


class TestPlateMoves:
    def test_plate_move_with_the_tip_low_is_refused(self) -> None:
        model = homed()
        model.check(["G1 Z5\n"])
        assert model.check(["PLATE_MOVE PLATE=plate2 POS=120.0\n"]) == [
            (
                "error",
                "Klipper will refuse this (I1): tip below safe height "
                "(Z 5 > z_safe 0).",
            )
        ]

    def test_plate_move_updates_the_position_the_descent_checks(self) -> None:
        model = homed()
        assert model.check(["PLATE_MOVE PLATE=plate1 POS=100.0\n"]) == []
        assert model.check(["G1 Z5\n"])[0][0] == "error"
        assert model.check(["G1 Z0\n", "PLATES_IN\n", "G1 Z5\n"]) == []

    def test_homing_a_plate_with_the_tip_low_is_refused(self) -> None:
        model = homed()
        model.check(["G1 Z5\n"])
        assert model.check(["G28 U\n"]) == [
            (
                "error",
                "Klipper will refuse this (I4): home Z and raise the tip "
                "before homing plates (Z 5 > z_safe 0).",
            )
        ]

    def test_bare_g28_raises_the_tip_and_brings_every_plate_in(self) -> None:
        model = homed(plate1=100.0)
        assert model.check(["G1 Z5\n", "G28\n", "G1 Z5\n"]) == [
            (
                "error",
                "Klipper will refuse this (I2): plate1 not at a tip-safe "
                "position (100 mm).",
            )
        ]


class TestPlunger:
    def test_p_move_outside_the_stage_2_limits_is_refused(self) -> None:
        assert homed().check(["G1 P-70\n"]) == [
            ("error", "Klipper will refuse this (soft limit): P -70 outside -60 to 0.")
        ]

    def test_p_move_inside_the_limits_is_fine(self) -> None:
        assert homed().check(["G1 Z5 P-20\n"]) == []


class TestUnhomedNow:
    def test_unhomed_plunger_warns_once_and_is_then_assumed_homed(self) -> None:
        model = InterlockModel(
            AXES, z=0.0, plates={"plate1": 0.0, "plate2": 0.0}, plunger_homed=False
        )
        warning = (
            "warning",
            "plunger is not homed now; Klipper will refuse this (I6) unless "
            "it is homed before the run.",
        )
        assert model.check(["G1 P-10\n"]) == [warning]
        assert model.check(["G1 P-20\n"]) == []

    def test_unhomed_plate_warns_at_the_first_descent_assumed_in(self) -> None:
        model = InterlockModel(AXES, z=0.0, plates={"plate1": 0.0}, plunger_homed=True)
        assert model.check(["G1 Z5\n", "G1 Z0\n", "G1 Z5\n"]) == [
            (
                "warning",
                "plate2 is not homed now; Klipper will refuse this (I2) "
                "unless it is homed before the run.",
            )
        ]

    def test_unhomed_z_warns_at_a_plate_move_assumed_raised(self) -> None:
        model = InterlockModel(
            AXES, z=None, plates={"plate1": 0.0, "plate2": 0.0}, plunger_homed=True
        )
        assert model.check(["PLATE_MOVE PLATE=plate1 POS=350.0\n"]) == [
            (
                "warning",
                "Z is not homed now; Klipper will refuse this (I1) "
                "unless it is homed before the run.",
            )
        ]

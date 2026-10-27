"""Tests for recognising Klipper interlock refusals (issue #150, S-TAP9-1/2).

The texts below are what Tricca_Autopipette_Configs' ``plate-macros.cfg``
(CFG-1) raises through ``action_raise_error``.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.daemon.interlock import (
    InterlockRefusal,
    parse_interlock_refusal,
)


@pytest.mark.parametrize(
    ("text", "rule", "axis", "reason"),
    [
        ("Move refused by interlock: Z not homed", "interlock", "Z", "Z not homed"),
        (
            "Move refused by interlock: tip below safe height (Z > 0.0)",
            "interlock",
            "Z",
            "tip below safe height (Z > 0.0)",
        ),
        (
            "Move refused by interlock: plate3 not homed",
            "interlock",
            "plate3",
            "plate3 not homed",
        ),
        # CFG-1's wording; D45 renames it, so nothing may depend on it.
        (
            "Move refused by interlock: plate1 mid-travel (120.0)",
            "interlock",
            "plate1",
            "plate1 mid-travel (120.0)",
        ),
        (
            "Move refused by interlock: plate1 not at a tip-safe position (120.0)",
            "interlock",
            "plate1",
            "plate1 not at a tip-safe position (120.0)",
        ),
        (
            "Move refused by interlock: plunger not homed",
            "interlock",
            "plunger",
            "plunger not homed",
        ),
        (
            "Move refused by interlock: plunger axis P not bound "
            "(send any pipette_stepper command to rebind)",
            "interlock",
            "plunger",
            "plunger axis P not bound (send any pipette_stepper command to rebind)",
        ),
        (
            "RESTORE_GCODE_STATE MOVE=1 refused: state 'PAUSE_STATE' was not "
            "saved through SAVE_GCODE_STATE",
            "RESTORE_GCODE_STATE MOVE=1",
            None,
            "state 'PAUSE_STATE' was not saved through SAVE_GCODE_STATE",
        ),
        (
            "STEPPER_BUZZ on stepper_z refused: home Z and raise the tip first",
            "STEPPER_BUZZ",
            "stepper_z",
            "home Z and raise the tip first",
        ),
        (
            "MANUAL_STEPPER on plate2 refused: use HOME_PLATE / PLATE_* macros",
            "MANUAL_STEPPER",
            "plate2",
            "use HOME_PLATE / PLATE_* macros",
        ),
        (
            "SET_STEPPER_ENABLE ENABLE=0 on plate2 refused: use M84 "
            "(it also unhomes the axis)",
            "SET_STEPPER_ENABLE ENABLE=0",
            "plate2",
            "use M84 (it also unhomes the axis)",
        ),
        (
            "HOME_PLATE refused: home Z and raise the tip first",
            "HOME_PLATE",
            None,
            "home Z and raise the tip first",
        ),
        (
            "PLATE_MOVE refused: POS 400.0 outside 0..350",
            "PLATE_MOVE",
            None,
            "POS 400.0 outside 0..350",
        ),
    ],
)
def test_each_contract_refusal_maps_to_its_rule_axis_and_reason(
    text: str, rule: str, axis: str | None, reason: str
) -> None:
    assert parse_interlock_refusal(text) == InterlockRefusal(
        rule=rule, axis=axis, reason=reason, text=text
    )


def test_refusal_is_found_inside_a_longer_message() -> None:
    refusal = parse_interlock_refusal("!! Move refused by interlock: plate1 not homed")

    assert refusal is not None
    assert refusal.axis == "plate1"
    assert refusal.text == "Move refused by interlock: plate1 not homed"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Move out of range: 400.000 0.000 0.000 [0.000]",
        "Must home axis first: 10.000 0.000 0.000 [0.000]",
        "MCU 'mcu' shutdown: Timer too close",
        'Unknown command:"FOO"',
    ],
)
def test_unrelated_errors_are_not_refusals(text: str) -> None:
    assert parse_interlock_refusal(text) is None

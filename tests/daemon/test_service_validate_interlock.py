"""``validate_protocol`` knows about plates, stops and the interlock (issue #149).

TAP-8: the dry run reports, with the line number, every line Klipper's
interlock would refuse (I1/I2/I4 here; I6 and the plunger limits are in
``test_interlock_model.py``, since no protocol command emits ``G1 P`` yet),
plus pipetting at a drawer-linked location whose drawer isn't at its stop
(addendum D40). Klipper is faked at the Moonraker boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.moonraker_state import AxisConfig, PlateAxis
from tricca_autopipette.daemon.service import AutoPipetteService

AXES = AxisConfig(
    plates=(
        PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),
        PlateAxis("plate2", "V", 0.0, 350.0, (0.0, 120.0, 350.0)),
    ),
    z_safe=0.0,
    park_tol=0.1,
)


def _plate(name: str, x: float, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "x": x,
        "y": 10,
        "z": 5,
        "dip_top": 5,
        "num_row": 1,
        "num_col": 4,
        "spacing_col": 9,
        **extra,
    }


DECK: dict[str, Any] = {
    "drawers": {
        "plate2": {
            "stops": {"work_a": 0, "work_b": 120, "load": 350},
            "pipetting": ["work_a", "work_b"],
        },
    },
    "plates": [
        _plate("tipbox", 200, type="tipbox"),
        _plate("sample_plate", 100, type="array", drawer="plate2", stop="work_b"),
    ],
}

COMPLIANT = """\
next_tip
move 10 20 0
plate_move plate2 load
plate_move plate2 work_b
aspirate 10 sample_plate
dispense sample_plate
move 10 20 0
plates_in
"""

VIOLATIONS = """\
next_tip
plate_move plate2 load
move 10 20 0
plate_move plate1 100
move 10 20 5
home plate1
aspirate 10 sample_plate
"""


@pytest.fixture
def svc(
    service: AutoPipetteService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AutoPipetteService:
    # Gantry and both plates homed; Z raised, plate1 in, plate2 at work_b.
    monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", tmp_path)
    (tmp_path / "compliant.pipette").write_text(COMPLIANT)
    (tmp_path / "violations.pipette").write_text(VIOLATIONS)
    fake = service.moonraker_state
    assert isinstance(fake, FakeMoonrakerState)
    fake.axis_config = AXES  # type: ignore[misc]
    fake.set_homed(True)
    fake.homed_plates = {"plate1", "plate2"}
    fake.positions = {"Z": 0.0, "U": 0.0, "V": 120.0}
    lm = service._autopipette.location_manager
    lm.set_axis_config(AXES)
    lm.apply_locations_data(DECK, source="deck.json")
    return service


def findings(service: AutoPipetteService, filename: str) -> list[tuple[int, str, str]]:
    result = service.validate_protocol(filename)
    assert result.data is not None
    return [
        (f["line_number"], f["severity"], f["message"]) for f in result.data["findings"]
    ]


def test_compliant_protocol_has_no_findings(svc: AutoPipetteService) -> None:
    assert findings(svc, "compliant.pipette") == []


def test_one_finding_per_violation_with_its_line(svc: AutoPipetteService) -> None:
    assert findings(svc, "violations.pipette") == [
        (
            2,
            "error",
            "Klipper will refuse this (I1): tip below safe height (Z 5 > z_safe 0).",
        ),
        (
            5,
            "error",
            "Klipper will refuse this (I2): plate1 not at a tip-safe position "
            "(100 mm).",
        ),
        (
            6,
            "error",
            "Klipper will refuse this (I4): home Z and raise the tip before "
            "homing plates (Z 5 > z_safe 0).",
        ),
        (
            7,
            "error",
            "Location 'sample_plate' needs drawer 'plate2' at stop 'work_b'; "
            "the drawer is at 350 mm.",
        ),
    ]


def test_unhomed_machine_gets_warnings_not_errors(svc: AutoPipetteService) -> None:
    fake = svc.moonraker_state
    assert isinstance(fake, FakeMoonrakerState)
    fake.set_homed(False)
    fake.homed_plates = set()
    fake.positions = {}

    result = svc.validate_protocol("compliant.pipette")

    assert result.ok is True
    assert findings(svc, "compliant.pipette") == [
        (
            1,
            "warning",
            "plate1 is not homed now; Klipper will refuse this (I2) unless it "
            "is homed before the run.",
        ),
        (
            1,
            "warning",
            "plate2 is not homed now; Klipper will refuse this (I2) unless it "
            "is homed before the run.",
        ),
        (
            3,
            "warning",
            "Z is not homed now; Klipper will refuse this (I1) unless it is "
            "homed before the run.",
        ),
    ]

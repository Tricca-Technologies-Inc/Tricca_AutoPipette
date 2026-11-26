"""How an immediate job (a command run outside a protocol) ended (issue #187).

``home``/``move``/... upload their G-code and start it as a print, then
return at once. Klipper's ``print_stats`` reports how the job ended: a
failed one rides ``run.status``/``notify_run_status`` as ``last_job``, and
only a completed full home clears ``_homing_invalidated`` and models the
plates in.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.commands.tap_cmd_parsers import HomeArgs, MoveArgs
from tricca_autopipette.daemon.moonraker_state import AxisConfig, PlateAxis
from tricca_autopipette.daemon.service import AutoPipetteService, RunStatus

AXES = AxisConfig(
    plates=(PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),),
    z_safe=5.0,
    park_tol=0.5,
)


@pytest.fixture
def svc(service: AutoPipetteService) -> AutoPipetteService:
    service.client = FakeWebSocketClient()  # type: ignore[assignment]
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    service.moonraker_state.axis_config = AXES  # type: ignore[misc]
    service._homing_invalidated = True
    return service


@pytest.fixture
def pushes(svc: AutoPipetteService) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    svc.set_broadcast_callback(
        lambda method, params: (
            seen.append(params) if method == "notify_run_status" else None
        )
    )
    return seen


def _klipper(svc: AutoPipetteService, *states: str, message: str = "") -> None:
    for state in states:
        asyncio.run(svc._apply_print_state_change(state, message))


def _drawers(svc: AutoPipetteService) -> dict[str, float]:
    return dict(svc._autopipette.location_manager.drawer_positions)


@pytest.mark.parametrize("home", ["all", None])
def test_a_full_home_says_started_not_homed(
    svc: AutoPipetteService, home: str | None
) -> None:
    result = svc.init() if home is None else svc.home(HomeArgs(home))

    assert "started" in result.message.lower()
    assert "homed" not in result.message.lower()
    assert svc._homing_invalidated is True
    assert _drawers(svc) == {}


@pytest.mark.parametrize("home", ["all", None])
def test_a_completed_full_home_clears_the_flag_and_models_plates_in(
    svc: AutoPipetteService, pushes: list[dict[str, Any]], home: str | None
) -> None:
    svc.init() if home is None else svc.home(HomeArgs(home))

    _klipper(svc, "printing")
    assert svc._homing_invalidated is True
    _klipper(svc, "complete")

    assert svc._homing_invalidated is False
    assert _drawers(svc) == {"plate1": 0.0}
    assert pushes[-1]["last_job"] == {
        "filename": "home_all.gcode",
        "state": "complete",
        "message": "",
    }


@pytest.mark.parametrize("ending", ["cancelled", "error"])
def test_a_failed_full_home_leaves_the_flag_and_reports_klipper(
    svc: AutoPipetteService, pushes: list[dict[str, Any]], ending: str
) -> None:
    svc.home(HomeArgs("all"))

    _klipper(
        svc, "printing", ending, message="Endstop z3 still triggered after retract"
    )

    assert svc._homing_invalidated is True
    assert _drawers(svc) == {}
    expected = {
        "filename": "home_all.gcode",
        "state": ending,
        "message": "Endstop z3 still triggered after retract",
    }
    assert pushes[-1]["last_job"] == expected
    assert svc.status_dict()["last_job"] == expected


def test_a_completed_plate_home_models_only_those_plates_in(
    svc: AutoPipetteService,
) -> None:
    result = svc.home(HomeArgs("plate1"))
    assert "started" in result.message.lower()
    assert _drawers(svc) == {}

    _klipper(svc, "printing", "complete")

    assert _drawers(svc) == {"plate1": 0.0}
    assert svc._homing_invalidated is True


def test_a_failed_move_is_reported_too(
    svc: AutoPipetteService, pushes: list[dict[str, Any]]
) -> None:
    assert isinstance(svc.moonraker_state, FakeMoonrakerState)
    svc.moonraker_state.set_homed(True)
    svc._homing_invalidated = False
    svc.move(MoveArgs(x=10.0, y=10.0, z=0.0))

    _klipper(svc, "error", message="Move out of range")

    last_job = pushes[-1]["last_job"]
    assert last_job["state"] == "error"
    assert last_job["message"] == "Move out of range"
    assert last_job["filename"].endswith(".gcode")


def test_a_stale_complete_before_the_job_prints_is_ignored(
    svc: AutoPipetteService,
) -> None:
    # The previous job's "complete" can arrive after this one has started.
    svc.home(HomeArgs("all"))

    _klipper(svc, "complete")

    assert svc._homing_invalidated is True


def test_no_job_before_any_is_run(svc: AutoPipetteService) -> None:
    assert svc.status_dict()["last_job"] is None


def test_a_protocol_run_home_still_applies_at_once(svc: AutoPipetteService) -> None:
    # Batch mode only buffers: the run's own compile-time model moves on.
    svc.gcode_manager.start_batch()
    svc.home(HomeArgs("all"))
    svc.gcode_manager.end_batch()

    assert svc._homing_invalidated is False
    assert _drawers(svc) == {"plate1": 0.0}


def test_the_next_job_clears_the_last_outcome(
    svc: AutoPipetteService, pushes: list[dict[str, Any]]
) -> None:
    # So a repeat of the same failure (same file, same message) still shows.
    svc.home(HomeArgs("all"))
    _klipper(svc, "printing", "cancelled", message="Endstop z3 still triggered")

    svc.home(HomeArgs("all"))

    assert pushes[-1]["last_job"] is None
    assert svc.status_dict()["last_job"] is None


def test_a_protocol_run_drops_a_job_still_pending(svc: AutoPipetteService) -> None:
    # A home whose ending tapd never saw must not settle on a later print.
    svc.home(HomeArgs("all"))
    svc._current = RunStatus(status="running", run_id="r1", filename="a.pipette")
    _klipper(svc, "printing")
    svc._current = RunStatus(status="done")

    _klipper(svc, "printing", "complete")

    assert svc._homing_invalidated is True

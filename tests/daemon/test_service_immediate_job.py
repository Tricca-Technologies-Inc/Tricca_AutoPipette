"""How an immediate job (a command run outside a protocol) ended (issue #187).

``home``/``move``/... upload their G-code and start it as a print, then
return at once. Moonraker's job history reports how each job ended
(``notify_history_changed``, action ``finished``): the outcome rides
``run.status``/``notify_run_status`` as ``last_job``, and only a completed
full home clears ``_homing_invalidated`` and models the plates in.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any, cast

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.commands.tap_cmd_parsers import HomeArgs, MoveArgs
from tricca_autopipette.daemon.moonraker_state import AxisConfig, PlateAxis
from tricca_autopipette.daemon.service import AutoPipetteService

AXES = AxisConfig(
    plates=(PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),),
    z_safe=5.0,
    park_tol=0.5,
)


@pytest.fixture
def svc(service: AutoPipetteService) -> Iterator[AutoPipetteService]:
    service.client = FakeWebSocketClient()  # type: ignore[assignment]
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    service.moonraker_state.axis_config = AXES  # type: ignore[misc]
    service._homing_invalidated = True
    service._loop = asyncio.new_event_loop()
    yield service
    service._loop.close()


@pytest.fixture
def pushes(svc: AutoPipetteService) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    svc.set_broadcast_callback(
        lambda method, params: (
            seen.append(params) if method == "notify_run_status" else None
        )
    )
    return seen


def _history(svc: AutoPipetteService, action: str, filename: str, status: str) -> None:
    """Feed a ``notify_history_changed`` push, as the client's thread would."""
    svc._handle_history_changed([
        {"action": action, "job": {"filename": filename, "status": status}}
    ])
    assert svc._loop is not None
    svc._loop.run_until_complete(asyncio.sleep(0.01))


def _finished(
    svc: AutoPipetteService, filename: str, status: str, message: str = ""
) -> None:
    cast("FakeMoonrakerState", svc.moonraker_state).print_message = message
    _history(svc, "finished", filename, status)


def _drawers(svc: AutoPipetteService) -> dict[str, float]:
    return dict(svc._autopipette.location_manager.drawer_positions)


def _uploaded(svc: AutoPipetteService) -> str:
    assert isinstance(svc.client, FakeWebSocketClient)
    return svc.client.uploaded_files[-1][0]


@pytest.mark.parametrize("home", ["all", None])
def test_a_full_home_says_started_not_homed(
    svc: AutoPipetteService, home: str | None
) -> None:
    result = svc.init() if home is None else svc.home(HomeArgs(home))

    assert "started" in result.message.lower()
    assert "homed" not in result.message.lower()
    assert svc._homing_invalidated is True
    assert _drawers(svc) == {}


def test_the_history_handler_is_registered_on_connect(
    svc: AutoPipetteService,
) -> None:
    svc.connect()

    assert isinstance(svc.client, FakeWebSocketClient)
    assert "notify_history_changed" in svc.client.handlers


@pytest.mark.parametrize("home", ["all", None])
def test_a_completed_full_home_clears_the_flag_and_models_plates_in(
    svc: AutoPipetteService, pushes: list[dict[str, Any]], home: str | None
) -> None:
    svc.init() if home is None else svc.home(HomeArgs(home))

    _finished(svc, "home_all.gcode", "completed")

    assert svc._homing_invalidated is False
    assert _drawers(svc) == {"plate1": 0.0}
    assert pushes[-1]["last_job"] == {
        "filename": "home_all.gcode",
        "state": "completed",
        "message": "",
    }


@pytest.mark.parametrize("ending", ["cancelled", "error", "klippy_shutdown"])
def test_a_failed_full_home_leaves_the_flag_and_reports_klipper(
    svc: AutoPipetteService, pushes: list[dict[str, Any]], ending: str
) -> None:
    svc.home(HomeArgs("all"))

    _finished(svc, "home_all.gcode", ending, "Endstop z3 still triggered after retract")

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

    _finished(svc, "home_plate1.gcode", "completed")

    assert _drawers(svc) == {"plate1": 0.0}
    assert svc._homing_invalidated is True


def test_a_failed_move_is_reported_too(
    svc: AutoPipetteService, pushes: list[dict[str, Any]]
) -> None:
    assert isinstance(svc.moonraker_state, FakeMoonrakerState)
    svc.moonraker_state.set_homed(True)
    svc._homing_invalidated = False
    svc.move(MoveArgs(x=10.0, y=10.0, z=0.0))
    filename = _uploaded(svc)

    _finished(svc, filename, "error", "Move out of range")

    assert pushes[-1]["last_job"] == {
        "filename": filename,
        "state": "error",
        "message": "Move out of range",
    }


def test_back_to_back_jobs_both_settle(
    svc: AutoPipetteService, pushes: list[dict[str, Any]]
) -> None:
    # Too short for a print_stats change to show; history sees each job.
    svc.home(HomeArgs("x"))
    _finished(svc, "home_x.gcode", "completed")
    first = pushes[-1]["last_job"]

    svc.home(HomeArgs("all"))
    _finished(svc, "home_all.gcode", "completed")

    assert first == {"filename": "home_x.gcode", "state": "completed", "message": ""}
    assert pushes[-1]["last_job"]["filename"] == "home_all.gcode"
    assert svc._homing_invalidated is False


def test_a_finished_job_with_another_filename_does_not_settle(
    svc: AutoPipetteService,
) -> None:
    svc.home(HomeArgs("all"))

    _finished(svc, "someone_elses.gcode", "completed")

    assert svc._homing_invalidated is True
    assert svc.status_dict()["last_job"] is None

    _finished(svc, "home_all.gcode", "completed")  # still pending

    assert svc._homing_invalidated is False


def test_other_history_actions_are_ignored(svc: AutoPipetteService) -> None:
    svc.home(HomeArgs("all"))

    _history(svc, "added", "home_all.gcode", "in_progress")

    assert svc.status_dict()["last_job"] is None


def test_print_stats_does_not_settle_a_job(svc: AutoPipetteService) -> None:
    svc.home(HomeArgs("all"))

    asyncio.run(svc._apply_print_state_change("printing"))
    asyncio.run(svc._apply_print_state_change("complete"))

    assert svc._homing_invalidated is True
    assert svc.status_dict()["last_job"] is None


def test_replacing_a_still_pending_job_warns(
    svc: AutoPipetteService, caplog: pytest.LogCaptureFixture
) -> None:
    svc.home(HomeArgs("all"))

    with caplog.at_level(logging.WARNING):
        svc.home(HomeArgs("x"))

    assert "home_all.gcode" in caplog.text
    assert "still pending" in caplog.text


def test_no_job_before_any_is_run(svc: AutoPipetteService) -> None:
    assert svc.status_dict()["last_job"] is None


def test_the_next_job_clears_the_last_outcome(
    svc: AutoPipetteService, pushes: list[dict[str, Any]]
) -> None:
    # So a repeat of the same failure (same file, same message) still shows.
    svc.home(HomeArgs("all"))
    _finished(svc, "home_all.gcode", "cancelled", "Endstop z3 still triggered")

    svc.home(HomeArgs("all"))

    assert pushes[-1]["last_job"] is None
    assert svc.status_dict()["last_job"] is None


def test_a_protocol_run_home_still_applies_at_once(svc: AutoPipetteService) -> None:
    # Batch mode only buffers: the run's own compile-time model moves on.
    svc.gcode_manager.start_batch()
    svc.home(HomeArgs("all"))
    svc.gcode_manager.end_batch()

    assert svc._homing_invalidated is False
    assert _drawers(svc) == {"plate1": 0.0}

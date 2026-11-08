"""Tests for discovering plate/plunger axis configuration from Klipper (issue #138).

The status dicts mirror what ``printer.objects.query`` returns for the
Tricca_Autopipette_Configs CFG-1 config (``plate-macros.cfg``'s
``_PLATE_CFG``/``_PIPETTE_CFG``, ``octopus-plates.cfg``'s
``[manual_stepper plateN]``, CFG-3's stage-2 plunger limits).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.daemon.moonraker_state import (
    AxisConfig,
    MoonrakerStateTracker,
    PipetteAxis,
    PlateAxis,
    parse_axis_config,
)
from tricca_autopipette.daemon.service import AutoPipetteService
from tricca_autopipette.moonraker.moonraker_requests import MoonrakerRequests


def klipper_status() -> dict[str, Any]:
    # A two-plate, stage-2 machine's ``printer.objects.query`` status.
    return {
        "gcode_macro _PLATE_CFG": {
            "axes": {"plate1": "U", "plate2": "V"},
            "z_safe": 0.0,
            "park_tol": 0.1,
            "safe_stops": {"plate1": [0, 350], "plate2": [0, 120, 350]},
            "limit_velocity": 50,
            "limit_accel": 500,
        },
        "gcode_macro _PIPETTE_CFG": {
            "axis": "P",
            "stage": 2,
            "limit_velocity": 50,
            "limit_accel": 200,
            "max_travel": 60,
        },
        "configfile": {
            "settings": {
                "manual_stepper plate1": {"position_min": 0.0, "position_max": 350.0},
                "manual_stepper plate2": {"position_min": 0.0, "position_max": 350.0},
                "manual_stepper pipette_stepper": {
                    "position_min": -60.0,
                    "position_max": 0.0,
                },
            }
        },
    }


class TestParseAxisConfig:
    def test_full_status_produces_description_with_safe_list(self) -> None:
        assert parse_axis_config(klipper_status()) == AxisConfig(
            plates=(
                PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),
                PlateAxis("plate2", "V", 0.0, 350.0, (0.0, 120.0, 350.0)),
            ),
            z_safe=0.0,
            park_tol=0.1,
            pipette=PipetteAxis("P", 2, -60.0, 0.0),
        )

    def test_stage_one_plunger_has_no_limits(self) -> None:
        status = klipper_status()
        status["gcode_macro _PIPETTE_CFG"]["stage"] = 1
        del status["configfile"]["settings"]["manual_stepper pipette_stepper"]

        assert parse_axis_config(status).pipette == PipetteAxis("P", 1, None, None)

    def test_absent_objects_mean_not_configured(self) -> None:
        status = {"configfile": {"settings": {"printer": {"kinematics": "corexy"}}}}

        assert parse_axis_config(status) == AxisConfig()


def _tracker(client: FakeWebSocketClient) -> MoonrakerStateTracker:
    return MoonrakerStateTracker(client, MoonrakerRequests())  # type: ignore[arg-type]


class TestTrackerAxisConfig:
    def test_queries_the_axis_objects_after_start(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        fake_websocket_client.queue_response({"result": {"status": {}}})
        fake_websocket_client.queue_response({"result": {"status": klipper_status()}})
        tracker = _tracker(fake_websocket_client)
        tracker.start()

        description = tracker.axis_config

        query = fake_websocket_client.sent_requests[-1]
        assert query["method"] == "printer.objects.query"
        assert set(query["params"]["objects"]) == {
            "gcode_macro _PLATE_CFG",
            "gcode_macro _PIPETTE_CFG",
            "configfile",
        }
        assert description == parse_axis_config(klipper_status())

    def test_klipper_restart_refreshes_the_description(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        fake_websocket_client.queue_response({"result": {"status": {}}})
        fake_websocket_client.queue_response({"result": {"status": {}}})
        tracker = _tracker(fake_websocket_client)
        tracker.start()
        assert tracker.axis_config == AxisConfig()  # old config: no plate objects

        fake_websocket_client.queue_response({"result": {"status": klipper_status()}})
        fake_websocket_client.trigger_notification("notify_klippy_ready", None)

        assert tracker.axis_config == parse_axis_config(klipper_status())

    def test_failed_query_reads_as_not_configured(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        fake_websocket_client.queue_response({"result": {"status": {}}})
        fake_websocket_client.queue_response({
            "error": {"message": "Klippy Host not connected"}
        })
        tracker = _tracker(fake_websocket_client)

        tracker.start()

        assert tracker.axis_config == AxisConfig()


class TestSystemSummary:
    def test_reports_discovered_axes(self, service: AutoPipetteService) -> None:
        discovered = parse_axis_config(klipper_status())
        service.moonraker_state.axis_config = discovered  # type: ignore[union-attr]

        data = service.system_summary().data or {}

        assert data["extra_axes"] == asdict(discovered)
        assert data["extra_axes"]["plates"][1]["safe_stops"] == (0.0, 120.0, 350.0)

    def test_unupgraded_machine_reports_not_configured(
        self, service: AutoPipetteService
    ) -> None:
        data = service.system_summary().data or {}

        assert data["extra_axes"] == asdict(AxisConfig())
        assert data["pipette_model"] == "P100_Vertical"  # existing fields intact

    def test_no_moonraker_connection_reports_not_configured(
        self, service: AutoPipetteService
    ) -> None:
        service.moonraker_state = None

        assert service.system_summary().data["extra_axes"] == asdict(AxisConfig())  # type: ignore[index]

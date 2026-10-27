"""Interlock refusals reach run status (issue #150, S-TAP9-1/2/3).

Klipper's interlock is the authority; these tests only check that tapd
reports its refusals specifically. Mocks only the Moonraker boundary
(``FakeWebSocketClient``), whose ``send_jsonrpc`` raises ``JsonRpcError`` for
an error response, like the real client.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.daemon.interlock import InterlockRefusal
from tricca_autopipette.daemon.service import AutoPipetteService, RunStatus
from tricca_autopipette.moonraker.websocket_client import JsonRpcError

MID_TRAVEL = "Move refused by interlock: plate1 mid-travel (120.0)"


@pytest.fixture
def pushes(service: AutoPipetteService) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    service.set_broadcast_callback(
        lambda method, params: (
            seen.append(params) if method == "notify_run_status" else None
        )
    )
    return seen


@pytest.fixture
def client(service: AutoPipetteService) -> FakeWebSocketClient:
    fake = FakeWebSocketClient()
    service.client = fake  # type: ignore[assignment]
    return fake


def _running(service: AutoPipetteService) -> None:
    service._current = RunStatus(
        status="running", message="Running a.pipette", run_id="r1", filename="a.pipette"
    )


class TestPrintErrorDuringARun:
    def test_refusal_is_reported_with_rule_axis_and_reason(
        self, service: AutoPipetteService, pushes: list[dict[str, Any]]
    ) -> None:
        _running(service)

        asyncio.run(
            service._apply_print_state_change(
                "error", "Move refused by interlock: plate1 not homed"
            )
        )

        status = service.get_status()
        assert status.status == "error"
        assert "Move refused by interlock: plate1 not homed" in status.message
        assert status.refusal == InterlockRefusal(
            rule="interlock",
            axis="plate1",
            reason="plate1 not homed",
            text="Move refused by interlock: plate1 not homed",
        )
        assert pushes[-1]["refusal"] == {
            "rule": "interlock",
            "axis": "plate1",
            "reason": "plate1 not homed",
            "text": "Move refused by interlock: plate1 not homed",
        }

    def test_unrelated_error_keeps_todays_message(
        self, service: AutoPipetteService, pushes: list[dict[str, Any]]
    ) -> None:
        _running(service)

        asyncio.run(service._apply_print_state_change("error", "Move out of range"))

        status = service.get_status()
        assert status.status == "error"
        assert status.message == "Print job error"
        assert status.refusal is None
        assert pushes[-1]["refusal"] is None


class TestRefusedResume:
    def test_run_stays_paused_with_the_reason(
        self,
        service: AutoPipetteService,
        client: FakeWebSocketClient,
        pushes: list[dict[str, Any]],
    ) -> None:
        _running(service)
        client.queue_response({"error": {"code": 400, "message": MID_TRAVEL}})

        status = asyncio.run(service.resume_run())

        assert status.status == "running"
        assert status.config_locked is True
        assert status.message.startswith("Paused")
        assert MID_TRAVEL in status.message
        assert "tip-safe position" in status.message
        assert status.refusal is not None
        assert status.refusal.axis == "plate1"
        assert pushes[-1]["message"] == status.message

    def test_a_later_resume_works_and_clears_the_refusal(
        self,
        service: AutoPipetteService,
        client: FakeWebSocketClient,
        pushes: list[dict[str, Any]],
    ) -> None:
        _running(service)
        client.queue_response({"error": {"code": 400, "message": MID_TRAVEL}})
        asyncio.run(service.resume_run())

        status = asyncio.run(service.resume_run())

        assert [r["method"] for r in client.sent_requests] == [
            "printer.print.resume",
            "printer.print.resume",
        ]
        assert status.status == "running"
        assert status.message == "Running a.pipette"
        assert status.refusal is None
        assert pushes[-1]["refusal"] is None

    def test_unrelated_resume_error_is_raised_as_today(
        self,
        service: AutoPipetteService,
        client: FakeWebSocketClient,
        pushes: list[dict[str, Any]],
    ) -> None:
        _running(service)
        client.queue_response({
            "error": {"code": 400, "message": "Print is not paused"}
        })

        with pytest.raises(JsonRpcError):
            asyncio.run(service.resume_run())

        assert service.get_status().message == "Running a.pipette"
        assert pushes == []

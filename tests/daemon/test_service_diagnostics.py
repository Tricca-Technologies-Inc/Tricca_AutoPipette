"""Unit tests for ``AutoPipetteService``'s WebSocket-diagnostics and

reporting methods (Phase 4 of the ports-and-adapters migration -- see
CLAUDE.md), migrated off cmd2's ``WebSocketCommands``/``ls``/``list_liquids``.
Uses ``FakeWebSocketClient`` (Phase 0) as ``service.client`` directly,
since none of these methods need a real background-thread connection.
"""

from __future__ import annotations

import pytest
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.daemon.service import AutoPipetteService
from tricca_autopipette.moonraker.websocket_client import MessageType


def _wire_fake_client(
    service: AutoPipetteService, *, connected: bool = True
) -> FakeWebSocketClient:
    client = FakeWebSocketClient(connected=connected)
    service.client = client  # type: ignore[assignment]
    return client


class TestWsStatus:
    def test_reports_no_client(self, service: AutoPipetteService) -> None:
        result = service.ws_status()

        assert result.ok is False
        assert result.data is None

    def test_reports_connected_client_details(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service, connected=True)
        client.register_handler("notify_status_update", lambda _params: None)
        client.queue_message()

        result = service.ws_status()

        assert result.ok is True
        assert result.data is not None
        assert result.data["connected"] is True
        assert result.data["uri"] == service.uri
        assert result.data["queued_messages"] == 1
        assert result.data["handlers"] == ["notify_status_update"]
        assert result.data["pending_requests"] == 0

    def test_reports_disconnected_client(self, service: AutoPipetteService) -> None:
        _wire_fake_client(service, connected=False)

        result = service.ws_status()

        assert result.ok is False


class TestPingMoonraker:
    def test_raises_when_no_client(self, service: AutoPipetteService) -> None:
        with pytest.raises(RuntimeError, match="not connected"):
            service.ping_moonraker()

    def test_raises_when_disconnected(self, service: AutoPipetteService) -> None:
        _wire_fake_client(service, connected=False)

        with pytest.raises(RuntimeError, match="not connected"):
            service.ping_moonraker()

    def test_succeeds_when_connected(self, service: AutoPipetteService) -> None:
        client = _wire_fake_client(service, connected=True)
        client.queue_response({"result": {}})

        result = service.ping_moonraker()

        assert result.ok is True
        assert "Pong" in result.message


class TestSendNotifyRaw:
    def test_send_raw_raises_when_disconnected(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(RuntimeError, match="not connected"):
            service.send_raw("printer.info", None)

    def test_send_raw_returns_the_response(self, service: AutoPipetteService) -> None:
        client = _wire_fake_client(service, connected=True)
        client.queue_response({"result": {"state": "ready"}})

        result = service.send_raw("printer.info", None)

        assert result.ok is True
        assert result.data == {"response": {"result": {"state": "ready"}}}
        assert client.sent_requests[0]["method"] == "printer.info"

    def test_notify_raw_raises_when_disconnected(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(RuntimeError, match="not connected"):
            service.notify_raw("printer.restart", None)

    def test_notify_raw_sends_a_notification(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service, connected=True)

        result = service.notify_raw("printer.restart", {"a": 1})

        assert result.ok is True
        assert client.sent_notifications == [("printer.restart", {"a": 1})]


class TestSubscribeUnsubscribeRaw:
    def test_subscribe_raises_when_no_client(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(RuntimeError):
            service.subscribe_raw("notify_status_update")

    def test_subscribe_registers_a_handler(self, service: AutoPipetteService) -> None:
        client = _wire_fake_client(service)

        result = service.subscribe_raw("notify_status_update")

        assert result.ok is True
        assert "notify_status_update" in client.handlers

    def test_subscribe_forwards_notifications_via_broadcast_callback(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service)
        broadcasts: list[tuple[str, dict[str, object]]] = []
        service.set_broadcast_callback(lambda m, p: broadcasts.append((m, p)))

        service.subscribe_raw("notify_status_update")
        client.trigger_notification("notify_status_update", {"foo": "bar"})

        assert broadcasts == [
            (
                "notify_raw_event",
                {"method": "notify_status_update", "params": {"foo": "bar"}},
            )
        ]

    def test_unsubscribe_removes_a_handler(self, service: AutoPipetteService) -> None:
        client = _wire_fake_client(service)
        service.subscribe_raw("notify_status_update")

        result = service.unsubscribe_raw("notify_status_update")

        assert result.ok is True
        assert "notify_status_update" not in client.handlers

    def test_unsubscribe_when_not_subscribed_is_a_noop(
        self, service: AutoPipetteService
    ) -> None:
        _wire_fake_client(service)

        result = service.unsubscribe_raw("notify_status_update")

        assert result.ok is False


class TestMessageQueue:
    def test_read_message_raises_when_no_client(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(RuntimeError):
            service.read_message()

    def test_read_message_empty_queue_is_a_noop(
        self, service: AutoPipetteService
    ) -> None:
        _wire_fake_client(service)

        result = service.read_message()

        assert result.ok is False

    def test_read_message_returns_the_oldest_message(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service)
        client.queue_message(MessageType.NOTIFICATION, {"x": 1})
        client.queue_message(MessageType.NOTIFICATION, {"x": 2})

        result = service.read_message()

        assert result.ok is True
        assert result.data is not None
        assert result.data["message_data"] == {"x": 1}
        assert result.data["remaining"] == 1

    def test_read_all_messages_drains_the_queue(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service)
        client.queue_message(MessageType.NOTIFICATION, {"x": 1})
        client.queue_message(MessageType.NOTIFICATION, {"x": 2})

        result = service.read_all_messages()

        assert result.data is not None
        assert len(result.data["messages"]) == 2
        assert len(client) == 0

    def test_clear_message_queue_reports_count(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service)
        client.queue_message()
        client.queue_message()

        result = service.clear_message_queue()

        assert result.data == {"cleared": 2}
        assert len(client) == 0


class TestRunControl:
    def test_emergency_stop_raises_when_disconnected(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(RuntimeError, match="not connected"):
            service.emergency_stop()

    def test_emergency_stop_sends_the_moonraker_request(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service)

        result = service.emergency_stop()

        assert result.ok is True
        assert client.sent_requests[0]["method"] == "printer.emergency_stop"

    def test_send_pause_sends_the_moonraker_request(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service)

        result = service.send_pause()

        assert result.ok is True
        assert client.sent_requests[0]["method"] == "printer.print.pause"

    def test_send_resume_sends_the_moonraker_request(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service)

        result = service.send_resume()

        assert result.ok is True
        assert client.sent_requests[0]["method"] == "printer.print.resume"

    def test_send_cancel_sends_the_moonraker_request(
        self, service: AutoPipetteService
    ) -> None:
        client = _wire_fake_client(service)

        result = service.send_cancel()

        assert result.ok is True
        assert client.sent_requests[0]["method"] == "printer.print.cancel"


class TestRunProtocolBlocking:
    def test_missing_file_raises_file_not_found(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(FileNotFoundError):
            service.run_protocol_blocking("does_not_exist.pipette")


class TestReporting:
    def test_list_locations_empty_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.list_locations()

        assert result.ok is False
        assert result.data == {"locations": []}

    def test_list_locations_reports_a_coordinate(
        self, service: AutoPipetteService
    ) -> None:
        service._autopipette.location_manager.set_coordinate(
            "bench", Coordinate(x=1.0, y=2.0, z=3.0)
        )

        result = service.list_locations()

        assert result.ok is True
        rows = (result.data or {})["locations"]
        assert rows == [
            {
                "name": "bench",
                "type": "Coordinate",
                "x": 1.0,
                "y": 2.0,
                "z": 3.0,
                "details": "",
            }
        ]

    def test_list_plates_reports_a_plate(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        result = service_with_plates.list_plates()

        assert result.ok is True
        names = {row["name"] for row in (result.data or {})["plates"]}
        assert "plate_a" in names

    def test_list_liquids_reports_profiles(self, service: AutoPipetteService) -> None:
        result = service.list_liquids()

        assert result.ok is True
        data = result.data or {}
        assert data["active_liquid"] == service._autopipette.active_liquid
        names = {row["name"] for row in data["liquids"]}
        assert "methanol" in names
        assert "water" in names

    def test_system_summary_reports_config(self, service: AutoPipetteService) -> None:
        result = service.system_summary()

        assert result.ok is True
        data = result.data or {}
        assert data["system_name"] == "TAP-Tyson"
        assert data["pipette_model"] == "P100_Vertical"

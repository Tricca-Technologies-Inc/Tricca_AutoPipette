"""Unit tests for ``daemon/moonraker_state.py``'s ``MoonrakerStateTracker``.

Uses `FakeWebSocketClient` (the same fake `AutoPipetteService`-layer tests
build against) plus a real `MoonrakerRequests`, since the tracker's whole
job is translating between the two -- there is no Moonraker-boundary fake
specific to this module to build, just canned `send_jsonrpc` responses.
"""

from __future__ import annotations

from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.daemon.moonraker_state import (
    DB_KEY_CURRENT_LIQUID,
    DB_KEY_HAS_LIQUID,
    DB_KEY_TIP_LIQUID_STATE,
    DB_KEY_TIP_PRESENCE,
    DB_KEY_TIP_STATE,
    DB_NAMESPACE,
    MoonrakerStateTracker,
)
from tricca_autopipette.moonraker.moonraker_requests import MoonrakerRequests


def _tracker(client: FakeWebSocketClient) -> MoonrakerStateTracker:
    return MoonrakerStateTracker(client, MoonrakerRequests())  # type: ignore[arg-type]


class TestStart:
    def test_registers_status_update_handler(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)

        tracker.start()

        assert "notify_status_update" in fake_websocket_client.handlers

    def test_subscribes_to_toolhead_and_print_stats(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)

        tracker.start()

        assert len(fake_websocket_client.sent_requests) == 1
        request = fake_websocket_client.sent_requests[0]
        assert request["method"] == "printer.objects.subscribe"
        assert set(request["params"]["objects"]) == {"toolhead", "print_stats"}

    def test_applies_initial_status_from_subscribe_response(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        fake_websocket_client.queue_response({
            "result": {
                "status": {
                    "toolhead": {"homed_axes": "xyz"},
                    "print_stats": {"state": "printing"},
                }
            }
        })
        tracker = _tracker(fake_websocket_client)

        tracker.start()

        assert tracker.is_homed() is True
        assert tracker.print_state == "printing"

    def test_tolerates_a_response_with_no_result(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        fake_websocket_client.queue_response({})
        tracker = _tracker(fake_websocket_client)

        tracker.start()  # must not raise

        assert tracker.is_homed() is False
        assert tracker.print_state == "standby"


class TestIsHomed:
    def test_false_before_any_status_is_applied(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)

        assert tracker.is_homed() is False

    def test_true_once_x_y_z_all_reported_homed(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)

        tracker._apply_status({"toolhead": {"homed_axes": ["x", "y", "z"]}})

        assert tracker.is_homed() is True

    def test_false_when_an_axis_is_missing(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)

        tracker._apply_status({"toolhead": {"homed_axes": "xy"}})

        assert tracker.is_homed() is False

    def test_extra_axes_beyond_xyz_still_count_as_homed(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)

        tracker._apply_status({"toolhead": {"homed_axes": "xyze"}})

        assert tracker.is_homed() is True

    def test_a_later_status_can_clear_homed_state(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)
        tracker._apply_status({"toolhead": {"homed_axes": "xyz"}})
        assert tracker.is_homed() is True

        tracker._apply_status({"toolhead": {"homed_axes": ""}})

        assert tracker.is_homed() is False


class TestStatusUpdateNotifications:
    def test_notification_updates_homed_axes(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)
        tracker.start()

        fake_websocket_client.trigger_notification(
            "notify_status_update",
            [{"toolhead": {"homed_axes": "xyz"}}, 123.0],
        )

        assert tracker.is_homed() is True

    def test_notification_params_as_bare_dict_also_works(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)
        tracker.start()

        fake_websocket_client.trigger_notification(
            "notify_status_update", {"toolhead": {"homed_axes": "xyz"}}
        )

        assert tracker.is_homed() is True

    def test_empty_params_are_ignored(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)
        tracker.start()

        fake_websocket_client.trigger_notification("notify_status_update", [])
        fake_websocket_client.trigger_notification("notify_status_update", None)

        assert tracker.is_homed() is False
        assert tracker.print_state == "standby"

    def test_non_dict_candidate_is_ignored(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)
        tracker.start()

        fake_websocket_client.trigger_notification("notify_status_update", [None])

        assert tracker.is_homed() is False


class TestPrintStateCallbacks:
    def test_callback_invoked_on_state_change(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)
        seen: list[str] = []
        tracker.on_print_state_change(seen.append)

        tracker._apply_status({"print_stats": {"state": "printing"}})

        assert seen == ["printing"]
        assert tracker.print_state == "printing"

    def test_callback_not_invoked_when_state_is_unchanged(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)
        tracker._apply_status({"print_stats": {"state": "printing"}})
        seen: list[str] = []
        tracker.on_print_state_change(seen.append)

        tracker._apply_status({"print_stats": {"state": "printing"}})

        assert seen == []

    def test_multiple_callbacks_all_invoked_in_registration_order(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)
        seen: list[str] = []
        tracker.on_print_state_change(lambda state: seen.append(f"a:{state}"))
        tracker.on_print_state_change(lambda state: seen.append(f"b:{state}"))

        tracker._apply_status({"print_stats": {"state": "complete"}})

        assert seen == ["a:complete", "b:complete"]


class TestLoadTipLiquidState:
    def test_returns_all_three_keys_when_stored(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        fake_websocket_client.queue_response({
            "result": {
                "value": {
                    DB_KEY_TIP_STATE: "attached",
                    DB_KEY_HAS_LIQUID: True,
                    DB_KEY_CURRENT_LIQUID: "water",
                }
            }
        })
        tracker = _tracker(fake_websocket_client)

        result = tracker.load_tip_liquid_state()

        assert result == {
            DB_KEY_TIP_STATE: "attached",
            DB_KEY_HAS_LIQUID: True,
            DB_KEY_CURRENT_LIQUID: "water",
        }
        requests = fake_websocket_client.sent_requests
        assert [r["method"] for r in requests] == ["server.database.get_item"]
        assert requests[0]["params"]["key"] == DB_KEY_TIP_LIQUID_STATE
        assert requests[0]["params"]["namespace"] == DB_NAMESPACE

    def test_first_run_with_nothing_stored_returns_empty(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        # First run: the key has never been persisted, so Moonraker's
        # `get_item` response lacks the shape `load_tip_liquid_state`
        # expects, and the lookup falls into the `except` branch.
        fake_websocket_client.queue_response({})
        tracker = _tracker(fake_websocket_client)

        result = tracker.load_tip_liquid_state()

        assert result == {}

    def test_non_mapping_value_is_ignored(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        # A stored value from before this key existed in this shape, or any
        # other malformed record, must not raise or be handed onward.
        fake_websocket_client.queue_response({"result": {"value": "not-a-dict"}})
        tracker = _tracker(fake_websocket_client)

        result = tracker.load_tip_liquid_state()

        assert result == {}


class TestSaveTipLiquidState:
    def test_sends_one_post_item_for_all_three_fields(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)

        tracker.save_tip_liquid_state("attached", True, "water")

        requests = fake_websocket_client.sent_requests
        assert [r["method"] for r in requests] == ["server.database.post_item"]
        assert requests[0]["params"]["key"] == DB_KEY_TIP_LIQUID_STATE
        assert requests[0]["params"]["namespace"] == DB_NAMESPACE
        assert requests[0]["params"]["value"] == {
            DB_KEY_TIP_STATE: "attached",
            DB_KEY_HAS_LIQUID: True,
            DB_KEY_CURRENT_LIQUID: "water",
        }

    def test_current_liquid_none_is_persisted_as_none(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        tracker = _tracker(fake_websocket_client)

        tracker.save_tip_liquid_state("none", False, None)

        requests = fake_websocket_client.sent_requests
        assert requests[0]["params"]["value"][DB_KEY_CURRENT_LIQUID] is None


class TestLoadTipPresence:
    def test_returns_stored_mapping(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        snapshot = {"tipbox_a": {"consumed": ["A1"], "rows": 8, "cols": 12}}
        fake_websocket_client.queue_response({"result": {"value": snapshot}})
        tracker = _tracker(fake_websocket_client)

        result = tracker.load_tip_presence()

        assert result == snapshot
        request = fake_websocket_client.sent_requests[0]
        assert request["method"] == "server.database.get_item"
        assert request["params"] == {
            "namespace": DB_NAMESPACE,
            "key": DB_KEY_TIP_PRESENCE,
        }

    def test_returns_empty_dict_on_first_run(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        fake_websocket_client.queue_response({})
        tracker = _tracker(fake_websocket_client)

        assert tracker.load_tip_presence() == {}

    def test_returns_empty_dict_when_stored_value_is_not_a_mapping(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        fake_websocket_client.queue_response({
            "result": {"value": ["not", "a", "dict"]}
        })
        tracker = _tracker(fake_websocket_client)

        assert tracker.load_tip_presence() == {}


class TestSaveTipPresence:
    def test_posts_the_snapshot_under_the_tip_presence_key(
        self, fake_websocket_client: FakeWebSocketClient
    ) -> None:
        snapshot = {"tipbox_a": {"consumed": ["A1", "A2"], "rows": 8, "cols": 12}}
        tracker = _tracker(fake_websocket_client)

        tracker.save_tip_presence(snapshot)

        assert len(fake_websocket_client.sent_requests) == 1
        request = fake_websocket_client.sent_requests[0]
        assert request["method"] == "server.database.post_item"
        assert request["params"] == {
            "namespace": DB_NAMESPACE,
            "key": DB_KEY_TIP_PRESENCE,
            "value": snapshot,
        }

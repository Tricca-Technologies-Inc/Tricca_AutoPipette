"""Tests for the kiosk's Move page backend (`main.py`, issue #86).

Same real-control-plane style as `test_main.py`: every route here is
exercised via `TestClient` against a real `ControlServer`/`AutoPipetteService`
(`LiveControlPlane`), mocking only at the Moonraker boundary
(`FakeMoonrakerState`/`FakeWebSocketClient`) -- see `docs/agents/tdd.md`.
"""

from __future__ import annotations

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient
from fastapi.testclient import TestClient
from support.live_control_plane import LiveControlPlane

from autopipette_kiosk import main as kiosk_main
from tricca_autopipette.core.coordinate import Coordinate


def _set_homed(plane: LiveControlPlane, *, homed: bool = True) -> None:
    assert isinstance(plane.service.moonraker_state, FakeMoonrakerState)
    plane.service.moonraker_state.set_homed(homed)


class TestMoveEndpoint:
    def test_moves_to_absolute_coordinates_when_homed(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        _set_homed(live_control_plane)

        response = kiosk_client.post("/move", json={"x": 1.0, "y": 2.0, "z": 3.0})

        assert response.status_code == 200
        assert "1.0" in response.json()["message"]

    def test_returns_409_when_not_homed(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        del live_control_plane  # starts unhomed by default

        response = kiosk_client.post("/move", json={"x": 1.0, "y": 2.0, "z": 3.0})

        assert response.status_code == 409

    def test_returns_503_when_the_daemon_is_not_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)  # no lifespan, see TestRunEndpoint above
        response = client.post("/move", json={"x": 1.0, "y": 2.0, "z": 3.0})

        assert response.status_code == 503


class TestMoveLocEndpoint:
    def test_moves_to_a_named_location_when_homed(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        _set_homed(live_control_plane)
        live_control_plane.service._autopipette.location_manager.set_coordinate(
            "bench", Coordinate(x=1, y=2, z=3)
        )

        response = kiosk_client.post("/move_loc", json={"name_loc": "bench"})

        assert response.status_code == 200
        assert "bench" in response.json()["message"]

    def test_returns_404_for_an_unknown_location(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        _set_homed(live_control_plane)

        response = kiosk_client.post("/move_loc", json={"name_loc": "does-not-exist"})

        assert response.status_code == 404

    def test_returns_409_when_not_homed(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        del live_control_plane  # starts unhomed by default

        response = kiosk_client.post("/move_loc", json={"name_loc": "bench"})

        assert response.status_code == 409

    def test_returns_503_when_the_daemon_is_not_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)
        response = client.post("/move_loc", json={"name_loc": "bench"})

        assert response.status_code == 503


class TestMoveRelEndpoint:
    def test_moves_relative_when_homed(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        _set_homed(live_control_plane)

        response = kiosk_client.post("/move_rel", json={"x": 1.0, "y": 0.0, "z": 0.0})

        assert response.status_code == 200

    def test_all_zero_offsets_is_a_200_not_an_error(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        # move_rel's all-zero case is a soft no-op CommandResult(ok=False),
        # not a raised exception -- unlike NotHomedError/NotALocationError,
        # this must not translate to an HTTP error status.
        _set_homed(live_control_plane)

        response = kiosk_client.post("/move_rel", json={"x": 0.0, "y": 0.0, "z": 0.0})

        assert response.status_code == 200
        assert "zero" in response.json()["message"].lower()

    def test_returns_409_when_not_homed(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        del live_control_plane  # starts unhomed by default

        response = kiosk_client.post("/move_rel", json={"x": 1.0, "y": 0.0, "z": 0.0})

        assert response.status_code == 409

    def test_returns_503_when_the_daemon_is_not_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)
        response = client.post("/move_rel", json={"x": 1.0, "y": 0.0, "z": 0.0})

        assert response.status_code == 503


class TestLocationsEndpoint:
    def test_lists_defined_locations(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        live_control_plane.service._autopipette.location_manager.set_coordinate(
            "bench", Coordinate(x=1, y=2, z=3)
        )

        response = kiosk_client.get("/locations")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        names = [loc["name"] for loc in body["data"]["locations"]]
        assert "bench" in names

    def test_empty_deck_reports_ok_false_not_an_http_error(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        del live_control_plane

        response = kiosk_client.get("/locations")

        assert response.status_code == 200
        assert response.json()["ok"] is False

    def test_returns_503_when_the_daemon_is_not_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)
        response = client.get("/locations")

        assert response.status_code == 503


class TestToolheadRelay:
    def test_ws_status_carries_toolhead_position_and_homed_axes(
        self,
        kiosk_client_with_moonraker: TestClient,
        live_control_plane: LiveControlPlane,
    ) -> None:
        # kiosk_client_with_moonraker's lifespan already sent
        # ws.subscribe("notify_status_update") to the (fake-backed) daemon,
        # so the daemon's own "Moonraker connection" firing that
        # notification should reach this browser-facing /ws/status socket
        # as part of the existing status payload (issue #86: extends the
        # existing re-broadcast, no new push type).
        assert isinstance(live_control_plane.service.client, FakeWebSocketClient)

        with kiosk_client_with_moonraker.websocket_connect("/ws/status") as ws:
            assert ws.receive_json()["status"] == "idle"

            live_control_plane.service.client.trigger_notification(
                "notify_status_update",
                [
                    {
                        "toolhead": {
                            "position": [1.0, 2.0, 3.0, 0.0],
                            "homed_axes": "xyz",
                        }
                    },
                    123.0,
                ],
            )

            pushed = ws.receive_json()
            assert pushed["toolhead"] == {
                "position": [1.0, 2.0, 3.0, 0.0],
                "homed_axes": "xyz",
            }

    def test_partial_toolhead_update_only_overwrites_the_fields_present(
        self,
        kiosk_client_with_moonraker: TestClient,
        live_control_plane: LiveControlPlane,
    ) -> None:
        assert isinstance(live_control_plane.service.client, FakeWebSocketClient)

        with kiosk_client_with_moonraker.websocket_connect("/ws/status") as ws:
            ws.receive_json()

            live_control_plane.service.client.trigger_notification(
                "notify_status_update",
                [
                    {
                        "toolhead": {
                            "position": [1.0, 2.0, 3.0, 0.0],
                            "homed_axes": "xyz",
                        }
                    },
                    1.0,
                ],
            )
            ws.receive_json()

            # Klipper only sends the fields that changed -- a later push
            # naming only position must not clobber the previously known
            # homed_axes back to unset.
            live_control_plane.service.client.trigger_notification(
                "notify_status_update",
                [{"toolhead": {"position": [4.0, 5.0, 6.0, 0.0]}}, 2.0],
            )
            pushed = ws.receive_json()

            assert pushed["toolhead"] == {
                "position": [4.0, 5.0, 6.0, 0.0],
                "homed_axes": "xyz",
            }

    def test_non_toolhead_status_updates_are_ignored(
        self,
        kiosk_client_with_moonraker: TestClient,
        live_control_plane: LiveControlPlane,
    ) -> None:
        assert isinstance(live_control_plane.service.client, FakeWebSocketClient)

        with kiosk_client_with_moonraker.websocket_connect("/ws/status") as ws:
            assert ws.receive_json()["toolhead"] == {
                "position": None,
                "homed_axes": None,
            }

            live_control_plane.service.client.trigger_notification(
                "notify_status_update", [{"print_stats": {"state": "printing"}}, 1.0]
            )

            # No toolhead data in this push -- nothing to broadcast, so the
            # next thing this socket receives is whatever the *next* real
            # update sends, not a spurious duplicate. Prove it indirectly:
            # trigger a real toolhead update and confirm exactly one more
            # message (not the print_stats one) arrives with the data.
            live_control_plane.service.client.trigger_notification(
                "notify_status_update",
                [{"toolhead": {"position": [9.0, 9.0, 9.0, 0.0]}}, 2.0],
            )
            pushed = ws.receive_json()
            assert pushed["toolhead"]["position"] == [9.0, 9.0, 9.0, 0.0]

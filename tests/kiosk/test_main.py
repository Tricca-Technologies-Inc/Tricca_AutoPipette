"""Tests for the kiosk backend (`autopipette_kiosk/main.py`) against a real,

in-process control plane.

Issue #37 called this out as non-trivial logic, not pure forwarding: the
`/ws/status` re-broadcast and the daemon-error-to-HTTP-status mapping in
`/run`/`/home` are real client-side reactions to what a real `ControlServer`
sends back, not something a test mocking `send_jsonrpc` directly can
exercise honestly. Every test here drives the real FastAPI app (via
`fastapi.testclient.TestClient`) against a real `ControlServer`
(`tests/support/live_control_plane.py`, the same one `tests/cli/` uses for
`RemoteTapShell`) over a real localhost socket.

`autopipette_kiosk/main.py` keeps its run/breakpoint/websocket-client state
in plain module globals rather than per-request state (it's a long-lived
singleton in production) -- the `kiosk_client`/`protocols_dir` fixtures
(`tests/kiosk/conftest.py`) reset and redirect those per test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.live_control_plane import LiveControlPlane
from support.polling import poll_until

from autopipette_kiosk import main as kiosk_main
from tricca_autopipette.core.pipette_constants import DefaultPaths


class TestConnectionLifecycle:
    def test_lifespan_identifies_the_connection_as_kiosk(
        self, kiosk_client: TestClient, live_control_plane: LiveControlPlane
    ) -> None:
        """The kiosk's `lifespan` sends `daemon.identify("kiosk")` right
        after connecting, so the server's RPC log can attribute this
        connection's later calls (issue #53). `kiosk_client` already
        entered the app's lifespan by the time this test body runs.
        """
        del kiosk_client  # only needed to enter the app's lifespan
        # tests/ disables reportPrivateUsage (see pyproject.toml) --
        # reaching into the live server's client registry to observe the
        # identity `lifespan` just sent is deliberate white-box testing,
        # the same style `live_control_plane.py` itself uses.
        server = live_control_plane._server  # pyright: ignore[reportPrivateUsage]
        assert server is not None
        assert "kiosk" in server._clients.values()  # pyright: ignore[reportPrivateUsage]


class TestProtocolListing:
    def test_empty_dir_returns_empty_list(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        del protocols_dir  # exists (redirected), just empty
        response = kiosk_client.get("/protocols")

        assert response.status_code == 200
        assert response.json() == []

    def test_lists_pipette_files_sorted_by_name(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "b.pipette").write_text("wait 1\n")
        (protocols_dir / "a.pipette").write_text("wait 1\n")
        (protocols_dir / "not-a-protocol.txt").write_text("ignore me\n")

        response = kiosk_client.get("/protocols")

        assert response.json() == [
            {"name": "a", "filename": "a.pipette"},
            {"name": "b", "filename": "b.pipette"},
        ]

    def test_missing_dir_returns_500(
        self,
        kiosk_client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(kiosk_main, "PROTOCOLS_DIR", tmp_path / "does-not-exist")

        response = kiosk_client.get("/protocols")

        assert response.status_code == 500

    def test_local_only_protocol_is_listed_alongside_the_shared_ones(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (protocols_dir / "shared.pipette").write_text("wait 1\n")
        local_dir = tmp_path / "local-protocols"
        local_dir.mkdir()
        (local_dir / "local_only.pipette").write_text("wait 1\n")
        monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_PROTOCOL", local_dir)

        response = kiosk_client.get("/protocols")

        assert response.json() == [
            {"name": "local_only", "filename": "local_only.pipette"},
            {"name": "shared", "filename": "shared.pipette"},
        ]

    def test_local_file_wins_over_a_same_named_shared_one(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (protocols_dir / "a.pipette").write_text("wait 1\n")
        local_dir = tmp_path / "local-protocols"
        local_dir.mkdir()
        (local_dir / "a.pipette").write_text("wait 2\n")
        monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_PROTOCOL", local_dir)

        response = kiosk_client.get("/protocols")

        # Still just one entry -- a name collision resolves to the local
        # file, it doesn't produce two rows.
        assert response.json() == [{"name": "a", "filename": "a.pipette"}]


class TestRunEndpoint:
    def test_starts_a_run_and_returns_the_real_daemon_reply(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')

        response = kiosk_client.post("/run", json={"filename": "a.pipette"})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "running"
        assert "a.pipette" in body["message"]

    def test_local_only_protocol_can_be_run(
        self,
        kiosk_client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Not in `protocols_dir` (the shared side) at all -- only in the
        # local root, which both the kiosk's own pre-check and the daemon's
        # real resolution must consult for this to succeed end to end.
        local_dir = tmp_path / "local-protocols"
        local_dir.mkdir()
        (local_dir / "local_only.pipette").write_text('gcode_print "hi"\n')
        monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_PROTOCOL", local_dir)

        response = kiosk_client.post("/run", json={"filename": "local_only.pipette"})

        assert response.status_code == 200
        assert response.json()["status"] == "running"

    def test_missing_file_in_the_kiosk_dir_returns_404_without_contacting_daemon(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        del protocols_dir
        response = kiosk_client.post(
            "/run", json={"filename": "does-not-exist.pipette"}
        )

        assert response.status_code == 404

    def test_file_missing_only_on_the_daemon_side_returns_a_real_404(
        self,
        kiosk_client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Deliberately mismatched dirs: the kiosk's own PROTOCOLS_DIR has the
        # file (passes its local pre-check) but the daemon's DIR_PROTOCOL --
        # a genuinely separate system, reached over the real control plane
        # -- does not. Only a real round trip can surface this; a test that
        # mocked send_jsonrpc would have no daemon-side file list to be
        # wrong about.
        kiosk_dir = tmp_path / "kiosk-protocols"
        kiosk_dir.mkdir()
        (kiosk_dir / "a.pipette").write_text('gcode_print "hi"\n')
        daemon_dir = tmp_path / "daemon-protocols"
        daemon_dir.mkdir()
        monkeypatch.setattr(kiosk_main, "PROTOCOLS_DIR", kiosk_dir)
        monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", daemon_dir)

        response = kiosk_client.post("/run", json={"filename": "a.pipette"})

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_second_run_while_one_is_active_returns_409(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
        first = kiosk_client.post("/run", json={"filename": "a.pipette"})
        assert first.status_code == 200

        second = kiosk_client.post("/run", json={"filename": "a.pipette"})

        assert second.status_code == 409

    def test_returns_503_when_the_daemon_is_not_connected(
        self, protocols_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        # Not entered as `with TestClient(...) as client:` -- lifespan never
        # runs, so `_control_client` stays None regardless of the monkeypatch
        # above (belt-and-suspenders: makes the precondition explicit rather
        # than relying on "lifespan never ran" alone).
        client = TestClient(kiosk_main.app)
        response = client.post("/run", json={"filename": "a.pipette"})

        assert response.status_code == 503


class TestHomeEndpoint:
    def test_dispatches_init_and_reports_done(self, kiosk_client: TestClient) -> None:
        response = kiosk_client.post("/home")

        assert response.status_code == 200
        assert response.json()["status"] == "done"

    def test_returns_503_when_the_daemon_is_not_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)  # no lifespan, see TestRunEndpoint above
        response = client.post("/home")

        assert response.status_code == 503


class TestTipsEndpoints:
    """Tests for `GET /tips`, `POST /tips/reset`, `POST /tips/set` (issue #17).

    Use `kiosk_client_with_plates`, not the plain `kiosk_client` -- these
    routes need a real registered tipbox (named ``"tipbox"``, 1x2, both
    positions present by default) to report or mutate.
    """

    def test_list_reports_the_registered_tipbox(
        self, kiosk_client_with_plates: TestClient
    ) -> None:
        response = kiosk_client_with_plates.get("/tips")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        boxes = body["data"]["boxes"]
        assert len(boxes) == 1
        assert boxes[0]["name"] == "tipbox"
        assert boxes[0]["present"] == [True, True]

    def test_set_declares_exact_consumed_state(
        self, kiosk_client_with_plates: TestClient
    ) -> None:
        response = kiosk_client_with_plates.post(
            "/tips/set",
            json={"name": "tipbox", "ranges": ["A1"], "available": False},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        listing = kiosk_client_with_plates.get("/tips").json()
        assert listing["data"]["boxes"][0]["present"] == [False, True]

    def test_set_invalid_range_reports_ok_false_not_an_http_error(
        self, kiosk_client_with_plates: TestClient
    ) -> None:
        # config.set_tips reports a bad range via CommandResult(ok=False),
        # not by raising -- so this is a normal 200, unlike /run's 404/409.
        response = kiosk_client_with_plates.post(
            "/tips/set",
            json={"name": "tipbox", "ranges": ["Z99"], "available": False},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is False

    def test_reset_marks_the_box_full_again(
        self, kiosk_client_with_plates: TestClient
    ) -> None:
        kiosk_client_with_plates.post(
            "/tips/set",
            json={"name": "tipbox", "ranges": ["A1", "A2"], "available": False},
        )

        response = kiosk_client_with_plates.post("/tips/reset", json={"name": "tipbox"})

        assert response.status_code == 200
        assert response.json()["ok"] is True
        listing = kiosk_client_with_plates.get("/tips").json()
        assert listing["data"]["boxes"][0]["present"] == [True, True]

    def test_reset_unknown_box_reports_ok_false_not_an_http_error(
        self, kiosk_client_with_plates: TestClient
    ) -> None:
        response = kiosk_client_with_plates.post(
            "/tips/reset", json={"name": "does-not-exist"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "does-not-exist" in body["message"]

    def test_list_returns_503_when_the_daemon_is_not_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)  # no lifespan, see TestRunEndpoint above
        response = client.get("/tips")

        assert response.status_code == 503


class TestLocationsEndpoint:
    """Tests for `GET /locations` (issue #87): a thin proxy over
    `config.list_locations`, for the kiosk Deck page's spatial tiles.
    """

    def test_lists_registered_locations_sorted_by_name(
        self, kiosk_client_with_plates: TestClient
    ) -> None:
        response = kiosk_client_with_plates.get("/locations")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        rows = body["data"]["locations"]
        assert [row["name"] for row in rows] == ["plate_a", "tipbox", "waste"]
        tipbox = next(row for row in rows if row["name"] == "tipbox")
        assert tipbox["type"] == "TipBox"
        assert tipbox["x"] == pytest.approx(10.0)
        assert tipbox["y"] == pytest.approx(10.0)

    def test_returns_503_when_the_daemon_is_not_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)  # no lifespan, see TestRunEndpoint above
        response = client.get("/locations")

        assert response.status_code == 503


class TestIndexRoute:
    def test_serves_the_frontend(self, kiosk_client: TestClient) -> None:
        response = kiosk_client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestBreakpointRespond:
    def test_returns_503_when_the_daemon_is_not_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)  # no lifespan, see TestRunEndpoint above
        response = client.post("/breakpoint/respond", json={"proceed": True})

        assert response.status_code == 503

    def test_confirms_and_releases_a_pending_breakpoint(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        (protocols_dir / "bp.pipette").write_text(
            'gcode_print "before"\nbreak\ngcode_print "after"\n'
        )

        with kiosk_client.websocket_connect("/ws/status") as ws:
            assert ws.receive_json()["status"] == "idle"

            kiosk_client.post("/run", json={"filename": "bp.pipette"})
            assert ws.receive_json()["status"] == "running"

            pending = ws.receive_json()
            assert pending["breakpoint"] is not None
            assert pending["breakpoint"]["pending"] is True

            response = kiosk_client.post("/breakpoint/respond", json={"proceed": True})
            assert response.status_code == 200
            assert response.json() == {"ok": True}

            cleared = ws.receive_json()
            assert cleared["breakpoint"] is None

        # request_breakpoint() blocks the worker thread for the run's whole
        # duration, holding service._lock the entire time -- proceeding past
        # the breakpoint is what releases it (the same real signal
        # tests/cli/test_remote_shell.py checks for RemoteTapShell's
        # "continue", since there's no real Moonraker connection here to
        # ever move status off "running" on its own).
        assert poll_until(lambda: not live_control_plane.service._lock.locked())


class TestStatusEndpoint:
    def test_idle_by_default(self, kiosk_client: TestClient) -> None:
        response = kiosk_client.get("/status")

        assert response.json() == {"status": "idle", "message": ""}

    def test_reflects_the_real_status_after_a_run_starts(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')

        kiosk_client.post("/run", json={"filename": "a.pipette"})
        response = kiosk_client.get("/status")

        assert response.json()["status"] == "running"


class TestWebSocketStatusBroadcast:
    def test_new_connection_receives_the_current_status_immediately(
        self, kiosk_client: TestClient
    ) -> None:
        with kiosk_client.websocket_connect("/ws/status") as ws:
            payload = ws.receive_json()

        assert payload == {"status": "idle", "message": "", "breakpoint": None}

    def test_receives_a_push_when_a_run_starts(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')

        with kiosk_client.websocket_connect("/ws/status") as ws:
            assert ws.receive_json()["status"] == "idle"

            kiosk_client.post("/run", json={"filename": "a.pipette"})

            pushed = ws.receive_json()
            assert pushed["status"] == "running"
            assert pushed["breakpoint"] is None

    def test_fans_out_to_every_connected_client(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')

        with (
            kiosk_client.websocket_connect("/ws/status") as ws1,
            kiosk_client.websocket_connect("/ws/status") as ws2,
        ):
            ws1.receive_json()
            ws2.receive_json()

            kiosk_client.post("/run", json={"filename": "a.pipette"})

            assert ws1.receive_json()["status"] == "running"
            assert ws2.receive_json()["status"] == "running"

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

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient
from fastapi.testclient import TestClient
from support.live_control_plane import LiveControlPlane
from support.polling import poll_until

from autopipette_kiosk import main as kiosk_main
from tricca_autopipette.core.pipette_constants import DefaultPaths


class JobClient(FakeWebSocketClient):
    """Moonraker fake with a controllable job-status snapshot."""

    def __init__(self) -> None:
        super().__init__()
        self.job: dict[str, Any] = {}

    def send_jsonrpc(
        self, payload: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any]:
        if payload["method"] == "printer.objects.query":
            if not self.is_connected():
                raise RuntimeError("Disconnected")
            return {"result": {"status": self.job}}
        return super().send_jsonrpc(payload, timeout)


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
    def test_lists_nested_protocols_by_relative_path(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "examples").mkdir()
        (protocols_dir / "examples" / "transfer.pipette").write_text("wait 1\n")

        response = kiosk_client.get("/protocols")

        assert response.json() == [
            {"name": "transfer", "filename": "examples/transfer.pipette"}
        ]

    def test_nested_local_override_is_validated_instead_of_shared(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        shared = protocols_dir / "examples"
        shared.mkdir()
        (shared / "transfer.pipette").write_text("wait 1\n")
        local = tmp_path / "local-protocols"
        (local / "examples").mkdir(parents=True)
        (local / "examples" / "transfer.pipette").write_text("move_loc missing\n")
        monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_PROTOCOL", local)

        assert kiosk_client.get("/protocols").json() == [
            {"name": "transfer", "filename": "examples/transfer.pipette"}
        ]
        result = kiosk_client.post(
            "/validate", json={"filename": "examples/transfer.pipette"}
        ).json()
        assert any(f["severity"] == "error" for f in result["data"]["findings"])

    def test_symlink_override_outside_root_is_not_listed_or_executable(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        shared = protocols_dir / "shared"
        shared.mkdir()
        (shared / "a.pipette").write_text("wait 1\n")
        monkeypatch.setattr(kiosk_main, "PROTOCOLS_DIR", shared)
        monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", shared)
        outside = tmp_path / "outside.pipette"
        outside.write_text("wait 1\n")
        local = tmp_path / "local-protocols"
        local.mkdir()
        (local / "a.pipette").symlink_to(outside)
        monkeypatch.setattr(DefaultPaths, "DIR_LOCAL_PROTOCOL", local)
        assert kiosk_client.get("/protocols").json() == []
        assert (
            kiosk_client.post("/run", json={"filename": "a.pipette"}).status_code == 404
        )
        response = kiosk_client.post(
            "/validate", json={"filename": "../outside.pipette"}
        )
        assert response.status_code == 404

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
    def test_starts_nested_protocol(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "examples").mkdir()
        (protocols_dir / "examples" / "a.pipette").write_text('gcode_print "hi"\n')

        response = kiosk_client.post("/run", json={"filename": "examples/a.pipette"})

        assert response.status_code == 200
        assert response.json()["status"] == "running"

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

    def test_a_status_push_arriving_before_the_run_response_is_not_clobbered(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Issue #102: the daemon's `notify_run_status` push for a run that
        fails immediately can reach the kiosk *before* the `run.start` RPC
        response does. `/run` must not then overwrite that newer status with
        the RPC's stale "running" result -- doing so left the kiosk (and
        every browser, via the next broadcast) stuck on "Running" forever.
        """
        # `next_tip` is homed-gated and the fake Moonraker starts unhomed, so
        # the daemon's run fails on line 1 and pushes "error" for real.
        (protocols_dir / "a.pipette").write_text("next_tip\n")
        client = kiosk_main._control_client  # pyright: ignore[reportPrivateUsage]
        assert client is not None
        real_send = client.send_jsonrpc

        def send_then_await_error_push(request: dict[str, object], **kwargs: object):
            response = real_send(request, **kwargs)  # pyright: ignore[reportArgumentType]
            # Hold the RPC response back until the real error push has
            # landed -- forcing the losing interleaving deterministically.
            poll_until(lambda: kiosk_main._current_run.status == "error")  # pyright: ignore[reportPrivateUsage]
            return response

        monkeypatch.setattr(client, "send_jsonrpc", send_then_await_error_push)

        kiosk_client.post("/run", json={"filename": "a.pipette"})

        assert kiosk_client.get("/status").json()["status"] == "error"

    def test_second_run_while_one_is_active_returns_409(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text("break\n")
        first = kiosk_client.post("/run", json={"filename": "a.pipette"})
        assert first.status_code == 200
        try:
            assert poll_until(lambda: kiosk_main._current_breakpoint is not None)
            second = kiosk_client.post("/run", json={"filename": "a.pipette"})
            assert second.status_code == 409
        finally:
            kiosk_client.post("/breakpoint/respond", json={"proceed": False})

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


class TestValidateEndpoint:
    """Tests for `POST /validate` (issue #88): a thin proxy over
    `run.validate`, for the Run tab's pre-flight "Check" button.
    """

    def test_clean_protocol_reports_ok_with_no_findings(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text("wait 1\n")

        response = kiosk_client.post("/validate", json={"filename": "a.pipette"})

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["data"]["findings"] == []

    def test_bad_location_reports_ok_false_with_an_error_finding(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text("move_loc missing\n")

        response = kiosk_client.post("/validate", json={"filename": "a.pipette"})

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        findings = body["data"]["findings"]
        assert len(findings) == 1
        assert findings[0]["severity"] == "error"

    def test_missing_file_in_the_kiosk_dir_returns_404_without_contacting_daemon(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        del protocols_dir
        response = kiosk_client.post(
            "/validate", json={"filename": "does-not-exist.pipette"}
        )

        assert response.status_code == 404

    def test_returns_503_when_the_daemon_is_not_connected(
        self, protocols_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (protocols_dir / "a.pipette").write_text("wait 1\n")
        monkeypatch.setattr(kiosk_main, "_control_client", None)

        client = TestClient(kiosk_main.app)  # no lifespan, see TestRunEndpoint above
        response = client.post("/validate", json={"filename": "a.pipette"})

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
        monkeypatch.setattr(kiosk_main, "_run_control_client", None)

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

    def test_cancel_during_breakpoint_aborts_preparation(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        (protocols_dir / "bp.pipette").write_text(
            'gcode_print "before"\nbreak\ngcode_print "after"\n'
        )
        kiosk_client.post("/run", json={"filename": "bp.pipette"})
        assert poll_until(lambda: kiosk_main._current_breakpoint is not None)
        try:
            run_id = live_control_plane.service.get_status().run_id
            assert run_id is not None
            response = kiosk_client.post("/run/cancel", json={"run_id": run_id})
            assert response.status_code == 200
            assert poll_until(
                lambda: live_control_plane.service.get_status().status == "error"
            )
            assert "cancel" in live_control_plane.service.get_status().message.lower()
            assert poll_until(lambda: kiosk_main._current_breakpoint is None)
        finally:
            kiosk_client.post("/breakpoint/respond", json={"proceed": False})

    def test_cancel_during_upload_does_not_start_the_job(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        class DelayedUpload(FakeWebSocketClient):
            def __init__(self) -> None:
                super().__init__()
                self.upload: Future[str] = Future()

            def upload_gcode_file(
                self, file_name: str, file_path: str | Path
            ) -> Future[str]:
                self.uploaded_files.append((file_name, str(file_path)))
                return self.upload

        fake = DelayedUpload()
        live_control_plane.service.client = fake  # type: ignore[assignment]
        (protocols_dir / "upload.pipette").write_text('gcode_print "hello"\n')
        kiosk_client.post("/run", json={"filename": "upload.pipette"})
        try:
            assert poll_until(lambda: bool(fake.uploaded_files))
            client = kiosk_main._control_client
            assert client is not None
            client.send_jsonrpc(
                kiosk_main._control_requests.run_cancel()
            )
        finally:
            fake.upload.set_result("gcodes/upload.gcode")
        assert poll_until(
            lambda: live_control_plane.service.get_status().status == "error"
        )
        assert "cancel" in live_control_plane.service.get_status().message.lower()
        assert not any(r["method"] == "printer.print.start" for r in fake.sent_requests)

    def test_cancel_is_not_blocked_by_a_queued_validation(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        (protocols_dir / "bp.pipette").write_text("break\n")
        (protocols_dir / "check.pipette").write_text("wait 1\n")
        kiosk_client.post("/run", json={"filename": "bp.pipette"})
        assert poll_until(lambda: kiosk_main._current_breakpoint is not None)
        run_id = live_control_plane.service.get_status().run_id
        assert run_id is not None
        client = kiosk_main._control_client
        assert client is not None
        with ThreadPoolExecutor() as pool:
            validation = pool.submit(
                kiosk_client.post, "/validate", json={"filename": "check.pipette"}
            )
            try:
                assert poll_until(lambda: client.pending_count > 0)
                response = kiosk_client.post("/run/cancel", json={"run_id": run_id})
                assert response.status_code == 200
            finally:
                asyncio.run_coroutine_threadsafe(
                    live_control_plane.service.confirm_breakpoint(False),
                    live_control_plane._loop,
                ).result(timeout=5)
            assert validation.result(timeout=5).status_code == 200

    def test_cancel_during_preparation_persistence_does_not_start_the_job(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        class DelayedPersistence(FakeMoonrakerState):
            def __init__(self) -> None:
                super().__init__()
                self.entered = Event()
                self.release = Event()

            def save_tip_liquid_state(
                self, tip_state: str, has_liquid: bool, current_liquid: str | None
            ) -> None:
                self.entered.set()
                assert self.release.wait(10)
                super().save_tip_liquid_state(tip_state, has_liquid, current_liquid)

        fake = FakeWebSocketClient()
        state = DelayedPersistence()
        service = live_control_plane.service
        service.client = fake  # type: ignore[assignment]
        service.moonraker_state = state  # type: ignore[assignment]
        service._last_persisted_state = None
        (protocols_dir / "persist.pipette").write_text('gcode_print "hello"\n')
        kiosk_client.post("/run", json={"filename": "persist.pipette"})
        try:
            assert state.entered.wait(5)
            run_id = service.get_status().run_id
            assert run_id is not None
            response = kiosk_client.post("/run/cancel", json={"run_id": run_id})
            assert response.status_code == 200
            assert not any(
                request["method"] == "printer.print.start"
                for request in fake.sent_requests
            )
        finally:
            state.release.set()
        assert poll_until(lambda: service.get_status().status == "error")
        assert "cancel" in service.get_status().message.lower()
        assert not any(r["method"] == "printer.print.start" for r in fake.sent_requests)


class TestStatusEndpoint:
    def test_progress_belongs_to_the_current_job(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        fake = JobClient()
        live_control_plane.service.client = fake  # type: ignore[assignment]
        (protocols_dir / "progress.pipette").write_text('gcode_print "hello"\n')
        kiosk_client.post("/run", json={"filename": "progress.pipette"})
        assert poll_until(lambda: bool(fake.uploaded_files))
        name = fake.uploaded_files[0][0]
        fake.job = {
            "print_stats": {"filename": name, "state": "printing"},
            "virtual_sdcard": {"progress": 0.41},
        }
        assert poll_until(
            lambda: (
                live_control_plane.service.get_status().progress == pytest.approx(0.41)
            )
        )
        fake.job = {
            "print_stats": {"filename": "different.gcode", "state": "printing"},
            "virtual_sdcard": {"progress": 0.9},
        }
        assert poll_until(
            lambda: (
                live_control_plane.service.get_status().to_dict().get("phase")
                == "unknown"
            )
        )
        assert live_control_plane.service.get_status().to_dict().get("progress") is None
        fake.job = {
            "print_stats": {"filename": name, "state": "paused"},
            "virtual_sdcard": {},
        }
        assert poll_until(
            lambda: live_control_plane.service.get_status().phase == "paused"
        )
        assert live_control_plane.service.get_status().progress is None
        fake.set_connected(False)
        assert poll_until(
            lambda: live_control_plane.service.get_status().phase == "unknown"
        )
        assert live_control_plane.service.get_status().config_locked
        fake.set_connected(True)
        fake.job = {
            "print_stats": {"filename": name, "state": "complete"},
            "virtual_sdcard": {"progress": 1.0},
        }
        assert poll_until(
            lambda: live_control_plane.service.get_status().status == "done"
        )

    def test_controls_require_the_current_confirmed_job_state(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        fake = JobClient()
        live_control_plane.service.client = fake  # type: ignore[assignment]
        (protocols_dir / "controls.pipette").write_text('gcode_print "hello"\n')
        started = kiosk_client.post("/run", json={"filename": "controls.pipette"})
        run_id = live_control_plane.service.get_status().run_id
        assert started.status_code == 200 and run_id is not None
        assert poll_until(lambda: bool(fake.uploaded_files))
        fake.job = {
            "print_stats": {"filename": fake.uploaded_files[0][0], "state": "printing"},
            "virtual_sdcard": {"progress": 0.25},
        }
        assert poll_until(
            lambda: live_control_plane.service.get_status().phase == "printing"
        )
        response = kiosk_client.post("/run/pause", json={"run_id": run_id})
        assert response.status_code == 200
        assert any(r["method"] == "printer.print.pause" for r in fake.sent_requests)
        assert live_control_plane.service.get_status().phase == "printing"
        fake.job["print_stats"]["state"] = "paused"
        assert poll_until(
            lambda: live_control_plane.service.get_status().phase == "paused"
        )
        fake.queue_response({
            "error": {
                "code": 400,
                "message": "Move refused by interlock: plate1 mid-travel (120.0)",
            }
        })
        refused = kiosk_client.post("/run/resume", json={"run_id": run_id})
        assert refused.status_code == 200
        assert "resume refused" in refused.json()["message"]
        assert live_control_plane.service.get_status().phase == "paused"
        assert live_control_plane.service.get_status().config_locked
        response = kiosk_client.post("/run/resume", json={"run_id": run_id})
        assert response.status_code == 200
        assert any(r["method"] == "printer.print.resume" for r in fake.sent_requests)
        assert (
            kiosk_client.post("/run/pause", json={"run_id": "old-run"}).status_code
            != 200
        )
        fake.job["print_stats"]["filename"] = "other.gcode"
        response = kiosk_client.post("/run/cancel", json={"run_id": run_id})
        assert response.status_code != 200
        assert not any(
            r["method"] == "printer.print.cancel" for r in fake.sent_requests
        )

    def test_uncertain_start_stays_locked_until_job_is_confirmed(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        class StartTimeout(JobClient):
            def send_jsonrpc(
                self, payload: dict[str, Any], timeout: float = 5.0
            ) -> dict[str, Any]:
                if payload["method"] == "printer.print.start":
                    raise TimeoutError("Start response lost")
                return super().send_jsonrpc(payload, timeout)

        fake = StartTimeout()
        live_control_plane.service.client = fake  # type: ignore[assignment]
        (protocols_dir / "timeout.pipette").write_text('gcode_print "hello"\n')
        kiosk_client.post("/run", json={"filename": "timeout.pipette"})
        assert poll_until(lambda: bool(fake.uploaded_files))
        assert poll_until(
            lambda: live_control_plane.service.get_status().phase == "unknown"
        )
        assert live_control_plane.service.get_status().config_locked
        fake.job = {
            "print_stats": {
                "filename": fake.uploaded_files[0][0],
                "state": "printing",
            },
            "virtual_sdcard": {"progress": 0.1},
        }
        assert poll_until(
            lambda: live_control_plane.service.get_status().phase == "printing"
        )

    def test_new_run_waits_for_previous_control_and_cancelled_wait_releases_gate(
        self,
        kiosk_client: TestClient,
        protocols_dir: Path,
        live_control_plane: LiveControlPlane,
    ) -> None:
        class DelayedPause(JobClient):
            def __init__(self) -> None:
                super().__init__()
                self.pause_started = Event()
                self.release_pause = Event()

            def send_jsonrpc(
                self, payload: dict[str, Any], timeout: float = 5.0
            ) -> dict[str, Any]:
                if payload["method"] == "printer.print.pause":
                    self.pause_started.set()
                    assert self.release_pause.wait(timeout=5)
                return super().send_jsonrpc(payload, timeout)

        fake = DelayedPause()
        live_control_plane.service.client = fake  # type: ignore[assignment]
        (protocols_dir / "a.pipette").write_text('gcode_print "hello"\n')
        kiosk_client.post("/run", json={"filename": "a.pipette"})
        run_id = live_control_plane.service.get_status().run_id
        assert run_id is not None
        assert poll_until(lambda: bool(fake.uploaded_files))
        fake.job = {
            "print_stats": {"filename": fake.uploaded_files[0][0], "state": "printing"}
        }
        assert poll_until(
            lambda: live_control_plane.service.get_status().phase == "printing"
        )
        with ThreadPoolExecutor() as pool:
            pause = pool.submit(
                kiosk_client.post, "/run/pause", json={"run_id": run_id}
            )
            try:
                assert fake.pause_started.wait(timeout=5)
                fake.job["print_stats"]["state"] = "complete"
                assert poll_until(
                    lambda: live_control_plane.service.get_status().status == "done"
                )
                waiting = asyncio.run_coroutine_threadsafe(
                    live_control_plane.service.start_run("a.pipette"),
                    live_control_plane._loop,
                )
                with pytest.raises(TimeoutError):
                    waiting.result(timeout=0.2)
                assert waiting.cancel()
            finally:
                fake.release_pause.set()
            assert pause.result(timeout=5).status_code == 200
        next_run = asyncio.run_coroutine_threadsafe(
            live_control_plane.service.start_run("a.pipette"), live_control_plane._loop
        ).result(timeout=5)
        assert next_run.run_id != run_id

    def test_idle_by_default(self, kiosk_client: TestClient) -> None:
        response = kiosk_client.get("/status")

        assert response.json()["status"] == "idle"
        assert response.json()["message"] == ""

    def test_reflects_the_real_status_after_a_run_starts(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text("break\n")

        kiosk_client.post("/run", json={"filename": "a.pipette"})
        try:
            assert poll_until(lambda: kiosk_main._current_breakpoint is not None)
            assert kiosk_client.get("/status").json()["status"] == "running"
        finally:
            kiosk_client.post("/breakpoint/respond", json={"proceed": False})


class TestWebSocketStatusBroadcast:
    def test_new_connection_receives_the_current_status_immediately(
        self, kiosk_client: TestClient
    ) -> None:
        with kiosk_client.websocket_connect("/ws/status") as ws:
            payload = ws.receive_json()

        assert payload["status"] == "idle"
        assert payload["message"] == ""
        assert payload["breakpoint"] is None
        assert payload["toolhead"] == {"position": None, "homed_axes": None}
        assert payload["config_locked"] is False
        assert payload["daemon_connected"] is True

    def test_receives_a_push_when_a_run_starts(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text("break\n")

        try:
            with kiosk_client.websocket_connect("/ws/status") as ws:
                assert ws.receive_json()["status"] == "idle"
                kiosk_client.post("/run", json={"filename": "a.pipette"})
                pushed = ws.receive_json()
                assert pushed["status"] == "running"
        finally:
            assert poll_until(lambda: kiosk_main._current_breakpoint is not None)
            kiosk_client.post("/breakpoint/respond", json={"proceed": False})

    def test_fans_out_to_every_connected_client(
        self, kiosk_client: TestClient, protocols_dir: Path
    ) -> None:
        (protocols_dir / "a.pipette").write_text("break\n")

        try:
            with (
                kiosk_client.websocket_connect("/ws/status") as ws1,
                kiosk_client.websocket_connect("/ws/status") as ws2,
            ):
                ws1.receive_json()
                ws2.receive_json()
                kiosk_client.post("/run", json={"filename": "a.pipette"})
                assert ws1.receive_json()["status"] == "running"
                assert ws2.receive_json()["status"] == "running"
        finally:
            assert poll_until(lambda: kiosk_main._current_breakpoint is not None)
            kiosk_client.post("/breakpoint/respond", json={"proceed": False})

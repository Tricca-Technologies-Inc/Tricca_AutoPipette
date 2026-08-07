"""Tests for the actual `tap` CLI (`cli/remote_shell.py`) against a real,
in-process control plane.

`RemoteTapShell` owns no domain/Moonraker objects of its own -- it either
builds a `ControlRequests` request directly (hand-written `do_*` methods) or
is one of the generated `_STRUCTURED_COMMANDS` entries. What a request-
builder-level test can't exercise honestly is the *client-side reaction* to
what comes back over the wire: `_on_run_status`/`_on_breakpoint` react to
real `notify_run_status`/`notify_breakpoint` pushes (issue #37's specific
ask), and `_call_and_print`/`_send` react to a real JSON-RPC error frame,
not a canned one. Every test here drives a real `RemoteTapShell` against a
real `ControlServer` (`tests/support/live_control_plane.py`, via the
`live_control_plane` fixture in `tests/conftest.py`) over a real localhost
socket -- no mocking at the `send_jsonrpc` boundary.

`cli/tap_shell.py` and its `commands/*.py` CommandSets are out of scope (see
issue #39): this file only covers `RemoteTapShell`, the actual `tap` CLI.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.live_control_plane import LiveControlPlane
from support.polling import poll_until

from tricca_autopipette.cli import remote_shell as remote_shell_module
from tricca_autopipette.cli.remote_shell import RemoteTapShell
from tricca_autopipette.core.pipette_constants import DefaultPaths


@pytest.fixture
def shell(live_control_plane: LiveControlPlane) -> Iterator[RemoteTapShell]:
    """A `RemoteTapShell` connected to a real, in-process control plane.

    `stdout` is swapped for a plain `io.StringIO()` rather than left as
    cmd2's default (`sys.stdout`) captured via pytest's `capsys`: cmd2 reads
    `self.stdout` fresh on every `poutput()` call, but `self.stdout` itself
    is a snapshot taken once, here during fixture *setup* -- pytest's capsys
    swaps in a distinct stdout proxy per test phase (setup/call/teardown),
    so a snapshot taken during setup silently stops matching the proxy
    `capsys.readouterr()` reads from during the test's own call phase. A
    plain `io.StringIO()` sidesteps that entirely. `perror` (stderr) has no
    such problem -- it looks up `sys.stderr` fresh each call rather than a
    cached attribute -- so stderr-focused tests below use `capsys` directly.
    """
    tap = RemoteTapShell(live_control_plane.url)
    tap.stdout = io.StringIO()
    tap.preloop()
    assert tap.client.is_connected()
    tap.stdout = io.StringIO()  # discard preloop's own "Connecting.../Connected."
    yield tap
    tap.postloop()


def _output(shell: RemoteTapShell) -> str:
    """Read everything written to `shell.stdout` so far.

    `Cmd.stdout` is typed as the more general `TextIO`; the `shell` fixture
    always sets it to a real `io.StringIO()`, so narrowing here is safe.
    """
    stream = shell.stdout
    assert isinstance(stream, io.StringIO)
    return stream.getvalue()


@pytest.fixture
def protocol_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect `DefaultPaths.DIR_PROTOCOL` to an empty temp dir for the test.

    `AutoPipetteService.start_run` reads this class attribute fresh on every
    call, so patching it for the duration of one test is enough -- no need
    to thread a protocols-dir override through the service/fixture chain the
    way `gcode_path`/`locations_dir` already are in `tests/conftest.py`.
    """
    monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", tmp_path)
    return tmp_path


class TestConnectionLifecycle:
    def test_preloop_connects_and_reports_success(
        self, live_control_plane: LiveControlPlane, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tap = RemoteTapShell(live_control_plane.url)
        tap.preloop()
        try:
            assert tap.client.is_connected()
            assert "Connected." in capsys.readouterr().out
        finally:
            tap.postloop()

    def test_preloop_reports_failure_when_daemon_unreachable(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(remote_shell_module, "WEBSOCKET_TIMEOUT_SECONDS", 0.3)
        # Nothing listens on this port -- connection is refused immediately.
        tap = RemoteTapShell("ws://127.0.0.1:1/control")
        tap.preloop()
        try:
            assert not tap.client.is_connected()
            assert "Failed to connect" in capsys.readouterr().err
        finally:
            tap.postloop()

    def test_postloop_disconnects(self, live_control_plane: LiveControlPlane) -> None:
        tap = RemoteTapShell(live_control_plane.url)
        tap.preloop()
        assert tap.client.is_connected()

        tap.postloop()

        assert not tap.client.is_connected()


class TestRunLifecycleAlerts:
    """The alert-driven state handling issue #37 specifically calls out."""

    def test_do_run_renders_the_reply_and_pushes_a_running_alert(
        self, shell: RemoteTapShell, protocol_dir: Path
    ) -> None:
        (protocol_dir / "smoke.pipette").write_text('gcode_print "hi"\n')

        shell.onecmd_plus_hooks("run smoke.pipette")

        # 1. The direct run.start reply, rendered synchronously by
        #    _call_and_print.
        assert "running: Running smoke.pipette" in _output(shell)

        # 2. The daemon's own notify_run_status broadcast, delivered
        #    asynchronously and rendered by _on_run_status -> add_alert --
        #    the part a request-builder-level test can't reach at all.
        assert poll_until(
            lambda: any(
                a.msg and "[run:running] Running smoke.pipette" in a.msg
                for a in shell._alert_queue
            )
        )

    def test_do_run_surfaces_a_missing_protocol_file_as_a_real_rpc_error(
        self,
        shell: RemoteTapShell,
        protocol_dir: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        del protocol_dir  # exists (redirected), just empty
        capsys.readouterr()

        shell.onecmd_plus_hooks("run does_not_exist.pipette")

        err = capsys.readouterr().err
        assert "FileNotFoundError" in err
        assert "does_not_exist.pipette" in err

    def test_do_run_without_a_filename_reports_usage_locally(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()

        shell.onecmd_plus_hooks("run")

        assert "Usage: run <filename>" in capsys.readouterr().err


class TestBreakpointFlow:
    """`break`'s notify_breakpoint push, and continue/abort answering it."""

    def test_continue_releases_the_worker_thread_blocked_on_the_breakpoint(
        self,
        shell: RemoteTapShell,
        live_control_plane: LiveControlPlane,
        protocol_dir: Path,
    ) -> None:
        (protocol_dir / "bp.pipette").write_text(
            'gcode_print "before"\nbreak\ngcode_print "after"\n'
        )

        shell.onecmd_plus_hooks("run bp.pipette")
        assert poll_until(
            lambda: any(
                a.msg and "paused at a breakpoint" in a.msg for a in shell._alert_queue
            )
        )

        shell.onecmd_plus_hooks("continue")

        # request_breakpoint() blocks the worker thread _run_protocol
        # dispatches onto for the run's whole duration, holding
        # service._lock (an asyncio.Lock) the entire time; "continue"
        # resolving the breakpoint's threading.Event is what lets
        # _run_protocol_sync return and that lock release. There's no
        # observable RunStatus transition to poll instead: with no real
        # Moonraker connection (client is None here), a successful run
        # never reaches "done" -- that's detected later, from real
        # print_stats pushes -- so the lock release is the one honest
        # signal that "continue" actually unblocked the dispatch loop
        # rather than merely being accepted.
        assert poll_until(lambda: not live_control_plane.service._lock.locked())

    def test_abort_ends_the_run_with_an_error_status(
        self, shell: RemoteTapShell, protocol_dir: Path
    ) -> None:
        (protocol_dir / "bp.pipette").write_text("break\n")

        shell.onecmd_plus_hooks("run bp.pipette")
        assert poll_until(
            lambda: any(
                a.msg and "paused at a breakpoint" in a.msg for a in shell._alert_queue
            )
        )

        shell.onecmd_plus_hooks("abort")

        def _run_is_error() -> bool:
            response = shell.client.send_jsonrpc(shell.requests.run_status())
            return response["result"]["status"] == "error"

        assert poll_until(_run_is_error)


class TestStructuredCommands:
    """One passing and one failing round trip through a generated `do_*`."""

    def test_wait_dispatches_through_the_generated_handler(
        self, shell: RemoteTapShell
    ) -> None:
        shell.onecmd_plus_hooks("wait 5")

        assert "Wait: 5 ms" in _output(shell)

    def test_move_without_homing_surfaces_the_real_interlock_error(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # live_control_plane's underlying `service` fixture starts unhomed
        # (FakeMoonrakerState(homed=False)) -- this is the real
        # require_homed decorator raising NotHomedError inside the daemon,
        # not a canned client-side response.
        capsys.readouterr()

        shell.onecmd_plus_hooks("move 10 10 10")

        err = capsys.readouterr().err
        assert "NotHomedError" in err
        assert "not homed" in err


class TestReporting:
    """`ls`/`list_liquids` rendering real data fetched over the wire."""

    def test_ls_system_renders_the_real_default_config(
        self, shell: RemoteTapShell
    ) -> None:
        shell.onecmd_plus_hooks("ls system")

        # The exact table layout is build_system_table's concern (already
        # covered where that's tested); this just confirms the real
        # config.system_summary round trip reached the renderer at all.
        assert _output(shell).strip() != ""

    def test_list_liquids_reports_the_active_liquid(
        self, shell: RemoteTapShell
    ) -> None:
        shell.onecmd_plus_hooks("list_liquids")

        assert "Active liquid:" in _output(shell)


class TestRpcErrorSurfacing:
    """A control command failing for a reason unrelated to run lifecycle."""

    def test_do_stop_with_no_moonraker_connection_reports_the_real_error(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The underlying service was built with connect_websocket=False
        # (tests/conftest.py's `service` fixture) -- emergency_stop's
        # RuntimeError ("no connected WebSocket client") is real, not
        # injected for this test.
        capsys.readouterr()

        shell.onecmd_plus_hooks("stop")

        assert "RuntimeError" in capsys.readouterr().err


class TestUtilityCommands:
    def test_webcam_prints_a_url_built_from_the_real_hostname(
        self, shell: RemoteTapShell
    ) -> None:
        shell.onecmd_plus_hooks("webcam")

        assert "/webcam/" in _output(shell)

    def test_steps_to_vol_rejects_a_non_numeric_argument_locally(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # do_steps_to_vol parses its argument itself before sending
        # anything -- no round trip to the daemon for this one.
        capsys.readouterr()

        shell.onecmd_plus_hooks("steps_to_vol not-a-number")

        assert "Invalid steps value" in capsys.readouterr().err

    def test_steps_to_vol_rejects_a_negative_value_server_side(
        self, shell: RemoteTapShell
    ) -> None:
        shell.onecmd_plus_hooks("steps_to_vol -5")

        assert "cannot be negative" in _output(shell).lower()


class TestWebSocketDiagnostics:
    """The `ws.*` diagnostics/reporting group -- entirely hand-written,

    entirely unexercised before this PR.
    """

    def test_ws_status_reports_no_moonraker_client_configured(
        self, shell: RemoteTapShell
    ) -> None:
        # connect_websocket=False in the underlying `service` fixture, so
        # `self.client is None` server-side -- a real, not injected, state.
        shell.onecmd_plus_hooks("ws_status")

        assert "not initialized" in _output(shell).lower()

    def test_ping_surfaces_the_real_not_connected_error(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()

        shell.onecmd_plus_hooks("ping")

        assert "not connected" in capsys.readouterr().err.lower()

    def test_send_rejects_invalid_json_params_locally(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()

        shell.onecmd_plus_hooks("send server.info not-valid-json")

        assert "Invalid JSON" in capsys.readouterr().err

    def test_subscribe_without_a_method_reports_usage_locally(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()

        shell.onecmd_plus_hooks("subscribe")

        assert "Usage: subscribe <method>" in capsys.readouterr().err

    def test_reconnect_surfaces_the_real_no_client_error(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()

        shell.onecmd_plus_hooks("reconnect")

        # No Moonraker WebSocketClient exists at all in this service
        # (connect_websocket=False), so reconnect_websocket's own
        # precondition check is what's really being exercised here.
        assert capsys.readouterr().err != ""


class TestLsReporting:
    def test_ls_locs_reports_an_empty_deck(self, shell: RemoteTapShell) -> None:
        shell.onecmd_plus_hooks("ls locs")

        assert "No locations defined." in _output(shell)

    def test_ls_unknown_category_reports_the_valid_choices_locally(
        self, shell: RemoteTapShell, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()

        shell.onecmd_plus_hooks("ls nonsense")

        err = capsys.readouterr().err
        assert "Unknown category" in err
        assert "locs, plates, liquids, system" in err

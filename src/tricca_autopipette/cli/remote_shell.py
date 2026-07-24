"""Thin interactive client shell that talks to the `tapd` control daemon.

Unlike `TriccaAutoPipetteShell`, this owns no `AutoPipette`/`WebSocketClient`
of its own — all domain logic, config loading, and the Moonraker connection
live in the daemon's `HeadlessTapShell` (see `tricca_autopipette.daemon`).
Unrecognized commands are forwarded verbatim to the daemon's `shell.exec`;
`run`/`cancel`/`pause`/`resume`/`continue`/`abort` are explicit thin
wrappers around the matching control-plane RPCs so live progress renders
from `notify_run_status`/`notify_breakpoint` pushes instead of a single
blocking round-trip.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from cmd2 import Cmd, Statement

from tricca_autopipette.daemon.control_requests import ControlRequests
from tricca_autopipette.moonraker.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)

WEBSOCKET_TIMEOUT_SECONDS = 10


def _as_dict(value: Any) -> dict[str, Any]:  # noqa: ANN401
    """Narrow a loosely-typed JSON-RPC result/params value to a dict.

    Args:
        value: Value to narrow, typically a JSON-RPC ``result`` or
            notification ``params`` of otherwise unknown shape.

    Returns:
        ``value`` if it is a dict, otherwise an empty dict.
    """
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return {}


class RemoteTapShell(Cmd):
    """Interactive shell that proxies commands to a running `tapd` daemon.

    Attributes:
        control_uri: WebSocket URI of the daemon's control plane.
        requests: Pure-function builder for control-plane JSON-RPC requests.
        client: WebSocket client connected to the daemon's control plane.
    """

    def __init__(self, control_uri: str) -> None:
        """Initialize the remote shell.

        Args:
            control_uri: WebSocket URI of the daemon's control plane, e.g.
                "ws://127.0.0.1:8765/control".
        """
        super().__init__(allow_cli_args=False)
        self.intro = ""
        self.prompt = "tap >> "
        self.control_uri = control_uri
        self.requests = ControlRequests()
        self.client = WebSocketClient(control_uri)
        self.client.register_handler("notify_run_status", self._on_run_status)
        self.client.register_handler("notify_breakpoint", self._on_breakpoint)

    # ==================== lifecycle ====================

    def preloop(self) -> None:
        """Connect to the daemon's control plane before entering the loop."""
        self.poutput(f"Connecting to tapd at {self.control_uri}...")
        self.client.start()
        if not self.client.wait_for_connection(timeout=WEBSOCKET_TIMEOUT_SECONDS):
            self.perror(
                "Failed to connect to tapd. Is the daemon running? "
                "(see `tapd`/systemd/tapd.service)"
            )
        else:
            self.poutput("Connected.")

    def postloop(self) -> None:
        """Disconnect from the daemon's control plane on exit."""
        self.poutput("Disconnecting...")
        self.client.stop()

    # ==================== notification handlers ====================

    def _on_run_status(self, params: Any) -> None:  # noqa: ANN401
        """Show a live run-status update without disrupting the prompt.

        Args:
            params: `{"status", "message", "run_id", "filename"}` as sent by
                `AutoPipetteService._broadcast_status`.
        """
        notification = _as_dict(params)
        if not notification:
            return
        status = notification.get("status")
        message = notification.get("message", "")
        self.add_alert(msg=f"[run:{status}] {message}")

    def _on_breakpoint(self, params: Any) -> None:  # noqa: ANN401
        """Prompt the user to answer a pending breakpoint.

        Args:
            params: `{"run_id", "filename", "pending"}` as sent by
                `AutoPipetteService.request_breakpoint`/`confirm_breakpoint`.
        """
        notification = _as_dict(params)
        if notification.get("pending"):
            self.add_alert(
                msg="⏸ Protocol paused at a breakpoint. "
                "Type 'continue' or 'abort' to proceed."
            )

    # ==================== explicit run commands ====================

    def do_run(self, arg: Statement) -> None:
        """Start a protocol run: run <filename>."""
        filename = arg.args.strip()
        if not filename:
            self.perror("Usage: run <filename>")
            return
        self._call_and_print(self.requests.run_start(filename))

    def do_cancel(self, _: Statement) -> None:
        """Cancel the active run."""
        self._call_and_print(self.requests.run_cancel())

    def do_pause(self, _: Statement) -> None:
        """Pause the active run."""
        self._call_and_print(self.requests.run_pause())

    def do_resume(self, _: Statement) -> None:
        """Resume the active run."""
        self._call_and_print(self.requests.run_resume())

    def do_continue(self, _: Statement) -> None:
        """Confirm a pending breakpoint and continue the protocol."""
        self._confirm_breakpoint(proceed=True)

    def do_abort(self, _: Statement) -> None:
        """Confirm a pending breakpoint and abort the protocol."""
        self._confirm_breakpoint(proceed=False)

    def _confirm_breakpoint(self, *, proceed: bool) -> None:
        """Send a breakpoint confirmation to the daemon.

        Args:
            proceed: True to continue the protocol, False to abort it.
        """
        try:
            self.client.send_jsonrpc(self.requests.run_confirm_breakpoint(proceed))
        except RuntimeError as exc:
            self.perror(str(exc))
            return
        self.poutput("Continuing..." if proceed else "Aborting...")

    def _call_and_print(self, request: dict[str, Any]) -> None:
        """Send a control-plane request and print its result.

        Args:
            request: JSON-RPC request dict, as built by `self.requests`.
        """
        try:
            response = self.client.send_jsonrpc(request)
        except RuntimeError as exc:
            self.perror(str(exc))
            return
        raw_result: Any = response.get("result")
        result = _as_dict(raw_result)
        if "status" in result:
            self.poutput(f"{result.get('status')}: {result.get('message', '')}")
        else:
            self.poutput(str(raw_result))

    # ==================== catch-all: forward to shell.exec ====================

    def default(self, statement: Statement) -> None:
        """Forward any unrecognized command to the daemon's `shell.exec`.

        Args:
            statement: The parsed (but unrecognized-as-a-local-command)
                statement; its raw text is forwarded verbatim.
        """
        try:
            response = self.client.send_jsonrpc(self.requests.shell_exec(statement.raw))
        except RuntimeError as exc:
            self.perror(str(exc))
            return

        result = _as_dict(response.get("result"))
        output = result.get("output", "")
        if output:
            self.poutput(str(output).rstrip("\n"))

        error = result.get("error")
        if error:
            self.perror(str(error))

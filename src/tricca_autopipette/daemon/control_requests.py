"""Request builders for the ``tapd`` control-plane JSON-RPC protocol.

Pure functions, no I/O — mirrors the shape of
``moonraker/moonraker_requests.py`` so callers can send the resulting dicts
through the same ``WebSocketClient.send_jsonrpc`` transport used to talk to
Moonraker itself.

Example:
    >>> from tricca_autopipette.moonraker.websocket_client import WebSocketClient
    >>> client = WebSocketClient("ws://127.0.0.1:8765/control")
    >>> client.start()
    >>> client.wait_for_connection()
    >>> response = client.send_jsonrpc(ControlRequests().run_start("A1.pipette"))
"""

from __future__ import annotations

import uuid
from typing import Any


class ControlRequests:
    """JSON-RPC request builder for the ``tapd`` control-plane protocol."""

    JSON_RPC_VERSION: str = "2.0"

    def gen_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Generate a JSON-RPC 2.0 request.

        Args:
            method: Control-plane method to call.
            params: Optional parameters dictionary for the method.

        Returns:
            Dictionary representing the JSON-RPC request.
        """
        request: dict[str, Any] = {
            "jsonrpc": self.JSON_RPC_VERSION,
            "method": method,
            "id": str(uuid.uuid4()),
        }
        if params is not None:
            request["params"] = params
        return request

    def shell_exec(self, line: str) -> dict[str, Any]:
        """Build a request to run one raw shell command line.

        Args:
            line: Raw shell command line, exactly as typed interactively.

        Returns:
            Request to execute the given line.
        """
        return self.gen_request("shell.exec", {"line": line})

    def run_start(self, filename: str) -> dict[str, Any]:
        """Build a request to start a protocol run.

        Args:
            filename: Bare filename under ``protocols/`` (e.g. "A1.pipette").

        Returns:
            Request to start the run.
        """
        return self.gen_request("run.start", {"filename": filename})

    def run_status(self) -> dict[str, Any]:
        """Build a request for the current run status.

        Returns:
            Request for run status.
        """
        return self.gen_request("run.status")

    def run_cancel(self) -> dict[str, Any]:
        """Build a request to cancel the active run.

        Returns:
            Request to cancel the run.
        """
        return self.gen_request("run.cancel")

    def run_pause(self) -> dict[str, Any]:
        """Build a request to pause the active run.

        Returns:
            Request to pause the run.
        """
        return self.gen_request("run.pause")

    def run_resume(self) -> dict[str, Any]:
        """Build a request to resume the active run.

        Returns:
            Request to resume the run.
        """
        return self.gen_request("run.resume")

    def protocols_list(self) -> dict[str, Any]:
        """Build a request to list available protocol files.

        Returns:
            Request for the protocol list.
        """
        return self.gen_request("protocols.list")

    def daemon_ping(self) -> dict[str, Any]:
        """Build a health-check request.

        Returns:
            Request for daemon/Moonraker connectivity status.
        """
        return self.gen_request("daemon.ping")

"""A real kiosk HTTP server, run on its own thread, for browser-driven tests.

Playwright needs a real ``http://`` socket to point a browser at --
`fastapi.testclient.TestClient`'s in-process ASGI transport (what
`tests/kiosk/conftest.py`'s `kiosk_client` fixture uses) doesn't provide one.
Mirrors `tests/support/live_control_plane.py`'s shape: its own background
thread, so a synchronous test body (Playwright's sync API included) can
block freely without starving the server's own event loop.
"""

from __future__ import annotations

import threading
import time

import uvicorn
from fastapi import FastAPI


class LiveKioskServer(uvicorn.Server):
    """A real `uvicorn` server for the kiosk app, bound to an ephemeral port.

    Attributes:
        url: The `http://127.0.0.1:<port>` base URL, valid once `start()`
            returns.
    """

    def __init__(self, app: FastAPI) -> None:
        """Configure the server; nothing runs until `start()`.

        Args:
            app: The kiosk's FastAPI app (`autopipette_kiosk.main.app`),
                with `TAPD_CONTROL_URI` and the run/breakpoint/ws-client
                module globals already patched to a test backend -- same
                setup `tests/kiosk/conftest.py`'s `kiosk_client` does.
        """
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        super().__init__(config)
        self.url = ""
        self._thread = threading.Thread(target=self.run, daemon=True)

    def install_signal_handlers(self) -> None:
        """No-op: uvicorn's default SIGINT/SIGTERM handlers need the main
        thread, but this server runs on a background one."""

    def start(self, *, timeout: float = 5.0) -> None:
        """Start the server thread and block until `url` is ready to dial.

        Raises:
            RuntimeError: If the server doesn't become ready within
                `timeout` seconds.
        """
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Live kiosk server failed to start")
            time.sleep(1e-3)
        host, port = self.servers[0].sockets[0].getsockname()[:2]
        self.url = f"http://{host}:{port}"

    def stop(self, *, timeout: float = 5.0) -> None:
        """Signal shutdown and join the server thread."""
        self.should_exit = True
        self._thread.join(timeout=timeout)

"""A real `ControlServer`, run on its own thread, for control-plane tests.

Backs both the CLI (`tests/cli/`) and kiosk (`tests/kiosk/`, once it exists)
test suites: rather than mocking at the RPC-call boundary, both connect to
this as genuine control-plane clients over a real localhost socket, exercising
the real JSON-RPC envelope and real `notify_run_status`/`notify_breakpoint`
push timing -- the thing a client-side unit test mocking `send_jsonrpc`
directly can't catch (see issue #37).

Mirrors `tests/moonraker/test_websocket_client.py`'s `_RealServer`: its own
background thread with its own event loop, rather than an async pytest
fixture on a per-test loop, so a synchronous test body (or, for the kiosk, a
`fastapi.testclient.TestClient` -- itself synchronous) can freely make
blocking calls without starving the server's own I/O.
"""

from __future__ import annotations

import asyncio
import threading

from tricca_autopipette.daemon.control_server import ControlServer
from tricca_autopipette.daemon.service import AutoPipetteService


class LiveControlPlane:
    """A real `ControlServer`, wrapping an already-built `AutoPipetteService`.

    Attributes:
        service: The service instance backing the server -- build it with
            the fakes-at-the-Moonraker-boundary style `tests/conftest.py`'s
            `service`/`service_with_plates` fixtures already use.
        url: The `ws://127.0.0.1:<port>/control` URL a control-plane client
            can connect to, valid once `start()` returns.
    """

    def __init__(self, service: AutoPipetteService) -> None:
        """Store the service; nothing runs until `start()`.

        Args:
            service: A fully constructed `AutoPipetteService`, not yet
                started -- `ControlServer.start()` calls `service.start()`
                itself.
        """
        self.service = service
        self.url = ""
        self._server: ControlServer | None = None
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._shutdown: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        server = ControlServer(self.service, host="127.0.0.1", port=0)
        self._server = server
        await server.start()
        # tests/ disables reportPrivateUsage (see pyproject.toml) -- reaching
        # into the runner for its ephemeral bound port is deliberate, the
        # same white-box style the daemon tests already use. `start()` just
        # set `_runner`; pyright can't see across that method call.
        assert server._runner is not None  # pyright: ignore[reportPrivateUsage]
        host, port = server._runner.addresses[0]  # pyright: ignore[reportPrivateUsage]
        self.url = f"ws://{host}:{port}/control"

        self._shutdown = asyncio.Event()
        self._ready.set()
        await self._shutdown.wait()
        await server.stop()

    def start(self, *, timeout: float = 5.0) -> None:
        """Start the server thread and block until `url` is ready to dial.

        Raises:
            RuntimeError: If the server doesn't become ready within
                `timeout` seconds.
        """
        self._thread.start()
        if not self._ready.wait(timeout=timeout):
            raise RuntimeError("Live control plane failed to start")

    def stop(self, *, timeout: float = 5.0) -> None:
        """Shut down the server and its service, and join the thread."""
        if self._shutdown is not None:
            self._loop.call_soon_threadsafe(self._shutdown.set)
        self._thread.join(timeout=timeout)
        self._loop.close()

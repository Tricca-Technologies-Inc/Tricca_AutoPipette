"""Local control-plane WebSocket server for the ``tapd`` daemon.

Exposes a single ``aiohttp`` WebSocket route carrying JSON-RPC 2.0 requests
(``{"jsonrpc","method","id","params"}``), deliberately isomorphic to the
envelope ``MoonrakerRequests.gen_request`` already produces, so the same
client transport shape (``WebSocketClient``) works for both the
daemon-to-Moonraker hop and the client-to-daemon hop. See
``daemon/control_requests.py`` for the pure-function request builders
clients should use instead of hand-rolling these dicts.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import WSMsgType, web

from tricca_autopipette.daemon.service import AutoPipetteService, RunStatus

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _run_status_to_dict(status: RunStatus) -> dict[str, Any]:
    """Convert a ``RunStatus`` dataclass to a JSON-serializable dict.

    Args:
        status: The ``RunStatus`` instance to convert.

    Returns:
        Dict with ``status``, ``message``, ``run_id``, ``filename`` keys.
    """
    return {
        "status": status.status,
        "message": status.message,
        "run_id": status.run_id,
        "filename": status.filename,
    }


class ControlServer:
    """Hosts the control-plane WebSocket and dispatches RPCs to a service.

    Attributes:
        service: The ``AutoPipetteService`` backing this server.
    """

    def __init__(
        self,
        service: AutoPipetteService,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        """Initialize the control server.

        Args:
            service: The service to dispatch requests to.
            host: Address to bind the control-plane WebSocket to.
            port: Port to bind the control-plane WebSocket to.
        """
        self.service = service
        self._host = host
        self._port = port
        self._clients: set[web.WebSocketResponse] = set()
        self._app = web.Application()
        self._app.router.add_get("/control", self._handle_control)
        self._runner: web.AppRunner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        """Start the underlying service and begin listening for clients."""
        self._loop = asyncio.get_running_loop()
        self.service.set_broadcast_callback(self._broadcast)
        await self.service.start()

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info(
            "Control server listening on ws://%s:%d/control", self._host, self._port
        )

    async def stop(self) -> None:
        """Close all client connections and shut down the service."""
        for ws in list(self._clients):
            await ws.close()
        if self._runner is not None:
            await self._runner.cleanup()
        await self.service.stop()

    def _broadcast(self, method: str, params: dict[str, Any]) -> None:
        """Schedule a notification push to every connected client.

        Called both from the event loop thread (``AutoPipetteService``'s own
        async methods) and from worker threads (e.g.
        ``request_breakpoint``, invoked via ``asyncio.to_thread``), so this
        must not assume it's running on the loop's thread —
        ``asyncio.create_task`` would raise ``RuntimeError: no running
        event loop`` when called from a worker thread.

        Args:
            method: Notification method name (e.g. "notify_run_status").
            params: Notification payload.
        """
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._broadcast_async(method, params), self._loop
        )

    async def _broadcast_async(self, method: str, params: dict[str, Any]) -> None:
        """Send a notification frame to every connected client.

        Args:
            method: Notification method name.
            params: Notification payload.
        """
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        stale: list[web.WebSocketResponse] = []
        # Snapshot: _handle_control's finally-block can discard from
        # self._clients concurrently (e.g. a client disconnecting mid-
        # broadcast), which would otherwise raise "Set changed size during
        # iteration" and silently drop this broadcast.
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except ConnectionResetError:
                stale.append(ws)
        for ws in stale:
            self._clients.discard(ws)

    async def _handle_control(self, request: web.Request) -> web.WebSocketResponse:
        """Handle one control-plane client connection for its lifetime.

        Args:
            request: Incoming HTTP request being upgraded to a WebSocket.

        Returns:
            The WebSocket response object for this connection.
        """
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._dispatch(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.warning("Control websocket error: %s", ws.exception())
        finally:
            self._clients.discard(ws)
        return ws

    async def _dispatch(self, ws: web.WebSocketResponse, raw: str) -> None:
        """Parse and dispatch one incoming JSON-RPC request.

        Args:
            ws: The client connection the request arrived on.
            raw: Raw text frame payload.
        """
        try:
            request = json.loads(raw)
        except json.JSONDecodeError as exc:
            error = {"message": f"invalid json: {exc}"}
            await ws.send_json({"id": None, "error": error})
            return

        method = request.get("method")
        params: dict[str, Any] = request.get("params") or {}
        request_id = request.get("id")

        try:
            result = await self._call(method, params)
            await ws.send_json({"id": request_id, "result": result})
        except Exception as exc:
            logger.exception("Error dispatching control-plane method '%s'", method)
            await ws.send_json({
                "id": request_id,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })

    async def _call(self, method: str | None, params: dict[str, Any]) -> Any:  # noqa: ANN401
        """Route one method name to the corresponding service call.

        Args:
            method: JSON-RPC method name.
            params: JSON-RPC params dict.

        Returns:
            JSON-serializable result.

        Raises:
            ValueError: If the method name is unknown.
            RunAlreadyActiveError: If ``run.start`` is called while a run is
                already active.
            FileNotFoundError: If ``run.start`` names a missing protocol.
        """
        if method == "shell.exec":
            return await self.service.execute_line(params["line"])
        if method == "run.start":
            status = await self.service.start_run(params["filename"])
            return _run_status_to_dict(status)
        if method == "run.status":
            return _run_status_to_dict(self.service.get_status())
        if method == "run.cancel":
            return _run_status_to_dict(await self.service.cancel_run())
        if method == "run.pause":
            return _run_status_to_dict(await self.service.pause_run())
        if method == "run.resume":
            return _run_status_to_dict(await self.service.resume_run())
        if method == "run.confirm_breakpoint":
            await self.service.confirm_breakpoint(bool(params["proceed"]))
            return {}
        if method == "protocols.list":
            return {"protocols": self.service.list_protocols()}
        if method == "daemon.ping":
            return await self.service.ping()
        raise ValueError(f"Unknown method: {method}")

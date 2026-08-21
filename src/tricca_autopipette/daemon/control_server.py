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
import dataclasses
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from tricca_autopipette.commands.tap_cmd_parsers import (
    AspirateArgs,
    CoorArgs,
    DelLocArgs,
    DispenseArgs,
    GcodePrintArgs,
    HomeArgs,
    LoadLocationsArgs,
    MoveArgs,
    MoveLocArgs,
    MoveRelArgs,
    PipetteArgs,
    PlateArgs,
    ResetPlateArgs,
    ResetTipsArgs,
    SetArgs,
    SetTipsArgs,
    TipsArgs,
    TriggerArgs,
    UnloadLocationsArgs,
    VolToStepsArgs,
    WaitArgs,
)
from tricca_autopipette.daemon.service import (
    AutoPipetteService,
    CommandResult,
    RunStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclasses.dataclass(frozen=True)
class _RpcCommand:
    """One entry in the regular-shaped RPC dispatch table.

    Covers every control-plane method whose handling is exactly "build an
    ``*Args`` dataclass from ``params`` (or take no arguments), dispatch the
    named ``AutoPipetteService`` method through ``service.dispatch``, and
    ``dataclasses.asdict`` the ``CommandResult`` it returns" -- the large
    majority of methods. Methods with any other shape (a bare-value
    argument instead of an ``*Args`` dataclass, a non-``CommandResult``
    return, special handling of ``ws``/``self._clients``, ...) are handled
    as explicit branches in :meth:`ControlServer._call` instead of forced
    into this table.

    Mirrors ``daemon/service.py``'s ``_LineCommand``/``_LINE_DISPATCH``,
    which solves the identical "command name -> parser/args -> service
    method" problem for protocol-file lines -- one shape for both.

    Attributes:
        args_cls: The ``*Args`` dataclass to build from ``params``, or None
            for a zero-argument RPC.
        method: The corresponding *unbound* ``AutoPipetteService`` method
            (``AutoPipetteService.move``, not a bound instance method) --
            called as ``method(service_instance, args)`` (or
            ``method(service_instance)`` when ``args_cls`` is None).
    """

    args_cls: type | None
    method: Callable[..., CommandResult]


#: Maps a control-plane method name to how to build its args and which
#: service method to dispatch it to. Built once at import time -- see
#: :class:`_RpcCommand`'s docstring for the shape this covers and why some
#: methods are deliberately not listed here.
_RPC_DISPATCH: dict[str, _RpcCommand] = {
    "movement.init": _RpcCommand(None, AutoPipetteService.init),
    "movement.home": _RpcCommand(HomeArgs, AutoPipetteService.home),
    "movement.move": _RpcCommand(MoveArgs, AutoPipetteService.move),
    "movement.move_loc": _RpcCommand(MoveLocArgs, AutoPipetteService.move_loc),
    "movement.move_rel": _RpcCommand(MoveRelArgs, AutoPipetteService.move_rel),
    "pipette.aspirate": _RpcCommand(AspirateArgs, AutoPipetteService.aspirate),
    "pipette.dispense": _RpcCommand(DispenseArgs, AutoPipetteService.dispense),
    "pipette.transfer": _RpcCommand(PipetteArgs, AutoPipetteService.transfer),
    "pipette.next_tip": _RpcCommand(None, AutoPipetteService.next_tip),
    "pipette.eject_tip": _RpcCommand(None, AutoPipetteService.eject_tip),
    "pipette.dispose_tip": _RpcCommand(None, AutoPipetteService.dispose_tip),
    "pipette.change_tip": _RpcCommand(None, AutoPipetteService.change_tip),
    "config.set": _RpcCommand(SetArgs, AutoPipetteService.set),
    "config.coor": _RpcCommand(CoorArgs, AutoPipetteService.coor),
    "config.plate": _RpcCommand(PlateArgs, AutoPipetteService.plate),
    "config.reset_plate": _RpcCommand(ResetPlateArgs, AutoPipetteService.reset_plate),
    "config.reset_plates": _RpcCommand(None, AutoPipetteService.reset_plates),
    "config.del_loc": _RpcCommand(DelLocArgs, AutoPipetteService.del_loc),
    "config.clear_locs": _RpcCommand(None, AutoPipetteService.clear_locs),
    "config.load_locations": _RpcCommand(
        LoadLocationsArgs, AutoPipetteService.load_locations
    ),
    "config.unload_locations": _RpcCommand(
        UnloadLocationsArgs, AutoPipetteService.unload_locations
    ),
    "config.reset_tips": _RpcCommand(ResetTipsArgs, AutoPipetteService.reset_tips),
    "config.reset_tips_all": _RpcCommand(None, AutoPipetteService.reset_tips_all),
    "config.set_tips": _RpcCommand(SetTipsArgs, AutoPipetteService.set_tips),
    "config.tips": _RpcCommand(TipsArgs, AutoPipetteService.tips),
    "util.wait": _RpcCommand(WaitArgs, AutoPipetteService.wait),
    "util.trigger": _RpcCommand(TriggerArgs, AutoPipetteService.trigger),
    "util.gcode_print": _RpcCommand(GcodePrintArgs, AutoPipetteService.gcode_print),
    "util.webcam_url": _RpcCommand(None, AutoPipetteService.webcam_url),
    "util.vol_to_steps": _RpcCommand(VolToStepsArgs, AutoPipetteService.vol_to_steps),
    "ws.status": _RpcCommand(None, AutoPipetteService.ws_status),
    "ws.ping": _RpcCommand(None, AutoPipetteService.ping_moonraker),
    "ws.read": _RpcCommand(None, AutoPipetteService.read_message),
    "ws.read_all": _RpcCommand(None, AutoPipetteService.read_all_messages),
    "ws.clear_queue": _RpcCommand(None, AutoPipetteService.clear_message_queue),
    "ws.reconnect": _RpcCommand(None, AutoPipetteService.reconnect_websocket),
    "ws.query_endstops": _RpcCommand(None, AutoPipetteService.query_endstops),
    "config.list_locations": _RpcCommand(None, AutoPipetteService.list_locations),
    "config.list_plates": _RpcCommand(None, AutoPipetteService.list_plates),
    "config.list_liquids": _RpcCommand(None, AutoPipetteService.list_liquids),
    "config.system_summary": _RpcCommand(None, AutoPipetteService.system_summary),
}


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
        # Maps each connected client to the type it identified itself as
        # via `daemon.identify` ("tap"/"kiosk"), or "unknown" for a
        # connection that hasn't (yet) sent one -- an audit-trail label for
        # the RPC log, not access control (see issue #53).
        self._clients: dict[web.WebSocketResponse, str] = {}
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
            self._clients.pop(ws, None)

    async def _handle_control(self, request: web.Request) -> web.WebSocketResponse:
        """Handle one control-plane client connection for its lifetime.

        Args:
            request: Incoming HTTP request being upgraded to a WebSocket.

        Returns:
            The WebSocket response object for this connection.
        """
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients[ws] = "unknown"
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._dispatch(ws, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.warning("Control websocket error: %s", ws.exception())
        finally:
            self._clients.pop(ws, None)
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

        # The control plane has no authentication (loopback-only trust, see
        # CLAUDE.md) -- this is the only audit trail available for who did
        # what, so every RPC is logged before it runs, not just failures.
        # Client type comes from a prior `daemon.identify` call on this same
        # connection (see issue #53); a connection that never identified
        # itself just logs as "unknown" -- this is an audit label, not
        # access control, so nothing is rejected for omitting it.
        client_type = self._clients.get(ws, "unknown")
        logger.info("Control-plane RPC [%s]: %s %r", client_type, method, params)

        try:
            result = await self._call(method, params, ws)
            await ws.send_json({"id": request_id, "result": result})
        except Exception as exc:
            logger.exception("Error dispatching control-plane method '%s'", method)
            await ws.send_json({
                "id": request_id,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            })

    async def _call(
        self,
        method: str | None,
        params: dict[str, Any],
        ws: web.WebSocketResponse | None = None,
    ) -> Any:  # ruff:ignore[any-type]
        """Route one method name to the corresponding service call.

        Args:
            method: JSON-RPC method name.
            params: JSON-RPC params dict.
            ws: The connection the request arrived on, used only by
                ``daemon.identify`` to record that connection's client
                type. ``None`` (e.g. in the dispatch-completeness test,
                which calls ``_call`` directly) just means the identity
                can't be recorded.

        Returns:
            JSON-serializable result.

        Raises:
            ValueError: If the method name is unknown.
            RunAlreadyActiveError: If ``run.start`` is called while a run is
                already active.
            FileNotFoundError: If ``run.start`` names a missing protocol.
        """  # ruff: ignore[docstring-extraneous-exception]
        spec = _RPC_DISPATCH.get(method) if method is not None else None
        if spec is not None:
            if spec.args_cls is None:
                return dataclasses.asdict(
                    await self.service.dispatch(lambda: spec.method(self.service))
                )
            args = spec.args_cls(**params)
            return dataclasses.asdict(
                await self.service.dispatch(lambda: spec.method(self.service, args))
            )
        if method == "config.switch_liquid":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.switch_liquid(params["liquid_name"])
                )
            )
        if method == "config.load_liquid":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.load_liquid(params["filename"])
                )
            )
        if method == "config.save_locations":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.save_locations(params["filename"])
                )
            )
        if method == "util.steps_to_vol":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.steps_to_vol(params["steps"])
                )
            )
        if method == "util.see_calibration":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.see_calibration(params.get("liquid"))
                )
            )
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
        if method == "run.stop":
            return _run_status_to_dict(await self.service.stop_run())
        if method == "protocols.list":
            return {"protocols": self.service.list_protocols()}
        if method == "daemon.ping":
            return await self.service.ping()
        if method == "daemon.identify":
            client_type = str(params.get("client_type", "unknown"))
            if ws is not None:
                self._clients[ws] = client_type
            return {}
        if method == "daemon.clients":
            return {
                "clients": [
                    {"client_type": client_type}
                    for client_type in self._clients.values()
                ]
            }
        if method == "ws.send":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.send_raw(
                        params["method"], params.get("params")
                    )
                )
            )
        if method == "ws.notify":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.notify_raw(
                        params["method"], params.get("params")
                    )
                )
            )
        if method == "ws.subscribe":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.subscribe_raw(params["method"])
                )
            )
        if method == "ws.unsubscribe":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.unsubscribe_raw(params["method"])
                )
            )
        if method == "ws.upload":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.upload_gcode_result(
                        params["file_name"], Path(params["file_path"])
                    )
                )
            )
        raise ValueError(f"Unknown method: {method}")

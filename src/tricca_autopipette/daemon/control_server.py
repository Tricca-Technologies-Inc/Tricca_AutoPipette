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
        if method == "movement.init":
            return dataclasses.asdict(await self.service.dispatch(self.service.init))
        if method == "movement.home":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.home(HomeArgs(**params))
                )
            )
        if method == "movement.move":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.move(MoveArgs(**params))
                )
            )
        if method == "movement.move_loc":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.move_loc(MoveLocArgs(**params))
                )
            )
        if method == "movement.move_rel":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.move_rel(MoveRelArgs(**params))
                )
            )
        if method == "pipette.aspirate":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.aspirate(AspirateArgs(**params))
                )
            )
        if method == "pipette.dispense":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.dispense(DispenseArgs(**params))
                )
            )
        if method == "pipette.transfer":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.transfer(PipetteArgs(**params))
                )
            )
        if method == "pipette.next_tip":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.next_tip)
            )
        if method == "pipette.eject_tip":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.eject_tip)
            )
        if method == "pipette.dispose_tip":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.dispose_tip)
            )
        if method == "pipette.change_tip":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.change_tip)
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
        if method == "config.set":
            return dataclasses.asdict(
                await self.service.dispatch(lambda: self.service.set(SetArgs(**params)))
            )
        if method == "config.coor":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.coor(CoorArgs(**params))
                )
            )
        if method == "config.plate":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.plate(PlateArgs(**params))
                )
            )
        if method == "config.reset_plate":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.reset_plate(ResetPlateArgs(**params))
                )
            )
        if method == "config.reset_plates":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.reset_plates)
            )
        if method == "config.del_loc":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.del_loc(DelLocArgs(**params))
                )
            )
        if method == "config.clear_locs":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.clear_locs)
            )
        if method == "config.save_locations":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.save_locations(params["filename"])
                )
            )
        if method == "config.load_locations":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.load_locations(LoadLocationsArgs(**params))
                )
            )
        if method == "config.unload_locations":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.unload_locations(UnloadLocationsArgs(**params))
                )
            )
        if method == "config.reset_tips":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.reset_tips(ResetTipsArgs(**params))
                )
            )
        if method == "config.reset_tips_all":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.reset_tips_all)
            )
        if method == "config.set_tips":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.set_tips(SetTipsArgs(**params))
                )
            )
        if method == "config.tips":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.tips(TipsArgs(**params))
                )
            )
        if method == "util.wait":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.wait(WaitArgs(**params))
                )
            )
        if method == "util.trigger":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.trigger(TriggerArgs(**params))
                )
            )
        if method == "util.gcode_print":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.gcode_print(GcodePrintArgs(**params))
                )
            )
        if method == "util.webcam_url":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.webcam_url)
            )
        if method == "util.vol_to_steps":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.vol_to_steps(VolToStepsArgs(**params))
                )
            )
        if method == "util.steps_to_vol":
            return dataclasses.asdict(
                await self.service.dispatch(
                    lambda: self.service.steps_to_vol(params["steps"])
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
        if method == "ws.status":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.ws_status)
            )
        if method == "ws.ping":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.ping_moonraker)
            )
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
        if method == "ws.read":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.read_message)
            )
        if method == "ws.read_all":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.read_all_messages)
            )
        if method == "ws.clear_queue":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.clear_message_queue)
            )
        if method == "ws.reconnect":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.reconnect_websocket)
            )
        if method == "config.list_locations":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.list_locations)
            )
        if method == "config.list_plates":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.list_plates)
            )
        if method == "config.list_liquids":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.list_liquids)
            )
        if method == "config.system_summary":
            return dataclasses.asdict(
                await self.service.dispatch(self.service.system_summary)
            )
        raise ValueError(f"Unknown method: {method}")

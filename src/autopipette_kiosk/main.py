"""AutoPipette Kiosk — FastAPI backend.

Serves the protocol list from the protocols/ directory and dispatches runs
by talking to the `tapd` control daemon's control-plane WebSocket (see
`tricca_autopipette.daemon`) instead of spawning a fresh CLI subprocess per
run. One `WebSocketClient` connection is held for the app's lifetime;
`notify_run_status` pushes from the daemon (driven by real Moonraker
`print_stats` transitions) are re-broadcast to connected browser clients.

Run with:
    uvicorn autopipette_kiosk.main:app --host 127.0.0.1 --port 8000

This app has no authentication of any kind, so bind loopback only: the
touchscreen runs a browser on the same host. Binding another interface
publishes unauthenticated control of a gantry and syringe to the network.
See systemd/README.md before exposing it.
"""

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tricca_autopipette.commands.tap_cmd_parsers import (
    ResetTipsArgs,
    SetTipsArgs,
    TipsArgs,
)
from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.control_requests import ControlRequests
from tricca_autopipette.moonraker.websocket_client import (
    JsonRpcError,
    WebSocketClient,
    as_dict,
)

logger = logging.getLogger(__name__)

# ── paths ──────────────────────────────────────────────────────────────────────
# Reuse the core's repo-root resolution rather than recomputing it from
# __file__ here: this package sits next to tricca_autopipette in the same
# install, and a second copy of the logic silently diverged once already
# (it missed the AUTOPIPETTE_REPO_ROOT override added for installed
# layouts, where __file__-relative walking lands a directory too high).
REPO_ROOT = DefaultPaths.DIR_REPO_ROOT
PROTOCOLS_DIR = Path(
    os.environ.get("AUTOPIPETTE_PROTOCOLS_DIR", REPO_ROOT / "protocols")
)
STATIC_DIR = Path(__file__).parent / "static"

TAPD_CONTROL_URI = os.environ.get("TAPD_CONTROL_URI", "ws://127.0.0.1:8765/control")
TAPD_CONNECT_TIMEOUT_SECONDS = 10


# ── models ─────────────────────────────────────────────────────────────────────
class Protocol(BaseModel):
    """A protocol file available to run, as listed under `protocols/`."""

    name: str  # display name, e.g. "A1"
    filename: str  # bare filename, e.g. "A1.pipette"


class RunRequest(BaseModel):
    """Request body for `POST /run`."""

    filename: str  # e.g. "A1.pipette"


class RunStatus(BaseModel):
    """Current (or most recent) protocol run status."""

    status: Literal["idle", "running", "done", "error"]
    message: str = ""


class BreakpointResponse(BaseModel):
    """Request body for `POST /breakpoint/respond`."""

    proceed: bool


class TipsResetRequest(BaseModel):
    """Request body for `POST /tips/reset`."""

    name: str  # tipbox location name


class TipsSetRequest(BaseModel):
    """Request body for `POST /tips/set`.

    `ranges`/`available` mirror `SetTipsArgs` (see `tap_cmd_parsers.py`):
    `config.set_tips` *replaces* the named box's entire state, so the
    frontend always sends the box's complete new consumed (or available)
    set, never a single toggled cell.
    """

    name: str  # tipbox location name
    ranges: list[str]  # well IDs/ranges, e.g. ["A1", "B3:B6"]
    available: bool = False


class TipsResult(BaseModel):
    """Response envelope for the `/tips*` routes.

    Mirrors `CommandResult` (`ok`/`message`/`data`) rather than translating
    to an HTTP error status: unlike `/run`/`/home`, the tip RPCs
    (`config.tips`/`config.reset_tips`/`config.set_tips`) report failure
    (e.g. "no such tipbox") as `CommandResult(ok=False, ...)`, not as a
    raised exception, so there's no exception to translate.
    """

    ok: bool
    message: str = ""
    data: dict[str, Any] | None = None


# ── daemon control-plane connection ────────────────────────────────────────────
_control_client: WebSocketClient | None = None
_control_requests = ControlRequests()
_main_loop: asyncio.AbstractEventLoop | None = None

# ── in-memory run state, mirrored from the daemon's notify_run_status pushes ──
_current_run: RunStatus = RunStatus(status="idle")
# Pending breakpoint, mirrored from notify_breakpoint pushes: {"run_id",
# "filename", "pending"} while one is awaiting a response, None otherwise.
_current_breakpoint: dict[str, Any] | None = None
_ws_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Connect to the tapd control plane for the lifetime of the app.

    Args:
        _app: The FastAPI app instance (unused; required by the lifespan
            protocol).

    Yields:
        None. Control-plane connection teardown happens after the yield.
    """
    global _control_client, _main_loop
    _main_loop = asyncio.get_running_loop()

    client = WebSocketClient(TAPD_CONTROL_URI)
    client.register_handler("notify_run_status", _on_run_status_notification)
    client.register_handler("notify_breakpoint", _on_breakpoint_notification)
    client.start()
    connected = await asyncio.to_thread(
        client.wait_for_connection, TAPD_CONNECT_TIMEOUT_SECONDS
    )
    if not connected:
        logger.error("Failed to connect to tapd control plane at %s", TAPD_CONTROL_URI)
    else:
        # One-time identity so the daemon's RPC log can attribute
        # subsequent calls on this connection to "kiosk" (issue #53) -- an
        # audit-trail label, not access control, so a failure here is
        # logged rather than treated as fatal to startup.
        try:
            await asyncio.to_thread(
                client.send_jsonrpc, _control_requests.identify("kiosk")
            )
        except RuntimeError:
            logger.warning("Failed to identify this connection to tapd.")
    _control_client = client

    try:
        yield
    finally:
        _control_client = None
        await asyncio.to_thread(client.stop)


app = FastAPI(title="AutoPipette Kiosk", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def index() -> FileResponse:
    """Serve the kiosk's single-page frontend.

    Returns:
        The static `index.html` file.
    """
    return FileResponse(STATIC_DIR / "index.html")


def _list_protocol_files() -> list[Path]:
    """Union `PROTOCOLS_DIR` with the per-machine local config root's protocols/.

    `PROTOCOLS_DIR` (not `DefaultPaths.DIR_PROTOCOL` directly) so this keeps
    honoring `AUTOPIPETTE_PROTOCOLS_DIR`, which `LocalConfigRoots` doesn't
    know about. Local wins on a filename collision, matching every other
    config category's shared/local union (see `config/README.md`).

    Returns:
        Sorted list of resolved `.pipette` paths.
    """
    found: dict[str, Path] = {}
    if PROTOCOLS_DIR.exists():
        for path in sorted(PROTOCOLS_DIR.glob("*.pipette")):
            found[path.name] = path
    if DefaultPaths.DIR_LOCAL_PROTOCOL.exists():
        for path in sorted(DefaultPaths.DIR_LOCAL_PROTOCOL.glob("*.pipette")):
            found[path.name] = path
    return sorted(found.values())


@app.get("/protocols", response_model=list[Protocol])
def list_protocols() -> list[Protocol]:
    """Return all .pipette files, sorted by name (see `_list_protocol_files`).

    Raises:
        HTTPException: 500 if neither the shared nor the local protocols
            directory exists.
    """
    if not PROTOCOLS_DIR.exists() and not DefaultPaths.DIR_LOCAL_PROTOCOL.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                f"Protocols directory not found: {PROTOCOLS_DIR} or "
                f"{DefaultPaths.DIR_LOCAL_PROTOCOL}"
            ),
        )

    return [Protocol(name=f.stem, filename=f.name) for f in _list_protocol_files()]


@app.post("/run", response_model=RunStatus)
async def run_protocol(req: RunRequest) -> RunStatus:
    """Kick off a protocol run via the tapd control daemon's `run.start`.

    Completion is reported later through `notify_run_status` pushes (see
    `_on_run_status_notification`), driven by the daemon's real Moonraker
    `print_stats` tracking rather than this call returning.

    Returns:
        The just-dispatched run's initial status (not its completion).

    Raises:
        HTTPException: 404 if `req.filename` doesn't exist, 409 if a run is
            already active, 503 if the control daemon isn't connected, or
            500 for any other dispatch failure.
    """
    global _current_run

    # Fails fast without round-tripping to the daemon only when the file is
    # missing from *both* roots the kiosk itself can see -- a file that
    # exists only in the local root still passes this and reaches the
    # daemon, which resolves the same shared/local union for real.
    known_names = {path.name for path in _list_protocol_files()}
    if req.filename not in known_names:
        raise HTTPException(
            status_code=404, detail=f"Protocol not found: {req.filename}"
        )

    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    try:
        response = await asyncio.to_thread(
            _control_client.send_jsonrpc, _control_requests.run_start(req.filename)
        )
    except JsonRpcError as exc:
        if exc.error_type == "RunAlreadyActiveError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if exc.error_type == "FileNotFoundError":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result: dict[str, Any] = response.get("result", {})
    _current_run = RunStatus(
        status=result.get("status", "running"),
        message=result.get("message", ""),
    )
    return _current_run


@app.post("/home", response_model=RunStatus)
async def home_pipette() -> RunStatus:
    """Home the pipette (`init`) via the tapd control daemon.

    Unlike `/run`, this dispatches the structured `movement.init` method
    directly rather than tracking a run: `init` itself is fire-and-forget
    (it uploads G-code and requests print-start, same as any other
    command), so this reports whether dispatch succeeded, not physical
    completion. Once Klipper actually finishes homing, the daemon's live
    `toolhead.homed_axes` tracking (see `daemon/moonraker_state.py`)
    unblocks gated commands automatically — no separate "homing done"
    signal is needed here.

    Returns:
        A status reporting dispatch success, not physical homing completion.

    Raises:
        HTTPException: 503 if the control daemon isn't connected, or 500 if
            dispatch itself fails.
    """
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    try:
        response = await asyncio.to_thread(
            _control_client.send_jsonrpc, _control_requests.init()
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result: dict[str, Any] = response.get("result", {})
    message = str(result.get("message", "")) or "Homing dispatched"
    return RunStatus(status="done", message=message)


@app.post("/breakpoint/respond")
async def respond_to_breakpoint(req: BreakpointResponse) -> dict[str, bool]:
    """Answer a pending protocol breakpoint (Continue/Abort).

    Only one run (and therefore one pending breakpoint) can be active at a
    time, so no run/breakpoint id is needed to disambiguate.

    Returns:
        ``{"ok": True}`` once the response has been relayed to the daemon.

    Raises:
        HTTPException: 503 if the control daemon isn't connected.
    """
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    await asyncio.to_thread(
        _control_client.send_jsonrpc,
        _control_requests.run_confirm_breakpoint(req.proceed),
    )
    return {"ok": True}


async def _dispatch_tips_request(request: dict[str, Any]) -> TipsResult:
    """Send a `config.tips*` control-plane request and forward its result.

    Shared by the three `/tips*` routes below -- each just builds the
    request and lets this translate the daemon's `CommandResult` shape
    (`ok`/`message`/`data`) into a `TipsResult`, or the connection state
    into an `HTTPException`.

    Args:
        request: A `ControlRequests.tips`/`reset_tips`/`set_tips` result.

    Returns:
        The forwarded `CommandResult`, as a `TipsResult`.

    Raises:
        HTTPException: 503 if the control daemon isn't connected, or 500 if
            dispatch itself fails.
    """
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    try:
        response = await asyncio.to_thread(_control_client.send_jsonrpc, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result: dict[str, Any] = response.get("result", {})
    return TipsResult(
        ok=bool(result.get("ok")),
        message=str(result.get("message", "")),
        data=result.get("data"),
    )


@app.get("/tips", response_model=TipsResult)
async def list_tips() -> TipsResult:
    """Report tip availability for every registered tipbox.

    Routing only, per issue #17's constraint -- `TipBoxManager.describe`
    (via `AutoPipetteService.tips`) is the data source; this adds no tip
    logic of its own. `data["boxes"]` carries each box's `num_row`/
    `num_col`, `present` (one flag per flat well index), `eligible` (flat
    indices actually usable -- a box may have masked-out positions), and
    `next_well`.

    Returns:
        `TipsResult` with `data["boxes"]`/`data["total_remaining"]`/
        `data["total_capacity"]`.
    """
    return await _dispatch_tips_request(_control_requests.tips(TipsArgs()))


@app.post("/tips/reset", response_model=TipsResult)
async def reset_tips(req: TipsResetRequest) -> TipsResult:
    """Mark one tipbox as full, after it's been physically reloaded.

    Returns:
        `TipsResult` naming the box's new tip count, or `ok=False` if no
        tipbox by that name is registered.
    """
    return await _dispatch_tips_request(
        _control_requests.reset_tips(ResetTipsArgs(name=req.name))
    )


@app.post("/tips/set", response_model=TipsResult)
async def set_tips(req: TipsSetRequest) -> TipsResult:
    """Declare exactly which positions of a tipbox hold tips.

    Replaces the named box's state rather than adding to it -- the
    frontend always sends the box's complete new consumed (or available)
    set (see `TipsSetRequest`), never a single toggled cell.

    Returns:
        `TipsResult` naming the box's new tip count, or `ok=False` if the
        box is unknown or a range is invalid.
    """
    return await _dispatch_tips_request(
        _control_requests.set_tips(
            SetTipsArgs(name=req.name, ranges=req.ranges, available=req.available)
        )
    )


@app.get("/status", response_model=RunStatus)
def get_status() -> RunStatus:
    """Return the current (or most recent) protocol run status."""
    return _current_run


@app.websocket("/ws/status")
async def status_ws(websocket: WebSocket) -> None:
    """Push status updates to the frontend as the daemon reports them."""
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        await websocket.send_json(_status_payload())
        while True:
            # No messages are expected from the browser; this just blocks
            # until the client disconnects, since updates are pushed via
            # _broadcast_status instead of polled here.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ── internal ───────────────────────────────────────────────────────────────────
def _on_run_status_notification(params: Any) -> None:  # ruff:ignore[any-type]
    """Handle a `notify_run_status` push from the tapd control daemon.

    Args:
        params: Notification params, `{"status", "message", "run_id",
            "filename"}` as sent by `AutoPipetteService._broadcast_status`.

    Note:
        Invoked from the control-plane WebSocketClient's background thread;
        marshals the browser-facing broadcast back onto the main event loop.
    """
    global _current_run, _current_breakpoint
    if not isinstance(params, dict):
        return
    notification = as_dict(params)
    _current_run = RunStatus(
        status=notification.get("status", "idle"),
        message=notification.get("message", ""),
    )
    if _current_run.status != "running":
        # A run that's no longer active can't have a pending breakpoint;
        # clear any stale one (e.g. an aborted run) rather than waiting for
        # the matching notify_breakpoint(pending=False).
        _current_breakpoint = None
    if _main_loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast_status(), _main_loop)


def _on_breakpoint_notification(params: Any) -> None:  # ruff:ignore[any-type]
    """Handle a `notify_breakpoint` push from the tapd control daemon.

    Args:
        params: Notification params, `{"run_id", "filename", "pending"}` as
            sent by `AutoPipetteService.request_breakpoint`/
            `confirm_breakpoint`.

    Note:
        Invoked from the control-plane WebSocketClient's background thread;
        marshals the browser-facing broadcast back onto the main event loop.
    """
    global _current_breakpoint
    if not isinstance(params, dict):
        return
    notification = as_dict(params)
    _current_breakpoint = notification if notification.get("pending") else None
    if _main_loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast_status(), _main_loop)


def _status_payload() -> dict[str, Any]:
    """Build the JSON payload pushed over `/ws/status`.

    Returns:
        The current `RunStatus` fields plus a `breakpoint` key: the pending
        breakpoint's `{"run_id", "filename", "pending"}` dict, or None.
    """
    return {**_current_run.model_dump(), "breakpoint": _current_breakpoint}


async def _broadcast_status() -> None:
    """Push the current run/breakpoint status to every connected browser."""
    payload = _status_payload()
    stale: list[WebSocket] = []
    # Snapshot: status_ws's finally-block can discard from _ws_clients
    # concurrently (e.g. a browser disconnecting mid-broadcast), which would
    # otherwise raise "Set changed size during iteration" here.
    for ws in list(_ws_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _ws_clients.discard(ws)

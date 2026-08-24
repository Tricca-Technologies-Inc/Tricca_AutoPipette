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
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tricca_autopipette.commands.tap_cmd_parsers import (
    MoveArgs,
    MoveLocArgs,
    MoveRelArgs,
    ResetTipsArgs,
    SetTipsArgs,
    TipsArgs,
)
from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.control_requests import ControlRequests
from tricca_autopipette.moonraker.websocket_client import WebSocketClient

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


class LocationsResult(BaseModel):
    """Response envelope for `GET /locations`.

    Mirrors `TipsResult`'s `CommandResult`-shaped `ok`/`message`/`data`
    forwarding -- `config.list_locations` (like `config.tips`) is a pure
    reporting getter that never raises, only reports `ok=False` for an
    empty deck.
    """

    ok: bool
    message: str = ""
    data: dict[str, Any] | None = None


class MoveRequest(BaseModel):
    """Request body for `POST /move` (absolute XYZ, mirrors `MoveArgs`)."""

    x: float
    y: float
    z: float


class MoveLocRequest(BaseModel):
    """Request body for `POST /move_loc` (mirrors `MoveLocArgs`)."""

    name_loc: str
    row: int | None = None
    col: int | None = None


class MoveRelRequest(BaseModel):
    """Request body for `POST /move_rel` (mirrors `MoveRelArgs`)."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class MoveResult(BaseModel):
    """Response body for `POST /move`, `/move_loc`, `/move_rel`.

    A move that fails outright (not homed, unknown location, ...) is a
    raised daemon exception translated to an HTTP error status (see
    `_translate_move_error`), not a field on this model -- so a 200 here
    always means the daemon accepted and ran the move (or, for
    `move_rel`'s all-zero-offset case, a soft no-op it reported instead of
    raising; `message` says which).
    """

    message: str


# ── daemon control-plane connection ────────────────────────────────────────────
_control_client: WebSocketClient | None = None
_control_requests = ControlRequests()
_main_loop: asyncio.AbstractEventLoop | None = None

# ── in-memory run state, mirrored from the daemon's notify_run_status pushes ──
_current_run: RunStatus = RunStatus(status="idle")
# Pending breakpoint, mirrored from notify_breakpoint pushes: {"run_id",
# "filename", "pending"} while one is awaiting a response, None otherwise.
_current_breakpoint: dict[str, Any] | None = None
# Live toolhead state (Move page, issue #86), mirrored from notify_raw_event
# pushes carrying a raw Moonraker "notify_status_update" for the "toolhead"
# object -- see `_on_raw_event_notification`. Klipper only sends the fields
# that actually changed in each push, so these are updated field-by-field,
# never wholesale replaced, and start unset until the first real push
# arrives (there's no synchronous initial value here, unlike the daemon's
# own `MoonrakerStateTracker.start()`).
_current_toolhead: dict[str, Any] = {"position": None, "homed_axes": None}
_ws_clients: set[WebSocket] = set()

_ERROR_TYPE_RE = re.compile(r"'type':\s*'([^']+)'")


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
    client.register_handler("notify_raw_event", _on_raw_event_notification)
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
        # Ask the daemon to relay live toolhead (position/homed_axes)
        # updates as notify_raw_event pushes, for the Move page (issue
        # #86). Opt-in and kiosk-only -- ws.subscribe re-broadcasts to
        # *every* connected control-plane client, so subscribing
        # unconditionally would also spam a `tap` session with raw
        # per-move notifications it has no use for. Non-fatal on failure
        # (e.g. `tapd --no-connect`, or the daemon's own Moonraker
        # connection being down), same as `identify` above.
        try:
            await asyncio.to_thread(
                client.send_jsonrpc,
                _control_requests.ws_subscribe("notify_status_update"),
            )
        except RuntimeError:
            logger.warning("Failed to subscribe to live toolhead updates.")
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
    except RuntimeError as exc:
        error_type = _extract_error_type(exc)
        if error_type == "RunAlreadyActiveError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if error_type == "FileNotFoundError":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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


def _translate_move_error(exc: RuntimeError) -> HTTPException:
    """Map a `movement.*` control-plane error to an HTTP status.

    Unlike `/tips*`'s ok/false-forwarding, `movement.move`/`move_loc`/
    `move_rel` report failure by raising (`NotHomedError`,
    `NotALocationError`, `ValueError`), the same shape `/run` already
    translates -- see that route's own docstring for the general pattern.

    Args:
        exc: The RuntimeError raised by `send_jsonrpc`.

    Returns:
        An `HTTPException` with a status matching the daemon's error type:
        409 for `NotHomedError` (a precondition the operator can clear by
        homing, not a client mistake), 404 for `NotALocationError`, 400 for
        a bad `ValueError` (e.g. only one of row/col given), 500 otherwise.
    """
    error_type = _extract_error_type(exc)
    if error_type == "NotHomedError":
        return HTTPException(status_code=409, detail=str(exc))
    if error_type == "NotALocationError":
        return HTTPException(status_code=404, detail=str(exc))
    if error_type == "ValueError":
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@app.post("/move", response_model=MoveResult)
async def move(req: MoveRequest) -> MoveResult:
    """Move to absolute XYZ coordinates via the tapd control daemon.

    Returns:
        The completed move's message.

    Raises:
        HTTPException: 503 if the control daemon isn't connected, 409 if
            not homed, or 500 for any other dispatch failure.
    """  # ruff: ignore[docstring-missing-exception]
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    try:
        response = await asyncio.to_thread(
            _control_client.send_jsonrpc,
            _control_requests.move(MoveArgs(x=req.x, y=req.y, z=req.z)),
        )
    except RuntimeError as exc:
        raise _translate_move_error(exc) from exc

    result: dict[str, Any] = response.get("result", {})
    return MoveResult(message=str(result.get("message", "")))


@app.post("/move_loc", response_model=MoveResult)
async def move_loc(req: MoveLocRequest) -> MoveResult:
    """Move to a named location via the tapd control daemon.

    Returns:
        The completed move's message.

    Raises:
        HTTPException: 503 if the control daemon isn't connected, 409 if
            not homed, 404 if `req.name_loc` is not a defined location, 400
            if only one of `req.row`/`req.col` is given for a plate
            location, or 500 for any other dispatch failure.
    """  # ruff: ignore[docstring-missing-exception]
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    try:
        response = await asyncio.to_thread(
            _control_client.send_jsonrpc,
            _control_requests.move_loc(
                MoveLocArgs(name_loc=req.name_loc, row=req.row, col=req.col)
            ),
        )
    except RuntimeError as exc:
        raise _translate_move_error(exc) from exc

    result: dict[str, Any] = response.get("result", {})
    return MoveResult(message=str(result.get("message", "")))


@app.post("/move_rel", response_model=MoveResult)
async def move_rel(req: MoveRelRequest) -> MoveResult:
    """Move relative to the current position via the tapd control daemon.

    An all-zero offset is a soft no-op the daemon reports as
    `CommandResult(ok=False, ...)` rather than raising, so unlike the other
    error cases below it's still a 200 here -- `message` explains why
    nothing moved.

    Returns:
        The completed (or no-op) move's message.

    Raises:
        HTTPException: 503 if the control daemon isn't connected, 409 if
            not homed, or 500 for any other dispatch failure.
    """  # ruff: ignore[docstring-missing-exception]
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    try:
        response = await asyncio.to_thread(
            _control_client.send_jsonrpc,
            _control_requests.move_rel(MoveRelArgs(x=req.x, y=req.y, z=req.z)),
        )
    except RuntimeError as exc:
        raise _translate_move_error(exc) from exc

    result: dict[str, Any] = response.get("result", {})
    return MoveResult(message=str(result.get("message", "")))


@app.get("/locations", response_model=LocationsResult)
async def list_locations() -> LocationsResult:
    """List all defined locations (coordinates and plates).

    Populates the Move page's named-location dropdown (issue #86).
    Routing only, per the client parity rule -- `config.list_locations`
    (via `AutoPipetteService.list_locations`) is the data source; this adds
    no location logic of its own. Each entry in `data["locations"]` carries
    `name`/`type`/`x`/`y`/`z`/`details`; `type` is `"Coordinate"` for a
    plain named point, or a `Plate` subclass name (e.g. `"PlateArray"`) for
    a plate -- the frontend uses that to decide whether to show row/col
    inputs.

    Returns:
        `LocationsResult` with `data["locations"]`, or `ok=False` if no
        locations are defined.

    Raises:
        HTTPException: 503 if the control daemon isn't connected, or 500 if
            dispatch itself fails.
    """
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    try:
        response = await asyncio.to_thread(
            _control_client.send_jsonrpc, _control_requests.list_locations()
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result: dict[str, Any] = response.get("result", {})
    return LocationsResult(
        ok=bool(result.get("ok")),
        message=str(result.get("message", "")),
        data=result.get("data"),
    )


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
def _extract_error_type(exc: RuntimeError) -> str | None:
    """Recover the daemon's error type name from a control-plane RuntimeError.

    `WebSocketClient.send_jsonrpc` raises `RuntimeError(f"Server error:
    {data['error']}")` on any control-plane error response, folding the
    structured `{"type": ..., "message": ...}` error payload into a string.
    This picks the type name back out so callers can map it to an HTTP
    status code without matching on message text.

    Args:
        exc: The RuntimeError raised by `send_jsonrpc`.

    Returns:
        The error's type name (e.g. "RunAlreadyActiveError"), or None if it
        could not be recovered.
    """
    match = _ERROR_TYPE_RE.search(str(exc))
    return match.group(1) if match else None


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
    notification = cast("dict[str, Any]", params)
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
    notification = cast("dict[str, Any]", params)
    _current_breakpoint = notification if notification.get("pending") else None
    if _main_loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast_status(), _main_loop)


def _first_status_dict(raw_params: Any) -> dict[str, Any] | None:  # ruff:ignore[any-type]
    """Extract the status dict from a Moonraker `notify_status_update`'s params.

    Moonraker's own notification carries `[status_dict, eventtime]`;
    defensively also accepts a bare status dict.

    Args:
        raw_params: The raw notification params of unknown shape.

    Returns:
        The status dict, or None if `raw_params` didn't carry one.
    """
    candidate: Any = raw_params
    if isinstance(raw_params, list):
        items = cast("list[Any]", raw_params)
        candidate = items[0] if items else None
    if isinstance(candidate, dict):
        return cast("dict[str, Any]", candidate)
    return None


def _on_raw_event_notification(params: Any) -> None:  # ruff:ignore[any-type]
    """Handle a `notify_raw_event` push from the tapd control daemon.

    Only acts on a relayed raw Moonraker `"notify_status_update"` naming
    the `"toolhead"` object (Move page, issue #86) -- the kiosk's own
    `ws.subscribe("notify_status_update")` call in `lifespan` is what makes
    this arrive at all; anything else relayed under a different method name
    is ignored.

    Args:
        params: `{"method": <relayed Moonraker method>, "params": <that
            method's own raw notification params>}`, as sent by
            `AutoPipetteService._forward_raw_notification`. For
            `"notify_status_update"`, `params["params"]` is Moonraker's own
            `[status_dict, eventtime]` shape (or, defensively, a bare
            status dict).

    Note:
        Invoked from the control-plane WebSocketClient's background thread;
        marshals the browser-facing broadcast back onto the main event loop.
    """
    if not isinstance(params, dict):
        return
    envelope = cast("dict[str, Any]", params)
    if envelope.get("method") != "notify_status_update":
        return
    status = _first_status_dict(envelope.get("params"))
    if status is None:
        return
    toolhead = status.get("toolhead")
    if not isinstance(toolhead, dict):
        return
    updated = _apply_toolhead_update(cast("dict[str, Any]", toolhead))
    if updated and _main_loop is not None:
        asyncio.run_coroutine_threadsafe(_broadcast_status(), _main_loop)


def _apply_toolhead_update(toolhead: dict[str, Any]) -> bool:
    """Merge a partial toolhead status update into `_current_toolhead`.

    Klipper only includes the fields that actually changed in each
    `notify_status_update` push (`position` changes on every move,
    `homed_axes` only at homing time), so this updates known fields
    in place rather than replacing the cached dict wholesale -- otherwise
    a position-only push would clobber a previously-known `homed_axes`
    back to unset.

    Args:
        toolhead: The `"toolhead"` sub-dict from one status update.

    Returns:
        True if anything was actually updated (worth broadcasting), False
        if `toolhead` carried neither field.
    """
    changed = False
    if "position" in toolhead:
        _current_toolhead["position"] = toolhead["position"]
        changed = True
    homed_axes = toolhead.get("homed_axes")
    if isinstance(homed_axes, str):
        _current_toolhead["homed_axes"] = homed_axes
        changed = True
    elif isinstance(homed_axes, list):
        _current_toolhead["homed_axes"] = "".join(
            str(axis) for axis in cast("list[Any]", homed_axes)
        )
        changed = True
    return changed


def _status_payload() -> dict[str, Any]:
    """Build the JSON payload pushed over `/ws/status`.

    Returns:
        The current `RunStatus` fields plus `breakpoint` (the pending
        breakpoint's `{"run_id", "filename", "pending"}` dict, or None) and
        `toolhead` (`{"position", "homed_axes"}`, either possibly still
        None if no live update has arrived yet -- see
        `_on_raw_event_notification`).
    """
    return {
        **_current_run.model_dump(),
        "breakpoint": _current_breakpoint,
        "toolhead": dict(_current_toolhead),
    }


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

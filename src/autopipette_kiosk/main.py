"""AutoPipette Kiosk — FastAPI backend.

Serves the protocol list from the protocols/ directory and dispatches runs
by talking to the `tapd` control daemon's control-plane WebSocket (see
`tricca_autopipette.daemon`) instead of spawning a fresh CLI subprocess per
run. One `WebSocketClient` connection is held for the app's lifetime;
`notify_run_status` pushes from the daemon (driven by real Moonraker
`print_stats` transitions) are re-broadcast to connected browser clients.

Run with:
    uvicorn autopipette_kiosk.main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import os
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tricca_autopipette.daemon.control_requests import ControlRequests
from tricca_autopipette.moonraker.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)

# ── paths ──────────────────────────────────────────────────────────────────────
# main.py -> autopipette_kiosk -> src -> repo root.
REPO_ROOT = Path(__file__).parents[2]
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

    status: str  # "idle" | "running" | "done" | "error"
    message: str = ""


class BreakpointResponse(BaseModel):
    """Request body for `POST /breakpoint/respond`."""

    proceed: bool


# ── daemon control-plane connection ────────────────────────────────────────────
_control_client: WebSocketClient | None = None
_control_requests = ControlRequests()
_main_loop: asyncio.AbstractEventLoop | None = None

# ── in-memory run state, mirrored from the daemon's notify_run_status pushes ──
_current_run: RunStatus = RunStatus(status="idle")
# Pending breakpoint, mirrored from notify_breakpoint pushes: {"run_id",
# "filename"} while one is awaiting a response, None otherwise.
_current_breakpoint: dict[str, Any] | None = None
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
    client.start()
    connected = await asyncio.to_thread(
        client.wait_for_connection, TAPD_CONNECT_TIMEOUT_SECONDS
    )
    if not connected:
        logger.error("Failed to connect to tapd control plane at %s", TAPD_CONTROL_URI)
    _control_client = client

    yield

    _control_client = None
    await asyncio.to_thread(client.stop)


app = FastAPI(title="AutoPipette Kiosk", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def index() -> FileResponse:
    """Serve the kiosk's single-page frontend."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/protocols", response_model=list[Protocol])
def list_protocols() -> list[Protocol]:
    """Return all .pipette files in the protocols directory, sorted by name."""
    if not PROTOCOLS_DIR.exists():
        raise HTTPException(
            status_code=500, detail=f"Protocols directory not found: {PROTOCOLS_DIR}"
        )

    files = sorted(PROTOCOLS_DIR.glob("*.pipette"))
    return [Protocol(name=f.stem, filename=f.name) for f in files]


@app.post("/run", response_model=RunStatus)
async def run_protocol(req: RunRequest) -> RunStatus:
    """Kick off a protocol run via the tapd control daemon's `run.start`.

    Completion is reported later through `notify_run_status` pushes (see
    `_on_run_status_notification`), driven by the daemon's real Moonraker
    `print_stats` tracking rather than this call returning.
    """
    global _current_run

    protocol_path = PROTOCOLS_DIR / req.filename
    if not protocol_path.exists():
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

    Unlike `/run`, this dispatches a single shell command directly
    (`shell.exec "init"`) rather than tracking a run: `init` itself is
    fire-and-forget (it uploads G-code and requests print-start, same as
    any other command), so this reports whether dispatch succeeded, not
    physical completion. Once Klipper actually finishes homing, the
    daemon's live `toolhead.homed_axes` tracking (see
    `daemon/moonraker_state.py`) unblocks gated commands automatically —
    no separate "homing done" signal is needed here.
    """
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    response = await asyncio.to_thread(
        _control_client.send_jsonrpc, _control_requests.shell_exec("init")
    )
    result: dict[str, Any] = response.get("result", {})
    output = str(result.get("output", "")).strip()
    error = result.get("error")
    if error:
        raise HTTPException(status_code=500, detail=str(error))
    return RunStatus(status="done", message=output or "Homing dispatched")


@app.post("/breakpoint/respond")
async def respond_to_breakpoint(req: BreakpointResponse) -> dict[str, bool]:
    """Answer a pending protocol breakpoint (Continue/Abort).

    Only one run (and therefore one pending breakpoint) can be active at a
    time, so no run/breakpoint id is needed to disambiguate.
    """
    if _control_client is None:
        raise HTTPException(status_code=503, detail="Control daemon not connected")

    await asyncio.to_thread(
        _control_client.send_jsonrpc,
        _control_requests.run_confirm_breakpoint(req.proceed),
    )
    return {"ok": True}


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


def _on_run_status_notification(params: Any) -> None:  # noqa: ANN401
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


def _on_breakpoint_notification(params: Any) -> None:  # noqa: ANN401
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


def _status_payload() -> dict[str, Any]:
    """Build the JSON payload pushed over `/ws/status`.

    Returns:
        The current `RunStatus` fields plus a `breakpoint` key: the pending
        breakpoint's `{"run_id", "filename"}` dict, or None.
    """
    return {**_current_run.model_dump(), "breakpoint": _current_breakpoint}


async def _broadcast_status() -> None:
    """Push the current run/breakpoint status to every connected browser."""
    payload = _status_payload()
    stale: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _ws_clients.discard(ws)

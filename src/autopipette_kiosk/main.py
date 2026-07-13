"""
AutoPipette Kiosk — FastAPI backend

Serves the protocol list from the protocols/ directory and dispatches
runs by invoking the existing AutoPipette machinery.

Run with:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── paths ──────────────────────────────────────────────────────────────────────
# Adjust REPO_ROOT to wherever the project lives on the Pi.
REPO_ROOT = Path(__file__).parent.parent  # e.g. ~/Documents/Tricca_AutoPipette
PROTOCOLS_DIR = REPO_ROOT / "protocols"
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AutoPipette Kiosk")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── models ─────────────────────────────────────────────────────────────────────
class Protocol(BaseModel):
    name: str       # display name, e.g. "A1"
    filename: str   # bare filename, e.g. "A1.pipette"


class RunRequest(BaseModel):
    filename: str   # e.g. "A1.pipette"


class RunStatus(BaseModel):
    status: str     # "running" | "done" | "error"
    message: str = ""


# ── in-memory run state ────────────────────────────────────────────────────────
_current_run: RunStatus | None = None
_run_lock = asyncio.Lock()


# ── routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/protocols", response_model=list[Protocol])
def list_protocols():
    """Return all .pipette files in the protocols directory, sorted by name."""
    if not PROTOCOLS_DIR.exists():
        raise HTTPException(status_code=500, detail=f"Protocols directory not found: {PROTOCOLS_DIR}")

    files = sorted(PROTOCOLS_DIR.glob("*.pipette"))
    return [
        Protocol(name=f.stem, filename=f.name)
        for f in files
    ]


@app.post("/run", response_model=RunStatus)
async def run_protocol(req: RunRequest):
    """
    Kick off a protocol run.

    Currently shells out to tricca_autopipette.py with the protocol path.
    Swap the subprocess call for a direct Python call once you've confirmed
    the integration path with your existing AutoPipette machinery.
    """
    global _current_run

    protocol_path = PROTOCOLS_DIR / req.filename
    if not protocol_path.exists():
        raise HTTPException(status_code=404, detail=f"Protocol not found: {req.filename}")

    # Prevent concurrent runs
    if _current_run and _current_run.status == "running":
        raise HTTPException(status_code=409, detail="A protocol is already running")

    async with _run_lock:
        _current_run = RunStatus(status="running", message=f"Running {req.filename}")

    asyncio.create_task(_execute_protocol(protocol_path))
    return _current_run


@app.get("/status", response_model=RunStatus)
def get_status():
    if _current_run is None:
        return RunStatus(status="idle")
    return _current_run


@app.websocket("/ws/status")
async def status_ws(websocket: WebSocket):
    """Push status updates to the frontend every 500ms."""
    await websocket.accept()
    try:
        while True:
            status = _current_run or RunStatus(status="idle")
            await websocket.send_json(status.model_dump())
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass


# ── internal ───────────────────────────────────────────────────────────────────
async def _execute_protocol(protocol_path: Path):
    """
    Run a protocol file. Currently uses subprocess; replace with a direct call
    to your AutoPipette/ProtocolCommands class once you've wired it in.

    Example direct call (uncomment and adapt):
        from Tricca_AutoPipette.autopipette import AutoPipette
        ap = AutoPipette()
        ap.run_protocol(str(protocol_path))
    """
    global _current_run
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3",
            str(REPO_ROOT / "Tricca_AutoPipette" / "tricca_autopipette.py"),
            "--protocol", str(protocol_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(REPO_ROOT),
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            _current_run = RunStatus(status="done", message="Protocol completed successfully")
        else:
            err = stderr.decode().strip().splitlines()[-1] if stderr else "Unknown error"
            _current_run = RunStatus(status="error", message=err)

    except Exception as e:
        logger.exception("Protocol execution failed")
        _current_run = RunStatus(status="error", message=str(e))

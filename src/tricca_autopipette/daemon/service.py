"""Core orchestration object for the ``tapd`` daemon.

``AutoPipetteService`` owns the one long-lived ``HeadlessTapShell`` (and,
through it, the single Moonraker connection) and exposes an async API that
``ControlServer`` dispatches control-plane JSON-RPC requests to. It also
owns the "current run" bookkeeping that replaces the kiosk's old
subprocess-exit-code heuristic with real Moonraker ``print_stats``
transitions (see ``daemon/moonraker_state.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import shlex
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cmd2.py_bridge import PyBridge

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.headless_shell import HeadlessTapShell
from tricca_autopipette.daemon.moonraker_state import MoonrakerStateTracker

logger = logging.getLogger(__name__)

WEBSOCKET_TIMEOUT_SECONDS = 10


class RunAlreadyActiveError(Exception):
    """Raised when a run is requested while another run is in progress."""


@dataclass
class RunStatus:
    """Status of the daemon's current (or most recent) protocol run.

    Attributes:
        status: One of "idle", "running", "done", "error".
        message: Human-readable status detail.
        run_id: Unique identifier for the run, or None if idle.
        filename: Protocol filename for the run, or None if idle.
    """

    status: str
    message: str = ""
    run_id: str | None = None
    filename: str | None = None


class AutoPipetteService:
    """Owns the shared shell/Moonraker connection and run lifecycle.

    Attributes:
        shell: The single ``HeadlessTapShell`` instance all clients act
            through.
    """

    def __init__(
        self,
        config_system: Path,
        config_gantry: Path | None,
        config_pipette: Path | None,
        config_locations: Path | None,
        config_liquids: Path | None,
        connect_websocket: bool = True,
        connect_local_websocket: bool = False,
    ) -> None:
        """Build the shell and Moonraker state tracker.

        Args:
            config_system: Path to master configuration file.
            config_gantry: Path to gantry configuration file (optional).
            config_pipette: Path to pipette model configuration file
                (optional).
            config_locations: Path to named locations configuration file
                (optional).
            config_liquids: Path to liquids configuration file (optional).
            connect_websocket: Whether to connect to Moonraker on startup.
            connect_local_websocket: Whether to connect to a local Moonraker
                for testing.
        """
        self.shell = HeadlessTapShell(
            config_system=config_system,
            config_gantry=config_gantry,
            config_pipette=config_pipette,
            config_locations=config_locations,
            config_liquids=config_liquids,
            connect_websocket=connect_websocket,
            connect_local_websocket=connect_local_websocket,
        )
        self.moonraker_state: MoonrakerStateTracker | None = None
        if self.shell.client is not None:
            self.moonraker_state = MoonrakerStateTracker(
                self.shell.client, self.shell.mrr
            )
            self.shell.moonraker_state = self.moonraker_state
        self.shell.breakpoint_handler = self.request_breakpoint

        self._lock = asyncio.Lock()
        self._current = RunStatus(status="idle")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._broadcast_callback: Callable[[str, dict[str, Any]], None] | None = None
        self._breakpoint_event: threading.Event | None = None
        self._breakpoint_proceed = False
        self._background_tasks: set[asyncio.Task[None]] = set()

    def set_broadcast_callback(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Register the callback used to push notifications to clients.

        Args:
            callback: Called with ``(method, params)`` whenever the daemon
                needs to push an unsolicited notification (e.g.
                ``notify_run_status``). Scheduled onto the service's event
                loop, so it may itself be a coroutine-scheduling function.
        """
        self._broadcast_callback = callback

    async def start(self) -> None:
        """Connect to Moonraker, subscribe to state, replay the init script."""
        self._loop = asyncio.get_running_loop()

        if self.shell.client is not None:
            self.shell.client.start()
            connected = await asyncio.to_thread(
                self.shell.client.wait_for_connection, WEBSOCKET_TIMEOUT_SECONDS
            )
            if not connected:
                logger.error(
                    "Failed to connect to Moonraker at startup; "
                    "WebSocketClient will keep retrying in the background"
                )

        if self.moonraker_state is not None:
            await asyncio.to_thread(self.moonraker_state.start)
            self.moonraker_state.on_print_state_change(self._handle_print_state_change)
            persisted = await asyncio.to_thread(
                self.moonraker_state.load_tip_liquid_state
            )
            self.shell.apply_persisted_state(persisted)

        await asyncio.to_thread(self._run_startup_script)

    async def stop(self) -> None:
        """Disconnect from Moonraker and release resources."""
        if self.shell.client is not None:
            await asyncio.to_thread(self.shell.client.stop)

    def _run_startup_script(self) -> None:
        """Replay ``core/.init_pipette`` once, mirroring interactive startup.

        The interactive shell runs this via cmd2's ``startup_script``
        mechanism, which only fires from within ``cmdloop()``. Since the
        daemon never calls ``cmdloop()``, it replays the same file directly.
        """
        startup_path = DefaultPaths.DIR_SHELL / ".init_pipette"
        if not startup_path.exists():
            return
        lines = [
            line
            for line in startup_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if lines:
            self.shell.runcmds_plus_hooks(lines, add_to_history=False)

    # ==================== Command execution ====================

    async def execute_line(self, line: str) -> dict[str, str | None]:
        """Run one shell command line, capturing its rich/cmd2 output.

        Args:
            line: Raw shell command line, exactly as a user would type it.

        Returns:
            Dict with ``output`` (captured stdout text) and ``error`` (an
            error message string, or None on success).
        """
        async with self._lock:
            return await asyncio.to_thread(self._execute_line_sync, line)

    def _execute_line_sync(self, line: str) -> dict[str, str | None]:
        """Synchronous half of :meth:`execute_line`, run in a worker thread.

        Combines two capture mechanisms, since cmd2 commands write through
        two different channels: `contextlib.redirect_stdout` catches rich's
        ``rprint`` calls (rich resolves ``sys.stdout`` dynamically on every
        call), while cmd2's own `PyBridge` — its official "run a command
        and capture its output" API, normally used by ``do_py``/scripting —
        catches everything routed through ``self.shell.stdout`` instead:
        argparse usage/error text and ``self.poutput``/``self.perror``
        calls, none of which respond to ``redirect_stdout`` because
        ``self.shell.stdout`` is a reference cmd2 captures once at shell
        construction, not looked up fresh per call. Without both, half of
        a command's output silently leaks to the daemon's own real stdout
        instead of being returned to the caller.

        Args:
            line: Raw shell command line.

        Returns:
            Dict with ``output`` and ``error`` keys.
        """
        rich_buffer = io.StringIO()
        bridge = PyBridge(self.shell, add_to_history=False)
        try:
            with contextlib.redirect_stdout(rich_buffer):
                result = bridge(line)
        except Exception as exc:
            return {"output": rich_buffer.getvalue(), "error": str(exc)}
        output = rich_buffer.getvalue() + result.stdout + result.stderr
        return {"output": output, "error": None}

    # ==================== Run lifecycle ====================

    async def start_run(self, filename: str) -> RunStatus:
        """Start executing a protocol file.

        Args:
            filename: Bare filename under ``protocols/`` (e.g. "A1.pipette").

        Returns:
            The run's initial status. This returns as soon as the run is
            *started*, not when it finishes — ``do_run`` can block for an
            arbitrarily long time (e.g. at a ``break``, waiting on a remote
            client), so the actual protocol replay runs as a background
            task rather than being awaited here; completion (or a
            halt/error) is reported later via the broadcast callback as
            ``notify_run_status``.

        Raises:
            RunAlreadyActiveError: If a run is already in progress.
            FileNotFoundError: If the protocol file does not exist.
        """
        async with self._lock:
            if self._current.status == "running":
                raise RunAlreadyActiveError(
                    f"A protocol is already running: {self._current.filename}"
                )

            proto_path = DefaultPaths.DIR_PROTOCOL / filename
            if not proto_path.exists():
                raise FileNotFoundError(f"Protocol not found: {filename}")

            run_id = str(uuid.uuid4())
            self._current = RunStatus(
                status="running",
                message=f"Running {filename}",
                run_id=run_id,
                filename=filename,
            )
            self._broadcast_status()

        task = asyncio.create_task(self._run_protocol(filename, run_id))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return self._current

    async def _run_protocol(self, filename: str, run_id: str) -> None:
        """Replay a protocol file and update run status with the outcome.

        Args:
            filename: Bare filename under ``protocols/``.
            run_id: The run's id, as set by :meth:`start_run`.

        Note:
            Holds ``self._lock`` for the whole replay (potentially a long
            time, if it pauses at a breakpoint) so ``shell.exec`` calls from
            other clients can't interleave G-code generation with this run.
            ``cancel_run``/``pause_run``/``resume_run`` deliberately bypass
            this lock — see their docstrings.
        """
        async with self._lock:
            self.shell.last_blocked_command = None
            # shlex.quote is required since filenames may contain spaces --
            # cmd2's statement parser splits on unquoted whitespace, and
            # parser_run takes a single positional argument.
            result = await asyncio.to_thread(
                self._execute_line_sync, f"run {shlex.quote(filename)}"
            )

            if result["error"] is not None:
                self._current = RunStatus(
                    status="error",
                    message=result["error"],
                    run_id=run_id,
                    filename=filename,
                )
                self._broadcast_status()
            elif self.shell.last_blocked_command:
                # do_run's runcmds_plus_hooks aborts the whole protocol on the
                # first blocked line rather than skipping just that line, so an
                # unhomed run silently produces no G-code and never calls
                # print.start — without this check, print_stats would never
                # transition and the run would hang at "running" forever.
                self._current = RunStatus(
                    status="error",
                    message=(
                        f"Protocol halted: '{self.shell.last_blocked_command}' "
                        "blocked — pipette not homed. Run 'init' or 'home all' first."
                    ),
                    run_id=run_id,
                    filename=filename,
                )
                self._broadcast_status()

    async def cancel_run(self) -> RunStatus:
        """Cancel the active run via ``ProtocolCommands.do_cancel``.

        Deliberately bypasses ``self._lock``: that lock can be held for a
        long time by an in-progress run (including one paused at a
        breakpoint), but ``do_cancel`` only sends a Moonraker control RPC —
        it never touches the G-code buffer or ``AutoPipette`` domain state
        — so it's safe to run concurrently, and it must be able to
        interrupt a run that's stuck.
        """
        await asyncio.to_thread(self._execute_line_sync, "cancel")
        return self._current

    async def pause_run(self) -> RunStatus:
        """Pause the active run via ``ProtocolCommands.do_pause``.

        See :meth:`cancel_run` for why this bypasses ``self._lock``.
        """
        await asyncio.to_thread(self._execute_line_sync, "pause")
        return self._current

    async def resume_run(self) -> RunStatus:
        """Resume the active run via ``ProtocolCommands.do_resume``.

        See :meth:`cancel_run` for why this bypasses ``self._lock``.
        """
        await asyncio.to_thread(self._execute_line_sync, "resume")
        return self._current

    def get_status(self) -> RunStatus:
        """Return the current (or most recent) run status."""
        return self._current

    def list_protocols(self) -> list[dict[str, str]]:
        """List available protocol files.

        Returns:
            List of ``{"name": stem, "filename": name}`` dicts, sorted by
            filename.
        """
        files = sorted(DefaultPaths.DIR_PROTOCOL.glob("*.pipette"))
        return [{"name": f.stem, "filename": f.name} for f in files]

    def request_breakpoint(self) -> bool:
        """Pause for operator confirmation, called synchronously from `do_break`.

        `do_break` runs on the worker thread `execute_line`/`start_run`
        dispatch onto via `asyncio.to_thread`, so blocking here with a plain
        `threading.Event` only blocks that worker thread — the daemon's
        event loop (and thus `confirm_breakpoint`, which resolves the event)
        keeps running normally.

        Returns:
            True to continue the protocol, False to abort it — whatever the
            client passed to `confirm_breakpoint`.
        """
        event = threading.Event()
        self._breakpoint_event = event
        if self._broadcast_callback is not None:
            self._broadcast_callback(
                "notify_breakpoint",
                {
                    "run_id": self._current.run_id,
                    "filename": self._current.filename,
                    "pending": True,
                },
            )
        event.wait()
        return self._breakpoint_proceed

    async def confirm_breakpoint(self, proceed: bool) -> None:
        """Resolve the pending breakpoint raised by `request_breakpoint`.

        Args:
            proceed: True to continue the protocol, False to abort it.
        """
        self._breakpoint_proceed = proceed
        event, self._breakpoint_event = self._breakpoint_event, None
        if event is not None:
            event.set()
        if self._broadcast_callback is not None:
            self._broadcast_callback(
                "notify_breakpoint",
                {
                    "run_id": self._current.run_id,
                    "filename": self._current.filename,
                    "pending": False,
                },
            )

    async def ping(self) -> dict[str, bool]:
        """Health check for control-plane clients.

        Returns:
            Dict indicating whether the daemon's Moonraker connection is up.
        """
        connected = self.shell.client is not None and self.shell.client.is_connected()
        return {"connected_to_moonraker": connected}

    def _handle_print_state_change(self, new_state: str) -> None:
        """Map a Moonraker ``print_stats.state`` transition onto run status.

        Args:
            new_state: New Klipper ``print_stats.state`` value (e.g.
                "printing", "complete", "error", "cancelled", "standby").

        Note:
            Invoked from the WebSocket client's background thread; marshals
            back onto the service's own event loop before touching any
            asyncio-guarded state.
        """
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._apply_print_state_change(new_state), self._loop
        )

    async def _apply_print_state_change(self, new_state: str) -> None:
        """Update run status from a print-state transition, and broadcast it.

        Args:
            new_state: New Klipper ``print_stats.state`` value.
        """
        async with self._lock:
            if self._current.status != "running":
                return
            if new_state == "complete":
                self._current = RunStatus(
                    status="done",
                    message="Protocol completed successfully",
                    run_id=self._current.run_id,
                    filename=self._current.filename,
                )
            elif new_state in ("error", "cancelled"):
                self._current = RunStatus(
                    status="error",
                    message=f"Print job {new_state}",
                    run_id=self._current.run_id,
                    filename=self._current.filename,
                )
            else:
                return
            self._broadcast_status()

    def _broadcast_status(self) -> None:
        """Push the current run status to control-plane clients, if wired up."""
        if self._broadcast_callback is None:
            return
        self._broadcast_callback(
            "notify_run_status",
            {
                "status": self._current.status,
                "message": self._current.message,
                "run_id": self._current.run_id,
                "filename": self._current.filename,
            },
        )

"""Core orchestration object for the ``tapd`` daemon.

``AutoPipetteService`` owns the single Moonraker connection (``client``/
``mrr``), the domain layer (``_autopipette``/``gcode_manager``), and
exposes an async API that ``ControlServer`` dispatches control-plane
JSON-RPC requests to. It also owns the "current run" bookkeeping that
replaces the kiosk's old subprocess-exit-code heuristic with real Moonraker
``print_stats`` transitions (see ``daemon/moonraker_state.py``).

Migration Phase 4 (see CLAUDE.md's ports-and-adapters notes) removed cmd2
from this class entirely: it used to construct and delegate to a
``HeadlessTapShell`` (a ``cmd2.Cmd`` subclass) for all of this. Now it
builds ``AutoPipette``/``WebSocketClient``/``GCodeManager`` directly, the
same way ``cli/tap_shell.py``'s ``TriccaAutoPipetteShell`` does for
standalone/local-scripting use -- in fact ``TriccaAutoPipetteShell``
constructs one of these internally too, so both the daemon and the
standalone interactive shell share this exact class as their one business-
logic layer, differing only in whether ``start()``/``stop()`` (async, for
the daemon's event loop) or ``connect()``/``disconnect()`` (plain sync, for
a caller with no event loop) drives its lifecycle.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import shlex
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cmd2 import Cmd2ArgumentParser

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
    TAPCmdParsers,
    TipsArgs,
    TriggerArgs,
    UnloadLocationsArgs,
    VolToStepsArgs,
    WaitArgs,
    args_from_namespace,
)
from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.gcode_manager import GCodeManager
from tricca_autopipette.core.json_config_manager import JsonConfigManager
from tricca_autopipette.core.location_manager import LocationManager
from tricca_autopipette.core.pipette_constants import (
    ConfigKey,
    CoordinateSystem,
    DefaultFilenames,
    DefaultPaths,
    HomingTargets,
    TriggerChannels,
)
from tricca_autopipette.core.pipette_exceptions import (
    NotALocationError,
    NotHomedError,
    ProtocolAbortedError,
)
from tricca_autopipette.core.pipette_models import SystemConfig, TipState
from tricca_autopipette.core.plates import Plate, PlateParams
from tricca_autopipette.core.splits import parse_splits_spec
from tricca_autopipette.core.traversal import parse_well_ranges
from tricca_autopipette.core.well import StrategyType, Well
from tricca_autopipette.daemon.moonraker_state import MoonrakerStateTracker
from tricca_autopipette.moonraker.moonraker_requests import MoonrakerRequests
from tricca_autopipette.moonraker.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)

WEBSOCKET_TIMEOUT_SECONDS = 10

#: Shared message for diagnostic methods that require an active Moonraker
#: connection (as opposed to `output_gcode`'s own "no client at all" case,
#: which degrades gracefully instead -- see its docstring).
_NOT_CONNECTED_MSG = "WebSocket not connected. Cannot communicate with pipette."


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


@dataclass
class CommandResult:
    """Outcome of one typed command dispatched to ``AutoPipetteService``.

    The common return type for the structured, per-command methods (e.g.
    :meth:`AutoPipetteService.move`) that are gradually replacing the
    ``shell.exec``/cmd2-text-dispatch path. Adapters (cmd2 ``do_*`` methods,
    ``ControlServer``'s JSON-RPC dispatch) render ``message``/``data``
    directly rather than inferring success from captured stdout.

    Attributes:
        ok: True if the command completed as a normal (if possibly
            no-op) outcome. False for an expected "nothing to do" result
            (e.g. a relative move with all-zero offsets) -- genuine errors
            are raised as exceptions instead, not encoded here.
        message: Human-readable summary.
        data: Optional structured payload, or None.
    """

    ok: bool
    message: str
    data: dict[str, Any] | None = None


def require_homed(
    command_name: str,
) -> Callable[[Callable[..., CommandResult]], Callable[..., CommandResult]]:
    """Decorator factory: block an ``AutoPipetteService`` method until homed.

    Replaces ``HeadlessTapShell``'s ``_homed_interlock_hook`` (a cmd2
    postparsing hook, only reachable via cmd2 dispatch) with a check at
    the actual point of business logic -- works identically whether the
    method is reached via the interactive/``shell.exec`` cmd2 path, the
    protocol-file dispatch loop (Phase 2), or directly from
    ``ControlServer`` (Phase 1), none of which have to know about it.
    Raises :class:`NotHomedError` instead of the hook's ``stop=True`` +
    ``last_blocked_command`` side channel, so every caller gets one
    unambiguous signal instead of having to poll a mutable flag.

    Always checks before the wrapped method's own body runs, including
    before any "soft precondition" short-circuit (e.g. an all-zero
    relative move) the method itself might otherwise check first --
    consistent behavior across every gated method beats optimizing the
    homed check away for a no-op input.

    Args:
        command_name: Name to include in the raised ``NotHomedError``'s
            message (e.g. "move", or "pipette" for ``transfer``).

    Returns:
        Decorator wrapping the method with the homed check.
    """

    def decorator(
        func: Callable[..., CommandResult],
    ) -> Callable[..., CommandResult]:
        @functools.wraps(func)
        def wrapper(
            self: AutoPipetteService,
            *args: Any,  # ruff:ignore[any-type]
            **kwargs: Any,  # ruff:ignore[any-type]
        ) -> CommandResult:
            homed = self.moonraker_state is not None and self.moonraker_state.is_homed()
            if not homed:
                raise NotHomedError(command_name)
            return func(self, *args, **kwargs)

        return wrapper

    return decorator


def persist_tip_liquid_state(
    func: Callable[..., CommandResult],
) -> Callable[..., CommandResult]:
    """Decorator: persist tip/liquid state to Moonraker's DB if it changed.

    Replaces ``HeadlessTapShell``'s ``_persist_tip_liquid_state_hook`` (a
    cmd2 postcmd hook) the same way :func:`require_homed` replaces the
    interlock hook -- applied directly to the state-mutating methods that
    need it, rather than firing generically after every cmd2 command.
    This also closes a real gap the hook left behind once Phase 1/2 gave
    these methods non-cmd2 call paths: a ``pipette.next_tip`` RPC call or
    a protocol-file line never went through cmd2 dispatch at all, so the
    hook never ran for them and tip/liquid state silently stopped
    persisting on those paths -- this decorator persists regardless of
    which path called the method.

    Runs in a ``finally`` block, so state is persisted even if the
    wrapped method raises partway through (e.g. a chunked ``pipette()``
    transfer erroring after already picking up a tip) -- physical reality
    (a tip is or isn't attached) doesn't roll back just because a later
    step failed.

    Args:
        func: The ``AutoPipetteService`` method to wrap.

    Returns:
        The wrapped method.
    """

    @functools.wraps(func)
    def wrapper(self: AutoPipetteService, *args: Any, **kwargs: Any) -> CommandResult:  # ruff:ignore[any-type]
        try:
            return func(self, *args, **kwargs)
        finally:
            # This decorator is part of AutoPipetteService's own implementation
            # (same module, applied only to its methods), so reaching into the
            # service's privates here is deliberate rather than an outside
            # caller breaking encapsulation.
            if self.moonraker_state is not None:
                autopipette = self._autopipette  # pyright: ignore[reportPrivateUsage]
                state = autopipette.state
                snapshot = (
                    state.tip_state.value,
                    state.has_liquid,
                    autopipette.active_liquid,
                )
                if snapshot != self._last_persisted_state:  # pyright: ignore[reportPrivateUsage]
                    self._last_persisted_state = snapshot  # pyright: ignore[reportPrivateUsage]
                    self.moonraker_state.save_tip_liquid_state(*snapshot)

    return wrapper


def persist_tip_presence(
    func: Callable[..., CommandResult],
) -> Callable[..., CommandResult]:
    """Decorator: persist per-tipbox consumed positions if they changed.

    The sibling of :func:`persist_tip_liquid_state`, for the *other* piece of
    state Klipper has no notion of: which tip positions are still occupied.
    Applied directly to the methods that consume or redeclare tips, so every
    call path -- control-plane RPC, protocol-file line, interactive shell --
    persists identically, the same reason the interlock is a decorator rather
    than a cmd2 hook.

    Runs in a ``finally`` block: a transfer that picks up a tip and then fails
    has still physically consumed that tip, and the record must reflect it.

    Args:
        func: The ``AutoPipetteService`` method to wrap.

    Returns:
        The wrapped method.
    """

    @functools.wraps(func)
    def wrapper(self: AutoPipetteService, *args: Any, **kwargs: Any) -> CommandResult:  # ruff:ignore[any-type]
        try:
            return func(self, *args, **kwargs)
        finally:
            # Same rationale as persist_tip_liquid_state: this decorator is
            # part of AutoPipetteService's own implementation.
            if self.moonraker_state is not None:
                manager = self._autopipette.location_manager.tipbox_manager  # pyright: ignore[reportPrivateUsage]
                snapshot = manager.snapshot()
                if snapshot != self._persisted_tip_presence:  # pyright: ignore[reportPrivateUsage]
                    self._persisted_tip_presence = snapshot  # pyright: ignore[reportPrivateUsage]
                    self.moonraker_state.save_tip_presence(snapshot)

    return wrapper


class AutoPipetteService:
    """Owns the Moonraker connection, domain layer, and run lifecycle.

    Attributes:
        client: WebSocket client connected (or connecting) to Moonraker, or
            None if constructed with ``connect_websocket=False``.
        mrr: Moonraker request builder.
        gcode_manager: G-code generation/buffering for this service's
            ``AutoPipette``.
        moonraker_state: Live Klipper state tracker, or None if ``client``
            is None.
        breakpoint_handler: Called by ``break`` in place of a TTY prompt.
            None for standalone/local-scripting use (falls back to an
            interactive prompt there); set to :meth:`request_breakpoint` by
            :meth:`start` for daemon use.
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
        """Build the domain layer and Moonraker connection.

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
        json_config_manager = JsonConfigManager()
        fn_system = (
            config_system.name if config_system else DefaultFilenames.CONFIG_SYSTEM
        )
        fn_gantry = (
            config_gantry.name if config_gantry else DefaultFilenames.CONFIG_GANTRY
        )
        fn_pipette = (
            config_pipette.name if config_pipette else DefaultFilenames.CONFIG_PIPETTE
        )
        fn_liquids = (
            config_liquids.name if config_liquids else DefaultFilenames.CONFIG_LIQUIDS
        )
        system_config = json_config_manager.load_configs(
            fn_system, fn_gantry, fn_pipette, fn_liquids
        )
        location_manager = LocationManager()
        self._load_locations(location_manager, system_config, config_locations)
        self._autopipette = AutoPipette(json_config_manager, location_manager)

        self.hostname = self._get_hostname()
        self.mrr = MoonrakerRequests()
        self.uri = (
            "ws://localhost/websocket"
            if connect_local_websocket
            else f"ws://{self.hostname}/websocket"
        )
        self.client: WebSocketClient | None = (
            WebSocketClient(self.uri) if connect_websocket else None
        )

        self.gcode_manager = GCodeManager(DefaultPaths.DIR_GCODE, self._autopipette)

        self.moonraker_state: MoonrakerStateTracker | None = None
        if self.client is not None:
            self.moonraker_state = MoonrakerStateTracker(self.client, self.mrr)

        self.breakpoint_handler: Callable[[], bool] | None = None
        self._last_persisted_state: tuple[str, bool, str | None] | None = None
        # Last snapshot written to Moonraker's DB, so the decorator can skip
        # a round trip when nothing about tip occupancy changed.
        self._persisted_tip_presence: dict[str, Any] | None = None

        self._lock = asyncio.Lock()
        self._current = RunStatus(status="idle")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._broadcast_callback: Callable[[str, dict[str, Any]], None] | None = None
        self._breakpoint_event: threading.Event | None = None
        self._breakpoint_proceed = False
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._raw_subscriptions: set[str] = set()

    @staticmethod
    def _load_locations(
        location_manager: LocationManager,
        system_config: SystemConfig,
        config_locations: Path | None,
    ) -> None:
        """Populate the deck from the system config and the CLI override.

        Precedence, applied in order so later sources win on a name collision:

        1. The system config's ``locations`` section, if it declares any.
           Otherwise ``default_locations.json``, preserving the historical boot.
        2. ``--config-locations``, if given. This is *additive* -- it layers a
           protocol's deck on top of the machine's standing one rather than
           replacing it. Pass a full ``locations`` section in the system config
           instead if you want sole control.

        Args:
            location_manager: The manager to populate.
            system_config: The loaded system configuration.
            config_locations: Path from ``--config-locations``, or None.

        Raises:
            FileNotFoundError: If a referenced locations file doesn't exist.
            ValueError: If a locations source is invalid.
        """
        if system_config.locations.is_empty():
            location_manager.load_from_json(DefaultFilenames.CONFIG_LOCATIONS)
        else:
            location_manager.load_spec(system_config.locations.sources)

        if config_locations is not None:
            location_manager.load_from_json(config_locations.name)

    def _get_hostname(self) -> str:
        """Retrieve hostname from the loaded system configuration.

        Returns:
            Hostname or IP address from configuration.

        Raises:
            RuntimeError: If no hostname or IP configured.
        """
        network = self._autopipette.system_config.network
        ip_key = ConfigKey.Network.IP.lower()
        hostname_key = ConfigKey.Network.HOSTNAME.lower()
        hostname = network.get(ip_key) or network.get(hostname_key)

        if not hostname:
            raise RuntimeError(
                f"No hostname or IP configured in system.network. "
                f"Please set '{hostname_key}' or '{ip_key}' in "
                f"config/system/system.json"
            )
        return hostname

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

    def connect(self) -> bool:
        """Connect to Moonraker, subscribe to state, replay the init script.

        Plain synchronous entry point for a caller with no event loop of
        its own (``cli/tap_shell.py``'s standalone ``TriccaAutoPipetteShell``).
        :meth:`start` is the async equivalent, for the daemon.

        Returns:
            True if the Moonraker connection was established (or no
            connection was requested at all), False if it timed out.
        """
        connected = True
        if self.client is not None:
            self.client.start()
            connected = self.client.wait_for_connection(WEBSOCKET_TIMEOUT_SECONDS)
            if not connected:
                logger.error(
                    "Failed to connect to Moonraker at startup; "
                    "WebSocketClient will keep retrying in the background"
                )

        if self.moonraker_state is not None:
            self.moonraker_state.start()
            self.moonraker_state.on_print_state_change(self._handle_print_state_change)
            persisted = self.moonraker_state.load_tip_liquid_state()
            self._apply_persisted_state(persisted)
            self._apply_persisted_tip_presence(self.moonraker_state.load_tip_presence())

        self._run_startup_script()
        return connected

    def disconnect(self) -> None:
        """Disconnect from Moonraker. Sync counterpart to :meth:`connect`."""
        if self.client is not None:
            self.client.stop()

    async def start(self) -> None:
        """Connect to Moonraker without blocking the daemon's event loop."""
        self._loop = asyncio.get_running_loop()
        self.breakpoint_handler = self.request_breakpoint
        await asyncio.to_thread(self.connect)

    async def stop(self) -> None:
        """Disconnect from Moonraker without blocking the daemon's event loop."""
        await asyncio.to_thread(self.disconnect)

    def _apply_persisted_state(self, values: dict[str, Any]) -> None:
        """Rehydrate tip/liquid state from a prior run.

        Args:
            values: Mapping as returned by
                ``MoonrakerStateTracker.load_tip_liquid_state`` — any subset
                of ``tip_state``/``has_liquid``/``current_liquid`` may be
                absent (e.g. first run, nothing persisted yet).
        """
        state = self._autopipette.state
        if "tip_state" in values:
            state.tip_state = TipState(values["tip_state"])
        if "has_liquid" in values:
            state.has_liquid = bool(values["has_liquid"])
        current_liquid = values.get("current_liquid")
        if current_liquid and current_liquid in self._autopipette.system_config.liquids:
            self._autopipette.switch_liquid(current_liquid)
        self._last_persisted_state = (
            state.tip_state.value,
            state.has_liquid,
            self._autopipette.active_liquid,
        )

    def _apply_persisted_tip_presence(self, values: dict[str, Any]) -> None:
        """Rehydrate per-tipbox consumed positions from a prior run.

        Runs after the deck has been built from config, so it layers stored
        consumption onto boxes that are already registered. A box the config
        declared as partially used keeps that declaration only if no stored
        state exists for it -- the database is the more recent truth, since it
        reflects tips actually consumed since the file was written.

        Args:
            values: Mapping as returned by
                ``MoonrakerStateTracker.load_tip_presence``. Boxes absent from
                it stay as configured.
        """
        if not values:
            return

        manager = self._autopipette.location_manager.tipbox_manager
        skipped = manager.restore(values)

        if skipped:
            # Surfaced loudly: the operator's tip state is not what the
            # database thought, so those boxes are now assumed full.
            logger.warning(
                "Tipbox(es) %s were reconfigured since their state was saved; "
                "treating them as full. Run 'tips' to check, 'set_tips' to "
                "correct.",
                ", ".join(skipped),
            )

        self._persisted_tip_presence = manager.snapshot()

    def _run_startup_script(self) -> None:
        """Replay ``core/.init_pipette`` once, mirroring interactive startup.

        Runs each line through :meth:`_dispatch_protocol_line`, the same
        per-line dispatch the protocol-file run loop uses, rather than
        cmd2's ``startup_script``/``cmdloop()`` mechanism (which this class
        no longer has access to at all, as of migration Phase 4).
        """
        startup_path = DefaultPaths.DIR_SHELL / ".init_pipette"
        if not startup_path.exists():
            return
        lines = [
            line
            for line in startup_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in lines:
            self._dispatch_protocol_line(line)

    async def dispatch(self, func: Callable[[], CommandResult]) -> CommandResult:
        """Run one synchronous typed command method under the dispatch lock.

        ``ControlServer`` calls this for every structured (``movement.*``
        and successors) RPC method so they serialize against
        ``_run_protocol`` -- without this, a ``move`` request arriving
        mid-protocol could race with G-code generation on the same
        ``AutoPipette``/``GCodeManager`` state.

        Args:
            func: A zero-argument callable wrapping one of the typed command
                methods below, e.g. ``lambda: self.move(args)``.

        Returns:
            Whatever ``func`` returns.
        """
        async with self._lock:
            return await asyncio.to_thread(func)

    # ==================== Movement commands ====================
    #
    # The first group of commands migrated off cmd2-text dispatch (see
    # CLAUDE.md's ports-and-adapters migration notes). Each method here is
    # the sole owner of its command's business logic -- commands/*.py's
    # do_* methods are thin cmd2 adapters that delegate to these directly
    # (via self.service, see base_command_set.py's TAPCommandSet.service
    # property), and ControlServer dispatches the matching movement.* RPC
    # method straight here too, with no cmd2 involved on that path at all.

    @persist_tip_liquid_state
    def init(self) -> CommandResult:
        """Initialise the pipette: coordinate system, speed, and full homing.

        Returns:
            Result describing the completed initialisation.
        """
        autopipette = self._autopipette
        autopipette.init_pipette()
        self.output_gcode(autopipette.get_gcode(), "home_all.gcode")
        return CommandResult(
            ok=True, message="Pipette initialised and all motors homed."
        )

    @persist_tip_liquid_state
    def home(self, args: HomeArgs) -> CommandResult:
        """Home one or more motors on the pipette.

        Args:
            args: Motor specification (x, y, z, pipette, axis, all, servo).

        Returns:
            Result describing the completed homing operation.

        Raises:
            ValueError: If ``args.motors`` is not a recognized motor name.
        """
        autopipette = self._autopipette
        motors = args.motors.lower()

        if motors not in HomingTargets.VALID_MOTORS:
            valid = ", ".join(sorted(HomingTargets.VALID_MOTORS))
            raise ValueError(
                f"'{motors}' is not a valid motor specification. Valid options: {valid}"
            )

        if motors in HomingTargets.MOTOR_SPECIAL:
            # "all" -- delegate to init_pipette() so coordinate system and
            # speed are always reset alongside homing (identical to init()).
            filename = HomingTargets.MOTOR_SPECIAL[motors]
            autopipette.init_pipette()
            self.output_gcode(autopipette.get_gcode(), filename)
            return CommandResult(
                ok=True, message="All motors homed (full init complete)."
            )

        filename, method_name = HomingTargets.MOTOR_METHODS[motors]
        getattr(autopipette, method_name)()
        self.output_gcode(autopipette.get_gcode(), filename)
        return CommandResult(ok=True, message=f"Homed {motors}.")

    @require_homed("move")
    @persist_tip_liquid_state
    def move(self, args: MoveArgs) -> CommandResult:
        """Move to absolute XYZ coordinates.

        Args:
            args: Target x/y/z coordinates in millimeters.

        Returns:
            Result describing the completed move.

        Raises:
            NotHomedError: If the pipette is not homed.
        """
        autopipette = self._autopipette
        coor = Coordinate(x=args.x, y=args.y, z=args.z)
        autopipette.move_to(coor)
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(
            ok=True, message=f"Moving to X:{args.x} Y:{args.y} Z:{args.z}"
        )

    @require_homed("move_loc")
    @persist_tip_liquid_state
    def move_loc(self, args: MoveLocArgs) -> CommandResult:
        """Move to a named location, optionally a specific plate well.

        Args:
            args: Location name and optional row/col well indices.

        Returns:
            Result describing the completed move.

        Raises:
            NotHomedError: If the pipette is not homed.
            NotALocationError: If ``args.name_loc`` is not a defined location
                (raised by ``LocationManager.get_coordinate``).
            ValueError: If only one of row/col is given for a plate location.
        """
        autopipette = self._autopipette
        coor = autopipette.location_manager.get_coordinate(
            args.name_loc, args.row, args.col
        )
        autopipette.move_to(coor)
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(
            ok=True,
            message=(
                f"Moving to '{args.name_loc}' "
                f"(X:{coor.x:.2f} Y:{coor.y:.2f} Z:{coor.z:.2f})"
            ),
        )

    @require_homed("move_rel")
    @persist_tip_liquid_state
    def move_rel(self, args: MoveRelArgs) -> CommandResult:
        """Move relative to the current position.

        Switches to relative coordinate mode, performs the movement, then
        switches back to absolute mode.

        Args:
            args: Relative x/y/z offsets in millimeters (0 if unspecified).

        Returns:
            Result describing the completed move, or an ``ok=False`` no-op
            result if all offsets are zero.

        Raises:
            NotHomedError: If the pipette is not homed (checked before the
                all-zero-offset no-op case, unlike the pre-Phase-3 behavior --
                see ``require_homed``'s docstring).
        """
        # Exact sentinel check, not an arithmetic result: args.x/y/z are the
        # literal user-supplied offsets (default 0.0 when omitted), and an
        # isclose() tolerance would silently swallow a genuinely tiny
        # requested move as a no-op.
        if (
            args.x == 0.0  # ruff:ignore[float-equality-comparison]
            and args.y == 0.0  # ruff:ignore[float-equality-comparison]
            and args.z == 0.0  # ruff:ignore[float-equality-comparison]
        ):
            return CommandResult(
                ok=False, message="No movement — all offsets are zero."
            )

        autopipette = self._autopipette
        coor = Coordinate(x=args.x, y=args.y, z=args.z)

        autopipette.set_coor_sys(CoordinateSystem.RELATIVE)
        autopipette.move_to(coor)
        autopipette.set_coor_sys(CoordinateSystem.ABSOLUTE)
        self.output_gcode(autopipette.get_gcode())

        parts: list[str] = []
        if args.x != 0:
            parts.append(f"X{args.x:+.2f}")
        if args.y != 0:
            parts.append(f"Y{args.y:+.2f}")
        if args.z != 0:
            parts.append(f"Z{args.z:+.2f}")
        return CommandResult(ok=True, message=f"Moving relative: {' '.join(parts)}")

    # ==================== Pipette commands ====================
    #
    # Second group migrated off shell.exec/cmd2-text dispatch. Every method
    # here is gated (see PipetteCommands._GATED_COMMANDS-equivalent list in
    # HeadlessTapShell) -- unlike movement, all of aspirate/dispense/
    # transfer/next_tip/eject_tip/dispose_tip/change_tip require a homed
    # machine.
    #
    # Soft, non-exceptional preconditions (no tip attached, no liquid in
    # tip, a non-positive volume) are checked inside the method body, i.e.
    # after `@require_homed` -- since Phase 3 the decorator always runs
    # first, so an unhomed call now raises `NotHomedError` even for an
    # input that would otherwise have been a no-op `CommandResult(ok=False,
    # ...)`. This is a deliberate consistency fix: 6 of these 10 gated
    # methods already checked homed-first before Phase 3, and a decorator
    # wrapping the whole method can't cheaply special-case "homed check
    # after this one soft precondition" per method anyway. Domain
    # exceptions (`NoTipboxError`, `TipAlreadyOnError`, `NotALocationError`,
    # `NoWasteContainerError`) propagate uncaught, same as the movement
    # group.

    @require_homed("aspirate")
    @persist_tip_liquid_state
    def aspirate(self, args: AspirateArgs) -> CommandResult:
        """Aspirate liquid from a source without dispensing.

        Args:
            args: Volume, source location, and aspirate options.

        Returns:
            Result describing the completed aspiration, or an ``ok=False``
            result if there's no tip attached or the volume isn't positive.

        Raises:
            NotHomedError: If the pipette is not homed (checked before the
                soft no-tip/non-positive-volume no-op cases -- see
                ``require_homed``'s docstring).
            NotALocationError: If ``args.source`` is not a defined location.
        """
        autopipette = self._autopipette

        if autopipette.state.tip_state != TipState.ATTACHED:
            return CommandResult(
                ok=False, message="No tip attached. Use 'next_tip' first."
            )
        if args.vol_ul <= 0:
            return CommandResult(ok=False, message="Volume must be greater than zero.")

        autopipette.aspirate_volume(
            volume=args.vol_ul,
            source=args.source,
            src_row=args.src_row,
            src_col=args.src_col,
            pre_air_gap_ul=args.pre_air_gap_ul,
            post_air_gap_ul=args.post_air_gap_ul,
            prewet_cycles=args.prewet_cycles,
            prewet_vol_ul=args.prewet_vol_ul,
        )
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(
            ok=True, message=f"Aspirated {args.vol_ul} μL from {args.source}"
        )

    @require_homed("dispense")
    @persist_tip_liquid_state
    def dispense(self, args: DispenseArgs) -> CommandResult:
        """Dispense previously-aspirated liquid to a destination.

        Args:
            args: Destination location and dispense options.

        Returns:
            Result describing the completed dispense, or an ``ok=False``
            result if there's no liquid in the tip.

        Raises:
            NotHomedError: If the pipette is not homed (checked before the
                soft no-liquid-in-tip no-op case -- see ``require_homed``'s
                docstring).
            NotALocationError: If ``args.dest`` is not a defined location.
        """
        autopipette = self._autopipette

        if not autopipette.state.has_liquid:
            return CommandResult(
                ok=False, message="No liquid in tip. Use 'aspirate' first."
            )

        autopipette.dispense_volume(
            dest=args.dest,
            dest_row=args.dest_row,
            dest_col=args.dest_col,
            volume=args.volume,
            wiggle=args.wiggle,
        )
        self.output_gcode(autopipette.get_gcode())
        if args.volume is not None:
            message = f"Dispensed {args.volume} μL to {args.dest}"
        else:
            message = f"Dispensed all liquid to {args.dest}"
        return CommandResult(ok=True, message=message)

    @require_homed("pipette")
    @persist_tip_liquid_state
    @persist_tip_presence
    def transfer(self, args: PipetteArgs) -> CommandResult:
        """Transfer liquid from source to destination (the ``pipette`` command).

        Named ``transfer`` here (and in the ``pipette.*`` control-plane
        namespace) to avoid a ``pipette.pipette`` stutter -- the interactive
        command name stays ``pipette``.

        Args:
            args: Full transfer parameters (volume, source, dest, tip/prewet_cycles/
                wiggle options).

        Returns:
            Result describing the completed transfer, or an ``ok=False``
            result if the volume isn't positive.

        Raises:
            NotHomedError: If the pipette is not homed (checked before the
                soft non-positive-volume no-op case -- see ``require_homed``'s
                docstring).
            NoTipboxError: If a tip pickup is needed but no tipbox is
                configured.
            TipAlreadyOnError: If a tip is already attached when one is
                needed.
            NoWasteContainerError: If the transfer disposes of its tip (i.e.
                ``keep_tip`` is False) and no waste container is configured,
                or if ``args.leftover`` is ``"waste"`` and there is none.
            NotALocationError: If ``args.source``/``args.dest`` (or a
                ``--splits`` destination) is not a defined location.
            ValueError: If a ``--splits`` spec fails validation against the
                deck -- see ``AutoPipette.resolve_splits``.
            VolumeCapacityError: If the requested volume exceeds usable
                syringe capacity.
        """
        if args.vol_ul <= 0:
            return CommandResult(ok=False, message="Volume must be greater than zero.")

        autopipette = self._autopipette

        if args.splits:
            try:
                splits = parse_splits_spec(args.splits)
            except ValueError as exc:
                return CommandResult(ok=False, message=str(exc))

            autopipette.pipette_splits(
                vol_ul=args.vol_ul,
                source=args.source,
                splits=splits,
                src_row=args.src_row,
                src_col=args.src_col,
                tipbox_name=args.tipbox_name,
                pre_air_gap_ul=args.pre_air_gap_ul,
                post_air_gap_ul=args.post_air_gap_ul,
                prewet_cycles=args.prewet_cycles,
                prewet_vol_ul=args.prewet_vol_ul,
                wiggle=args.wiggle,
                leftover=args.leftover,
                keep_tip=args.keep_tip,
            )
            destination = ", ".join(f"{s.dest}:{s.vol_ul}" for s in splits)
            split_count = len(splits)
        else:
            autopipette.pipette(
                vol_ul=args.vol_ul,
                source=args.source,
                dest=args.dest,
                disp_vol_ul=args.disp_vol_ul,
                src_row=args.src_row,
                src_col=args.src_col,
                dest_row=args.dest_row,
                dest_col=args.dest_col,
                tipbox_name=args.tipbox_name,
                pre_air_gap_ul=args.pre_air_gap_ul,
                post_air_gap_ul=args.post_air_gap_ul,
                prewet_cycles=args.prewet_cycles,
                prewet_vol_ul=args.prewet_vol_ul,
                wiggle=args.wiggle,
                keep_tip=args.keep_tip,
            )
            destination = args.dest
            split_count = 0

        features: list[str] = []
        if args.prewet_cycles:
            features.append(f"prewet×{args.prewet_cycles}")
        if args.wiggle:
            features.append("wiggle")
        if args.keep_tip:
            features.append("keep-tip")
        if split_count:
            features.append(f"splits×{split_count}")
        if args.leftover:
            features.append(f"leftover={args.leftover}")

        comment = f"\n; Pipette {args.vol_ul} μL from {args.source} to {destination}"
        if features:
            comment += f" [{', '.join(features)}]"
        comment += "\n"

        self.output_gcode([comment, *autopipette.get_gcode(), "\n"])
        return CommandResult(
            ok=True,
            message=(
                f"Pipetting complete ({args.vol_ul} μL: {args.source} → {destination})"
            ),
        )

    @require_homed("next_tip")
    @persist_tip_liquid_state
    @persist_tip_presence
    def next_tip(self) -> CommandResult:
        """Pick up the next available tip from the tipbox.

        Returns:
            Result describing the completed pickup.

        Raises:
            NotHomedError: If the pipette is not homed.
            NoTipboxError: If no tipbox is configured.
            TipAlreadyOnError: If a tip is already attached.
        """
        autopipette = self._autopipette
        autopipette.next_tip()
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(ok=True, message="Tip picked up.")

    @require_homed("eject_tip")
    @persist_tip_liquid_state
    def eject_tip(self) -> CommandResult:
        """Eject the current tip in place (does not move to waste).

        Returns:
            Result describing the completed ejection, or an ``ok=False``
            result if there's no tip attached.

        Raises:
            NotHomedError: If the pipette is not homed.
        """
        autopipette = self._autopipette
        if autopipette.state.tip_state != TipState.ATTACHED:
            return CommandResult(
                ok=False, message="No tip attached — nothing to eject."
            )

        autopipette.eject_tip()
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(
            ok=True,
            message=(
                "Tip ejected at current position. "
                "Note: tip was not moved to the waste container."
            ),
        )

    @require_homed("dispose_tip")
    @persist_tip_liquid_state
    def dispose_tip(self) -> CommandResult:
        """Dispose the current tip in the waste container.

        Returns:
            Result describing the completed disposal, or an ``ok=False``
            result if there's no tip attached.

        Raises:
            NotHomedError: If the pipette is not homed.
            NoWasteContainerError: If no waste container is configured.
        """
        autopipette = self._autopipette
        if autopipette.state.tip_state != TipState.ATTACHED:
            return CommandResult(
                ok=False, message="No tip attached — nothing to dispose."
            )

        autopipette.dispose_tip()
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(ok=True, message="Tip disposed.")

    @require_homed("change_tip")
    @persist_tip_liquid_state
    @persist_tip_presence
    def change_tip(self) -> CommandResult:
        """Dispose the current tip (if any) and pick up a fresh one.

        Returns:
            Result describing the completed change.

        Raises:
            NotHomedError: If the pipette is not homed.
            NoTipboxError: If no tipbox is configured.
            NoWasteContainerError: If a tip is currently attached and no
                waste container is configured to dispose of it.
        """
        autopipette = self._autopipette
        if autopipette.state.tip_state == TipState.ATTACHED:
            autopipette.dispose_tip()

        autopipette.next_tip()
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(ok=True, message="Tip changed.")

    # ==================== Configuration commands ====================
    #
    # Third group migrated off cmd2-text dispatch. None of these are
    # gated (no @require_homed). The read-only reporting commands this
    # CommandSet exposes (list_liquids, ls) are handled by the
    # "Reporting (read-only)" methods further down this file, which return
    # structured data -- table rendering itself stays in each driving
    # adapter (see cli/report_tables.py), not here.

    @persist_tip_liquid_state
    def switch_liquid(self, liquid_name: str) -> CommandResult:
        """Switch to a different liquid profile.

        Args:
            liquid_name: Name of the liquid profile to activate.

        Returns:
            Result naming the new liquid, with its key parameters
            (viscosity, aspirate speed, prewet_cycles recommendation) in ``data``
            for adapters that want to render them individually.

        Raises:
            ValueError: If ``liquid_name`` is not a loaded liquid profile.
        """
        autopipette = self._autopipette
        autopipette.switch_liquid(liquid_name)
        liquid = autopipette.system_config.liquids[liquid_name]

        return CommandResult(
            ok=True,
            message=f"Switched to liquid: {liquid_name}",
            data={
                "viscosity_cP": liquid.viscosity_cP,
                "speed_aspirate": liquid.speed_aspirate,
                "prewet_cycles": liquid.prewet_cycles,
                "pre_air_gap_ul": liquid.pre_air_gap_ul,
                "post_air_gap_ul": liquid.post_air_gap_ul,
            },
        )

    @persist_tip_liquid_state
    def load_liquid(self, filename: str) -> CommandResult:
        """Load a new liquid profile from a JSON file.

        Args:
            filename: Liquid config filename (looked up under
                ``config/liquids/``).

        Returns:
            Result naming the loaded profile.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file's contents are an invalid liquid profile.
        """
        liquid = self._autopipette.config_manager.load_liquid(filename)
        return CommandResult(
            ok=True,
            message=f"Loaded liquid profile: {liquid.name}",
            data={"name": liquid.name, "viscosity_cP": liquid.viscosity_cP},
        )

    def set(self, args: SetArgs) -> CommandResult:
        """Set a gantry configuration variable, emitting G-code immediately.

        Args:
            args: Variable name (SPEED_FACTOR, VELOCITY_MAX, or ACCEL_MAX)
                and its new numeric value.

        Returns:
            Result describing the change, or an ``ok=False`` result if
            ``args.var`` isn't a recognized variable.
        """
        autopipette = self._autopipette
        var_name = args.var.upper()

        if var_name == "SPEED_FACTOR":
            autopipette.set_speed_factor(args.value)
            self.output_gcode(autopipette.get_gcode())
            return CommandResult(ok=True, message=f"Set {var_name} = {args.value}")
        if var_name == "VELOCITY_MAX":
            autopipette.set_max_velocity(args.value)
            self.output_gcode(autopipette.get_gcode())
            return CommandResult(ok=True, message=f"Set {var_name} = {args.value} mm/s")
        if var_name == "ACCEL_MAX":
            autopipette.set_max_accel(args.value)
            self.output_gcode(autopipette.get_gcode())
            return CommandResult(
                ok=True, message=f"Set {var_name} = {args.value} mm/s²"
            )
        return CommandResult(
            ok=False,
            message=(
                f"Unknown variable '{var_name}'. "
                "Available: SPEED_FACTOR, VELOCITY_MAX, ACCEL_MAX"
            ),
        )

    def coor(self, args: CoorArgs) -> CommandResult:
        """Define a named coordinate location.

        Args:
            args: Location name and x/y/z coordinates in millimeters.

        Returns:
            Result describing the created coordinate.
        """
        autopipette = self._autopipette
        coord = Coordinate(x=args.x, y=args.y, z=args.z)
        autopipette.location_manager.set_coordinate(args.name, coord)
        return CommandResult(
            ok=True,
            message=(
                f"Created coordinate '{args.name}' (X={args.x}, Y={args.y}, Z={args.z})"
            ),
        )

    def plate(self, args: PlateArgs) -> CommandResult:
        """Define a plate at a named location.

        Args:
            args: Plate name, type, dimensions, position, and dip strategy.

        Returns:
            Result describing the created plate.

        Raises:
            TypeError: If the plate factory produces a type mismatched with
                ``args.plate_type`` (see ``LocationManager.set_plate``).
            RuntimeError: If appending an additional tipbox to an existing
                non-tipbox location (see ``LocationManager.set_plate``).
        """
        well = Well(
            coor=Coordinate(x=args.x, y=args.y, z=args.z),
            dip_top=args.dip_top,
            dip_btm=args.dip_btm,
            strategy_type=StrategyType(args.dip_func),
            well_diameter=args.well_diameter,
        )
        plate_params = PlateParams(
            plate_type=args.plate_type,
            well_template=well,
            num_row=args.num_row,
            num_col=args.num_col,
            spacing_row=args.spacing_row,
            spacing_col=args.spacing_col,
        )

        self._autopipette.location_manager.set_plate(args.name, plate_params)
        return CommandResult(
            ok=True,
            message=(
                f"Created plate '{args.name}' ({args.plate_type}, "
                f"{args.num_row}×{args.num_col} wells) at "
                f"X={args.x}, Y={args.y}, Z={args.z}"
            ),
        )

    def reset_plate(self, args: ResetPlateArgs) -> CommandResult:
        """Reset a specific plate's current position to the origin well.

        Args:
            args: Name of the plate to reset.

        Returns:
            Result describing the reset, or an ``ok=False`` result if
            ``args.name`` doesn't exist or isn't a plate.
        """
        loc_mgr = self._autopipette.location_manager

        if not loc_mgr.has_location(args.name):
            return CommandResult(ok=False, message=f"Location '{args.name}' not found.")

        location = loc_mgr.locations[args.name]
        if not isinstance(location, Plate):
            return CommandResult(ok=False, message=f"'{args.name}' is not a plate.")

        location.reset()
        return CommandResult(
            ok=True, message=f"Reset plate '{args.name}' to position 0"
        )

    def reset_plates(self) -> CommandResult:
        """Reset all plates to their origin well.

        Returns:
            Result describing how many plates were reset, or an
            ``ok=False`` result if there are none.
        """
        loc_mgr = self._autopipette.location_manager
        plate_names = loc_mgr.get_plate_names()

        if not plate_names:
            return CommandResult(ok=False, message="No plates to reset.")

        for name in plate_names:
            plate = loc_mgr.locations[name]
            if isinstance(plate, Plate):
                plate.reset()
        return CommandResult(
            ok=True, message=f"Reset {len(plate_names)} plate(s) to origin."
        )

    def del_loc(self, args: DelLocArgs) -> CommandResult:
        """Delete a named location or plate.

        Args:
            args: Name of the location to delete.

        Returns:
            Result describing the deletion, or an ``ok=False`` result if
            ``args.name`` doesn't exist.
        """
        loc_mgr = self._autopipette.location_manager

        if not loc_mgr.has_location(args.name):
            return CommandResult(ok=False, message=f"Location '{args.name}' not found.")

        loc_mgr.remove_location(args.name)
        return CommandResult(ok=True, message=f"Deleted location '{args.name}'.")

    def clear_locs(self) -> CommandResult:
        """Delete all locations and plates.

        Returns:
            Result describing how many locations were cleared, or an
            ``ok=False`` result if there were none.
        """
        loc_mgr = self._autopipette.location_manager
        count = len(loc_mgr.locations)

        if count == 0:
            return CommandResult(ok=False, message="No locations to clear.")

        loc_mgr.clear()
        return CommandResult(ok=True, message=f"Cleared {count} location(s).")

    def save_locations(self, filename: str) -> CommandResult:
        """Save current locations to a JSON file under ``config/locations/``.

        Args:
            filename: Output filename.

        Returns:
            Result naming the saved file.
        """
        self._autopipette.location_manager.save_to_json(filename)
        return CommandResult(ok=True, message=f"Saved locations to {filename}")

    @persist_tip_presence
    def load_locations(self, args: LoadLocationsArgs) -> CommandResult:
        """Load locations from a JSON file, adding to the current deck.

        Loading is additive so a deck can be composed from reusable groups;
        pass ``--replace`` for the old wipe-then-load behavior.

        Args:
            args: Filename under ``config/locations/`` and the replace flag.

        Returns:
            Result summarizing how many coordinates/plates are now loaded.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file's contents are invalid.

        Note:
            A failed load leaves the existing deck untouched -- the file is
            fully parsed before anything is applied.
        """
        location_manager = self._autopipette.location_manager
        location_manager.load_from_json(args.filename, replace=args.replace)
        coords = location_manager.get_coordinate_names()
        plates = location_manager.get_plate_names()
        verb = "Replaced deck with" if args.replace else "Loaded"
        return CommandResult(
            ok=True,
            message=(
                f"{verb} locations from {args.filename}; deck now holds "
                f"{len(coords)} coordinate(s), {len(plates)} plate(s)"
            ),
        )

    @persist_tip_presence
    def unload_locations(self, args: UnloadLocationsArgs) -> CommandResult:
        """Remove a single location from the deck by name.

        Args:
            args: Name of the location to unload.

        Returns:
            Result naming the unloaded location, or an ``ok=False`` result if
            no location by that name is loaded.
        """
        if not self._autopipette.location_manager.unload(args.name):
            return CommandResult(ok=False, message=f"No such location: {args.name}")
        return CommandResult(ok=True, message=f"Unloaded location: {args.name}")

    # ==================== Tip inventory ====================
    #
    # Klipper has no notion of which tip positions are occupied, so these
    # commands are how an operator reconciles the daemon's record with the
    # physical boxes after reloading or swapping one.

    @persist_tip_presence
    def reset_tips(self, args: ResetTipsArgs) -> CommandResult:
        """Mark one tipbox as full, after physically reloading it.

        Args:
            args: Name of the tipbox to reset.

        Returns:
            Result naming the box and its tip count, or an ``ok=False`` result
            if no tipbox by that name is registered.
        """
        manager = self._autopipette.location_manager.tipbox_manager
        try:
            manager.reset_tips(args.name)
        except NotALocationError:
            return CommandResult(ok=False, message=f"No such tipbox: {args.name}")

        box = manager.boxes[args.name]
        return CommandResult(
            ok=True, message=f"Reset {args.name}: {box.remaining} tip(s) available"
        )

    @persist_tip_presence
    def reset_tips_all(self) -> CommandResult:
        """Mark every registered tipbox as full.

        Returns:
            Result summarizing the boxes reset and the total tips available.
        """
        manager = self._autopipette.location_manager.tipbox_manager
        if not manager.has_boxes():
            return CommandResult(ok=False, message="No tipboxes are loaded.")

        manager.reset_all()
        return CommandResult(
            ok=True,
            message=(
                f"Reset {len(manager.boxes)} tipbox(es): "
                f"{manager.remaining} tip(s) available"
            ),
        )

    @persist_tip_presence
    def set_tips(self, args: SetTipsArgs) -> CommandResult:
        """Declare exactly which positions of a tipbox hold tips.

        Replaces the box's state rather than adding to it, so it can both
        consume and restore positions -- the intended way to correct drift
        between the daemon's record and the physical box.

        Args:
            args: Tipbox name, well ranges, and whether the ranges name the
                available positions rather than the consumed ones.

        Returns:
            Result summarizing the box's new tip count, or an ``ok=False``
            result if the box is unknown or a range is invalid.
        """
        manager = self._autopipette.location_manager.tipbox_manager
        box = manager.boxes.get(args.name)
        if box is None:
            return CommandResult(ok=False, message=f"No such tipbox: {args.name}")

        try:
            listed = parse_well_ranges(args.ranges, box.num_row, box.num_col)
        except ValueError as e:
            return CommandResult(ok=False, message=str(e))

        # --available names what remains, so invert to get the consumed set.
        consumed = set(range(len(box.wells))) - listed if args.available else listed
        manager.set_consumed(args.name, consumed)

        return CommandResult(
            ok=True,
            message=(f"{args.name}: {box.remaining}/{box.capacity} tip(s) available"),
        )

    def tips(self, args: TipsArgs) -> CommandResult:
        """Report tip availability per box.

        Data only -- the ASCII map is rendered by ``cli/report_tables.py`` so
        the local and remote shells display it identically.

        Args:
            args: Optional box name to narrow to, and whether to include the
                state persisted in Moonraker's database for comparison.

        Returns:
            Result whose ``data`` holds a ``boxes`` list of per-box records
            and, when requested, a ``persisted`` mapping to diff against.
        """
        manager = self._autopipette.location_manager.tipbox_manager

        if args.name is not None:
            if args.name not in manager.boxes:
                return CommandResult(ok=False, message=f"No such tipbox: {args.name}")
            boxes = [manager.describe(args.name)]
        else:
            boxes = manager.describe_all()

        data: dict[str, Any] = {
            "boxes": boxes,
            "total_remaining": manager.remaining,
            "total_capacity": manager.capacity,
        }

        if args.db:
            data["persisted"] = (
                self.moonraker_state.load_tip_presence()
                if self.moonraker_state is not None
                else {}
            )

        return CommandResult(
            ok=True,
            message=f"{manager.remaining}/{manager.capacity} tip(s) available",
            data=data,
        )

    # ==================== Utility commands ====================
    #
    # Fourth group migrated off shell.exec/cmd2-text dispatch. None of these
    # are in the homed-interlock's gated set. Unlike ConfigurationCommands'
    # excluded list_liquids/ls, every command here is migrated: even the
    # read-only ones (webcam, vol_to_steps, steps_to_vol) do a real domain
    # computation/lookup rather than rendering a `rich.table.Table`, so a
    # non-CLI client could plausibly want them too.

    def wait(self, args: WaitArgs) -> CommandResult:
        """Insert a timed pause into the G-code output.

        Args:
            args: Duration in milliseconds.

        Returns:
            Result describing the wait, or an ``ok=False`` result if
            ``args.ms`` isn't positive.
        """
        if args.ms <= 0:
            return CommandResult(
                ok=False, message="Wait duration must be greater than zero."
            )

        autopipette = self._autopipette
        autopipette.gcode_wait(args.ms)
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(ok=True, message=f"Wait: {args.ms:.0f} ms")

    def trigger(self, args: TriggerArgs) -> CommandResult:
        """Control an auxiliary trigger channel (air, shake, aux).

        Not yet implemented in ``AutoPipette`` -- this only validates the
        channel/state and reports that, matching the original stub's
        behavior.

        Args:
            args: Channel name and desired state (on/off).

        Returns:
            An ``ok=False`` result: either an invalid channel/state
            message, or the "not yet implemented" stub message.
        """
        channel = args.channel.lower()
        state = args.state.lower()

        if channel not in TriggerChannels.VALID_CHANNELS:
            valid = ", ".join(sorted(TriggerChannels.VALID_CHANNELS))
            return CommandResult(
                ok=False, message=f"Invalid channel '{channel}'. Valid: {valid}"
            )
        if state not in TriggerChannels.VALID_STATES:
            valid = ", ".join(sorted(TriggerChannels.VALID_STATES))
            return CommandResult(
                ok=False, message=f"Invalid state '{state}'. Valid: {valid}"
            )

        return CommandResult(
            ok=False,
            message=(
                f"Trigger functionality not yet implemented. "
                f"Would turn '{channel}' {state}."
            ),
        )

    def gcode_print(self, args: GcodePrintArgs) -> CommandResult:
        """Send a message to be displayed on the pipette screen.

        Args:
            args: Message to display.

        Returns:
            Result describing the queued message, or an ``ok=False``
            result if the message is empty.
        """
        if not args.msg.strip():
            return CommandResult(ok=False, message="Message cannot be empty.")

        autopipette = self._autopipette
        autopipette.gcode_print(args.msg)
        self.output_gcode(autopipette.get_gcode())
        return CommandResult(ok=True, message=f"Display message queued: {args.msg}")

    def webcam_url(self) -> CommandResult:
        """Build the webcam stream URL for this pipette.

        Returns:
            Result with the URL both in ``message`` and ``data["url"]``.
        """
        url = f"http://{self.hostname}/webcam/?action=stream"
        return CommandResult(ok=True, message=url, data={"url": url})

    def vol_to_steps(self, args: VolToStepsArgs) -> CommandResult:
        """Convert a volume in microliters to motor steps.

        Uses the active liquid's calibration curve.

        Args:
            args: Volume in microliters.

        Returns:
            Result with the step count in ``message``/``data``, or an
            ``ok=False`` result if the volume isn't positive.
        """
        if args.vol <= 0:
            return CommandResult(ok=False, message="Volume must be greater than zero.")

        converter = self._autopipette.volume_converter
        steps = converter.vol_to_steps(args.vol)
        return CommandResult(
            ok=True,
            message=f"{args.vol} μL = {steps} steps",
            data={"steps": steps, "round_trip_vol": converter.steps_to_vol(steps)},
        )

    def steps_to_vol(self, steps: int) -> CommandResult:
        """Convert motor steps to a volume in microliters.

        Inverse of :meth:`vol_to_steps`, using the active liquid's
        calibration curve.

        Args:
            steps: Number of motor steps.

        Returns:
            Result with the volume in ``message``/``data``, or an
            ``ok=False`` result if ``steps`` is negative.
        """
        if steps < 0:
            return CommandResult(ok=False, message="Steps cannot be negative.")

        converter = self._autopipette.volume_converter
        vol = converter.steps_to_vol(steps)
        return CommandResult(
            ok=True, message=f"{steps} steps = {vol:.2f} μL", data={"vol": vol}
        )

    # ==================== G-code file management ====================
    #
    # Moved here from cli/tap_shell.py in migration Phase 4 (see CLAUDE.md).
    # Previously fire-and-forget (a bare `threading.Thread` reporting success/
    # failure via `add_alert`/`perror`, since the interactive shell's caller
    # had no other way to observe a background thread's outcome); now plain
    # blocking calls on `Future.result()`, so upload failures propagate as
    # real exceptions -- through the control-plane error envelope for the
    # daemon (which wraps these in `asyncio.to_thread`), and directly to the
    # standalone shell's `except` blocks.

    def upload_gcode(self, filename: str, file_path: Path) -> str:
        """Upload a G-code file to the pipette, without starting execution.

        Args:
            filename: Name for the file on the server.
            file_path: Local path to the G-code file.

        Returns:
            The server-side path the file was uploaded to.

        Raises:
            RuntimeError: If there is no WebSocket client.
            Exception: Whatever ``WebSocketClient.upload_gcode_file``'s
                future raises (e.g. ``WebSocketClient.UploadError``).
        """
        if self.client is None:
            raise RuntimeError(
                "WebSocket client not initialized. Cannot upload G-code."
            )
        future = self.client.upload_gcode_file(filename, str(file_path))
        return future.result()

    def upload_gcode_result(self, file_name: str, file_path: Path) -> CommandResult:
        """``upload_gcode``, wrapped as a ``CommandResult`` for RPC dispatch.

        Args:
            file_name: Name for the file on the server.
            file_path: Local path to the G-code file.

        Returns:
            Result naming the server-side path.

        Raises:
            RuntimeError: If there is no WebSocket client.
            Exception: Whatever the upload raises.
        """
        server_path = self.upload_gcode(file_name, file_path)
        return CommandResult(
            ok=True, message=f"Upload successful. Server path: {server_path}"
        )

    def upload_and_execute_gcode(
        self, filename: str, file_path: Path, delete_file: bool = False
    ) -> str:
        """Upload a G-code file and immediately start execution.

        Args:
            filename: Name for the file on the server.
            file_path: Local path to the G-code file.
            delete_file: Whether to delete the local file after a
                successful upload.

        Returns:
            The server-side path the file was uploaded to.

        Raises:
            RuntimeError: If there is no WebSocket client.
            Exception: Whatever the upload or the ``printer.print.start``
                RPC raises.
        """
        server_path = self.upload_gcode(filename, file_path)
        self.client.send_jsonrpc(self.mrr.printer_print_start(filename))  # type: ignore[union-attr]
        if delete_file:
            file_path.unlink()
        return server_path

    def output_gcode(
        self,
        gcode: list[str],
        filename: str | None = None,
        append_header: bool = False,
    ) -> None:
        """Write G-code to file and upload for execution.

        Operates in two modes based on ``GCodeManager`` state:
        1. Batch mode: appends to the buffer for later combined upload.
        2. Immediate mode: writes to file and uploads/executes immediately.

        Args:
            gcode: List of G-code command strings.
            filename: Output filename, or None to auto-generate a timestamp.
            append_header: Whether to prepend the configuration header.

        Raises:
            OSError: If the G-code file can't be written.
            Exception: Whatever the upload-and-execute call raises, once
                actually connected (see the "no client at all" note below).

        Note:
            If there is no WebSocket client at all (``connect_websocket=
            False``, e.g. ``tapd --no-connect``, a documented local-testing
            mode -- see CLAUDE.md), this logs and returns rather than
            raising: every gated command calls this as a side effect of
            emitting G-code, and hard-failing all of them just because
            there's no live Moonraker connection would defeat the point of
            that mode. Contrast with :meth:`upload_gcode`/
            :meth:`upload_and_execute_gcode` themselves, which do raise for
            "no client" -- appropriate for their direct, explicit callers
            (e.g. the ``upload``/``ws.upload`` diagnostic command), where a
            silent no-op would be a confusing surprise instead.
        """
        if self.gcode_manager.is_batch_mode:
            self.gcode_manager.add_gcode(gcode)
            return

        if self.client is None:
            logger.error("Cannot upload G-code: no WebSocket client configured.")
            return

        file_path = self.gcode_manager.write_gcode_file(gcode, filename, append_header)
        self.upload_and_execute_gcode(file_path.name, file_path, delete_file=True)

    # ==================== WebSocket diagnostics ====================
    #
    # Migrated off cmd2/`WebSocketCommands` in Phase 4 (see CLAUDE.md) --
    # this group is diagnostic tooling rather than pipetting business logic,
    # but needed real service methods + control-plane RPCs once `shell.exec`
    # (its only path to a remote `tap` client) was removed. `subscribe`/
    # `unsubscribe` register a handler on this service's own Moonraker
    # connection that re-broadcasts matching notifications to every
    # connected control-plane client as `notify_raw_event` -- the daemon's
    # existing push mechanism (see `_broadcast_callback`), generalized
    # rather than duplicated -- since an arbitrary Python callback
    # registered by one remote client can't itself cross the wire.

    def ws_status(self) -> CommandResult:
        """Report the status of this service's own Moonraker connection.

        Returns:
            Result with ``ok`` mirroring connection state and connection/
            queue/handler/pending-request details in ``data``.
        """
        if self.client is None:
            return CommandResult(ok=False, message="WebSocket client not initialized.")
        connected = self.client.is_connected()
        data = {
            "connected": connected,
            "uri": self.uri,
            "queued_messages": len(self.client),
            "handlers": sorted(self.client.handlers),
            "pending_requests": self.client.pending_count,
        }
        message = "WebSocket connected." if connected else "WebSocket disconnected."
        return CommandResult(ok=connected, message=message, data=data)

    def ping_moonraker(self) -> CommandResult:
        """Ping Moonraker directly and measure round-trip time.

        Returns:
            Result describing the round trip.

        Raises:
            RuntimeError: If there is no connected WebSocket client.
            TimeoutError: If the ping times out.
        """
        if self.client is None or not self.client.is_connected():
            raise RuntimeError(_NOT_CONNECTED_MSG)
        start = time.monotonic()
        response = self.client.send_jsonrpc(self.mrr.server_info(), timeout=5.0)
        elapsed_ms = (time.monotonic() - start) * 1000
        if "result" in response:
            return CommandResult(
                ok=True, message=f"Pong! (Round-trip: {elapsed_ms:.1f}ms)"
            )
        return CommandResult(
            ok=False, message="Response received but contained no result."
        )

    def send_raw(self, method: str, params: dict[str, Any] | None) -> CommandResult:
        """Send an arbitrary JSON-RPC request to Moonraker and await a reply.

        Args:
            method: Moonraker JSON-RPC method name.
            params: Optional method parameters.

        Returns:
            Result with the raw response in ``data["response"]``.

        Raises:
            RuntimeError: If there is no connected WebSocket client.
            TimeoutError: If the request times out.
        """
        if self.client is None or not self.client.is_connected():
            raise RuntimeError(_NOT_CONNECTED_MSG)
        request = self.mrr.gen_request(method, params)
        response = self.client.send_jsonrpc(request, timeout=5.0)
        return CommandResult(
            ok=True,
            message=f"Response received for '{method}'.",
            data={"response": response},
        )

    def notify_raw(self, method: str, params: dict[str, Any] | None) -> CommandResult:
        """Send a fire-and-forget JSON-RPC notification to Moonraker.

        Args:
            method: Moonraker JSON-RPC method name.
            params: Optional method parameters.

        Returns:
            Result confirming the notification was sent.

        Raises:
            RuntimeError: If there is no connected WebSocket client.
        """
        if self.client is None or not self.client.is_connected():
            raise RuntimeError(_NOT_CONNECTED_MSG)
        self.client.send_notification(method, params)
        return CommandResult(ok=True, message=f"Notification sent: {method}")

    def subscribe_raw(self, method: str) -> CommandResult:
        """Subscribe to a raw Moonraker notification method.

        Matching notifications are re-broadcast to every connected
        control-plane client as ``notify_raw_event``.

        Args:
            method: Notification method name to subscribe to.

        Returns:
            Result confirming the subscription.

        Raises:
            RuntimeError: If there is no WebSocket client.
        """
        if self.client is None:
            raise RuntimeError("WebSocket client not initialized.")
        if method not in self._raw_subscriptions:
            self._raw_subscriptions.add(method)
            self.client.register_handler(
                method, lambda params: self._forward_raw_notification(method, params)
            )
        return CommandResult(ok=True, message=f"Subscribed to '{method}'.")

    def _forward_raw_notification(self, method: str, params: Any) -> None:  # ruff:ignore[any-type]
        """Re-broadcast a subscribed raw Moonraker notification.

        Args:
            method: The notification method that fired.
            params: The notification's raw params.
        """
        if self._broadcast_callback is not None:
            self._broadcast_callback(
                "notify_raw_event", {"method": method, "params": params}
            )

    def unsubscribe_raw(self, method: str) -> CommandResult:
        """Unsubscribe from a raw Moonraker notification method.

        Args:
            method: Notification method name to unsubscribe from.

        Returns:
            Result describing whether a subscription was actually removed.

        Raises:
            RuntimeError: If there is no WebSocket client.
        """
        if self.client is None:
            raise RuntimeError("WebSocket client not initialized.")
        if method in self._raw_subscriptions:
            self.client.unregister_handler(method)
            self._raw_subscriptions.discard(method)
            return CommandResult(ok=True, message=f"Unsubscribed from '{method}'.")
        return CommandResult(
            ok=False, message=f"Not currently subscribed to '{method}'."
        )

    def read_message(self) -> CommandResult:
        """Pop and return the next message from the WebSocket queue.

        Returns:
            Result with the message in ``data``, or an ``ok=False`` result
            if the queue is empty.

        Raises:
            RuntimeError: If there is no WebSocket client.
        """
        if self.client is None:
            raise RuntimeError("WebSocket client not initialized.")
        message = self.client.pop_message()
        if message is None:
            return CommandResult(ok=False, message="No messages in queue.")
        return CommandResult(
            ok=True,
            message="Message read.",
            data={
                "type": message.type.value,
                "message_data": message.data,
                "remaining": len(self.client),
            },
        )

    def read_all_messages(self) -> CommandResult:
        """Drain and return every message from the WebSocket queue.

        Returns:
            Result with the messages in ``data["messages"]``.

        Raises:
            RuntimeError: If there is no WebSocket client.
        """
        if self.client is None:
            raise RuntimeError("WebSocket client not initialized.")
        messages = self.client.get_queued_messages()
        return CommandResult(
            ok=True,
            message=f"{len(messages)} message(s).",
            data={
                "messages": [
                    {"type": m.type.value, "message_data": m.data} for m in messages
                ]
            },
        )

    def clear_message_queue(self) -> CommandResult:
        """Discard all messages from the WebSocket queue.

        Returns:
            Result describing how many messages were cleared.

        Raises:
            RuntimeError: If there is no WebSocket client.
        """
        if self.client is None:
            raise RuntimeError("WebSocket client not initialized.")
        count = self.client.clear_queue()
        return CommandResult(
            ok=True, message=f"Cleared {count} message(s).", data={"cleared": count}
        )

    def reconnect_websocket(self) -> CommandResult:
        """Reconnect the WebSocket and restore notification handlers.

        Closes the current connection, opens a new one to the same URI,
        and re-registers all previously registered notification handlers
        (client-side only -- server-side subscriptions like
        ``printer.objects.subscribe`` are not re-sent).

        Returns:
            Result describing whether reconnection succeeded.

        Raises:
            RuntimeError: If there is no WebSocket client.
        """
        if self.client is None:
            raise RuntimeError("WebSocket client not initialized.")
        existing_handlers = self.client.handlers
        self.client.stop()

        new_client = WebSocketClient(self.uri)
        for method, callback in existing_handlers.items():
            new_client.register_handler(method, callback)
        new_client.start()

        if new_client.wait_for_connection(timeout=10):
            self.client = new_client
            if self.moonraker_state is not None:
                self.moonraker_state.client = new_client
            return CommandResult(
                ok=True,
                message="WebSocket reconnected.",
                data={"handlers_restored": len(existing_handlers)},
            )
        return CommandResult(ok=False, message="Failed to reconnect.")

    # ==================== Reporting (read-only) ====================
    #
    # Migrated off `ConfigurationCommands`' `ls`/`list_liquids` in Phase 4
    # (see CLAUDE.md) -- these return structured data rather than a
    # `rich.table.Table`; presentation (table rendering) is each driving
    # adapter's job (see `cli/report_tables.py`, shared by
    # `TriccaAutoPipetteShell` and `RemoteTapShell`).

    def list_locations(self) -> CommandResult:
        """List all defined locations (coordinates and plates).

        Returns:
            Result with ``data["locations"]``: a list of dicts with
            ``name``/``type``/``x``/``y``/``z``/``details`` keys.
        """
        loc_mgr = self._autopipette.location_manager
        rows: list[dict[str, Any]] = []
        for name in sorted(loc_mgr.get_all_names()):
            location = loc_mgr.locations[name]
            if isinstance(location, Plate):
                origin = location.wells[0].coor if location.wells else None
                rows.append({
                    "name": name,
                    "type": location.__class__.__name__,
                    "x": origin.x if origin else None,
                    "y": origin.y if origin else None,
                    "z": origin.z if origin else None,
                    "details": (
                        f"{location.num_row}x{location.num_col} "
                        f"[{location.current_row},{location.current_col}]"
                    ),
                })
            else:
                rows.append({
                    "name": name,
                    "type": "Coordinate",
                    "x": location.x,
                    "y": location.y,
                    "z": location.z,
                    "details": "",
                })
        return CommandResult(
            ok=bool(rows),
            message=f"{len(rows)} location(s)." if rows else "No locations defined.",
            data={"locations": rows},
        )

    def list_plates(self) -> CommandResult:
        """List all defined plates.

        Returns:
            Result with ``data["plates"]``: a list of dicts with
            ``name``/``type``/``dimensions``/``current``/``wells`` keys.
        """
        loc_mgr = self._autopipette.location_manager
        rows: list[dict[str, Any]] = []
        for name in sorted(loc_mgr.get_plate_names()):
            plate = loc_mgr.locations[name]
            if not isinstance(plate, Plate):
                continue
            rows.append({
                "name": name,
                "type": plate.__class__.__name__,
                "dimensions": f"{plate.num_row}x{plate.num_col}",
                "current": f"{plate.current_row},{plate.current_col}",
                "wells": plate.num_row * plate.num_col,
            })
        return CommandResult(
            ok=bool(rows),
            message=f"{len(rows)} plate(s)." if rows else "No plates defined.",
            data={"plates": rows},
        )

    def list_liquids(self) -> CommandResult:
        """List all loaded liquid profiles.

        Returns:
            Result with ``data["liquids"]`` (list of dicts with
            ``name``/``active``/``viscosity_cP``/``has_custom_speed``/
            ``prewet_cycles``/``air_gap`` keys) and ``data["active_liquid"]``.
        """
        liquids = self._autopipette.system_config.liquids
        active = self._autopipette.active_liquid
        rows = [
            {
                "name": name,
                "active": name == active,
                "viscosity_cP": liquid.viscosity_cP,
                "has_custom_speed": bool(liquid.speed_aspirate),
                "prewet_cycles": liquid.prewet_cycles or 0,
                "pre_air_gap_ul": liquid.pre_air_gap_ul,
                "post_air_gap_ul": liquid.post_air_gap_ul,
            }
            for name, liquid in sorted(liquids.items())
        ]
        message = (
            f"{len(rows)} liquid profile(s)." if rows else "No liquid profiles loaded."
        )
        return CommandResult(
            ok=bool(rows),
            message=message,
            data={"liquids": rows, "active_liquid": active},
        )

    def system_summary(self) -> CommandResult:
        """Summarize the loaded system configuration.

        Returns:
            Result with a flat ``data`` dict of system/pipette/gantry/
            network settings.
        """
        ap = self._autopipette
        config = ap.system_config
        data = {
            "system_name": config.system_name,
            "version": config.version,
            "pipette_model": ap.pipette_model.name,
            "pipette_design": ap.pipette_model.design_type,
            "max_volume_ul": ap.syringe.max_volume_ul,
            "active_liquid": ap.active_liquid,
            "gantry_speed_xy": ap.gantry.speed_xy,
            "gantry_speed_z": ap.gantry.speed_z,
            "gantry_accel_max": ap.gantry.accel_max,
            "hostname": config.network.get("hostname"),
            "port": config.network.get("port"),
        }
        return CommandResult(ok=True, message="System configuration.", data=data)

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
            if not proto_path.exists() or not proto_path.is_file():
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
            time, if it pauses at a breakpoint) so other structured
            (``movement.*``/etc.) requests from other clients can't
            interleave G-code generation with this run (see
            :meth:`dispatch`). ``cancel_run``/``pause_run``/``resume_run``
            deliberately bypass this lock — see their docstrings.

            Does not set ``self._current`` to "done" on success: real
            completion is detected later, asynchronously, via Moonraker's
            ``print_stats`` transition (see ``_apply_print_state_change``),
            not by this method returning -- ``upload_and_execute_gcode``
            only starts the print job.
        """
        async with self._lock:
            try:
                await asyncio.to_thread(self._run_protocol_sync, filename)
            except ProtocolAbortedError as exc:
                self._current = RunStatus(
                    status="error", message=str(exc), run_id=run_id, filename=filename
                )
                self._broadcast_status()
            except Exception as exc:
                self._current = RunStatus(
                    status="error",
                    message=f"Protocol error: {exc}",
                    run_id=run_id,
                    filename=filename,
                )
                self._broadcast_status()

    def _run_protocol_sync(self, filename: str) -> None:
        """Synchronous half of :meth:`_run_protocol`; runs in a worker thread.

        Replaces the old ``_execute_line_sync(f"run {filename}")`` (text
        dispatch through cmd2's ``runcmds_plus_hooks``) with a real per-line
        loop over :data:`_LINE_DISPATCH`, calling each line's typed
        ``AutoPipetteService`` method directly. This structurally removes
        two bug classes at once: there's no longer a filename to
        shell-requote (``shlex.quote`` is gone -- the path is just used
        directly, not re-parsed as command text), and a raised exception
        (including :class:`ProtocolAbortedError` for an aborted breakpoint)
        is the one unambiguous "this line failed" signal, rather than
        inferring it from cmd2's overloaded ``bool`` return value.

        Args:
            filename: Bare filename under ``protocols/``.

        Raises:
            ValueError: If the file can't be decoded as UTF-8.
            ProtocolAbortedError: If a ``break`` line's breakpoint is
                answered "abort".
            Exception: Whatever a dispatched line's service method itself
                raises (e.g. ``NotALocationError``, a not-homed
                ``RuntimeError``) -- propagates uncaught, aborting the rest
                of the protocol.
        """
        proto_path = DefaultPaths.DIR_PROTOCOL / filename
        try:
            lines = proto_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"Error reading protocol file (encoding issue): {exc}"
            ) from exc

        commands = [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
        if not commands:
            return

        gcode_manager = self.gcode_manager
        try:
            with gcode_manager.batch_mode():
                for line in commands:
                    self._dispatch_protocol_line(line)

            gcode_buffer = gcode_manager.get_buffer()
            if not gcode_buffer:
                return

            # Output filename is always a flat .gcode file regardless of
            # any subdirectory in the input path -- intentional (matches
            # the interactive shell's do_run).
            output_filename = Path(filename).with_suffix(".gcode").name
            file_path = gcode_manager.write_gcode_file(
                gcode_buffer, output_filename, append_header=True
            )
            if self.client is None:
                # See output_gcode's docstring: no client at all (e.g.
                # `tapd --no-connect`) is a graceful no-op, not a hard
                # failure -- the G-code file is still written to disk.
                logger.error("Cannot upload G-code: no WebSocket client configured.")
                return
            self.upload_and_execute_gcode(output_filename, file_path, delete_file=True)
        finally:
            gcode_manager.clear_buffer()

    def _dispatch_protocol_line(self, line: str) -> CommandResult:
        """Dispatch one protocol-file line to its typed service method.

        ``break`` is special-cased: it isn't a real ``AutoPipetteService``
        method, it calls :meth:`request_breakpoint` directly (no cmd2
        involved on this path at all, nor ever was). A line starting with
        ``;`` is treated as a no-op comment -- cmd2 used to treat ``;`` as a
        default statement terminator, so ad hoc ``; some note`` lines in
        some real committed protocol files parsed as an empty statement
        rather than an error; that tolerance is preserved explicitly here
        now that cmd2 itself is gone. A handful of commands that take a
        single bare string argument (``switch_liquid``, ``load_liquid``,
        ``save_locations``) are looked up in :data:`_STR_ARG_DISPATCH`
        instead of :data:`_LINE_DISPATCH`, since they don't have an argparse
        parser/``*Args`` dataclass pair. (``load_locations`` used to be one
        of them; it moved to :data:`_LINE_DISPATCH` when it gained
        ``--replace``.) Any
        other command name not found in either table -- a typo, or a
        genuinely nonexistent command -- is reported as an ``ok=False``
        result rather than raised, preserving the tolerant (error-but-
        don't-abort) behavior this had even before migration Phase 4.

        Args:
            line: One non-blank, non-comment line from a protocol file.

        Returns:
            The command's result. The run loop only cares whether this
            raised, but callers (e.g. tests) can still inspect it.

        Raises:
            ProtocolAbortedError: If ``line`` is ``break`` and the operator
                (or a remote client) chose to abort.
            ValueError: If the line can't be tokenized, or a recognized
                command's arguments fail to parse.
            Exception: Whatever the underlying service method raises.
        """
        if line.strip().startswith(";"):
            return CommandResult(ok=True, message="")

        try:
            argv = shlex.split(line)
        except ValueError as exc:
            raise ValueError(f"Could not parse line: {line!r}") from exc
        if not argv:
            return CommandResult(ok=True, message="")

        command_name, rest = argv[0], argv[1:]

        if command_name == "break":
            if not self.request_breakpoint():
                raise ProtocolAbortedError("Protocol aborted at breakpoint.")
            return CommandResult(ok=True, message="Continuing after breakpoint.")

        str_arg_method = _STR_ARG_DISPATCH.get(command_name)
        if str_arg_method is not None:
            if rest:
                arg = rest[0]
            elif command_name == "save_locations":
                arg = "custom_locations.json"
            else:
                raise ValueError(f"'{command_name}' requires an argument: {line!r}")
            return str_arg_method(self, arg)

        spec = _LINE_DISPATCH.get(command_name)
        if spec is None:
            logger.warning("Unknown command in protocol file: %r", line)
            return CommandResult(ok=False, message=f"Unknown command: {command_name!r}")

        if spec.parser is None or spec.args_cls is None:
            return spec.method(self)

        try:
            namespace = spec.parser.parse_args(rest)
        except SystemExit as exc:
            raise ValueError(
                f"Invalid arguments for '{command_name}': {line!r}"
            ) from exc
        return spec.method(self, args_from_namespace(spec.args_cls, namespace))

    def run_protocol_blocking(self, filename: str) -> CommandResult:
        """Run a protocol file synchronously, blocking until it completes.

        For standalone/local-scripting use (``TriccaAutoPipetteShell``,
        which has no asyncio event loop to run :meth:`start_run`'s
        background-task machinery on). The daemon uses :meth:`start_run`
        instead, so a control-plane ``run.start`` call returns immediately.

        Args:
            filename: Bare filename under ``protocols/``.

        Returns:
            Result describing the completed run.

        Raises:
            FileNotFoundError: If the protocol file does not exist.
            ProtocolAbortedError: If a ``break`` line's breakpoint is
                answered "abort".
            Exception: Whatever a dispatched line's service method raises.
        """
        proto_path = DefaultPaths.DIR_PROTOCOL / filename
        if not proto_path.exists() or not proto_path.is_file():
            raise FileNotFoundError(f"Protocol not found: {filename}")
        self._run_protocol_sync(filename)
        return CommandResult(
            ok=True, message=f"Protocol '{filename}' executed successfully."
        )

    def emergency_stop(self) -> CommandResult:
        """Send an emergency stop to the pipette.

        Returns:
            Result confirming the stop was sent.

        Raises:
            RuntimeError: If there is no connected WebSocket client.
        """
        self._send_moonraker_control(self.mrr.printer_emergency_stop())
        return CommandResult(
            ok=True,
            message="Emergency stop sent. Re-home the pipette before continuing.",
        )

    def send_pause(self) -> CommandResult:
        """Pause the current print job on Moonraker.

        Returns:
            Result confirming the pause request was sent.

        Raises:
            RuntimeError: If there is no connected WebSocket client.
        """
        self._send_moonraker_control(self.mrr.printer_print_pause())
        return CommandResult(ok=True, message="Protocol paused.")

    def send_resume(self) -> CommandResult:
        """Resume the current print job on Moonraker.

        Returns:
            Result confirming the resume request was sent.

        Raises:
            RuntimeError: If there is no connected WebSocket client.
        """
        self._send_moonraker_control(self.mrr.printer_print_resume())
        return CommandResult(ok=True, message="Protocol resumed.")

    def send_cancel(self) -> CommandResult:
        """Cancel the current print job on Moonraker.

        Returns:
            Result confirming the cancel request was sent.

        Raises:
            RuntimeError: If there is no connected WebSocket client.
        """
        self._send_moonraker_control(self.mrr.printer_print_cancel())
        return CommandResult(ok=True, message="Protocol canceled.")

    def _send_moonraker_control(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a print-control JSON-RPC request to Moonraker.

        Args:
            request: JSON-RPC request dict, e.g. from
                ``MoonrakerRequests.printer_print_pause()``.

        Returns:
            The raw JSON-RPC response.

        Raises:
            RuntimeError: If there is no connected WebSocket client.
        """
        if self.client is None or not self.client.is_connected():
            raise RuntimeError(_NOT_CONNECTED_MSG)
        return self.client.send_jsonrpc(request)

    async def cancel_run(self) -> RunStatus:
        """Cancel the active run.

        Deliberately bypasses ``self._lock``: that lock can be held for a
        long time by an in-progress run (including one paused at a
        breakpoint), but :meth:`send_cancel` only sends a Moonraker control
        RPC — it never touches the G-code buffer or ``AutoPipette`` domain
        state — so it's safe to run concurrently, and it must be able to
        interrupt a run that's stuck.
        """
        await asyncio.to_thread(self.send_cancel)
        return self._current

    async def pause_run(self) -> RunStatus:
        """Pause the active run.

        See :meth:`cancel_run` for why this bypasses ``self._lock``.
        """
        await asyncio.to_thread(self.send_pause)
        return self._current

    async def resume_run(self) -> RunStatus:
        """Resume the active run.

        See :meth:`cancel_run` for why this bypasses ``self._lock``.
        """
        await asyncio.to_thread(self.send_resume)
        return self._current

    async def stop_run(self) -> RunStatus:
        """Send an emergency stop, interrupting the active run if any.

        See :meth:`cancel_run` for why this bypasses ``self._lock``.
        """
        await asyncio.to_thread(self.emergency_stop)
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
        """Pause for operator confirmation, called synchronously for a `break` line.

        Called directly by `_dispatch_protocol_line`, itself running on the
        worker thread `start_run`/`_run_protocol` dispatch onto via
        `asyncio.to_thread`, so blocking here with a plain `threading.Event`
        only blocks that worker thread — the daemon's event loop (and thus
        `confirm_breakpoint`, which resolves the event) keeps running
        normally.

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
        connected = self.client is not None and self.client.is_connected()
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


@dataclass(frozen=True)
class _LineCommand:
    """One entry in the protocol-file line dispatch table.

    Attributes:
        parser: Parser for this command's arguments, or None for a
            zero-argument command (e.g. ``next_tip``).
        args_cls: The ``*Args`` dataclass ``parser`` produces, or None to
            match ``parser``.
        method: The corresponding *unbound* ``AutoPipetteService`` method
            (``AutoPipetteService.move``, not a bound instance method) --
            called as ``method(service_instance, args)`` (or
            ``method(service_instance)`` when ``args_cls`` is None).
    """

    parser: Cmd2ArgumentParser | None
    args_cls: type | None
    method: Callable[..., CommandResult]


#: Maps a protocol-file command's bare name (e.g. "move", not "movement.move")
#: to how to parse and dispatch it -- built once at import time, directly
#: from the same parsers/dataclasses/methods Phase 1 already wired into
#: ``ControlServer``/``RemoteTapShell``, so there's one source of truth for
#: "command name -> parser -> service method", not three. Deliberately
#: defined at module scope, after the class body, since it references
#: ``AutoPipetteService``'s own methods as plain (unbound) functions.
#:
#: Single-bare-string-argument commands (no argparse parser/``*Args``
#: dataclass) go in :data:`_STR_ARG_DISPATCH` instead. ``break`` is handled
#: specially in ``_dispatch_protocol_line`` rather than listed in either
#: table, since it isn't an ``AutoPipetteService`` method at all. Diagnostic
#: commands (``ws_status``, ``ping_moonraker``, ``send_raw``, etc.) and
#: reporting commands (``list_locations``, ``list_liquids``, etc.) are
#: deliberately not protocol-file-dispatchable at all -- there's no
#: sensible use for them mid-protocol-replay, matching their behavior
#: before migration Phase 4.
_LINE_DISPATCH: dict[str, _LineCommand] = {
    "init": _LineCommand(None, None, AutoPipetteService.init),
    "home": _LineCommand(TAPCmdParsers.parser_home, HomeArgs, AutoPipetteService.home),
    "move": _LineCommand(TAPCmdParsers.parser_move, MoveArgs, AutoPipetteService.move),
    "move_loc": _LineCommand(
        TAPCmdParsers.parser_move_loc, MoveLocArgs, AutoPipetteService.move_loc
    ),
    "move_rel": _LineCommand(
        TAPCmdParsers.parser_move_rel, MoveRelArgs, AutoPipetteService.move_rel
    ),
    "aspirate": _LineCommand(
        TAPCmdParsers.parser_aspirate, AspirateArgs, AutoPipetteService.aspirate
    ),
    "dispense": _LineCommand(
        TAPCmdParsers.parser_dispense, DispenseArgs, AutoPipetteService.dispense
    ),
    "pipette": _LineCommand(
        TAPCmdParsers.parser_pipette, PipetteArgs, AutoPipetteService.transfer
    ),
    "next_tip": _LineCommand(None, None, AutoPipetteService.next_tip),
    "eject_tip": _LineCommand(None, None, AutoPipetteService.eject_tip),
    "dispose_tip": _LineCommand(None, None, AutoPipetteService.dispose_tip),
    "change_tip": _LineCommand(None, None, AutoPipetteService.change_tip),
    "set": _LineCommand(TAPCmdParsers.parser_set, SetArgs, AutoPipetteService.set),
    "coor": _LineCommand(TAPCmdParsers.parser_coor, CoorArgs, AutoPipetteService.coor),
    "plate": _LineCommand(
        TAPCmdParsers.parser_plate, PlateArgs, AutoPipetteService.plate
    ),
    "reset_plate": _LineCommand(
        TAPCmdParsers.parser_reset_plate, ResetPlateArgs, AutoPipetteService.reset_plate
    ),
    "reset_plates": _LineCommand(None, None, AutoPipetteService.reset_plates),
    "del_loc": _LineCommand(
        TAPCmdParsers.parser_del_loc, DelLocArgs, AutoPipetteService.del_loc
    ),
    "clear_locs": _LineCommand(None, None, AutoPipetteService.clear_locs),
    "load_locations": _LineCommand(
        TAPCmdParsers.parser_load_locations,
        LoadLocationsArgs,
        AutoPipetteService.load_locations,
    ),
    "unload_locations": _LineCommand(
        TAPCmdParsers.parser_unload_locations,
        UnloadLocationsArgs,
        AutoPipetteService.unload_locations,
    ),
    "reset_tips": _LineCommand(
        TAPCmdParsers.parser_reset_tips, ResetTipsArgs, AutoPipetteService.reset_tips
    ),
    "reset_tips_all": _LineCommand(None, None, AutoPipetteService.reset_tips_all),
    "set_tips": _LineCommand(
        TAPCmdParsers.parser_set_tips, SetTipsArgs, AutoPipetteService.set_tips
    ),
    "tips": _LineCommand(TAPCmdParsers.parser_tips, TipsArgs, AutoPipetteService.tips),
    "wait": _LineCommand(TAPCmdParsers.parser_wait, WaitArgs, AutoPipetteService.wait),
    "trigger": _LineCommand(
        TAPCmdParsers.parser_trigger, TriggerArgs, AutoPipetteService.trigger
    ),
    "gcode_print": _LineCommand(
        TAPCmdParsers.parser_gcode_print, GcodePrintArgs, AutoPipetteService.gcode_print
    ),
    "vol_to_steps": _LineCommand(
        TAPCmdParsers.parser_vol_to_steps,
        VolToStepsArgs,
        AutoPipetteService.vol_to_steps,
    ),
}

#: Protocol-file commands that take one bare positional string argument
#: (no argparse parser/``*Args`` dataclass) -- see :data:`_LINE_DISPATCH`'s
#: docstring for why this is a separate table.
_STR_ARG_DISPATCH: dict[str, Callable[[AutoPipetteService, str], CommandResult]] = {
    "switch_liquid": AutoPipetteService.switch_liquid,
    "load_liquid": AutoPipetteService.load_liquid,
    "save_locations": AutoPipetteService.save_locations,
}

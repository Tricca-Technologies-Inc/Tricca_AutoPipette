"""Thin interactive client shell that talks to the `tapd` control daemon.

This owns no `AutoPipette` and no *Moonraker-connected* `WebSocketClient`
of its own — it does own a `WebSocketClient` pointed at the daemon's
control plane, but all domain logic, config loading, and the actual
Moonraker connection live in the daemon's `AutoPipetteService` (see
`tricca_autopipette.daemon`). There is no `CommandSet` here (unlike the
standalone `TriccaAutoPipetteShell` this shell replaced with full parity —
see issue #39) and no `shell.exec` escape hatch either — every `do_*` is a
distinct, hand-written method with
a real docstring, thin enough to be a few lines: parse args (via
`@with_argparser`/a bare `Statement`), build a `ControlRequests` request,
and dispatch it through `_call_and_print`/`_send`. Commands were briefly
generated from a declarative table instead, but that made `help -v`'s
one-line summaries (and, for the handful of no-argument commands, `help
<cmd>` too) show a generic templated string rather than real text — cmd2
renders full detail from a command's `Cmd2ArgumentParser` description only
for `help <cmd>` on argparse-backed commands; every other help surface
reads the `do_*` function's own docstring directly. Hand-writing each
method costs a few dozen near-duplicate lines but keeps every command's
help genuinely useful, matching the hand-written commands (`do_run`,
`do_cancel`, ...) that were never generated in the first place. An
unrecognized command falls through to cmd2's own default "unknown
command" handling.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, cast

from cmd2 import Cmd, Statement, with_argparser

from tricca_autopipette.cli.report_tables import (
    build_calibration_table,
    build_endstops_table,
    build_liquids_table,
    build_locations_table,
    build_plates_table,
    build_system_table,
    build_tipbox_map,
)
from tricca_autopipette.commands.tap_cmd_parsers import (
    AspirateArgs,
    CoorArgs,
    DelLocArgs,
    DispenseArgs,
    GcodePrintArgs,
    HomeArgs,
    LoadLocationsArgs,
    LsArgs,
    MoveArgs,
    MoveLocArgs,
    MoveRelArgs,
    NotifyArgs,
    PipetteArgs,
    PlateArgs,
    ResetPlateArgs,
    ResetTipsArgs,
    SeeCalibrationArgs,
    SendArgs,
    SetArgs,
    SetTipsArgs,
    TAPCmdParsers,
    TipsArgs,
    TriggerArgs,
    UnloadLocationsArgs,
    UploadArgs,
    VolToStepsArgs,
    WaitArgs,
    args_from_namespace,
)
from tricca_autopipette.daemon.control_requests import ControlRequests
from tricca_autopipette.moonraker.websocket_client import WebSocketClient
from tricca_autopipette.resources.string_constants import TAP_CLR_BANNER

logger = logging.getLogger(__name__)

WEBSOCKET_TIMEOUT_SECONDS = 10


def _as_dict(value: Any) -> dict[str, Any]:  # ruff:ignore[any-type]
    """Narrow a loosely-typed JSON-RPC result/params value to a dict.

    Args:
        value: Value to narrow, typically a JSON-RPC ``result`` or
            notification ``params`` of otherwise unknown shape.

    Returns:
        ``value`` if it is a dict, otherwise an empty dict.
    """
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return {}


class RemoteTapShell(Cmd):
    """Interactive shell that proxies commands to a running `tapd` daemon.

    Attributes:
        control_uri: WebSocket URI of the daemon's control plane.
        requests: Pure-function builder for control-plane JSON-RPC requests.
        client: WebSocket client connected to the daemon's control plane.
    """

    def __init__(self, control_uri: str) -> None:
        """Initialize the remote shell.

        Args:
            control_uri: WebSocket URI of the daemon's control plane, e.g.
                "ws://127.0.0.1:8765/control".
        """
        super().__init__(allow_cli_args=False)
        self.intro = ""
        self.prompt = "tap >> "
        self.control_uri = control_uri
        self.requests = ControlRequests()
        self.client = WebSocketClient(control_uri)
        self.client.register_handler("notify_run_status", self._on_run_status)
        self.client.register_handler("notify_breakpoint", self._on_breakpoint)

    # ==================== lifecycle ====================

    def preloop(self) -> None:
        """Show the splash banner, then connect to the daemon's control plane."""
        self.poutput("\033c", end="")
        self.poutput(TAP_CLR_BANNER, markup=True)
        self.poutput(f"Connecting to tapd at {self.control_uri}...")
        self.client.start()
        if not self.client.wait_for_connection(timeout=WEBSOCKET_TIMEOUT_SECONDS):
            self.perror(
                "Failed to connect to tapd. Is the daemon running? "
                "(see `tapd`/systemd/tapd.service)"
            )
        else:
            self.poutput("Connected.")
            # One-time identity so the daemon's RPC log can attribute
            # subsequent calls on this connection to "tap" (issue #53) --
            # an audit-trail label, not access control, so a failure here
            # is logged rather than treated as fatal to the shell.
            try:
                self.client.send_jsonrpc(self.requests.identify("tap"))
            except RuntimeError:
                logger.warning("Failed to identify this connection to tapd.")
            self._print_pipette_status()

    def postloop(self) -> None:
        """Disconnect from the daemon's control plane on exit."""
        self.poutput("Disconnecting...")
        self.client.stop()

    # ==================== notification handlers ====================

    def _on_run_status(self, params: Any) -> None:  # ruff:ignore[any-type]
        """Show a live run-status update without disrupting the prompt.

        Args:
            params: `{"status", "message", "run_id", "filename"}` as sent by
                `AutoPipetteService._broadcast_status`.
        """
        notification = _as_dict(params)
        if not notification:
            return
        status = notification.get("status")
        message = notification.get("message", "")
        self.add_alert(msg=f"[run:{status}] {message}")

    def _on_breakpoint(self, params: Any) -> None:  # ruff:ignore[any-type]
        """Prompt the user to answer a pending breakpoint.

        Args:
            params: `{"run_id", "filename", "pending"}` as sent by
                `AutoPipetteService.request_breakpoint`/`confirm_breakpoint`.
        """
        notification = _as_dict(params)
        if notification.get("pending"):
            self.add_alert(
                msg="⏸ Protocol paused at a breakpoint. "
                "Type 'continue' or 'abort' to proceed."
            )

    # ==================== movement ====================

    def do_init(self, _: Statement) -> None:
        """Initialise the pipette: set coordinate system, speed, and home all motors.

        Runs once after connecting, before any other command. ``home all``
        is an alias for this.
        """
        self._call_and_print(self.requests.init())

    @with_argparser(TAPCmdParsers.parser_home)  # type: ignore[arg-type]
    def do_home(self, args: HomeArgs) -> None:
        """Home one or more motors on the pipette."""
        self._call_and_print(self.requests.home(args_from_namespace(HomeArgs, args)))

    @with_argparser(TAPCmdParsers.parser_move)  # type: ignore[arg-type]
    def do_move(self, args: MoveArgs) -> None:
        """Move to absolute XYZ coordinates."""
        self._call_and_print(self.requests.move(args_from_namespace(MoveArgs, args)))

    @with_argparser(TAPCmdParsers.parser_move_loc)  # type: ignore[arg-type]
    def do_move_loc(self, args: MoveLocArgs) -> None:
        """Move to a named location."""
        self._call_and_print(
            self.requests.move_loc(args_from_namespace(MoveLocArgs, args))
        )

    @with_argparser(TAPCmdParsers.parser_move_rel)  # type: ignore[arg-type]
    def do_move_rel(self, args: MoveRelArgs) -> None:
        """Move relative to the current position."""
        self._call_and_print(
            self.requests.move_rel(args_from_namespace(MoveRelArgs, args))
        )

    # ==================== pipette ====================

    @with_argparser(TAPCmdParsers.parser_aspirate)  # type: ignore[arg-type]
    def do_aspirate(self, args: AspirateArgs) -> None:
        """Aspirate liquid from a source location."""
        self._call_and_print(
            self.requests.aspirate(args_from_namespace(AspirateArgs, args))
        )

    @with_argparser(TAPCmdParsers.parser_dispense)  # type: ignore[arg-type]
    def do_dispense(self, args: DispenseArgs) -> None:
        """Dispense liquid to a destination location."""
        self._call_and_print(
            self.requests.dispense(args_from_namespace(DispenseArgs, args))
        )

    @with_argparser(TAPCmdParsers.parser_pipette)  # type: ignore[arg-type]
    def do_pipette(self, args: PipetteArgs) -> None:
        """Transfer liquid from source to destination."""
        self._call_and_print(
            self.requests.transfer(args_from_namespace(PipetteArgs, args))
        )

    def do_next_tip(self, _: Statement) -> None:
        """Pick up the next available tip from the tipbox."""
        self._call_and_print(self.requests.next_tip())

    def do_eject_tip(self, _: Statement) -> None:
        """Eject the current tip in place, without moving to waste.

        Use ``dispose_tip`` for normal tip disposal during a protocol.
        """
        self._call_and_print(self.requests.eject_tip())

    def do_dispose_tip(self, _: Statement) -> None:
        """Move to the waste container and eject the current tip."""
        self._call_and_print(self.requests.dispose_tip())

    def do_change_tip(self, _: Statement) -> None:
        """Dispose the current tip and pick up a fresh one."""
        self._call_and_print(self.requests.change_tip())

    # ==================== configuration & locations ====================

    @with_argparser(TAPCmdParsers.parser_set)  # type: ignore[arg-type]
    def do_set(self, args: SetArgs) -> None:
        """Set a configuration variable to a new value."""
        self._call_and_print(self.requests.set(args_from_namespace(SetArgs, args)))

    @with_argparser(TAPCmdParsers.parser_coor)  # type: ignore[arg-type]
    def do_coor(self, args: CoorArgs) -> None:
        """Define a named coordinate location."""
        self._call_and_print(self.requests.coor(args_from_namespace(CoorArgs, args)))

    @with_argparser(TAPCmdParsers.parser_plate)  # type: ignore[arg-type]
    def do_plate(self, args: PlateArgs) -> None:
        """Define a plate at a named location."""
        self._call_and_print(self.requests.plate(args_from_namespace(PlateArgs, args)))

    @with_argparser(TAPCmdParsers.parser_reset_plate)  # type: ignore[arg-type]
    def do_reset_plate(self, args: ResetPlateArgs) -> None:
        """Reset a plate's current position to the origin well."""
        self._call_and_print(
            self.requests.reset_plate(args_from_namespace(ResetPlateArgs, args))
        )

    def do_reset_plates(self, _: Statement) -> None:
        """Reset every plate's current position back to its origin well."""
        self._call_and_print(self.requests.reset_plates())

    @with_argparser(TAPCmdParsers.parser_del_loc)  # type: ignore[arg-type]
    def do_del_loc(self, args: DelLocArgs) -> None:
        """Delete a named location or plate."""
        self._call_and_print(
            self.requests.del_loc(args_from_namespace(DelLocArgs, args))
        )

    def do_clear_locs(self, _: Statement) -> None:
        """Delete all locations and plates.

        Cannot be undone without reloading from a file.
        """
        self._call_and_print(self.requests.clear_locs())

    def do_switch_liquid(self, statement: Statement) -> None:
        """Switch to a different liquid profile: switch_liquid <name>."""
        liquid_name = statement.arg_list[0] if statement.arg_list else None
        if not liquid_name:
            self.perror("Usage: switch_liquid <liquid_name>")
            return
        self._call_and_print(self.requests.switch_liquid(liquid_name))

    def do_load_liquid(self, statement: Statement) -> None:
        """Load a new liquid profile from a JSON file: load_liquid <filename>."""
        filename = statement.arg_list[0] if statement.arg_list else None
        if not filename:
            self.perror("Usage: load_liquid <filename.json>")
            return
        self._call_and_print(self.requests.load_liquid(filename))

    def do_save_locations(self, statement: Statement) -> None:
        """Save current locations to a JSON file: save_locations [filename]."""
        filename = (
            statement.arg_list[0] if statement.arg_list else "custom_locations.json"
        )
        self._call_and_print(self.requests.save_locations(filename))

    @with_argparser(TAPCmdParsers.parser_load_locations)  # type: ignore[arg-type]
    def do_load_locations(self, args: LoadLocationsArgs) -> None:
        """Load locations from a file, adding to the deck by default."""
        self._call_and_print(
            self.requests.load_locations(args_from_namespace(LoadLocationsArgs, args))
        )

    @with_argparser(TAPCmdParsers.parser_unload_locations)  # type: ignore[arg-type]
    def do_unload_locations(self, args: UnloadLocationsArgs) -> None:
        """Unload a single location from the deck by name."""
        self._call_and_print(
            self.requests.unload_locations(
                args_from_namespace(UnloadLocationsArgs, args)
            )
        )

    @with_argparser(TAPCmdParsers.parser_tips)  # type: ignore[arg-type]
    def do_tips(self, args: TipsArgs) -> None:
        """Show tip availability per tipbox, as an ASCII map."""
        response = self._send(self.requests.tips(args_from_namespace(TipsArgs, args)))
        data = self._result_data(response)
        if data is None:
            return

        boxes: list[dict[str, Any]] = data.get("boxes") or []
        if not boxes:
            self.poutput("No tipboxes are loaded.")
            return

        persisted: dict[str, Any] = data.get("persisted") or {}
        for box in boxes:
            self.poutput(build_tipbox_map(box, persisted.get(box["name"])))

    @with_argparser(TAPCmdParsers.parser_reset_tips)  # type: ignore[arg-type]
    def do_reset_tips(self, args: ResetTipsArgs) -> None:
        """Mark a tipbox as full, after physically reloading it."""
        self._call_and_print(
            self.requests.reset_tips(args_from_namespace(ResetTipsArgs, args))
        )

    def do_reset_tips_all(self, _: Statement) -> None:
        """Mark every loaded tipbox as full, after physically reloading them."""
        self._call_and_print(self.requests.reset_tips_all())

    @with_argparser(TAPCmdParsers.parser_set_tips)  # type: ignore[arg-type]
    def do_set_tips(self, args: SetTipsArgs) -> None:
        """Declare which tip positions of a box are consumed (or available)."""
        self._call_and_print(
            self.requests.set_tips(args_from_namespace(SetTipsArgs, args))
        )

    # ==================== protocol / run lifecycle ====================

    def do_run(self, arg: Statement) -> None:
        """Start a protocol run: run <filename>."""
        filename = arg.args.strip()
        if not filename:
            self.perror("Usage: run <filename>")
            return
        self._call_and_print(self.requests.run_start(filename))

    def do_run_status(self, _: Statement) -> None:
        """Report the active run's current status."""
        self._call_and_print(self.requests.run_status())

    def do_cancel(self, _: Statement) -> None:
        """Cancel the active run."""
        self._call_and_print(self.requests.run_cancel())

    def do_pause(self, _: Statement) -> None:
        """Pause the active run."""
        self._call_and_print(self.requests.run_pause())

    def do_resume(self, _: Statement) -> None:
        """Resume the active run."""
        self._call_and_print(self.requests.run_resume())

    def do_continue(self, _: Statement) -> None:
        """Confirm a pending breakpoint and continue the protocol."""
        self._confirm_breakpoint(proceed=True)

    def do_abort(self, _: Statement) -> None:
        """Confirm a pending breakpoint and abort the protocol."""
        self._confirm_breakpoint(proceed=False)

    def do_stop(self, _: Statement) -> None:
        """Send an emergency stop to the pipette."""
        self._call_and_print(self.requests.run_stop())

    def do_protocols(self, _: Statement) -> None:
        """List protocol files available to run."""
        response = self._send(self.requests.protocols_list())
        if response is None:
            return
        # {"protocols": [{"name": stem, "filename": name}, ...]} -- a plain
        # dict, not the CommandResult "data" envelope _result_data expects.
        protocols: list[dict[str, Any]] = _as_dict(response.get("result")).get(
            "protocols"
        ) or []
        if not protocols:
            self.poutput("No protocol files found.")
            return
        for protocol in protocols:
            self.poutput(str(_as_dict(protocol).get("filename", "")))

    def _confirm_breakpoint(self, *, proceed: bool) -> None:
        """Send a breakpoint confirmation to the daemon.

        Args:
            proceed: True to continue the protocol, False to abort it.
        """
        try:
            self.client.send_jsonrpc(self.requests.run_confirm_breakpoint(proceed))
        except RuntimeError as exc:
            self.perror(str(exc))
            return
        self.poutput("Continuing..." if proceed else "Aborting...")

    # ==================== utility ====================

    @with_argparser(TAPCmdParsers.parser_wait)  # type: ignore[arg-type]
    def do_wait(self, args: WaitArgs) -> None:
        """Insert a timed pause into the G-code output."""
        self._call_and_print(self.requests.wait(args_from_namespace(WaitArgs, args)))

    @with_argparser(TAPCmdParsers.parser_trigger)  # type: ignore[arg-type]
    def do_trigger(self, args: TriggerArgs) -> None:
        """Control auxiliary triggers (air, shake, aux).

        Stub: validates the channel/state and always reports "not yet
        implemented" -- see issue #16.
        """
        self._call_and_print(
            self.requests.trigger(args_from_namespace(TriggerArgs, args))
        )

    @with_argparser(TAPCmdParsers.parser_gcode_print)  # type: ignore[arg-type]
    def do_gcode_print(self, args: GcodePrintArgs) -> None:
        """Send a message to be displayed on the pipette screen."""
        self._call_and_print(
            self.requests.gcode_print(args_from_namespace(GcodePrintArgs, args))
        )

    def do_webcam(self, _: Statement) -> None:
        """Print the webcam stream URL for this pipette."""
        self._call_and_print(self.requests.webcam_url())

    @with_argparser(TAPCmdParsers.parser_vol_to_steps)  # type: ignore[arg-type]
    def do_vol_to_steps(self, args: VolToStepsArgs) -> None:
        """Convert a volume in μL to motor steps.

        The value is actually millimetres of plunger travel, not motor
        steps -- see issue #29.
        """
        self._call_and_print(
            self.requests.vol_to_steps(args_from_namespace(VolToStepsArgs, args))
        )

    def do_steps_to_vol(self, statement: Statement) -> None:
        """Convert a `vol_to_steps` value back to volume in μL.

        Usage: steps_to_vol <steps>

        The value is actually millimetres of plunger travel, not motor
        steps -- see issue #29.
        """
        arg = statement.arg_list[0] if statement.arg_list else ""
        if not arg.strip():
            self.perror("Usage: steps_to_vol <steps>")
            return
        try:
            steps = int(float(arg.strip()))
        except ValueError:
            self.perror(f"Invalid steps value: '{arg.strip()}'. Must be a number.")
            return
        self._call_and_print(self.requests.steps_to_vol(steps))

    # ==================== WebSocket / daemon diagnostics ====================

    def do_ws_status(self, _: Statement) -> None:
        """Show the daemon's own Moonraker connection status."""
        response = self._send(self.requests.ws_status())
        if response is None:
            return
        result = _as_dict(response.get("result"))
        data = _as_dict(result.get("data"))
        if "queued_messages" not in data:
            # No Moonraker client configured at all (`tapd --no-connect`) --
            # only the configured URI is known, not live connection details.
            self.poutput(result.get("message", ""))
            if data.get("uri"):
                self.poutput(f"Configured server: {data['uri']}")
            return
        self.poutput("Connected" if data.get("connected") else "Disconnected")
        self.poutput(f"Server: {data.get('uri')}")
        self.poutput(f"Queued messages: {data.get('queued_messages')}")
        self.poutput(f"Handlers: {', '.join(data.get('handlers') or []) or '(none)'}")
        self.poutput(f"Pending requests: {data.get('pending_requests')}")

    def do_ping(self, _: Statement) -> None:
        """Ping Moonraker directly and measure round-trip time."""
        self._call_and_print(self.requests.ws_ping())

    def do_daemon_ping(self, _: Statement) -> None:
        """Check daemon/Moonraker connectivity, without round-trip timing.

        A simpler health check than ``ping``, which pings Moonraker
        directly and measures round-trip time.
        """
        response = self._send(self.requests.daemon_ping())
        if response is None:
            return
        # {"connected_to_moonraker": bool} -- a plain dict, not the
        # CommandResult "data" envelope _result_data expects.
        connected = _as_dict(response.get("result")).get("connected_to_moonraker")
        self.poutput(
            "Connected to Moonraker" if connected else "Not connected to Moonraker"
        )

    def do_query_endstops(self, _: Statement) -> None:
        """Query live endstop trigger state from Klipper.

        Nearly identical to Klipper's own ``QUERY_ENDSTOPS``, but via
        Moonraker's structured ``printer.query_endstops.status`` RPC.
        Shows every endstop Klipper reports (each axis, and the pipette's
        ``MANUAL_STEPPER`` endstop), using Klipper's own "open"/"TRIGGERED"
        wording. Works before homing.
        """
        response = self._send(self.requests.ws_query_endstops())
        data = self._result_data(response)
        if data is None:
            return
        endstops: dict[str, str] = data.get("endstops") or {}
        if not endstops:
            self.poutput("No endstops reported.")
            return
        self.poutput(build_endstops_table(endstops))

    def do_clients(self, _: Statement) -> None:
        """List control-plane clients currently connected to the daemon."""
        response = self._send(self.requests.clients())
        if response is None:
            return
        clients: list[Any] = _as_dict(response.get("result")).get("clients") or []
        if not clients:
            self.poutput("(no clients connected)")
            return
        for client in clients:
            self.poutput(str(_as_dict(client).get("client_type", "unknown")))

    @with_argparser(TAPCmdParsers.parser_send)  # type: ignore[arg-type]
    def do_send(self, args: SendArgs) -> None:
        """Send a JSON-RPC request to Moonraker and await a response."""
        params = self._parse_json_params(args.params)
        if params is False:
            return
        response = self._send(self.requests.ws_send(args.method, params))
        if response is None:
            return
        data = _as_dict(_as_dict(response.get("result")).get("data"))
        self.poutput(json.dumps(data.get("response"), indent=2))

    @with_argparser(TAPCmdParsers.parser_notify)  # type: ignore[arg-type]
    def do_notify(self, args: NotifyArgs) -> None:
        """Send a fire-and-forget JSON-RPC notification to Moonraker."""
        params = self._parse_json_params(args.params)
        if params is False:
            return
        self._call_and_print(self.requests.ws_notify(args.method, params))

    def do_subscribe(self, arg: str) -> None:
        """Subscribe to a raw Moonraker notification method: subscribe <method>."""
        method = arg.strip()
        if not method:
            self.perror("Usage: subscribe <method>")
            return
        self._call_and_print(self.requests.ws_subscribe(method))

    def do_unsubscribe(self, arg: str) -> None:
        """Unsubscribe from a raw Moonraker notification method.

        Usage: unsubscribe <method>
        """
        method = arg.strip()
        if not method:
            self.perror("Usage: unsubscribe <method>")
            return
        self._call_and_print(self.requests.ws_unsubscribe(method))

    @with_argparser(TAPCmdParsers.parser_upload)  # type: ignore[arg-type]
    def do_upload(self, args: UploadArgs) -> None:
        """Upload a G-code file (local to the daemon's machine) to the pipette."""
        self._call_and_print(
            self.requests.ws_upload(args.file_name, str(args.file_path))
        )

    def do_read(self, _: Statement) -> None:
        """Read and display the next message from the WebSocket queue."""
        self._call_and_print(self.requests.ws_read())

    def do_read_all(self, _: Statement) -> None:
        """Read and display all messages from the WebSocket queue."""
        self._call_and_print(self.requests.ws_read_all())

    def do_clear_queue(self, _: Statement) -> None:
        """Discard all messages from the WebSocket queue."""
        self._call_and_print(self.requests.ws_clear_queue())

    def do_reconnect(self, _: Statement) -> None:
        """Reconnect the daemon's WebSocket connection to Moonraker."""
        self._call_and_print(self.requests.ws_reconnect())
        self._print_pipette_status()

    # ==================== reporting ====================

    @with_argparser(TAPCmdParsers.parser_ls)  # type: ignore[arg-type]
    def do_ls(self, args: LsArgs) -> None:
        """List configuration state by category: ls <locs|plates|liquids|system>."""
        var = args.var.lower()
        if var in ("locs", "locations"):
            response = self._send(self.requests.list_locations())
            data = self._result_data(response)
            if data is not None:
                rows: list[dict[str, Any]] = data.get("locations") or []
                self.poutput(
                    build_locations_table(rows) if rows else "No locations defined."
                )
        elif var == "plates":
            response = self._send(self.requests.list_plates())
            data = self._result_data(response)
            if data is not None:
                rows: list[dict[str, Any]] = data.get("plates") or []
                self.poutput(build_plates_table(rows) if rows else "No plates defined.")
        elif var == "liquids":
            self._print_liquids()
        elif var in ("system", "config"):
            response = self._send(self.requests.system_summary())
            data = self._result_data(response)
            if data is not None:
                self.poutput(build_system_table(data))
        else:
            self.perror(
                f"Unknown category '{var}'. Valid: locs, plates, liquids, system"
            )

    def do_list_liquids(self, _: Statement) -> None:
        """List all loaded liquid profiles."""
        self._print_liquids()

    @with_argparser(TAPCmdParsers.parser_see_calibration)  # type: ignore[arg-type]
    def do_see_calibration(self, args: SeeCalibrationArgs) -> None:
        """Show a liquid's calibration curve and its fitted line.

        Usage: see_calibration [liquid]

        Displays the (volume, plunger-travel) points a liquid's motion is
        actually fit from -- the liquid's own override if it has one,
        otherwise the pipette's base curve -- plus the resulting linear
        equation ``travel_mm = A * volume_ul + B``.
        """
        response = self._send(
            self.requests.see_calibration(args_from_namespace(SeeCalibrationArgs, args))
        )
        if response is None:
            return
        result = _as_dict(response.get("result"))
        data = _as_dict(result.get("data"))

        volumes_ul: list[float] = data.get("volumes_ul") or []
        travel_mm: list[float] = data.get("travel_mm") or []
        if not volumes_ul:
            self.poutput(result.get("message", ""))
            return

        self.poutput(f"{data.get('liquid')} ({data.get('source')})")
        self.poutput(build_calibration_table(volumes_ul, travel_mm))
        self.poutput(
            f"travel_mm = {data.get('slope'):.6f} * volume_ul "
            f"+ {data.get('intercept'):.6f}"
        )

    def _print_liquids(self) -> None:
        """Fetch and render the liquid-profile table (shared by `ls liquids`)."""
        response = self._send(self.requests.list_liquids())
        data = self._result_data(response)
        if data is None:
            return
        rows: list[dict[str, Any]] = data.get("liquids") or []
        if not rows:
            self.poutput("No liquid profiles loaded.")
            return
        self.poutput(build_liquids_table(rows))
        self.poutput(f"Active liquid: {data.get('active_liquid')}")

    # ==================== shared helpers ====================

    def _result_data(self, response: dict[str, Any] | None) -> dict[str, Any] | None:
        """Extract a `CommandResult`-shaped response's `data` dict, if any.

        Args:
            response: Raw JSON-RPC response, or None if the request failed
                (already reported to the user by `_send`).

        Returns:
            The `data` dict, or None if `response` was None.
        """
        if response is None:
            return None
        return _as_dict(_as_dict(response.get("result")).get("data"))

    def _parse_json_params(
        self, raw: str | None
    ) -> dict[str, Any] | Literal[False] | None:
        """Parse an optional JSON params string, reporting errors to the user.

        Args:
            raw: The raw JSON string (or None).

        Returns:
            The parsed dict, None if `raw` was empty/None, or False if
            parsing failed (error already printed).
        """
        if not raw or not raw.strip():
            return None
        try:
            return cast("dict[str, Any]", json.loads(raw.strip()))
        except json.JSONDecodeError as exc:
            self.perror(f"Invalid JSON in params: {exc}")
            return False

    def _call_and_print(self, request: dict[str, Any]) -> None:
        """Send a control-plane request and print its result.

        Args:
            request: JSON-RPC request dict, as built by `self.requests`.
        """
        response = self._send(request)
        if response is None:
            return
        raw_result: Any = response.get("result")
        result = _as_dict(raw_result)
        if "status" in result:
            # run.*-shaped reply: {"status", "message", "run_id", "filename"}.
            self.poutput(f"{result.get('status')}: {result.get('message', '')}")
        elif "message" in result:
            # CommandResult-shaped reply: {"ok", "message", "data"}, as
            # returned by the structured movement.*/etc. methods.
            self.poutput(str(result["message"]))
        else:
            self.poutput(str(raw_result))

    def _send(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Send a control-plane request, reporting a `RuntimeError` if it fails.

        Args:
            request: JSON-RPC request dict.

        Returns:
            The raw JSON-RPC response, or None if sending failed.
        """
        try:
            return self.client.send_jsonrpc(request)
        except RuntimeError as exc:
            self.perror(str(exc))
            return None

    def _print_pipette_status(self) -> None:
        """Print the pipette's configured Moonraker host, below the splash.

        Fetched via `ws.status` rather than known locally -- unlike the old
        pre-daemon shell, `tap` has no Moonraker connection of its own, only
        `tapd` does. Silently does nothing if the request fails (mirrors the
        `identify` call in `preloop`): this is a startup/status nicety, not
        something worth erroring the shell over.
        """
        try:
            response = self.client.send_jsonrpc(self.requests.ws_status())
        except RuntimeError:
            return
        data = _as_dict(_as_dict(response.get("result")).get("data"))
        uri = data.get("uri")
        if not uri:
            return
        # "ws://192.168.1.50/websocket" -> "192.168.1.50".
        host = str(uri).removeprefix("ws://").split("/", 1)[0]
        if data.get("connected"):
            self.poutput(f"[green]Pipette: {host}[/green]", markup=True)
        else:
            self.poutput(
                f"[yellow]Pipette: {host} (not connected)[/yellow]", markup=True
            )

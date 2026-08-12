"""Thin interactive client shell that talks to the `tapd` control daemon.

Unlike `TriccaAutoPipetteShell`, this owns no `AutoPipette` and no
*Moonraker-connected* `WebSocketClient` of its own — it does own a
`WebSocketClient` pointed at the daemon's control plane, but all domain
logic, config loading, and the actual Moonraker connection live in the
daemon's `AutoPipetteService` (see `tricca_autopipette.daemon`). Every
command has a structured control-plane method and a thin `do_*` wrapper
(either hand-written or generated from `_STRUCTURED_COMMANDS`) -- there is
no `shell.exec` escape hatch left to fall back to; an unrecognized command
falls through to cmd2's own default "unknown command" handling.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Literal, cast

from cmd2 import Cmd, Statement, with_argparser

from tricca_autopipette.cli.report_tables import (
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
        """Connect to the daemon's control plane before entering the loop."""
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

    # ==================== explicit run commands ====================

    def do_run(self, arg: Statement) -> None:
        """Start a protocol run: run <filename>."""
        filename = arg.args.strip()
        if not filename:
            self.perror("Usage: run <filename>")
            return
        self._call_and_print(self.requests.run_start(filename))

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

    def do_webcam(self, _: Statement) -> None:
        """Print the webcam stream URL for this pipette."""
        self._call_and_print(self.requests.webcam_url())

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

    def do_stop(self, _: Statement) -> None:
        """Send an emergency stop to the pipette."""
        self._call_and_print(self.requests.run_stop())

    # ==================== WebSocket diagnostics ====================

    def do_ws_status(self, _: Statement) -> None:
        """Show the daemon's own Moonraker connection status."""
        response = self._send(self.requests.ws_status())
        if response is None:
            return
        data = _as_dict(_as_dict(response.get("result")).get("data"))
        if not data:
            self.poutput(_as_dict(response.get("result")).get("message", ""))
            return
        self.poutput("Connected" if data.get("connected") else "Disconnected")
        self.poutput(f"Server: {data.get('uri')}")
        self.poutput(f"Queued messages: {data.get('queued_messages')}")
        self.poutput(f"Handlers: {', '.join(data.get('handlers') or []) or '(none)'}")
        self.poutput(f"Pending requests: {data.get('pending_requests')}")

    def do_ping(self, _: Statement) -> None:
        """Ping Moonraker directly and measure round-trip time."""
        self._call_and_print(self.requests.ws_ping())

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


# ==================== structured commands (generated do_* methods) ====================
#
# Declarative table of (name, parser, request-builder) driving a generated
# do_<name> method each, rather than ~25 hand-written near-duplicates, as
# landed when command groups were migrated off `shell.exec`. `parser` is
# None for commands that take no arguments; `build_request` takes the
# parsed argparse Namespace (or the raw Statement, for no-arg commands) and
# returns the JSON-RPC request
# dict to send. Namespace-to-dataclass conversion is `args_from_namespace`,
# shared with `daemon/service.py`'s protocol-file dispatch (see that
# module) so there's one copy of this logic, not two.

_STRUCTURED_COMMANDS: list[
    tuple[str, Any, Callable[[ControlRequests, Any], dict[str, Any]]]
] = [
    ("init", None, lambda r, _args: r.init()),
    (
        "home",
        TAPCmdParsers.parser_home,
        lambda r, a: r.home(args_from_namespace(HomeArgs, a)),
    ),
    (
        "move",
        TAPCmdParsers.parser_move,
        lambda r, a: r.move(args_from_namespace(MoveArgs, a)),
    ),
    (
        "move_loc",
        TAPCmdParsers.parser_move_loc,
        lambda r, a: r.move_loc(args_from_namespace(MoveLocArgs, a)),
    ),
    (
        "move_rel",
        TAPCmdParsers.parser_move_rel,
        lambda r, a: r.move_rel(args_from_namespace(MoveRelArgs, a)),
    ),
    (
        "aspirate",
        TAPCmdParsers.parser_aspirate,
        lambda r, a: r.aspirate(args_from_namespace(AspirateArgs, a)),
    ),
    (
        "dispense",
        TAPCmdParsers.parser_dispense,
        lambda r, a: r.dispense(args_from_namespace(DispenseArgs, a)),
    ),
    (
        "pipette",
        TAPCmdParsers.parser_pipette,
        lambda r, a: r.transfer(args_from_namespace(PipetteArgs, a)),
    ),
    ("next_tip", None, lambda r, _args: r.next_tip()),
    ("eject_tip", None, lambda r, _args: r.eject_tip()),
    ("dispose_tip", None, lambda r, _args: r.dispose_tip()),
    ("change_tip", None, lambda r, _args: r.change_tip()),
    (
        "set",
        TAPCmdParsers.parser_set,
        lambda r, a: r.set(args_from_namespace(SetArgs, a)),
    ),
    (
        "coor",
        TAPCmdParsers.parser_coor,
        lambda r, a: r.coor(args_from_namespace(CoorArgs, a)),
    ),
    (
        "plate",
        TAPCmdParsers.parser_plate,
        lambda r, a: r.plate(args_from_namespace(PlateArgs, a)),
    ),
    (
        "reset_plate",
        TAPCmdParsers.parser_reset_plate,
        lambda r, a: r.reset_plate(args_from_namespace(ResetPlateArgs, a)),
    ),
    ("reset_plates", None, lambda r, _args: r.reset_plates()),
    (
        "del_loc",
        TAPCmdParsers.parser_del_loc,
        lambda r, a: r.del_loc(args_from_namespace(DelLocArgs, a)),
    ),
    ("clear_locs", None, lambda r, _args: r.clear_locs()),
    (
        "load_locations",
        TAPCmdParsers.parser_load_locations,
        lambda r, a: r.load_locations(args_from_namespace(LoadLocationsArgs, a)),
    ),
    (
        "unload_locations",
        TAPCmdParsers.parser_unload_locations,
        lambda r, a: r.unload_locations(args_from_namespace(UnloadLocationsArgs, a)),
    ),
    (
        "reset_tips",
        TAPCmdParsers.parser_reset_tips,
        lambda r, a: r.reset_tips(args_from_namespace(ResetTipsArgs, a)),
    ),
    ("reset_tips_all", None, lambda r, _args: r.reset_tips_all()),
    (
        "set_tips",
        TAPCmdParsers.parser_set_tips,
        lambda r, a: r.set_tips(args_from_namespace(SetTipsArgs, a)),
    ),
    (
        "wait",
        TAPCmdParsers.parser_wait,
        lambda r, a: r.wait(args_from_namespace(WaitArgs, a)),
    ),
    (
        "trigger",
        TAPCmdParsers.parser_trigger,
        lambda r, a: r.trigger(args_from_namespace(TriggerArgs, a)),
    ),
    (
        "gcode_print",
        TAPCmdParsers.parser_gcode_print,
        lambda r, a: r.gcode_print(args_from_namespace(GcodePrintArgs, a)),
    ),
    (
        "vol_to_steps",
        TAPCmdParsers.parser_vol_to_steps,
        lambda r, a: r.vol_to_steps(args_from_namespace(VolToStepsArgs, a)),
    ),
]


def _register_structured_commands() -> None:
    """Attach a generated ``do_<name>`` method to ``RemoteTapShell`` per entry.

    Runs once at import time. Each generated method builds its request via
    the entry's callable and dispatches through ``_call_and_print`` --
    identical in shape to the hand-written ``do_run``/``do_cancel`` above,
    just generated instead of duplicated per command.
    """
    for name, parser, build_request in _STRUCTURED_COMMANDS:

        def handler(
            self: RemoteTapShell,
            args: Any,  # ruff:ignore[any-type]
            build_request: Any = build_request,  # ruff:ignore[any-type]
        ) -> None:
            # _call_and_print is a same-class method reached through a
            # properly-typed `self` -- pyright still flags it because this
            # function is defined outside RemoteTapShell's class body.
            self._call_and_print(  # pyright: ignore[reportPrivateUsage]
                build_request(self.requests, args)
            )

        handler.__name__ = f"do_{name}"
        # cmd2 caches each command's parser keyed by `__module__.__qualname__`
        # (see CommandParsers._fully_qualified_name), not by function identity
        # -- every handler defined here shares the same __qualname__ by
        # default (they're all `def handler` at this one call site), which
        # would silently collapse all of them onto whichever parser cmd2
        # resolves first. __qualname__ must be set explicitly, not just
        # __name__, to keep each command's parser distinct.
        handler.__qualname__ = f"{RemoteTapShell.__qualname__}.do_{name}"
        handler.__doc__ = f"Send a structured '{name}' command to the daemon."
        if parser is not None:
            # with_argparser's return type doesn't structurally match the
            # plain handler signature above (same mismatch every do_*
            # elsewhere in this codebase silences via `# type: ignore
            # [arg-type]` on its @with_argparser line) -- it's still the
            # right callable at runtime, cmd2 only cares about arity.
            handler = with_argparser(parser)(handler)  # type: ignore[assignment]
        setattr(RemoteTapShell, f"do_{name}", handler)


_register_structured_commands()

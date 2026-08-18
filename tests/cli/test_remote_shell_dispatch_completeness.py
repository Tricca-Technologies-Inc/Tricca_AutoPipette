"""Client-parity completeness test for ``RemoteTapShell``.

CLAUDE.md's client-parity rule: "Every capability reachable from the kiosk
must also be reachable from `tap`, and vice versa." Every `ControlRequests`
builder the daemon exposes should therefore be reachable from a `tap`
command. Unlike
`tests/daemon/test_control_server_dispatch_completeness.py` (which
dispatches a real request through `ControlServer._call` and checks for
"Unknown method"), there's no single dispatch point to probe here --
`RemoteTapShell`'s `do_*` methods are hand-written, and several command
names don't match their builder name 1:1 (`transfer` -> `pipette`,
`webcam_url` -> `webcam`, `run_start` -> `run`, the `ws_*` diagnostics are
named without the prefix, `list_locations`/`list_plates`/`system_summary`
all fold into `ls`, ...). So this file instead asserts an explicit
builder-name -> command-name mapping is both complete (covers every
`ControlRequests` builder) and accurate (every mapped command name is a
real `do_*` on `RemoteTapShell`).
"""

from __future__ import annotations

from tricca_autopipette.cli.remote_shell import RemoteTapShell
from tricca_autopipette.daemon.control_requests import ControlRequests

# Builders with no standalone `tap` command, by design rather than a gap:
# - "identify" is a one-time connection tag `preloop` sends itself, not a
#   user-invocable command (see CLAUDE.md's daemon.identify note, issue #53).
# - "run_confirm_breakpoint" is reached via `do_continue`/`do_abort`, which
#   pick the `proceed` value for the user rather than exposing it as a raw
#   argument.
_NO_COMMAND_BY_DESIGN = frozenset({"identify", "run_confirm_breakpoint"})

# ControlRequests builder name -> the `do_<name>` command on RemoteTapShell
# that reaches it. Most are 1:1 (`move` -> `do_move`); the rest are listed
# explicitly here because the command name diverges from the builder name.
_BUILDER_TO_COMMAND: dict[str, str] = {
    "init": "init",
    "home": "home",
    "move": "move",
    "move_loc": "move_loc",
    "move_rel": "move_rel",
    "aspirate": "aspirate",
    "dispense": "dispense",
    "transfer": "pipette",
    "next_tip": "next_tip",
    "eject_tip": "eject_tip",
    "dispose_tip": "dispose_tip",
    "change_tip": "change_tip",
    "switch_liquid": "switch_liquid",
    "load_liquid": "load_liquid",
    "set": "set",
    "coor": "coor",
    "plate": "plate",
    "reset_plate": "reset_plate",
    "reset_plates": "reset_plates",
    "del_loc": "del_loc",
    "clear_locs": "clear_locs",
    "save_locations": "save_locations",
    "load_locations": "load_locations",
    "unload_locations": "unload_locations",
    "reset_tips": "reset_tips",
    "reset_tips_all": "reset_tips_all",
    "set_tips": "set_tips",
    "tips": "tips",
    "wait": "wait",
    "trigger": "trigger",
    "gcode_print": "gcode_print",
    "webcam_url": "webcam",
    "vol_to_steps": "vol_to_steps",
    "steps_to_vol": "steps_to_vol",
    "see_calibration": "see_calibration",
    "run_start": "run",
    "run_status": "run_status",
    "run_cancel": "cancel",
    "run_pause": "pause",
    "run_resume": "resume",
    "protocols_list": "protocols",
    "daemon_ping": "daemon_ping",
    "clients": "clients",
    "run_stop": "stop",
    "ws_status": "ws_status",
    "ws_ping": "ping",
    "ws_send": "send",
    "ws_notify": "notify",
    "ws_subscribe": "subscribe",
    "ws_unsubscribe": "unsubscribe",
    "ws_upload": "upload",
    "ws_read": "read",
    "ws_read_all": "read_all",
    "ws_clear_queue": "clear_queue",
    "ws_reconnect": "reconnect",
    "ws_query_endstops": "query_endstops",
    "list_locations": "ls",
    "list_plates": "ls",
    "list_liquids": "list_liquids",
    "system_summary": "ls",
}


def test_builder_map_covers_every_control_requests_builder() -> None:
    """Every ``ControlRequests`` builder is either mapped or excluded by name.

    Guards the completeness check itself -- without this, a newly-added
    ``ControlRequests`` builder that nobody added to
    ``_BUILDER_TO_COMMAND``/``_NO_COMMAND_BY_DESIGN`` would just never get
    checked, silently reopening the client-parity gap this file exists to
    catch.
    """
    non_builder_attrs = {"gen_request", "JSON_RPC_VERSION"}
    builder_names = {
        name
        for name in dir(ControlRequests)
        if not name.startswith("_") and name not in non_builder_attrs
    }
    covered_names = set(_BUILDER_TO_COMMAND) | _NO_COMMAND_BY_DESIGN

    missing = builder_names - covered_names
    assert not missing, (
        f"No tap command (or by-design exclusion) covers: {sorted(missing)} "
        "-- add it to _BUILDER_TO_COMMAND, or to _NO_COMMAND_BY_DESIGN with "
        "a comment explaining why it has no standalone tap command."
    )
    stale = covered_names - builder_names
    assert not stale, (
        f"_BUILDER_TO_COMMAND/_NO_COMMAND_BY_DESIGN reference builders that "
        f"no longer exist: {sorted(stale)} -- ControlRequests must have "
        "been renamed/removed."
    )


def test_every_mapped_command_exists_on_remote_tap_shell() -> None:
    """Every command name in ``_BUILDER_TO_COMMAND`` must be a real ``do_*``."""
    missing = {
        f"do_{command}"
        for command in _BUILDER_TO_COMMAND.values()
        if not hasattr(RemoteTapShell, f"do_{command}")
    }
    assert not missing, (
        f"_BUILDER_TO_COMMAND names commands that don't exist on "
        f"RemoteTapShell: {sorted(missing)}"
    )

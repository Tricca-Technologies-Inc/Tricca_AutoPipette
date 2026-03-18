"""Command-line argument parsers for Tricca AutoPipette Shell commands.

This module defines all argument parsers used by the TAP shell commands,
along with corresponding dataclasses that provide type safety for parsed
arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cmd2 import Cmd2ArgumentParser


@dataclass
class HomeArgs:
    """Arguments for the home command.

    Attributes:
        motors: Which motors to home (x, y, z, pipette, axis, all, servo).
    """

    motors: str


@dataclass
class ProfileArgs:
    """Arguments for the profile command.

    Attributes:
        name: Name of the profile.
    """

    name: str


@dataclass
class SetArgs:
    """Arguments for the set command.

    Attributes:
        pip_var: Variable name to set.
        pip_val: Value to set the variable to.
    """

    pip_var: str
    pip_val: float


@dataclass
class CoorArgs:
    """Arguments for the coor command.

    Attributes:
        name_loc: Name for the location.
        x: X-coordinate in millimeters.
        y: Y-coordinate in millimeters.
        z: Z-coordinate in millimeters.
    """

    name: str
    x: float
    y: float
    z: float


@dataclass
class PlateArgs:
    """Arguments for the plate command.

    Attributes:
        name_loc: Name for the plate location.
        plate_type: Type of plate (array, singleton, tipbox, waste_container).
        row: Number of rows in the plate.
        col: Number of columns in the plate.
    """

    name_loc: str
    plate_type: str
    row: int | None
    col: int | None


@dataclass
class MoveArgs:
    """Arguments for the move command.

    Attributes:
        x: X-coordinate in millimeters.
        y: Y-coordinate in millimeters.
        z: Z-coordinate in millimeters.
    """

    x: float
    y: float
    z: float


@dataclass
class MoveLocArgs:
    """Arguments for the move_loc command.

    Attributes:
        name_loc: Name of the location to move to.
        row: Optional row index for plate locations.
        col: Optional column index for plate locations.
    """

    name_loc: str
    row: int | None
    col: int | None


@dataclass
class MoveRelArgs:
    """Arguments for the move_rel command.

    Attributes:
        x: X-axis offset in millimeters.
        y: Y-axis offset in millimeters.
        z: Z-axis offset in millimeters.
    """

    x: float
    y: float
    z: float


@dataclass
class AspirateArgs:
    """Arguments for the aspirate command."""

    vol_ul: float
    source: str
    src_row: int | None
    src_col: int | None
    aspirate_air: float
    prewet: int
    prewet_vol: float


@dataclass
class DispenseArgs:
    """Arguments for the dispense command."""

    dest: str
    dest_row: int | None
    dest_col: int | None
    volume: float | None
    wiggle: bool
    touch: bool


@dataclass
class PipetteArgs:
    """Arguments for the pipette command.

    Attributes:
        vol_ul: Volume to aspirate in microliters.
        src: Source location name.
        dest: Destination location name.
        prewet: Whether to prewet the tip before aspirating.
        keep_tip: Whether to keep the tip after dispensing.
        wiggle: Whether to wiggle during dispensing.
        touch: Whether to touch the tip to the side after dispensing.
        src_row: Source row index for plate locations.
        src_col: Source column index for plate locations.
        dest_row: Destination row index for plate locations.
        dest_col: Destination column index for plate locations.
        disp_vol_ul: Volume to dispense (if different from aspirate).
        splits: Semicolon-separated list of split dispenses.
        leftover: What to do with leftover volume (keep or waste).
        tipbox_name: Name of specific tipbox to use.
    """

    vol_ul: float
    source: str
    dest: str
    disp_vol_ul: float | None
    src_row: int | None
    src_col: int | None
    dest_row: int | None
    dest_col: int | None
    tipbox_name: str | None
    aspirate_air: float
    prewet: int
    prewet_vol: float
    wiggle: bool
    touch: bool
    keep_tip: bool


@dataclass
class TipboxArgs:
    """Arguments for the tipbox command.

    Attributes:
        name: Name of the tipbox.
    """

    name: str


@dataclass
class TriggerArgs:
    """Arguments for the trigger command.

    Attributes:
        channel: Trigger channel (air, shake, aux).
        state: Desired state (on/off/1/0/high/low/true/false).
    """

    channel: str
    state: str


@dataclass
class RunArgs:
    """Arguments for the run command.

    Attributes:
        filename: Name of the protocol file to execute.
    """

    filename: str


@dataclass
class ResetPlateArgs:
    """Arguments for the reset_plate command.

    Attributes:
        plate: Name of the plate to reset.
    """

    plate: str


@dataclass
class VolToStepsArgs:
    """Arguments for the vol_to_steps command.

    Attributes:
        vol: Volume in microliters to convert.
    """

    vol: float


@dataclass
class LsArgs:
    """Arguments for the ls command.

    Attributes:
        var: Category to list (locs, plates, vars, conf, vol).
    """

    var: str


@dataclass
class LoadConfArgs:
    """Arguments for the load_conf command.

    Attributes:
        filename: Path to configuration file.
    """

    filename: str


@dataclass
class GcodePrintArgs:
    """Arguments for the gcode_print command.

    Attributes:
        msg: Message to print via G-code.
    """

    msg: str


@dataclass
class SendArgs:
    """Arguments for the send command.

    Attributes:
        method: JSON-RPC method to call.
        params: JSON string of parameters.
    """

    method: str
    params: str | None


@dataclass
class NotifyArgs:
    """Arguments for the notify command.

    Attributes:
        method: JSON-RPC method to notify.
        params: JSON string of parameters.
    """

    method: str
    params: str | None


@dataclass
class UploadArgs:
    """Arguments for the upload command.

    Attributes:
        file_name: Name to assign on the server.
        file_path: Local path to G-code file.
    """

    file_name: str
    file_path: Path


class TAPCmdParsers:
    """Container for all Tricca AutoPipette Shell command parsers.

    This class provides centralized access to all argument parsers used
    by TAP shell commands. Each parser is configured with appropriate
    arguments and help text.
    """

    parser_home: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Home motors on the pipette."
    )
    parser_home.add_argument(
        "motors", type=str, help="Motors to home (x, y, z, pipette, axis, all, servo)"
    )

    parser_profile: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Select a configuration profile."
    )
    parser_profile.add_argument("name", type=str, help="Profile name")

    parser_set: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Set a configuration variable."
    )
    parser_set.add_argument("pip_var", type=str, help="Variable name")
    parser_set.add_argument("pip_val", type=float, help="Variable value")

    parser_coor: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Define a named coordinate location."
    )
    parser_coor.add_argument("name_loc", type=str, help="Location name")
    parser_coor.add_argument("x", type=float, help="X-coordinate in mm")
    parser_coor.add_argument("y", type=float, help="Y-coordinate in mm")
    parser_coor.add_argument("z", type=float, help="Z-coordinate in mm")

    parser_plate: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Define a plate at a named location."
    )
    parser_plate.add_argument("name_loc", type=str, help="Location name")
    parser_plate.add_argument(
        "plate_type",
        type=str,
        help="Plate type (array, singleton, tipbox, waste_container)",
    )
    parser_plate.add_argument("--row", default=None, type=int, help="Number of rows")
    parser_plate.add_argument("--col", default=None, type=int, help="Number of columns")

    parser_move: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Move to absolute XYZ coordinates."
    )
    parser_move.add_argument("x", type=float, help="X-coordinate in mm")
    parser_move.add_argument("y", type=float, help="Y-coordinate in mm")
    parser_move.add_argument("z", type=float, help="Z-coordinate in mm")

    parser_move_loc: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Move to a named location."
    )
    parser_move_loc.add_argument("name_loc", type=str, help="Location name")
    parser_move_loc.add_argument("--row", default=None, type=int, help="Row index")
    parser_move_loc.add_argument("--col", default=None, type=int, help="Column index")

    parser_move_rel: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Move relative to current position."
    )
    parser_move_rel.add_argument("--x", default=0, type=float, help="X-offset in mm")
    parser_move_rel.add_argument("--y", default=0, type=float, help="Y-offset in mm")
    parser_move_rel.add_argument("--z", default=0, type=float, help="Z-offset in mm")

    parser_aspirate: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Aspirate liquid from a source location."
    )
    parser_aspirate.add_argument(
        "vol_ul", type=float, help="Volume to aspirate in microliters"
    )
    parser_aspirate.add_argument("source", type=str, help="Source location name")
    parser_aspirate.add_argument(
        "--src_row",
        default=None,
        type=int,
        help="Source row index",
    )
    parser_aspirate.add_argument(
        "--src_col",
        default=None,
        type=int,
        help="Source column index",
    )
    parser_aspirate.add_argument(
        "--aspirate_air",
        default=0.0,
        type=float,
        help="Volume of air to aspirate after liquid (default: 0.0)",
    )
    parser_aspirate.add_argument(
        "--prewet",
        default=0,
        type=int,
        help="Number of prewet cycles before aspirating (default: 0)",
    )
    parser_aspirate.add_argument(
        "--prewet_vol",
        default=10.0,
        type=float,
        help="Volume to use for prewet cycles in microliters (default: 10.0)",
    )

    parser_dispense: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Dispense liquid to a destination location."
    )
    parser_dispense.add_argument("dest", type=str, help="Destination location name")
    parser_dispense.add_argument(
        "--volume",
        "-v",
        default=None,
        type=float,
        help="Volume to dispense in microliters (default: all remaining liquid)",
    )
    parser_dispense.add_argument(
        "--dest_row",
        default=None,
        type=int,
        help="Destination row index",
    )
    parser_dispense.add_argument(
        "--dest_col",
        default=None,
        type=int,
        help="Destination column index",
    )
    parser_dispense.add_argument(
        "--wiggle",
        action="store_true",
        help="Wiggle tip during dispensing",
    )
    parser_dispense.add_argument(
        "--touch",
        action="store_true",
        help="Touch tip to well side after dispensing",
    )

    parser_pipette: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Transfer liquid from source to destination."
    )
    parser_pipette.add_argument(
        "vol_ul", type=float, help="Volume to aspirate in microliters"
    )
    parser_pipette.add_argument("source", type=str, help="Source location name")
    parser_pipette.add_argument("dest", type=str, help="Destination location name")
    parser_pipette.add_argument(
        "--dispense_vol",
        "-d",
        dest="disp_vol_ul",
        default=None,
        type=float,
        help="Volume to dispense if different from aspirate volume",
    )
    parser_pipette.add_argument(
        "--src_row",
        default=None,
        type=int,
        help="Source row index",
    )
    parser_pipette.add_argument(
        "--src_col",
        default=None,
        type=int,
        help="Source column index",
    )
    parser_pipette.add_argument(
        "--dest_row",
        default=None,
        type=int,
        help="Destination row index",
    )
    parser_pipette.add_argument(
        "--dest_col",
        default=None,
        type=int,
        help="Destination column index",
    )
    parser_pipette.add_argument(
        "--tipbox",
        dest="tipbox_name",
        default=None,
        type=str,
        help="Named tipbox to use (e.g. tipbox, tipbox2)",
    )
    parser_pipette.add_argument(
        "--aspirate_air",
        default=0.0,
        type=float,
        help="Volume of air to aspirate after liquid (default: 0.0)",
    )
    parser_pipette.add_argument(
        "--prewet",
        default=0,
        type=int,
        help="Number of prewet cycles before aspirating (default: 0)",
    )
    parser_pipette.add_argument(
        "--prewet_vol",
        default=10.0,
        type=float,
        help="Volume to use for prewet cycles in microliters (default: 10.0)",
    )
    parser_pipette.add_argument(
        "--wiggle",
        action="store_true",
        help="Wiggle tip during dispensing",
    )
    parser_pipette.add_argument(
        "--touch",
        action="store_true",
        help="Touch tip to well side after dispensing",
    )
    parser_pipette.add_argument(
        "--keep_tip",
        action="store_true",
        help="Keep tip attached after dispensing (default: eject tip)",
    )

    parser_tipbox: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Configure a tipbox."
    )
    parser_tipbox.add_argument("name", type=str, help="Tipbox name")

    parser_trigger: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Control auxiliary triggers."
    )
    parser_trigger.add_argument(
        "channel", type=str, help="Trigger channel (air, shake, aux)"
    )
    parser_trigger.add_argument(
        "state", type=str, help="Desired state (on/off/1/0/high/low/true/false)"
    )

    parser_run: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Execute a protocol script file."
    )
    parser_run.add_argument("filename", type=str, help="Protocol filename")

    parser_reset_plate: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Reset a plate's position to origin."
    )
    parser_reset_plate.add_argument("plate", type=str, help="Plate name")

    parser_vol_to_steps: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Convert volume to motor steps."
    )
    parser_vol_to_steps.add_argument("vol", type=float, help="Volume in microliters")

    parser_ls: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="List configuration variables."
    )
    parser_ls.add_argument(
        "var", type=str, help="Category (locs, plates, vars, conf, vol)"
    )

    parser_load_conf: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Load a configuration file."
    )
    parser_load_conf.add_argument("filename", type=str, help="Configuration filename")

    parser_gcode_print: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Send a message to be displayed by the pipette."
    )
    parser_gcode_print.add_argument("msg", type=str, help="Message to print")

    parser_send: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Send a JSON-RPC request."
    )
    parser_send.add_argument("method", help="JSON-RPC method to call")
    parser_send.add_argument(
        "params", nargs="?", default=None, help="JSON string of parameters"
    )

    parser_notify: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Send a JSON-RPC notification."
    )
    parser_notify.add_argument("method", help="JSON-RPC method to notify")
    parser_notify.add_argument(
        "params", nargs="?", default=None, help="JSON string of parameters"
    )

    parser_upload: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Upload a G-code file to the pipette."
    )
    parser_upload.add_argument("file_name", help="Name to assign on the server")
    parser_upload.add_argument("file_path", type=Path, help="Local path to G-code file")

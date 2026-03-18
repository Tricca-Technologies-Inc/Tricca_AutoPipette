"""Command-line argument parsers for Tricca AutoPipette Shell commands.

This module defines all argument parsers used by the TAP shell commands,
along with corresponding dataclasses that provide type safety for parsed
arguments.

Each parser in TAPCmdParsers has a matching dataclass above it that
documents the exact attribute names produced after parsing. The dataclass
field names must always match the argparse ``dest`` values so that
``@with_argparser`` type annotations work correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cmd2 import Cmd2ArgumentParser

# ===========================================================================
# Movement
# ===========================================================================


@dataclass
class HomeArgs:
    """Arguments for the ``home`` command.

    Attributes:
        motors: Which motors to home (x, y, z, pipette, axis, all, servo).
    """

    motors: str


@dataclass
class MoveArgs:
    """Arguments for the ``move`` command.

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
    """Arguments for the ``move_loc`` command.

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
    """Arguments for the ``move_rel`` command.

    Attributes:
        x: X-axis offset in millimeters.
        y: Y-axis offset in millimeters.
        z: Z-axis offset in millimeters.
    """

    x: float
    y: float
    z: float


# ===========================================================================
# Pipetting
# ===========================================================================


@dataclass
class AspirateArgs:
    """Arguments for the ``aspirate`` command.

    Attributes:
        vol_ul: Volume to aspirate in microliters.
        source: Source location name.
        src_row: Source row index for plate locations.
        src_col: Source column index for plate locations.
        aspirate_air: Volume of air to aspirate before liquid (µL).
        prewet: Number of prewet cycles before aspirating.
        prewet_vol: Volume to use for each prewet cycle (µL).
    """

    vol_ul: float
    source: str
    src_row: int | None
    src_col: int | None
    aspirate_air: float
    prewet: int
    prewet_vol: float


@dataclass
class DispenseArgs:
    """Arguments for the ``dispense`` command.

    Attributes:
        dest: Destination location name.
        dest_row: Destination row index for plate locations.
        dest_col: Destination column index for plate locations.
        volume: Volume to dispense in µL, or None to dispense all.
        wiggle: If True, wiggle tip during dispensing.
        touch: If True, touch tip to well side after dispensing.
    """

    dest: str
    dest_row: int | None
    dest_col: int | None
    volume: float | None
    wiggle: bool
    touch: bool


@dataclass
class PipetteArgs:
    """Arguments for the ``pipette`` command.

    Attributes:
        vol_ul: Volume to aspirate in microliters.
        source: Source location name.
        dest: Destination location name.
        disp_vol_ul: Volume to dispense if different from aspirate volume.
        src_row: Source row index for plate locations.
        src_col: Source column index for plate locations.
        dest_row: Destination row index for plate locations.
        dest_col: Destination column index for plate locations.
        tipbox_name: Name of specific tipbox to use.
        aspirate_air: Volume of air to aspirate before liquid (µL).
        prewet: Number of prewet cycles before aspirating.
        prewet_vol: Volume to use for each prewet cycle (µL).
        wiggle: If True, wiggle tip during dispensing.
        touch: If True, touch tip to well side after dispensing.
        keep_tip: If True, retain tip after the full operation.
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


# ===========================================================================
# Configuration & locations
# ===========================================================================


@dataclass
class SetArgs:
    """Arguments for the ``set`` command.

    Attributes:
        var: Configuration variable name (e.g. SPEED_FACTOR).
        value: Numeric value to assign to the variable.
    """

    var: str
    value: float


@dataclass
class CoorArgs:
    """Arguments for the ``coor`` command.

    Attributes:
        name: Name to assign to the coordinate location.
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
    """Arguments for the ``plate`` command.

    Attributes:
        name: Name to assign to the plate location.
        plate_type: Plate type (array, singleton, tipbox, waste_container).
        num_row: Number of rows.
        num_col: Number of columns.
        x: X-coordinate of the first well in millimeters.
        y: Y-coordinate of the first well in millimeters.
        z: Z-coordinate of the first well in millimeters.
        dip_top: Z distance above the well to begin dipping (mm).
        dip_btm: Z distance for full-depth dip, or None for simple strategy.
        dip_func: Dipping strategy type (simple, linear, etc.).
        well_diameter: Well diameter in mm, required for some strategies.
        spacing_row: Row-to-row spacing in mm.
        spacing_col: Column-to-column spacing in mm.
    """

    name: str
    plate_type: str
    num_row: int
    num_col: int
    x: float
    y: float
    z: float
    dip_top: float
    dip_btm: float | None
    dip_func: str
    well_diameter: float | None
    spacing_row: float
    spacing_col: float


@dataclass
class ResetPlateArgs:
    """Arguments for the ``reset_plate`` command.

    Attributes:
        name: Name of the plate to reset to origin position.
    """

    name: str


@dataclass
class DelLocArgs:
    """Arguments for the ``del_loc`` command.

    Attributes:
        name: Name of the location to delete.
    """

    name: str


@dataclass
class LsArgs:
    """Arguments for the ``ls`` command.

    Attributes:
        var: Category to list (locs, plates, liquids, system).
    """

    var: str


@dataclass
class LoadConfArgs:
    """Arguments for the ``load_conf`` command.

    Attributes:
        filename: Path to the configuration file to load.
    """

    filename: str


# ===========================================================================
# Protocol execution
# ===========================================================================


@dataclass
class RunArgs:
    """Arguments for the ``run`` command.

    Attributes:
        filename: Name of the protocol file to execute.
    """

    filename: str


@dataclass
class WaitArgs:
    """Arguments for the ``wait`` command.

    Attributes:
        ms: Duration to wait in milliseconds.
    """

    ms: float


# ===========================================================================
# Utility / diagnostics
# ===========================================================================


@dataclass
class GcodePrintArgs:
    """Arguments for the ``gcode_print`` command.

    Attributes:
        msg: Message to send to the pipette display via G-code.
    """

    msg: str


@dataclass
class VolToStepsArgs:
    """Arguments for the ``vol_to_steps`` command.

    Attributes:
        vol: Volume in microliters to convert to motor steps.
    """

    vol: float


@dataclass
class TriggerArgs:
    """Arguments for the ``trigger`` command.

    Attributes:
        channel: Trigger channel (air, shake, aux).
        state: Desired state (on, off).
    """

    channel: str
    state: str


# ===========================================================================
# WebSocket / networking
# ===========================================================================


@dataclass
class SendArgs:
    """Arguments for the ``send`` command.

    Attributes:
        method: JSON-RPC method to call.
        params: Optional JSON string of parameters.
    """

    method: str
    params: str | None


@dataclass
class NotifyArgs:
    """Arguments for the ``notify`` command.

    Attributes:
        method: JSON-RPC method to notify.
        params: Optional JSON string of parameters.
    """

    method: str
    params: str | None


@dataclass
class UploadArgs:
    """Arguments for the ``upload`` command.

    Attributes:
        file_name: Name to assign to the file on the server.
        file_path: Local path to the G-code file to upload.
    """

    file_name: str
    file_path: Path


# ===========================================================================
# Unused / reserved (no do_ handler implemented yet)
# ===========================================================================


@dataclass
class ProfileArgs:
    """Arguments for a future ``profile`` command.

    Attributes:
        name: Name of the configuration profile.
    """

    name: str


@dataclass
class TipboxArgs:
    """Arguments for a future ``tipbox`` command.

    Attributes:
        name: Name of the tipbox.
    """

    name: str


# ===========================================================================
# Parser definitions
# ===========================================================================


class TAPCmdParsers:
    """Container for all Tricca AutoPipette Shell command parsers.

    Each class-level parser corresponds to a ``do_*`` method in one of the
    command modules. The argument ``dest`` names produced by each parser must
    match the field names in the associated dataclass above.
    """

    # -----------------------------------------------------------------------
    # Movement
    # -----------------------------------------------------------------------

    parser_home: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Home motors on the pipette."
    )
    parser_home.add_argument(
        "motors",
        type=str,
        help="Motors to home: x, y, z, pipette, axis, all, servo",
    )

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
    parser_move_loc.add_argument(
        "--row", default=None, type=int, help="Row index (for plate locations)"
    )
    parser_move_loc.add_argument(
        "--col", default=None, type=int, help="Column index (for plate locations)"
    )

    parser_move_rel: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Move relative to the current position."
    )
    parser_move_rel.add_argument(
        "--x", default=0.0, type=float, help="X-axis offset in mm (default: 0)"
    )
    parser_move_rel.add_argument(
        "--y", default=0.0, type=float, help="Y-axis offset in mm (default: 0)"
    )
    parser_move_rel.add_argument(
        "--z", default=0.0, type=float, help="Z-axis offset in mm (default: 0)"
    )

    # -----------------------------------------------------------------------
    # Pipetting
    # -----------------------------------------------------------------------

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
        help="Source row index (for plate locations)",
    )
    parser_aspirate.add_argument(
        "--src_col",
        default=None,
        type=int,
        help="Source column index (for plate locations)",
    )
    parser_aspirate.add_argument(
        "--aspirate_air",
        default=0.0,
        type=float,
        help="Volume of air to aspirate before liquid in µL (default: 0.0)",
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
        help="Volume per prewet cycle in µL (default: 10.0)",
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
        help="Volume to dispense in µL (default: all remaining liquid)",
    )
    parser_dispense.add_argument(
        "--dest_row",
        default=None,
        type=int,
        help="Destination row index (for plate locations)",
    )
    parser_dispense.add_argument(
        "--dest_col",
        default=None,
        type=int,
        help="Destination column index (for plate locations)",
    )
    parser_dispense.add_argument(
        "--wiggle",
        action="store_true",
        help="Wiggle tip during dispensing to dislodge residual droplets",
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
        help="Volume to dispense if different from the aspirate volume",
    )
    parser_pipette.add_argument(
        "--src_row",
        default=None,
        type=int,
        help="Source row index (for plate locations)",
    )
    parser_pipette.add_argument(
        "--src_col",
        default=None,
        type=int,
        help="Source column index (for plate locations)",
    )
    parser_pipette.add_argument(
        "--dest_row",
        default=None,
        type=int,
        help="Destination row index (for plate locations)",
    )
    parser_pipette.add_argument(
        "--dest_col",
        default=None,
        type=int,
        help="Destination column index (for plate locations)",
    )
    parser_pipette.add_argument(
        "--tipbox",
        dest="tipbox_name",
        default=None,
        type=str,
        help="Name of the tipbox to draw from (e.g. tipbox, tipbox2)",
    )
    parser_pipette.add_argument(
        "--aspirate_air",
        default=0.0,
        type=float,
        help="Volume of air to aspirate before liquid in µL (default: 0.0)",
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
        help="Volume per prewet cycle in µL (default: 10.0)",
    )
    parser_pipette.add_argument(
        "--wiggle",
        action="store_true",
        help="Wiggle tip during dispensing to dislodge residual droplets",
    )
    parser_pipette.add_argument(
        "--touch",
        action="store_true",
        help="Touch tip to well side after dispensing",
    )
    parser_pipette.add_argument(
        "--keep_tip",
        action="store_true",
        help="Keep tip attached after the operation (default: eject tip)",
    )

    # -----------------------------------------------------------------------
    # Configuration & locations
    # -----------------------------------------------------------------------

    parser_set: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Set a configuration variable to a new value."
    )
    parser_set.add_argument(
        "var",
        type=str,
        help="Variable name: SPEED_FACTOR, VELOCITY_MAX, ACCEL_MAX",
    )
    parser_set.add_argument("value", type=float, help="Numeric value to assign")

    parser_coor: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Define a named coordinate location."
    )
    parser_coor.add_argument("name", type=str, help="Name for the location")
    parser_coor.add_argument("x", type=float, help="X-coordinate in mm")
    parser_coor.add_argument("y", type=float, help="Y-coordinate in mm")
    parser_coor.add_argument("z", type=float, help="Z-coordinate in mm")

    parser_plate: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Define a plate at a named location."
    )
    parser_plate.add_argument("name", type=str, help="Name for the plate location")
    parser_plate.add_argument(
        "plate_type",
        type=str,
        help="Plate type: array, singleton, tipbox, waste_container",
    )
    parser_plate.add_argument("num_row", type=int, help="Number of rows")
    parser_plate.add_argument("num_col", type=int, help="Number of columns")
    parser_plate.add_argument("x", type=float, help="X-coordinate of first well in mm")
    parser_plate.add_argument("y", type=float, help="Y-coordinate of first well in mm")
    parser_plate.add_argument("z", type=float, help="Z-coordinate of first well in mm")
    parser_plate.add_argument(
        "--dip_top",
        default=0.0,
        type=float,
        help="Z distance above well to begin dipping in mm (default: 0.0)",
    )
    parser_plate.add_argument(
        "--dip_btm",
        default=None,
        type=float,
        help="Z distance for full-depth dip in mm (enables linear strategy)",
    )
    parser_plate.add_argument(
        "--dip_func",
        default="simple",
        type=str,
        help="Dipping strategy: simple, linear (default: simple)",
    )
    parser_plate.add_argument(
        "--well_diameter",
        default=None,
        type=float,
        help="Well diameter in mm (required for some dipping strategies)",
    )
    parser_plate.add_argument(
        "--spacing_row",
        default=9.0,
        type=float,
        help="Row-to-row spacing in mm (default: 9.0)",
    )
    parser_plate.add_argument(
        "--spacing_col",
        default=9.0,
        type=float,
        help="Column-to-column spacing in mm (default: 9.0)",
    )

    parser_reset_plate: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Reset a plate's current position to the origin well."
    )
    parser_reset_plate.add_argument("name", type=str, help="Plate name")

    parser_del_loc: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Delete a named location or plate."
    )
    parser_del_loc.add_argument("name", type=str, help="Name of the location to delete")

    parser_ls: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="List configuration state by category."
    )
    parser_ls.add_argument(
        "var",
        type=str,
        help="Category: locs, plates, liquids, system",
    )

    parser_load_conf: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Load a configuration file."
    )
    parser_load_conf.add_argument("filename", type=str, help="Configuration filename")

    # -----------------------------------------------------------------------
    # Protocol execution
    # -----------------------------------------------------------------------

    parser_run: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Execute a protocol script file."
    )
    parser_run.add_argument("filename", type=str, help="Protocol filename")

    parser_wait: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Insert a timed pause into the G-code output."
    )
    parser_wait.add_argument("ms", type=float, help="Duration to wait in milliseconds")

    # -----------------------------------------------------------------------
    # Utility / diagnostics
    # -----------------------------------------------------------------------

    parser_gcode_print: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Send a message to be displayed on the pipette screen."
    )
    parser_gcode_print.add_argument("msg", type=str, help="Message to display")

    parser_vol_to_steps: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Convert a volume in µL to motor steps."
    )
    parser_vol_to_steps.add_argument("vol", type=float, help="Volume in microliters")

    parser_trigger: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Control auxiliary triggers (air, shake, aux)."
    )
    parser_trigger.add_argument(
        "channel",
        type=str,
        help="Trigger channel: air, shake, aux",
    )
    parser_trigger.add_argument(
        "state",
        type=str,
        help="Desired state: on, off",
    )

    # -----------------------------------------------------------------------
    # WebSocket / networking
    # -----------------------------------------------------------------------

    parser_send: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Send a JSON-RPC request and await a response."
    )
    parser_send.add_argument("method", help="JSON-RPC method to call")
    parser_send.add_argument(
        "params",
        nargs="?",
        default=None,
        help="Optional JSON string of parameters",
    )

    parser_notify: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Send a JSON-RPC notification (fire-and-forget)."
    )
    parser_notify.add_argument("method", help="JSON-RPC method to notify")
    parser_notify.add_argument(
        "params",
        nargs="?",
        default=None,
        help="Optional JSON string of parameters",
    )

    parser_upload: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="Upload a G-code file to the pipette server."
    )
    parser_upload.add_argument("file_name", help="Name to assign on the server")
    parser_upload.add_argument(
        "file_path", type=Path, help="Local path to the G-code file"
    )

    # -----------------------------------------------------------------------
    # Reserved / not yet implemented
    # -----------------------------------------------------------------------

    parser_profile: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="(Reserved) Select a configuration profile."
    )
    parser_profile.add_argument("name", type=str, help="Profile name")

    parser_tipbox: Cmd2ArgumentParser = Cmd2ArgumentParser(
        description="(Reserved) Configure a tipbox."
    )
    parser_tipbox.add_argument("name", type=str, help="Tipbox name")

"""Movement-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for controlling pipette movement,
including initialisation, homing operations, and absolute/relative positioning.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from coordinate import Coordinate
from pipette_constants import CoordinateSystem
from rich import print as rprint

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import (
    HomeArgs,
    MoveArgs,
    MoveLocArgs,
    MoveRelArgs,
    TAPCmdParsers,
)


class MovementCommands(TAPCommandSet):
    """Commands for controlling pipette movement and homing.

    Provides shell commands for:
    - Full pipette initialisation (coordinate system, speed, homing)
    - Homing individual motors or groups (x, y, z, pipette, axis, all, servo)
    - Moving to absolute coordinates
    - Moving to named locations (with optional row/col for plates)
    - Relative movement from current position

    Example:
        >>> init
        >>> home axis
        >>> move 100 50 10
        >>> move_loc plate_a --row 0 --col 3
        >>> move_rel --z -5
    """

    # Maps motor name → (output filename, autopipette method name) for all
    # motors that map directly to a single AutoPipette method.
    MOTOR_METHODS: dict[str, tuple[str, str]] = {
        "x": ("home_x.gcode", "home_x"),
        "y": ("home_y.gcode", "home_y"),
        "z": ("home_z.gcode", "home_z"),
        "pipette": ("home_pipette.gcode", "home_pipette_motors"),
        "axis": ("home_axis.gcode", "home_axis"),
        "servo": ("home_servo.gcode", "home_servo"),
    }

    # Special-case motor names that do not map to a single method.
    # "all" delegates to init_pipette() via do_init logic.
    MOTOR_SPECIAL: dict[str, str] = {
        "all": "home_all.gcode",
    }

    # Combined set of all valid motor names for upfront validation.
    # Kept in sync with MOTOR_METHODS and MOTOR_SPECIAL manually.
    VALID_MOTORS: frozenset[str] = frozenset(
        {
            "x",
            "y",
            "z",
            "pipette",
            "axis",
            "servo",  # MOTOR_METHODS keys
            "all",  # MOTOR_SPECIAL keys
        }
    )

    def __init__(self) -> None:
        """Initialize movement commands."""
        super().__init__()

    # =========================================================================
    # INITIALISATION
    # =========================================================================

    def do_init(self, _: Statement) -> None:
        """Initialise the pipette: set coordinate system, speed, and home all motors.

        Performs the complete startup sequence:
          1. Set coordinate system to absolute mode
          2. Configure speed and acceleration from config
          3. Home all XYZ axes
          4. Home pipette motors (stepper and servo)

        This should be run once after connecting to the pipette before any
        other operations. ``home all`` is an alias for this command.

        Example:
            >>> init
        """
        autopipette = self.shell._autopipette

        try:
            autopipette.init_pipette()
            self.shell.output_gcode(autopipette.get_gcode(), "home_all.gcode")
            rprint("[green]✓ Pipette initialised and all motors homed.[/green]")
        except Exception as e:
            rprint(f"[red]Initialisation error: {e}[/red]")

    # =========================================================================
    # HOMING
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_home)  # type: ignore[arg-type]
    def do_home(self, args: HomeArgs) -> None:
        """Home one or more motors on the pipette.

        Valid options: x, y, z, pipette, axis, all, servo.
        Using ``all`` is equivalent to running ``init`` — it performs the
        full initialisation sequence including speed setup and coordinate
        system reset.

        Args:
            args: Parsed arguments containing motor specification.

        Example:
            >>> home all
            >>> home axis
            >>> home pipette
            >>> home x
        """
        autopipette = self.shell._autopipette
        motors: str = args.motors.lower()

        if motors not in self.VALID_MOTORS:
            rprint(f"[yellow]'{motors}' is not a valid motor specification.[/yellow]")
            rprint(
                f"[cyan]Valid options: {', '.join(sorted(self.VALID_MOTORS))}[/cyan]"
            )
            return

        try:
            if motors in self.MOTOR_SPECIAL:
                # "all" — delegate to init_pipette() so coordinate system and
                # speed are always reset alongside homing (identical to do_init).
                filename = self.MOTOR_SPECIAL[motors]
                autopipette.init_pipette()
                self.shell.output_gcode(autopipette.get_gcode(), filename)
                rprint("[green]✓ All motors homed (full init complete).[/green]")
            else:
                filename, method_name = self.MOTOR_METHODS[motors]
                method = getattr(autopipette, method_name)
                method()
                self.shell.output_gcode(autopipette.get_gcode(), filename)
                rprint(f"[green]✓ Homed {motors}.[/green]")

        except Exception as e:
            rprint(f"[red]Homing error: {e}[/red]")

    # =========================================================================
    # ABSOLUTE MOVEMENT
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_move)  # type: ignore[arg-type]
    def do_move(self, args: MoveArgs) -> None:
        """Move to absolute XYZ coordinates.

        Args:
            args: Parsed arguments containing x, y, z coordinates.

        Example:
            >>> move 100 50 10
            >>> move 0 0 50
        """
        autopipette = self.shell._autopipette

        coor = Coordinate(x=args.x, y=args.y, z=args.z)

        try:
            autopipette.move_to(coor)
            self.shell.output_gcode(autopipette.get_gcode())
            rprint(f"[green]Moving to X:{args.x} Y:{args.y} Z:{args.z}[/green]")
        except Exception as e:
            rprint(f"[red]Move error: {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_move_loc)  # type: ignore[arg-type]
    def do_move_loc(self, args: MoveLocArgs) -> None:
        """Move to a named location.

        For plate locations, optional ``--row`` and ``--col`` target a
        specific well. Without them the plate's next well is used.

        Args:
            args: Parsed arguments containing location name and optional
                  row/col indices.

        Example:
            >>> move_loc home
            >>> move_loc plate_a
            >>> move_loc plate_a --row 1 --col 3
        """
        autopipette = self.shell._autopipette
        loc: str = args.name_loc

        if not autopipette.location_manager.has_location(loc):
            rprint(f"[yellow]Location '{loc}' does not exist.[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        try:
            coor = autopipette.location_manager.get_coordinate(loc, args.row, args.col)
            autopipette.move_to(coor)
            self.shell.output_gcode(autopipette.get_gcode())
            rprint(
                f"[green]Moving to '{loc}' "
                f"(X:{coor.x:.2f} Y:{coor.y:.2f} Z:{coor.z:.2f})[/green]"
            )
        except ValueError as e:
            rprint(f"[red]Invalid well specification: {e}[/red]")
        except Exception as e:
            rprint(f"[red]Error moving to '{loc}': {e}[/red]")

    # =========================================================================
    # RELATIVE MOVEMENT
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_move_rel)  # type: ignore[arg-type]
    def do_move_rel(self, args: MoveRelArgs) -> None:
        """Move relative to the current position.

        Switches to relative coordinate mode, performs the movement, then
        switches back to absolute mode. At least one non-zero offset is
        required.

        Args:
            args: Parsed arguments containing relative offsets (all default
                  to 0 if not specified).

        Example:
            >>> move_rel --x 5
            >>> move_rel --z -10
            >>> move_rel --x 2 --y -3
        """
        x: float = args.x
        y: float = args.y
        z: float = args.z

        if x == 0.0 and y == 0.0 and z == 0.0:
            rprint("[yellow]No movement — all offsets are zero.[/yellow]")
            return

        autopipette = self.shell._autopipette
        coor = Coordinate(x=x, y=y, z=z)

        try:
            autopipette.set_coor_sys(CoordinateSystem.RELATIVE)
            autopipette.move_to(coor)
            autopipette.set_coor_sys(CoordinateSystem.ABSOLUTE)
            self.shell.output_gcode(autopipette.get_gcode())

            parts = []
            if x != 0:
                parts.append(f"X{x:+.2f}")
            if y != 0:
                parts.append(f"Y{y:+.2f}")
            if z != 0:
                parts.append(f"Z{z:+.2f}")
            rprint(f"[green]Moving relative: {' '.join(parts)}[/green]")

        except Exception as e:
            rprint(f"[red]Relative move error: {e}[/red]")

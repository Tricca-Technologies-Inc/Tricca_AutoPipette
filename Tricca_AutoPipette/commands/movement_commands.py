"""Movement-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for controlling pipette movement,
including homing operations and absolute/relative positioning.
"""

from __future__ import annotations

from cmd2 import with_argparser
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
    - Homing individual motors or groups (x, y, z, pipette, all)
    - Moving to absolute coordinates
    - Moving to named locations
    - Relative movement from current position

    Example:
        >>> home all
        >>> move 100 50 10
        >>> move_loc plate_a
        >>> move_rel 5 0 0
    """

    # Valid homing options
    VALID_MOTORS = {
        "x": ("home_x.gcode", "home_x"),
        "y": ("home_y.gcode", "home_y"),
        "z": ("home_z.gcode", "home_z"),
        "pipette": ("home_pipette.gcode", "home_pipette_motors"),
        "axis": ("home_axis.gcode", "home_axis"),
        "all": ("home_all.gcode", None),  # Special case
        "servo": ("home_servo.gcode", "home_servo"),
    }

    def __init__(self) -> None:
        """Initialize movement commands."""
        super().__init__()

    @with_argparser(TAPCmdParsers.parser_home)  # type: ignore[arg-type]
    def do_home(self, args: HomeArgs) -> None:
        """Home motors on the pipette.

        Homes specified subset of motors to establish coordinate system.
        Valid options: x, y, z, pipette, axis, all, servo.

        Args:
            args: Parsed arguments containing motors specification.

        Example:
            >>> home all
            >>> home x
            >>> home axis
        """
        autopipette = self.shell._autopipette
        motors: str = args.motors.lower()

        # Validate motor specification
        if motors not in self.VALID_MOTORS:
            rprint(f"[yellow]'{motors}' is not a valid argument.[/yellow]")
            rprint(
                f"[cyan]Valid options: " f"{', '.join(self.VALID_MOTORS.keys())}[/cyan]"
            )
            return

        # Execute homing sequence
        filename, method_name = self.VALID_MOTORS[motors]

        if motors == "all":
            # Special case: home everything
            autopipette.home_axis()
            autopipette.home_pipette_motors()
            autopipette.state.homed = True
            rprint("[green]All motors homed successfully.[/green]")
        else:
            # Standard case: call the appropriate method
            method = getattr(autopipette, method_name)
            method()
            rprint(f"[green]Homed {motors} successfully.[/green]")

        self.shell.output_gcode(autopipette.get_gcode(), filename)

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
        x: float = args.x
        y: float = args.y
        z: float = args.z

        coor = Coordinate(x=x, y=y, z=z)
        autopipette.move_to(coor)

        self.shell.output_gcode(autopipette.get_gcode())
        rprint(f"[green]Moving to X:{x} Y:{y} Z:{z}[/green]")

    @with_argparser(TAPCmdParsers.parser_move_loc)  # type: ignore[arg-type]
    def do_move_loc(self, args: MoveLocArgs) -> None:
        """Move to a named location.

        Args:
            args: Parsed arguments containing location name.

        Example:
            >>> move_loc home
            >>> move_loc plate_a
        """
        autopipette = self.shell._autopipette
        loc: str = args.name_loc

        # Validate location exists
        if not autopipette.location_manager.has_location(loc):
            rprint(f"[yellow]Location '{loc}' does not exist.[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        # Get coordinate and move
        try:
            coor = autopipette.location_manager.get_coordinate(loc)
            autopipette.move_to(coor)

            self.shell.output_gcode(autopipette.get_gcode())
            rprint(
                f"[green]Moving to location '{loc}' "
                f"(X:{coor.x} Y:{coor.y} Z:{coor.z})[/green]"
            )
        except Exception as e:
            rprint(f"[red]Error moving to location '{loc}': {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_move_rel)  # type: ignore[arg-type]
    def do_move_rel(self, args: MoveRelArgs) -> None:
        """Move relative to current position.

        Switches to relative coordinate mode, performs the movement,
        then switches back to absolute mode.

        Args:
            args: Parsed arguments containing relative offsets.

        Example:
            >>> move_rel 5 0 0    # Move 5mm in X
            >>> move_rel 0 0 -10  # Move 10mm down in Z
        """
        autopipette = self.shell._autopipette
        x: float = args.x
        y: float = args.y
        z: float = args.z

        coor = Coordinate(x=x, y=y, z=z)

        # Perform relative movement
        autopipette.set_coor_sys(CoordinateSystem.RELATIVE)
        autopipette.move_to(coor)
        autopipette.set_coor_sys(CoordinateSystem.ABSOLUTE)

        self.shell.output_gcode(autopipette.get_gcode())

        # Build movement description
        movements = []
        if x != 0:
            movements.append(f"X{x:+.1f}")
        if y != 0:
            movements.append(f"Y{y:+.1f}")
        if z != 0:
            movements.append(f"Z{z:+.1f}")

        if movements:
            movement_str = " ".join(movements)
            rprint(f"[green]Moving relative: {movement_str}[/green]")
        else:
            rprint("[yellow]No movement (all offsets are zero).[/yellow]")

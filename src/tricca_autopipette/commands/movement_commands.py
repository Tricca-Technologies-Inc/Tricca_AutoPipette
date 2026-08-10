"""Movement-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for controlling pipette movement,
including initialisation, homing operations, and absolute/relative positioning.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from rich import print as rprint

from tricca_autopipette.commands.base_command_set import TAPCommandSet
from tricca_autopipette.core.pipette_exceptions import NotALocationError

from .tap_cmd_parsers import (
    HomeArgs,
    MoveArgs,
    MoveLocArgs,
    MoveRelArgs,
    TAPCmdParsers,
)


class MovementCommands(TAPCommandSet):
    """Commands for controlling pipette movement and homing.

    Thin cmd2 adapter: each ``do_*`` method only parses arguments and
    renders the result -- the actual logic lives on ``AutoPipetteService``
    (``daemon/service.py``), reached via ``self.shell.service`` (see that
    attribute's docstring for why this indirection is temporary).

    Provides shell commands for:
    - Full pipette initialisation (coordinate system, speed, homing)
    - Homing individual motors or groups (x, y, z, pipette, axis, all, servo)
    - Moving to absolute coordinates
    - Moving to named locations (with optional row/col for plates)
    - Relative movement from current position

    Example:
        init
        home axis
        move 100 50 10
        move_loc plate_a --row 0 --col 3
        move_rel --z -5
    """

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
            init
        """
        try:
            result = self.service.init()
            rprint(f"[green]✓ {result.message}[/green]")
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
            home all
            home axis
            home pipette
            home x
        """
        try:
            result = self.service.home(args)
            rprint(f"[green]✓ {result.message}[/green]")
        except ValueError as e:
            rprint(f"[yellow]{e}[/yellow]")
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
            move 100 50 10
            move 0 0 50
        """
        try:
            result = self.service.move(args)
            rprint(f"[green]{result.message}[/green]")
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
            move_loc home
            move_loc plate_a
            move_loc plate_a --row 1 --col 3
        """
        try:
            result = self.service.move_loc(args)
            rprint(f"[green]{result.message}[/green]")
        except NotALocationError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
        except ValueError as e:
            rprint(f"[red]Invalid well specification: {e}[/red]")
        except Exception as e:
            rprint(f"[red]Error moving to '{args.name_loc}': {e}[/red]")

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
            move_rel --x 5
            move_rel --z -10
            move_rel --x 2 --y -3
        """
        try:
            result = self.service.move_rel(args)
            color = "green" if result.ok else "yellow"
            rprint(f"[{color}]{result.message}[/{color}]")
        except Exception as e:
            rprint(f"[red]Relative move error: {e}[/red]")

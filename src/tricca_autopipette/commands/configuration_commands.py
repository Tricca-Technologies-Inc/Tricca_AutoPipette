"""Configuration-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for managing pipette configuration,
including switching liquids, defining locations and plates, and viewing
configuration state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cmd2 import Statement, with_argparser
from rich import print as rprint

if TYPE_CHECKING:
    # Type-only: importing daemon.service at runtime would be a genuine
    # circular import -- it imports tap_cmd_parsers, which triggers this
    # package's __init__. Same reason ProtocolAbortedError lives in
    # core/pipette_exceptions.py rather than in the service module.
    from tricca_autopipette.daemon.service import CommandResult

from tricca_autopipette.cli.report_tables import (
    build_liquids_table,
    build_locations_table,
    build_plates_table,
    build_system_table,
    build_tipbox_map,
)
from tricca_autopipette.commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import (
    CoorArgs,
    DelLocArgs,
    LoadLocationsArgs,
    LsArgs,
    PlateArgs,
    ResetPlateArgs,
    ResetTipsArgs,
    SetArgs,
    SetTipsArgs,
    TAPCmdParsers,
    TipsArgs,
    UnloadLocationsArgs,
    args_from_namespace,
)


class ConfigurationCommands(TAPCommandSet):
    """Commands for managing configuration and locations.

    Thin cmd2 adapter: each ``do_*`` only parses arguments and renders the
    result -- the actual logic lives on ``AutoPipetteService``, reached via
    ``self.service`` (see ``base_command_set.py``'s ``TAPCommandSet.service``
    property). ``ls``/``list_liquids`` call the service's data-only
    reporting methods and render the returned data as a
    ``rich.table.Table`` locally (see ``cli/report_tables.py``) -- table
    rendering is this driving adapter's job, not the service's.

    Provides shell commands for:
    - Switching liquid profiles
    - Setting configuration variables (speed, acceleration, etc.)
    - Defining coordinate locations
    - Creating and managing plates
    - Deleting and clearing locations
    - Loading and saving configuration files
    - Listing configuration state

    Example:
        switch_liquid glycerol
        list_liquids
        coor home 0 0 50
        plate my_plate array 8 12 100 200 10
        ls locs
        del_loc old_plate
    """

    def __init__(self) -> None:
        """Initialize configuration commands."""
        super().__init__()

    # =========================================================================
    # LIQUID PROFILE COMMANDS
    # =========================================================================

    def do_switch_liquid(self, statement: Statement) -> None:
        """Switch to a different liquid profile.

        Changes the active liquid profile, updating calibration curves
        and pipetting parameters for the specified liquid.

        Args:
            statement: Command statement containing liquid name.

        Example:
            switch_liquid water
            switch_liquid glycerol
            switch_liquid methanol
        """
        liquid_name = statement.arg_list[0] if statement.arg_list else None

        if not liquid_name:
            rprint("[red]Error: Please specify a liquid name.[/red]")
            rprint("[cyan]Usage: switch_liquid <liquid_name>[/cyan]")
            return

        try:
            result = self.service.switch_liquid(liquid_name)
            data = result.data or {}

            rprint(f"[green]✓ {result.message}[/green]")
            rprint(f"  Viscosity: {data.get('viscosity_cP')} cP")
            if data.get("speed_aspirate"):
                rprint(f"  Aspirate speed: {data['speed_aspirate']} mm/s")
            if data.get("prewet_cycles"):
                rprint(f"  Prewet: {data['prewet_cycles']} cycles")
            pre_gap = data.get("pre_air_gap_ul")
            post_gap = data.get("post_air_gap_ul")
            if pre_gap or post_gap:
                rprint(f"  Air gap: {pre_gap or 0} μL pre / {post_gap or 0} μL post")

        except ValueError as e:
            # The domain layer's message already lists available liquids.
            rprint(f"[red]Error: {e}[/red]")

    def do_list_liquids(self, _: Statement) -> None:
        """List all available liquid profiles.

        Displays all loaded liquid profiles with their key properties.

        Example:
            list_liquids
        """
        result = self.service.list_liquids()
        data = result.data or {}
        liquids: list[dict[str, Any]] = data.get("liquids") or []
        if not liquids:
            rprint(f"[yellow]{result.message}[/yellow]")
            return
        rprint(build_liquids_table(liquids))
        rprint(f"\n[dim]Active liquid: {data.get('active_liquid')}[/dim]")

    def do_load_liquid(self, statement: Statement) -> None:
        """Load a new liquid profile from a JSON file.

        Dynamically loads a liquid profile and adds it to the available liquids.

        Args:
            statement: Command statement containing filename.

        Example:
            load_liquid acetone.json
            load_liquid custom_buffer.json
        """
        filename = statement.arg_list[0] if statement.arg_list else None

        if not filename:
            rprint("[red]Error: Please specify a liquid file.[/red]")
            rprint("[cyan]Usage: load_liquid <filename.json>[/cyan]")
            return

        try:
            result = self.service.load_liquid(filename)
            data = result.data or {}
            rprint(f"[green]✓ {result.message}[/green]")
            rprint(f"  Viscosity: {data.get('viscosity_cP')} cP")
            rprint(f"  File: {filename}")
            rprint(
                f"\n[cyan]Use 'switch_liquid {data.get('name')}' to activate.[/cyan]"
            )
        except FileNotFoundError as e:
            rprint(f"[red]Error: {e}[/red]")
        except ValueError as e:
            rprint(f"[red]Error: Invalid liquid configuration — {e}[/red]")

    # =========================================================================
    # CONFIGURATION VARIABLES
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_set)  # type: ignore[arg-type]
    def do_set(self, args: SetArgs) -> None:
        """Set a configuration variable to a new value.

        Modifies gantry parameters like speed and acceleration.
        Changes generate immediate G-code commands.

        Args:
            args: Parsed arguments containing variable name and value.

        Example:
            set SPEED_FACTOR 150
            set VELOCITY_MAX 5000
            set ACCEL_MAX 3000
        """
        result = self.service.set(args)
        if result.ok:
            rprint(f"[green]✓ {result.message}[/green]")
        else:
            rprint(f"[yellow]{result.message}[/yellow]")

    # =========================================================================
    # LOCATION MANAGEMENT
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_coor)  # type: ignore[arg-type]
    def do_coor(self, args: CoorArgs) -> None:
        """Define a named coordinate location.

        Creates a named reference point for later use in movement and
        pipetting commands.

        Args:
            args: Parsed arguments containing location name and coordinates.

        Example:
            coor home 0 0 50
            coor plate_a 100 200 10
        """
        result = self.service.coor(args)
        rprint(f"[green]✓ {result.message}[/green]")

    @with_argparser(TAPCmdParsers.parser_plate)  # type: ignore[arg-type]
    def do_plate(self, args: PlateArgs) -> None:
        """Define a plate at a named location.

        Creates a plate with specified dimensions and type at a location.

        Args:
            args: Parsed arguments containing plate configuration.

        Example:
            plate my_96well array 8 12 100 200 10
            plate tipbox1 tipbox 8 12 50 50 10
            plate reservoir singleton 1 1 30 30 5 --dip_top 2 --dip_btm 8
        """
        try:
            result = self.service.plate(args)
        except (TypeError, RuntimeError) as e:
            rprint(f"[red]Error creating plate: {e}[/red]")
            return

        rprint(f"[green]✓ {result.message}[/green]")
        rprint(f"  Spacing: row={args.spacing_row} mm, col={args.spacing_col} mm")

    @with_argparser(TAPCmdParsers.parser_reset_plate)  # type: ignore[arg-type]
    def do_reset_plate(self, args: ResetPlateArgs) -> None:
        """Reset a specific plate's current position to the origin well.

        Args:
            args: Parsed arguments containing plate name.

        Example:
            reset_plate my_96well
        """
        result = self.service.reset_plate(args)
        if result.ok:
            rprint(f"[green]✓ {result.message}[/green]")
        else:
            rprint(f"[yellow]{result.message}[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")

    def do_reset_plates(self, _: Statement) -> None:
        """Reset all plates to the origin well.

        Example:
            reset_plates
        """
        result = self.service.reset_plates()
        if result.ok:
            rprint(f"[green]✓ {result.message}[/green]")
        else:
            rprint(f"[yellow]{result.message}[/yellow]")

    @with_argparser(TAPCmdParsers.parser_del_loc)  # type: ignore[arg-type]
    def do_del_loc(self, args: DelLocArgs) -> None:
        """Delete a named location or plate.

        Removes the location from the manager. If the location is a
        waste container or tipbox, those references are cleared too.

        Args:
            args: Parsed arguments containing location name.

        Example:
            del_loc old_plate
            del_loc spare_coor
        """
        result = self.service.del_loc(args)
        if result.ok:
            rprint(f"[green]✓ {result.message}[/green]")
        else:
            rprint(f"[yellow]{result.message}[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")

    def do_clear_locs(self, _: Statement) -> None:
        """Delete all locations and plates.

        Clears all coordinates, plates, tipbox references, and the waste
        container. Use with caution — this cannot be undone without
        reloading from a file.

        Example:
            clear_locs
        """
        result = self.service.clear_locs()
        if result.ok:
            rprint(f"[green]✓ {result.message}[/green]")
        else:
            rprint(f"[yellow]{result.message}[/yellow]")

    # =========================================================================
    # CONFIGURATION FILE MANAGEMENT
    # =========================================================================

    def do_save_locations(self, statement: Statement) -> None:
        """Save current locations to a JSON file.

        Args:
            statement: Optional filename (defaults to 'custom_locations.json').

        Example:
            save_locations
            save_locations my_setup.json
        """
        filename = (
            statement.arg_list[0] if statement.arg_list else "custom_locations.json"
        )

        try:
            result = self.service.save_locations(filename)
            rprint(f"[green]✓ {result.message}[/green]")
        except Exception as e:
            rprint(f"[red]Error saving locations: {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_load_locations)  # type: ignore[arg-type]
    def do_load_locations(self, args: LoadLocationsArgs) -> None:
        """Load locations from a JSON file, adding to the current deck.

        Args:
            args: Filename to load and whether to replace the deck.

        Example:
            load_locations my_setup.json
            load_locations my_setup.json --replace
        """
        try:
            result = self.service.load_locations(
                args_from_namespace(LoadLocationsArgs, args)
            )
            rprint(f"[green]✓ {result.message}[/green]")
        except FileNotFoundError as e:
            rprint(f"[red]Error: {e}[/red]")
        except ValueError as e:
            rprint(f"[red]Error: Invalid locations file — {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_unload_locations)  # type: ignore[arg-type]
    def do_unload_locations(self, args: UnloadLocationsArgs) -> None:
        """Unload a single location from the deck by name.

        Args:
            args: Name of the location to unload.

        Example:
            unload_locations tipbox_a
        """
        self._render(
            self.service.unload_locations(
                args_from_namespace(UnloadLocationsArgs, args)
            )
        )

    # =========================================================================
    # TIP INVENTORY
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_reset_tips)  # type: ignore[arg-type]
    def do_reset_tips(self, args: ResetTipsArgs) -> None:
        """Mark a tipbox as full, after physically reloading it.

        Args:
            args: Name of the tipbox to reset.

        Example:
            reset_tips tipbox_a
        """
        self._render(self.service.reset_tips(args_from_namespace(ResetTipsArgs, args)))

    def do_reset_tips_all(self, _: Statement) -> None:
        """Mark every loaded tipbox as full.

        Args:
            _: Unused; the command takes no arguments.

        Example:
            reset_tips_all
        """
        self._render(self.service.reset_tips_all())

    @with_argparser(TAPCmdParsers.parser_set_tips)  # type: ignore[arg-type]
    def do_set_tips(self, args: SetTipsArgs) -> None:
        """Declare which tip positions of a box are consumed.

        Args:
            args: Tipbox name, well ranges, and whether the ranges list the
                available positions rather than the consumed ones.

        Example:
            set_tips tipbox_a A1:C12
            set_tips tipbox_a D1:H12 --available
        """
        self._render(self.service.set_tips(args_from_namespace(SetTipsArgs, args)))

    @with_argparser(TAPCmdParsers.parser_tips)  # type: ignore[arg-type]
    def do_tips(self, args: TipsArgs) -> None:
        """Show tip availability per tipbox, as an ASCII map.

        Args:
            args: Optional tipbox name, and whether to compare against the
                state persisted in Moonraker's database.

        Example:
            tips
            tips tipbox_a --db
        """
        result = self.service.tips(args_from_namespace(TipsArgs, args))
        if not result.ok:
            rprint(f"[red]✗ {result.message}[/red]")
            return

        data = result.data or {}
        boxes: list[dict[str, Any]] = data.get("boxes") or []
        if not boxes:
            rprint("[yellow]No tipboxes are loaded.[/yellow]")
            return

        persisted: dict[str, Any] = data.get("persisted") or {}
        for box in boxes:
            rprint(build_tipbox_map(box, persisted.get(box["name"])))

    def _render(self, result: CommandResult) -> None:
        """Print a command result with the shell's usual ok/error styling.

        Args:
            result: The result to render.
        """
        if result.ok:
            rprint(f"[green]✓ {result.message}[/green]")
        else:
            rprint(f"[red]✗ {result.message}[/red]")

    # =========================================================================
    # LISTING COMMANDS
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_ls)  # type: ignore[arg-type]
    def do_ls(self, args: LsArgs) -> None:
        """List configuration state by category.

        ``locations`` is accepted as an alias for ``locs``, and ``config``
        as an alias for ``system``.

        Args:
            args: Parsed arguments containing category to list.

        Example:
            ls locs
            ls plates
            ls liquids
            ls system
        """
        var: str = args.var.lower()

        ls_commands = {
            "locs": self._ls_locs,
            "locations": self._ls_locs,
            "plates": self._ls_plates,
            "liquids": self._ls_liquids,
            "system": self._ls_system,
            "config": self._ls_system,
        }

        if var in ls_commands:
            ls_commands[var]()
        else:
            rprint(f"[yellow]Unknown category '{var}'.[/yellow]")
            rprint("[cyan]Valid categories: locs, plates, liquids, system[/cyan]")

    def _ls_locs(self) -> None:
        """Display all defined locations (coordinates and plates)."""
        result = self.service.list_locations()
        locations: list[dict[str, Any]] = (result.data or {}).get("locations") or []
        if not locations:
            rprint(f"[yellow]{result.message}[/yellow]")
            return
        rprint(build_locations_table(locations))

    def _ls_plates(self) -> None:
        """Display all defined plates with full detail."""
        result = self.service.list_plates()
        plates: list[dict[str, Any]] = (result.data or {}).get("plates") or []
        if not plates:
            rprint(f"[yellow]{result.message}[/yellow]")
            return
        rprint(build_plates_table(plates))

    def _ls_liquids(self) -> None:
        """Display all liquid profiles."""
        result = self.service.list_liquids()
        data = result.data or {}
        liquids: list[dict[str, Any]] = data.get("liquids") or []
        if not liquids:
            rprint(f"[yellow]{result.message}[/yellow]")
            return
        rprint(build_liquids_table(liquids))
        rprint(f"\n[dim]Active liquid: {data.get('active_liquid')}[/dim]")

    def _ls_system(self) -> None:
        """Display system configuration summary."""
        result = self.service.system_summary()
        rprint(build_system_table(result.data or {}))

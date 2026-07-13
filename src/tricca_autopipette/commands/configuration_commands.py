"""Configuration-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for managing pipette configuration,
including switching liquids, defining locations and plates, and viewing
configuration state.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from coordinate import Coordinate
from plates import Plate, PlateParams
from rich import print as rprint
from rich.table import Table
from well import StrategyType, Well

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import (
    CoorArgs,
    DelLocArgs,
    LsArgs,
    PlateArgs,
    ResetPlateArgs,
    SetArgs,
    TAPCmdParsers,
)


class ConfigurationCommands(TAPCommandSet):
    """Commands for managing configuration and locations.

    Provides shell commands for:
    - Switching liquid profiles
    - Setting configuration variables (speed, acceleration, etc.)
    - Defining coordinate locations
    - Creating and managing plates
    - Deleting and clearing locations
    - Loading and saving configuration files
    - Listing configuration state

    Example:
        >>> switch_liquid glycerol
        >>> list_liquids
        >>> coor home 0 0 50
        >>> plate my_plate array 8 12 100 200 10
        >>> ls locs
        >>> del_loc old_plate
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
            >>> switch_liquid water
            >>> switch_liquid glycerol
            >>> switch_liquid methanol
        """
        liquid_name = statement.arg_list[0] if statement.arg_list else None

        if not liquid_name:
            rprint("[red]Error: Please specify a liquid name.[/red]")
            rprint("[cyan]Usage: switch_liquid <liquid_name>[/cyan]")
            return

        try:
            self.shell._autopipette.switch_liquid(liquid_name)

            liquid = self.shell._autopipette.system_config.liquids[liquid_name]

            rprint(f"[green]✓ Switched to liquid: {liquid_name}[/green]")
            rprint(f"  Viscosity: {liquid.viscosity_cP} cP")

            if liquid.speed_aspirate:
                rprint(f"  Aspirate speed: {liquid.speed_aspirate} steps/s")
            if liquid.prewet_recommended:
                rprint(
                    f"  [yellow]⚠ Prewet recommended "
                    f"({liquid.prewet_cycles} cycles)[/yellow]"
                )

        except ValueError as e:
            rprint(f"[red]Error: {e}[/red]")
            available = self.shell._autopipette.config_manager.list_available_liquids()
            rprint(f"[cyan]Available liquids: {', '.join(available)}[/cyan]")

    def do_list_liquids(self, _: Statement) -> None:
        """List all available liquid profiles.

        Displays all loaded liquid profiles with their key properties.

        Example:
            >>> list_liquids
        """
        table = self._build_liquids_table()
        if table is None:
            return
        rprint(table)
        rprint(f"\n[dim]Active liquid: {self.shell._autopipette.active_liquid}[/dim]")

    def do_load_liquid(self, statement: Statement) -> None:
        """Load a new liquid profile from a JSON file.

        Dynamically loads a liquid profile and adds it to the available liquids.

        Args:
            statement: Command statement containing filename.

        Example:
            >>> load_liquid acetone.json
            >>> load_liquid custom_buffer.json
        """
        filename = statement.arg_list[0] if statement.arg_list else None

        if not filename:
            rprint("[red]Error: Please specify a liquid file.[/red]")
            rprint("[cyan]Usage: load_liquid <filename.json>[/cyan]")
            return

        try:
            liquid = self.shell._autopipette.config_manager.load_liquid(filename)
            rprint(f"[green]✓ Loaded liquid profile: {liquid.name}[/green]")
            rprint(f"  Viscosity: {liquid.viscosity_cP} cP")
            rprint(f"  File: {filename}")
            rprint(f"\n[cyan]Use 'switch_liquid {liquid.name}' to activate.[/cyan]")
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
            >>> set SPEED_FACTOR 150
            >>> set VELOCITY_MAX 5000
            >>> set ACCEL_MAX 3000
        """
        var_name = args.var.upper()
        value: float = args.value

        if var_name == "SPEED_FACTOR":
            self.shell._autopipette.set_speed_factor(value)
            self.shell.output_gcode(self.shell._autopipette.get_gcode())
            rprint(f"[green]✓ Set {var_name} = {value}[/green]")
        elif var_name == "VELOCITY_MAX":
            self.shell._autopipette.set_max_velocity(value)
            self.shell.output_gcode(self.shell._autopipette.get_gcode())
            rprint(f"[green]✓ Set {var_name} = {value} mm/s[/green]")
        elif var_name == "ACCEL_MAX":
            self.shell._autopipette.set_max_accel(value)
            self.shell.output_gcode(self.shell._autopipette.get_gcode())
            rprint(f"[green]✓ Set {var_name} = {value} mm/s²[/green]")
        else:
            rprint(f"[yellow]Unknown variable '{var_name}'.[/yellow]")
            rprint("[cyan]Available: SPEED_FACTOR, VELOCITY_MAX, ACCEL_MAX[/cyan]")

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
            >>> coor home 0 0 50
            >>> coor plate_a 100 200 10
        """
        coord = Coordinate(x=args.x, y=args.y, z=args.z)
        self.shell._autopipette.location_manager.set_coordinate(args.name, coord)

        rprint(f"[green]✓ Created coordinate '{args.name}'[/green]")
        rprint(f"  Position: X={args.x}, Y={args.y}, Z={args.z}")

    @with_argparser(TAPCmdParsers.parser_plate)  # type: ignore[arg-type]
    def do_plate(self, args: PlateArgs) -> None:
        """Define a plate at a named location.

        Creates a plate with specified dimensions and type at a location.

        Args:
            args: Parsed arguments containing plate configuration.

        Example:
            >>> plate my_96well array 8 12 100 200 10
            >>> plate tipbox1 tipbox 8 12 50 50 10
            >>> plate reservoir singleton 1 1 30 30 5 --dip_top 2 --dip_btm 8
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

        try:
            self.shell._autopipette.location_manager.set_plate(args.name, plate_params)
        except (TypeError, RuntimeError) as e:
            rprint(f"[red]Error creating plate: {e}[/red]")
            return

        rprint(f"[green]✓ Created plate '{args.name}'[/green]")
        rprint(f"  Type: {args.plate_type}")
        rprint(
            f"  Dimensions: {args.num_row}×{args.num_col} "
            f"({args.num_row * args.num_col} wells)"
        )
        rprint(f"  Position: X={args.x}, Y={args.y}, Z={args.z}")
        rprint(f"  Spacing: row={args.spacing_row} mm, col={args.spacing_col} mm")

    @with_argparser(TAPCmdParsers.parser_reset_plate)  # type: ignore[arg-type]
    def do_reset_plate(self, args: ResetPlateArgs) -> None:
        """Reset a specific plate's current position to the origin well.

        Args:
            args: Parsed arguments containing plate name.

        Example:
            >>> reset_plate my_96well
        """
        loc_mgr = self.shell._autopipette.location_manager

        if not loc_mgr.has_location(args.name):
            rprint(f"[red]Error: Location '{args.name}' not found.[/red]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        location = loc_mgr.locations[args.name]

        if not isinstance(location, Plate):
            rprint(f"[red]Error: '{args.name}' is not a plate.[/red]")
            return

        location.reset()
        rprint(f"[green]✓ Reset plate '{args.name}' to position 0[/green]")

    def do_reset_plates(self, _: Statement) -> None:
        """Reset all plates to the origin well.

        Example:
            >>> reset_plates
        """
        loc_mgr = self.shell._autopipette.location_manager
        plate_names = loc_mgr.get_plate_names()

        if not plate_names:
            rprint("[yellow]No plates to reset.[/yellow]")
            return

        for name in plate_names:
            plate = loc_mgr.locations[name]
            if isinstance(plate, Plate):
                plate.reset()

        rprint(f"[green]✓ Reset {len(plate_names)} plate(s) to origin.[/green]")

    @with_argparser(TAPCmdParsers.parser_del_loc)  # type: ignore[arg-type]
    def do_del_loc(self, args: DelLocArgs) -> None:
        """Delete a named location or plate.

        Removes the location from the manager. If the location is a
        waste container or tipbox, those references are cleared too.

        Args:
            args: Parsed arguments containing location name.

        Example:
            >>> del_loc old_plate
            >>> del_loc spare_coor
        """
        loc_mgr = self.shell._autopipette.location_manager

        if not loc_mgr.has_location(args.name):
            rprint(f"[red]Error: Location '{args.name}' not found.[/red]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        loc_mgr.remove_location(args.name)
        rprint(f"[green]✓ Deleted location '{args.name}'.[/green]")

    def do_clear_locs(self, _: Statement) -> None:
        """Delete all locations and plates.

        Clears all coordinates, plates, tipbox references, and the waste
        container. Use with caution — this cannot be undone without
        reloading from a file.

        Example:
            >>> clear_locs
        """
        loc_mgr = self.shell._autopipette.location_manager
        count = len(loc_mgr.locations)

        if count == 0:
            rprint("[yellow]No locations to clear.[/yellow]")
            return

        loc_mgr.clear()
        rprint(f"[green]✓ Cleared {count} location(s).[/green]")

    # =========================================================================
    # CONFIGURATION FILE MANAGEMENT
    # =========================================================================

    def do_save_locations(self, statement: Statement) -> None:
        """Save current locations to a JSON file.

        Args:
            statement: Optional filename (defaults to 'custom_locations.json').

        Example:
            >>> save_locations
            >>> save_locations my_setup.json
        """
        filename = (
            statement.arg_list[0] if statement.arg_list else "custom_locations.json"
        )

        try:
            self.shell._autopipette.location_manager.save_to_json(filename)
            rprint(f"[green]✓ Saved locations to {filename}[/green]")
        except Exception as e:
            rprint(f"[red]Error saving locations: {e}[/red]")

    def do_load_locations(self, statement: Statement) -> None:
        """Load locations from a JSON file.

        Clears all existing locations before loading.

        Args:
            statement: Filename to load.

        Example:
            >>> load_locations my_setup.json
        """
        filename = statement.arg_list[0] if statement.arg_list else None

        if not filename:
            rprint("[red]Error: Please specify a filename.[/red]")
            rprint("[cyan]Usage: load_locations <filename.json>[/cyan]")
            return

        try:
            self.shell._autopipette.location_manager.load_from_json(filename)

            coords = self.shell._autopipette.location_manager.get_coordinate_names()
            plates = self.shell._autopipette.location_manager.get_plate_names()

            rprint(f"[green]✓ Loaded locations from {filename}[/green]")
            rprint(f"  Coordinates: {len(coords)}")
            rprint(f"  Plates: {len(plates)}")

        except FileNotFoundError as e:
            rprint(f"[red]Error: {e}[/red]")
        except ValueError as e:
            rprint(f"[red]Error: Invalid locations file — {e}[/red]")

    # =========================================================================
    # LISTING COMMANDS
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_ls)  # type: ignore[arg-type]
    def do_ls(self, args: LsArgs) -> None:
        """List configuration state by category.

        Args:
            args: Parsed arguments containing category to list.

        Example:
            >>> ls locs
            >>> ls plates
            >>> ls liquids
            >>> ls system
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
        loc_mgr = self.shell._autopipette.location_manager
        all_names = loc_mgr.get_all_names()

        if not all_names:
            rprint("[yellow]No locations defined.[/yellow]")
            return

        table = Table(title="All Locations", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("X", justify="right")
        table.add_column("Y", justify="right")
        table.add_column("Z", justify="right")
        table.add_column("Details", style="dim")

        for name in sorted(all_names):
            location = loc_mgr.locations[name]
            if isinstance(location, Plate):
                origin = location.wells[0].coor if location.wells else None
                x = f"{origin.x:.2f}" if origin else "—"
                y = f"{origin.y:.2f}" if origin else "—"
                z = f"{origin.z:.2f}" if origin else "—"
                details = (
                    f"{location.num_row}×{location.num_col} "
                    f"[{location.current_row},{location.current_col}]"
                )
                table.add_row(name, location.__class__.__name__, x, y, z, details)
            elif isinstance(location, Coordinate):
                table.add_row(
                    name,
                    "Coordinate",
                    f"{location.x:.2f}",
                    f"{location.y:.2f}",
                    f"{location.z:.2f}",
                    "",
                )

        rprint(table)

    def _ls_plates(self) -> None:
        """Display all defined plates with full detail."""
        loc_mgr = self.shell._autopipette.location_manager
        plate_names = loc_mgr.get_plate_names()

        if not plate_names:
            rprint("[yellow]No plates defined.[/yellow]")
            return

        table = Table(title="Defined Plates", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Dimensions", justify="center")
        table.add_column("Current", justify="center")
        table.add_column("Wells", justify="right")

        for name in sorted(plate_names):
            plate = loc_mgr.locations[name]
            if not isinstance(plate, Plate):
                continue
            dims = f"{plate.num_row}×{plate.num_col}"
            current = f"{plate.current_row},{plate.current_col}"
            total = plate.num_row * plate.num_col

            table.add_row(
                name,
                plate.__class__.__name__,
                dims,
                current,
                str(total),
            )

        rprint(table)

    def _ls_liquids(self) -> None:
        """Display all liquid profiles."""
        table = self._build_liquids_table()
        if table is None:
            return
        rprint(table)
        rprint(f"\n[dim]Active liquid: {self.shell._autopipette.active_liquid}[/dim]")

    def _ls_system(self) -> None:
        """Display system configuration summary."""
        ap = self.shell._autopipette
        config = ap.system_config

        table = Table(title="System Configuration", show_header=True)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("System Name", config.system_name)
        table.add_row("Version", config.version)
        table.add_row("", "")

        table.add_row("[bold]Pipette[/bold]", "")
        table.add_row("  Model", ap.pipette_model.name)
        table.add_row("  Design", ap.pipette_model.design_type)
        table.add_row("  Max Volume", f"{ap.syringe.max_volume_ul} µL")
        table.add_row("", "")

        table.add_row("[bold]Active Liquid[/bold]", ap.active_liquid)
        table.add_row("", "")

        table.add_row("[bold]Gantry[/bold]", "")
        table.add_row("  Speed XY", f"{ap.gantry.speed_xy} mm/min")
        table.add_row("  Speed Z", f"{ap.gantry.speed_z} mm/min")
        table.add_row("  Accel Max", f"{ap.gantry.accel_max} mm/s²")
        table.add_row("", "")

        table.add_row("[bold]Network[/bold]", "")
        table.add_row("  Hostname", config.network.get("hostname") or "—")
        table.add_row("  Port", str(config.network.get("port") or "—"))

        rprint(table)

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _build_liquids_table(self) -> Table | None:
        """Build a Rich table of all liquid profiles.

        Returns:
            A populated Table, or None if no profiles are loaded.
        """
        liquids = self.shell._autopipette.system_config.liquids
        active = self.shell._autopipette.active_liquid

        if not liquids:
            rprint("[yellow]No liquid profiles loaded.[/yellow]")
            return None

        table = Table(title="Available Liquid Profiles", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Active", style="green", justify="center")
        table.add_column("Viscosity (cP)", justify="right")
        table.add_column("Custom Speed", justify="center")
        table.add_column("Prewet", justify="center")

        for name, liquid in sorted(liquids.items()):
            is_active = "●" if name == active else ""
            has_custom_speed = "✓" if liquid.speed_aspirate else ""
            prewet = f"{liquid.prewet_cycles}×" if liquid.prewet_recommended else ""

            table.add_row(
                name,
                is_active,
                f"{liquid.viscosity_cP:.2f}" if liquid.viscosity_cP else "—",
                has_custom_speed,
                prewet,
            )

        return table

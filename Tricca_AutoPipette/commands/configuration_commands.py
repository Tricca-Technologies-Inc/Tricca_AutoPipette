"""Configuration-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for managing pipette configuration,
including switching liquids, defining locations and plates, and viewing
configuration state.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from coordinate import Coordinate
from plates import PlateParams
from rich import print as rprint
from rich.table import Table
from well import StrategyType, Well

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import (
    CoorArgs,
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
    - Loading and saving configuration files
    - Listing configuration state

    Example:
        >>> switch_liquid glycerol
        >>> list_liquids
        >>> coor home 0 0 50
        >>> plate my_plate array 8 12
        >>> ls locs
    """

    # Special config variables that generate G-code
    GCODE_GENERATING_VARS = {"SPEED_FACTOR", "VELOCITY_MAX", "ACCEL_MAX"}

    def __init__(self) -> None:
        """Initialize configuration commands."""
        super().__init__()

    # ========================================================================
    # LIQUID PROFILE COMMANDS
    # ========================================================================

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
            rprint("[red]Error: Please specify a liquid name[/red]")
            rprint("[cyan]Usage: switch_liquid <liquid_name>[/cyan]")
            return

        try:
            self.shell._autopipette.switch_liquid(liquid_name)

            # Get liquid info for display
            liquid = self.shell._autopipette.system_config.liquids[liquid_name]

            rprint(f"[green]✓ Switched to liquid: {liquid_name}[/green]")
            rprint(f"  Viscosity: {liquid.viscosity_cP} cP")

            if liquid.speed_aspirate:
                rprint(f"  Aspirate speed: {liquid.speed_aspirate} steps/s")
            if liquid.prewet_recommended:
                rprint(
                    f"  [yellow]⚠ Prewet recommended ({liquid.prewet_cycles} cycles)[/yellow]"
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
        liquids = self.shell._autopipette.system_config.liquids
        active = self.shell._autopipette.active_liquid

        if not liquids:
            rprint("[yellow]No liquid profiles loaded[/yellow]")
            return

        table = Table(title="Available Liquid Profiles", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Active", style="green")
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

        rprint(table)
        rprint(f"\n[dim]Active liquid: {active}[/dim]")

    def do_load_liquid(self, statement: Statement) -> None:
        """Load a new liquid profile from JSON file.

        Dynamically loads a liquid profile and adds it to available liquids.

        Args:
            statement: Command statement containing filename.

        Example:
            >>> load_liquid acetone.json
            >>> load_liquid custom_buffer.json
        """
        filename = statement.arg_list[0] if statement.arg_list else None

        if not filename:
            rprint("[red]Error: Please specify a liquid file[/red]")
            rprint("[cyan]Usage: load_liquid <filename.json>[/cyan]")
            return

        try:
            liquid = self.shell._autopipette.config_manager.load_liquid(filename)
            rprint(f"[green]✓ Loaded liquid profile: {liquid.name}[/green]")
            rprint(f"  Viscosity: {liquid.viscosity_cP} cP")
            rprint(f"  File: {filename}")
            rprint(f"\n[cyan]Use 'switch_liquid {liquid.name}' to activate[/cyan]")
        except FileNotFoundError as e:
            rprint(f"[red]Error: {e}[/red]")
        except ValueError as e:
            rprint(f"[red]Error: Invalid liquid configuration - {e}[/red]")

    # ========================================================================
    # CONFIGURATION VARIABLES
    # ========================================================================

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

        try:
            value = float(args.value)
        except ValueError:
            rprint(f"[red]Error: Invalid value '{args.value}' (must be numeric)[/red]")
            return

        # Map variable names to autopipette methods
        if var_name == "SPEED_FACTOR":
            self.shell._autopipette.set_speed_factor(value)
            rprint(f"[green]✓ Set {var_name} = {value}[/green]")
        elif var_name == "VELOCITY_MAX":
            self.shell._autopipette.set_max_velocity(value)
            rprint(f"[green]✓ Set {var_name} = {value} mm/s[/green]")
        elif var_name == "ACCEL_MAX":
            self.shell._autopipette.set_max_accel(value)
            rprint(f"[green]✓ Set {var_name} = {value} mm/s²[/green]")
        else:
            rprint(f"[yellow]Warning: Unknown variable '{var_name}'[/yellow]")
            rprint("[cyan]Available: SPEED_FACTOR, VELOCITY_MAX, ACCEL_MAX[/cyan]")

    # ========================================================================
    # LOCATION MANAGEMENT
    # ========================================================================

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
            >>> plate my_96well array 8 12 x=100 y=200 z=10
            >>> plate tipbox1 tipbox 8 12 x=50 y=50 z=10
        """
        # Create well template
        well = Well(
            coor=Coordinate(x=args.x, y=args.y, z=args.z),
            dip_top=args.dip_top,
            dip_btm=args.dip_btm if hasattr(args, "dip_btm") else None,
            strategy_type=StrategyType(
                args.dip_func if hasattr(args, "dip_func") else "simple"
            ),
            well_diameter=(
                args.well_diameter if hasattr(args, "well_diameter") else None
            ),
        )

        # Create plate parameters
        plate_params = PlateParams(
            plate_type=args.plate_type,
            well_template=well,
            num_row=args.num_row,
            num_col=args.num_col,
            spacing_row=args.spacing_row if hasattr(args, "spacing_row") else 9.0,
            spacing_col=args.spacing_col if hasattr(args, "spacing_col") else 9.0,
        )

        # Set the plate
        self.shell._autopipette.location_manager.set_plate(args.name, plate_params)

        rprint(f"[green]✓ Created plate '{args.name}'[/green]")
        rprint(f"  Type: {args.plate_type}")
        rprint(
            f"  Dimensions: {args.num_row}×{args.num_col} ({args.num_row * args.num_col} wells)"
        )
        rprint(f"  Position: X={args.x}, Y={args.y}, Z={args.z}")

    @with_argparser(TAPCmdParsers.parser_reset_plate)  # type: ignore[arg-type]
    def do_reset_plate(self, args: ResetPlateArgs) -> None:
        """Reset a specific plate's position to origin.

        Args:
            args: Parsed arguments containing plate name.

        Example:
            >>> reset_plate my_96well
        """
        loc_mgr = self.shell._autopipette.location_manager

        if not loc_mgr.has_location(args.name):
            rprint(f"[red]Error: Location '{args.name}' not found[/red]")
            return

        location = loc_mgr.locations[args.name]

        if not isinstance(location, Plate):
            rprint(f"[red]Error: '{args.name}' is not a plate[/red]")
            return

        location.reset()
        rprint(f"[green]✓ Reset plate '{args.name}' to position 0[/green]")

    def do_reset_plates(self, _: Statement) -> None:
        """Reset all plates to origin position.

        Example:
            >>> reset_plates
        """
        loc_mgr = self.shell._autopipette.location_manager
        plate_names = loc_mgr.get_plate_names()

        if not plate_names:
            rprint("[yellow]No plates to reset[/yellow]")
            return

        for name in plate_names:
            loc_mgr.locations[name].reset()

        rprint(f"[green]✓ Reset {len(plate_names)} plate(s) to origin[/green]")

    # ========================================================================
    # CONFIGURATION FILE MANAGEMENT
    # ========================================================================

    def do_save_locations(self, statement: Statement) -> None:
        """Save current locations to JSON file.

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
        """Load locations from JSON file.

        Args:
            statement: Filename to load.

        Example:
            >>> load_locations my_setup.json
        """
        filename = statement.arg_list[0] if statement.arg_list else None

        if not filename:
            rprint("[red]Error: Please specify a filename[/red]")
            rprint("[cyan]Usage: load_locations <filename.json>[/cyan]")
            return

        try:
            self.shell._autopipette.location_manager.load_from_json(filename)
            rprint(f"[green]✓ Loaded locations from {filename}[/green]")

            # Show summary
            coords = self.shell._autopipette.location_manager.get_coordinate_names()
            plates = self.shell._autopipette.location_manager.get_plate_names()
            rprint(f"  Coordinates: {len(coords)}")
            rprint(f"  Plates: {len(plates)}")

        except FileNotFoundError as e:
            rprint(f"[red]Error: {e}[/red]")
        except ValueError as e:
            rprint(f"[red]Error: Invalid locations file - {e}[/red]")

    # ========================================================================
    # LISTING COMMANDS
    # ========================================================================

    @with_argparser(TAPCmdParsers.parser_ls)  # type: ignore[arg-type]
    def do_ls(self, args: LsArgs) -> None:
        """List configuration variables.

        Categories: locs, locations, plates, liquids, system

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
            rprint(f"[yellow]Unknown category '{var}'[/yellow]")
            rprint("[cyan]Valid categories: locs, plates, liquids, system[/cyan]")

    def _ls_locs(self) -> None:
        """Display all defined locations."""
        loc_mgr = self.shell._autopipette.location_manager
        coord_names = loc_mgr.get_coordinate_names()

        if not coord_names:
            rprint("[yellow]No coordinates defined[/yellow]")
            return

        table = Table(title="Defined Coordinates", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("X", justify="right")
        table.add_column("Y", justify="right")
        table.add_column("Z", justify="right")

        for name in sorted(coord_names):
            location = loc_mgr.locations[name]
            if isinstance(location, Coordinate):
                table.add_row(
                    name,
                    f"{location.x:.2f}",
                    f"{location.y:.2f}",
                    f"{location.z:.2f}",
                )

        rprint(table)

    def _ls_plates(self) -> None:
        """Display all defined plates."""
        loc_mgr = self.shell._autopipette.location_manager
        plate_names = loc_mgr.get_plate_names()

        if not plate_names:
            rprint("[yellow]No plates defined[/yellow]")
            return

        table = Table(title="Defined Plates", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Dimensions", justify="center")
        table.add_column("Current", justify="center")
        table.add_column("Wells", justify="right")

        for name in sorted(plate_names):
            plate = loc_mgr.locations[name]
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
        """Display liquid profiles."""
        self.do_list_liquids(Statement(""))

    def _ls_system(self) -> None:
        """Display system configuration summary."""
        config = self.shell._autopipette.system_config

        table = Table(title="System Configuration", show_header=True)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("System Name", config.system_name)
        table.add_row("Version", config.version)
        table.add_row("", "")

        table.add_row("[bold]Pipette[/bold]", "")
        table.add_row("  Model", self.shell._autopipette.pipette_model.name)
        table.add_row("  Design", self.shell._autopipette.pipette_model.design_type)
        table.add_row(
            "  Max Volume", f"{self.shell._autopipette.syringe.max_volume_ul} µL"
        )
        table.add_row("", "")

        table.add_row(
            "[bold]Active Liquid[/bold]", self.shell._autopipette.active_liquid
        )
        table.add_row("", "")

        table.add_row("[bold]Gantry[/bold]", "")
        table.add_row("  Speed XY", f"{self.shell._autopipette.gantry.speed_xy} mm/min")
        table.add_row("  Speed Z", f"{self.shell._autopipette.gantry.speed_z} mm/min")
        table.add_row(
            "  Accel Max", f"{self.shell._autopipette.gantry.accel_max} mm/s²"
        )
        table.add_row("", "")

        table.add_row("[bold]Network[/bold]", "")
        table.add_row("  Hostname", config.network.get("hostname", "—"))
        table.add_row("  Port", config.network.get("port", "—"))

        rprint(table)

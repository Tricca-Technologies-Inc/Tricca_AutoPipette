"""Configuration-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for managing pipette configuration,
including setting variables, defining locations and plates, and viewing
configuration state.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from coordinate import Coordinate
from pipette_constants import ConfigSection
from plates import Plate, PlateFactory
from rich import print as rprint
from tap_cmd_parsers import (
    CoorArgs,
    LoadConfArgs,
    LsArgs,
    PlateArgs,
    ResetPlateArgs,
    SetArgs,
    TAPCmdParsers,
)
from well import StrategyType, Well

from commands.base_command_set import TAPCommandSet


class ConfigurationCommands(TAPCommandSet):
    """Commands for managing configuration and locations.

    Provides shell commands for:
    - Setting configuration variables (speed, acceleration, etc.)
    - Defining coordinate locations
    - Creating and managing plates
    - Loading and saving configuration files
    - Listing configuration state

    Example:
        >>> set SPEED_FACTOR 150
        >>> coor home 0 0 50
        >>> plate my_plate array 8 12
        >>> ls locs
    """

    # Special config variables that generate G-code
    GCODE_GENERATING_VARS = {"SPEED_FACTOR", "VELOCITY_MAX", "ACCEL_MAX"}

    def __init__(self) -> None:
        """Initialize configuration commands."""
        super().__init__()

    @with_argparser(TAPCmdParsers.parser_set)  # type: ignore[arg-type]
    def do_set(self, args: SetArgs) -> None:
        """Set a configuration variable to a new value.

        Modifies pipette configuration parameters like speed, acceleration,
        or other operational settings. Some variables (SPEED_FACTOR,
        VELOCITY_MAX, ACCEL_MAX) generate immediate G-code commands.

        Args:
            args: Parsed arguments containing variable name and value.

        Example:
            >>> set SPEED_FACTOR 150
            >>> set VELOCITY_MAX 5000
        """
        autopipette = self.shell._autopipette
        pip_var: str = args.pip_var.upper()
        pip_val: float = args.pip_val

        # Build list of valid configuration options
        config = autopipette.config_manager.config
        options: list[str] = []
        for section in config.keys():
            section_keys = list(config[section].keys())
            options.extend(section_keys)
        options = [opt.upper() for opt in options]

        if pip_var not in options:
            rprint(
                f"[yellow]Variable {pip_var} not recognized, "
                f"it could not be set.[/yellow]"
            )
            rprint("[dim]Hint: Use 'ls vars' to see available variables.[/dim]")
            return

        # Handle variables that generate G-code
        if pip_var in self.GCODE_GENERATING_VARS:
            self._set_gcode_variable(pip_var, pip_val)
        else:
            self._set_config_variable(pip_var, pip_val)

    def _set_gcode_variable(self, var_name: str, value: float) -> None:
        """Set a variable that generates G-code commands.

        Args:
            var_name: Variable name (SPEED_FACTOR, VELOCITY_MAX, ACCEL_MAX).
            value: New value to set.
        """
        autopipette = self.shell._autopipette
        config = autopipette.config_manager.config

        # Map variable names to config keys and setter methods
        var_mapping = {
            "SPEED_FACTOR": (
                ConfigSection.SPEED.value,
                "SPEED_FACTOR",
                autopipette.set_speed_factor,
                "SPEED_FACTOR",
            ),
            "VELOCITY_MAX": (
                ConfigSection.SPEED.value,
                "VELOCITY_MAX",
                autopipette.set_max_velocity,
                "MAX_VELOCITY",
            ),
            "ACCEL_MAX": (
                ConfigSection.SPEED.value,
                "ACCEL_MAX",
                autopipette.set_max_accel,
                "MAX_ACCEL",
            ),
        }

        if var_name not in var_mapping:
            return

        section, key, setter_func, display_name = var_mapping[var_name]
        old_value = config[section][key]

        # Generate G-code
        msg = f"; {display_name} changed from {old_value} to {value}\n"
        setter_func(value)
        gcode = autopipette.get_gcode()
        gcode.insert(0, msg)

        self.shell.output_gcode(gcode)
        rprint(f"[green]{display_name} changed from {old_value} to {value}" f"[/green]")

    def _set_config_variable(self, var_name: str, value: float) -> None:
        """Set a configuration variable without generating G-code.

        Args:
            var_name: Variable name.
            value: New value to set.
        """
        autopipette = self.shell._autopipette
        config = autopipette.config_manager.config

        # Find which section contains this variable
        for section in config.keys():
            if var_name in config[section].keys():
                old_value = config[section][var_name]
                autopipette.config_manager.update_value(section, var_name, str(value))
                rprint(
                    f"[green]{var_name} changed from {old_value} " f"to {value}[/green]"
                )
                return

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
        autopipette = self.shell._autopipette
        name_loc: str = args.name_loc
        x: float = args.x
        y: float = args.y
        z: float = args.z

        coordinate = Coordinate(x=x, y=y, z=z)
        autopipette.set_location_coordinate(name_loc, coordinate)

        self.shell.output_gcode([f"; Location:{name_loc} set to x:{x} y:{y} z:{z}\n"])
        rprint(f"[green]Location '{name_loc}' set to " f"x:{x} y:{y} z:{z}[/green]")

    @with_argparser(TAPCmdParsers.parser_plate)  # type: ignore[arg-type]
    def do_plate(self, args: PlateArgs) -> None:
        """Define a plate at a named location.

        Associates a plate type (array, singleton, tipbox, etc.) with a
        location for organized well access.

        Args:
            args: Parsed arguments containing plate configuration.

        Example:
            >>> plate my_96well array 8 12
            >>> plate tipbox1 tipbox 8 12
        """
        autopipette = self.shell._autopipette
        name_loc: str = args.name_loc
        plate_type: str = args.plate_type
        row: int | None = args.row
        col: int | None = args.col
        num_row: int = row if row is not None else 1
        num_col: int = col if col is not None else 1
        # Validate plate type
        if plate_type not in PlateFactory.registered():
            rprint(f"[yellow]Plate type '{plate_type}' does not exist." f"[/yellow]")
            rprint(
                f"[cyan]Valid types: {', '.join(PlateFactory.registered())}" f"[/cyan]"
            )
            return

        # Check if location exists and get coordinate
        if not autopipette.location_manager.has_location(name_loc):
            rprint(
                f"[yellow]Location '{name_loc}' not defined. "
                f"Use 'coor' command first.[/yellow]"
            )
            return

        # Get the coordinate for this location
        coordinate = autopipette.location_manager.get_coordinate(name_loc)

        # Create plate parameters with defaults
        from plates import PlateParams

        well_template = Well(
            coor=coordinate,
            dip_top=0.0,
            dip_btm=None,
            strategy_type=StrategyType.SIMPLE,  # ✅ Use enum default
            well_diameter=None,
        )

        plate_params = PlateParams(
            plate_type=plate_type,
            well_template=well_template,
            num_row=num_row,
            num_col=num_col,
            spacing_row=0.0,
            spacing_col=0.0,
        )

        autopipette.set_location_plate(name_loc, plate_params)

        rprint(
            f"[green]Location '{name_loc}' configured as {plate_type} "
            f"plate with {row} rows × {col} columns[/green]"
        )

    @with_argparser(TAPCmdParsers.parser_reset_plate)  # type: ignore[arg-type]
    def do_reset_plate(self, args: ResetPlateArgs) -> None:
        """Reset a specific plate's position to origin.

        Args:
            args: Parsed arguments containing plate name.

        Example:
            >>> reset_plate my_96well
        """
        autopipette = self.shell._autopipette
        plate: str = args.plate

        if plate not in autopipette.get_plate_locations():
            rprint(f"[yellow]'{plate}' is not a plate.[/yellow]")
            rprint("[dim]Hint: Use 'ls plates' to see available plates.[/dim]")
            return

        # Reset plate position via location manager
        plate_obj = autopipette.location_manager.locations[plate]
        if isinstance(plate_obj, Plate):
            plate_obj.curr = 0
            rprint(f"[green]Plate '{plate}' reset to origin.[/green]")

    def do_reset_plates(self, _: Statement) -> None:
        """Reset all plates to origin position.

        Example:
            >>> reset_plates
        """
        autopipette = self.shell._autopipette
        plate_count = 0

        for location_name in autopipette.get_plate_locations():
            location = autopipette.location_manager.locations[location_name]
            if isinstance(location, Plate):
                location.curr = 0
                plate_count += 1

        if plate_count == 0:
            rprint("[yellow]No plates to reset.[/yellow]")
        else:
            rprint(f"[green]All {plate_count} plate(s) reset to origin." f"[/green]")

    def do_save(self, _: Statement) -> None:
        """Save current configuration to file.

        Example:
            >>> save
        """
        autopipette = self.shell._autopipette
        try:
            autopipette.save_config_file()
            rprint("[green]Configuration saved successfully.[/green]")
        except Exception as e:
            rprint(f"[red]Error saving configuration: {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_load_conf)  # type: ignore[arg-type]
    def do_load_conf(self, args: LoadConfArgs) -> None:
        """Load a new configuration file.

        Args:
            args: Parsed arguments containing filename.

        Example:
            >>> load_conf alternate.conf
        """
        autopipette = self.shell._autopipette
        filename: str = args.filename

        try:
            autopipette.load_config_file(filename)
            rprint(f"[green]Configuration loaded from '{filename}'.[/green]")
        except FileNotFoundError:
            rprint(f"[red]Configuration file '{filename}' not found.[/red]")
        except Exception as e:
            rprint(f"[red]Error loading config: {e}[/red]")

    # List commands
    @with_argparser(TAPCmdParsers.parser_ls)  # type: ignore[arg-type]
    def do_ls(self, args: LsArgs) -> None:
        """List configuration variables.

        Categories: locs, locations, plates, vars, conf, config, vol, volume

        Args:
            args: Parsed arguments containing category to list.

        Example:
            >>> ls locs
            >>> ls plates
            >>> ls vars
        """
        var: str = args.var.lower()

        ls_commands = {
            "locs": self._ls_locs,
            "locations": self._ls_locs,
            "plates": self._ls_plates,
            "vars": self._ls_vars,
            "conf": self._ls_conf,
            "config": self._ls_conf,
            "vol": self._ls_vol,
            "volume": self._ls_vol,
        }

        if var in ls_commands:
            ls_commands[var]()
        else:
            rprint(f"[yellow]Unknown category '{var}'.[/yellow]")
            rprint("[cyan]Valid categories: locs, plates, vars, conf, vol" "[/cyan]")

    def _ls_locs(self) -> None:
        """Display all defined locations and their parameters."""
        autopipette = self.shell._autopipette
        locations = autopipette.location_manager.locations

        if not locations:
            rprint("[yellow]No locations defined.[/yellow]")
            rprint(
                "[dim]Hint: Use 'coor <name> <x> <y> <z>' to define a "
                "location.[/dim]"
            )
            return

        rprint(f"[bold]Defined Locations ({len(locations)}):[/bold]\n")

        for loc_name, location in locations.items():
            # Determine icon based on type
            if isinstance(location, Plate):
                icon = "📋"
                type_str = "Plate"
            else:
                icon = "📍"
                type_str = "Coordinate"

            rprint(f"{icon} [bold cyan]{loc_name}[/bold cyan] [{type_str}]")

            # Get config section
            if isinstance(location, Coordinate):
                key = f"COORDINATE {loc_name}"
            elif isinstance(location, Plate):
                key = f"PLATE {loc_name}"
            else:
                continue

            # Check if section exists and is a dict
            if key in autopipette.config_manager.config:
                config_section = autopipette.config_manager.config[key]
                # ConfigParser sections are dict-like
                if hasattr(config_section, "items"):
                    for var, val in config_section.items():
                        rprint(f"  {var}: {val}")
            rprint()  # Blank line between locations

    def _ls_plates(self) -> None:
        """Display all defined plates and their parameters."""
        autopipette = self.shell._autopipette
        plates = autopipette.get_plate_locations()

        if not plates:
            rprint("[yellow]No plates defined.[/yellow]")
            rprint(
                "[dim]Hint: Use 'plate <name> <type> <rows> <cols>' to "
                "define a plate.[/dim]"
            )
            return

        rprint(f"[bold]Defined Plates ({len(plates)}):[/bold]\n")

        for plate in plates:
            rprint(f"📋 [bold cyan]{plate}[/bold cyan]")
            key = f"PLATE {plate}"

            # Check if section exists and is a dict
            if key in autopipette.config_manager.config:
                config_section = autopipette.config_manager.config[key]
                if hasattr(config_section, "items"):
                    for var, val in config_section.items():
                        rprint(f"  {var}: {val}")
            rprint()  # Blank line between plates

    def _ls_vars(self) -> None:
        """Display all configuration variables (excluding coordinates)."""
        autopipette = self.shell._autopipette
        config = autopipette.config_manager.config

        # Filter out coordinate/plate sections and volume conversion
        filtered_sections = {
            key: value
            for key, value in config.items()
            if not key.startswith("COORDINATE")
            and not key.startswith("PLATE")
            and key != ConfigSection.VOLUME_CONV.value
        }

        if not filtered_sections:
            rprint("[yellow]No configuration variables found.[/yellow]")
            return

        rprint("[bold]Configuration Variables:[/bold]\n")

        for section, params in filtered_sections.items():
            rprint(f"[bold cyan][{section}][/bold cyan]")
            # ConfigParser sections are dict-like
            if hasattr(params, "items"):
                for var, val in params.items():
                    rprint(f"  {var} = {val}")
            rprint()  # Blank line between sections

    def _ls_conf(self) -> None:
        """Display complete configuration."""
        autopipette = self.shell._autopipette
        config = autopipette.config_manager.config

        rprint("[bold]Complete Configuration:[/bold]\n")

        for section, params in config.items():
            rprint(f"[bold cyan][{section}][/bold cyan]")
            # ConfigParser sections are dict-like
            if hasattr(params, "items"):
                for key, val in params.items():
                    rprint(f"  {key} = {val}")
            rprint()  # Blank line between sections

    def _ls_vol(self) -> None:
        """Display volume conversion parameters."""
        autopipette = self.shell._autopipette
        config = autopipette.config_manager.config

        vol_section = ConfigSection.VOLUME_CONV.value
        rprint(f"[bold cyan][{vol_section}][/bold cyan]")

        # Check if section exists
        if vol_section not in config:
            rprint("[yellow]  No volume conversion data found.[/yellow]")
            return

        vol_config = config[vol_section]

        # ConfigParser sections are dict-like
        if hasattr(vol_config, "items"):
            for var, val in vol_config.items():
                rprint(f"  {var} = {val}")
        else:
            rprint("[yellow]  Invalid volume conversion data.[/yellow]")

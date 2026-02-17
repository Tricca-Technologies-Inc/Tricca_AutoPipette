#!/usr/bin/env python3
"""Configuration management for the AutoPipette system.

This module handles loading, parsing, validating, and saving configuration
files for the pipette system.
"""

from __future__ import annotations

import logging
from configparser import ConfigParser, ExtendedInterpolation, SectionProxy
from pathlib import Path

from coordinate import Coordinate
from pipette_constants import ConfigSection, DefaultPaths
from pipette_exceptions import MissingConfigError
from pipette_models import PipetteParams
from plates import PlateParams
from well import StrategyType, Well

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration file operations for the AutoPipette.

    Handles loading, parsing, validation, and saving of INI-format
    configuration files. Extracts pipette parameters and location
    definitions from configuration sections.

    Attributes:
        config: ConfigParser instance with loaded configuration.
        config_path: Path to the directory containing config files.
        config_file: Name of the currently loaded config file.

    Example:
        >>> manager = ConfigManager()
        >>> manager.load("autopipette.conf")
        >>> params = manager.get_pipette_params()
        >>> locations = manager.get_locations()
    """

    def __init__(
        self, config_path: Path | None = None, config_file: str | None = None
    ) -> None:
        """Initialize the configuration manager.

        Args:
            config_path: Directory containing config files, or None for default.
            config_file: Config filename to load immediately, or None.

        Example:
            >>> # Use defaults
            >>> manager = ConfigManager()

            >>> # Custom path and immediate load
            >>> manager = ConfigManager(
            ...     config_path=Path("/custom/path"),
            ...     config_file="my_config.conf"
            ... )
        """
        self.config = ConfigParser(interpolation=ExtendedInterpolation())
        self.config_path = config_path or DefaultPaths.CONFIG_DIR
        self.config_file: str | None = None

        if config_file is not None:
            self.load(config_file)

    def load(self, filename: str) -> None:
        """Load and validate a configuration file.

        Args:
            filename: Name of the config file (relative to config_path).

        Raises:
            RuntimeError: If configuration file not found.
            MissingConfigError: If required sections are missing.

        Example:
            >>> manager = ConfigManager()
            >>> manager.load("autopipette.conf")
        """
        file_path = self.config_path / filename

        try:
            with file_path.open("r", encoding="utf-8") as f:
                self.config.read_file(f)
        except FileNotFoundError as e:
            logger.critical("Missing configuration file: %s", file_path)
            raise RuntimeError(f"Configuration file not found: {file_path}") from e

        # Validate required sections
        required = [section.value for section in ConfigSection]
        missing = list(set(required) - set(self.config.sections()))

        if missing:
            raise MissingConfigError(missing[0], str(file_path))

        self.config_file = filename
        logger.info(f"Loaded configuration from {filename}")

    def save(self, filename: str | None = None) -> None:
        """Save current configuration to a file.

        Args:
            filename: Output filename, or None to use current filename + '-test'.

        Note:
            Saves to the config_path directory.

        Raises:
            RuntimeError: If no config file loaded and no filename provided

        Example:
            >>> manager.save("backup.conf")
        """
        if filename is None:
            if self.config_file is None:
                raise RuntimeError("No config file loaded and no filename provided")
            filename = self.config_file + "-test"

        output_path = self.config_path / filename

        with open(output_path, "w", encoding="utf-8") as f:
            self.config.write(f)

        logger.info(f"Configuration saved to {output_path}")

    def get_default_pipette_params(self) -> PipetteParams:
        """Return default pipette configuration parameters.

        Creates and returns a new `PipetteParams` instance using the model's default
        field values.

        Returns:
            PipetteParams: A `PipetteParams` object populated with default settings.
        """
        return PipetteParams()

    def get_pipette_params(self) -> PipetteParams:
        """Extract and validate pipette parameters from configuration.

        Returns:
            Validated PipetteParams object.

        Example:
            >>> params = manager.get_pipette_params()
            >>> print(params.speed_xy)
            5000
        """

        # Helper to get int with error checking
        def get_required_int(section: str, key: str) -> int:
            """Get required integer config value.

            Args:
                section: Config section name.
                key: Config key name.

            Returns:
                Integer value.

            Raises:
                ValueError: If value is missing or invalid.
            """
            value = self.config[section].getint(key)
            if value is None:
                raise ValueError(f"Missing required config value: [{section}] {key}")
            return value

        return PipetteParams(
            name_pipette_servo=self.config["NAME"]["NAME_PIPETTE_SERVO"],
            name_pipette_stepper=self.config["NAME"]["NAME_PIPETTE_STEPPER"],
            speed_xy=get_required_int("SPEED", "SPEED_XY"),
            speed_z=get_required_int("SPEED", "SPEED_Z"),
            speed_pipette_down=get_required_int("SPEED", "SPEED_PIPETTE_DOWN"),
            speed_pipette_up=get_required_int("SPEED", "SPEED_PIPETTE_UP"),
            speed_pipette_up_slow=get_required_int("SPEED", "SPEED_PIPETTE_UP_SLOW"),
            speed_max=get_required_int("SPEED", "SPEED_MAX"),
            speed_factor=get_required_int("SPEED", "SPEED_FACTOR"),
            velocity_max=get_required_int("SPEED", "VELOCITY_MAX"),
            accel_pipette_home=get_required_int("SPEED", "ACCEL_PIPETTE_HOME"),
            accel_pipette_move=get_required_int("SPEED", "ACCEL_PIPETTE_MOVE"),
            accel_gantry_max=get_required_int("SPEED", "ACCEL_MAX"),
            servo_angle_retract=get_required_int("SERVO", "SERVO_ANGLE_RETRACT"),
            servo_angle_eject=get_required_int("SERVO", "SERVO_ANGLE_READY"),
            wait_eject=get_required_int("WAIT", "WAIT_EJECT"),
            wait_movement=get_required_int("WAIT", "WAIT_MOVEMENT"),
            wait_aspirate=get_required_int("WAIT", "WAIT_ASPIRATE"),
            max_vol=get_required_int("VOLUME_CONV", "max_vol"),
        )

    def get_volume_calibration(self) -> tuple[list[float], list[float]]:
        """Extract volume-to-steps calibration data.

        Returns:
            Tuple of (volumes, steps) as lists of floats.

        Example:
            >>> volumes, steps = manager.get_volume_calibration()
            >>> # volumes = [0, 100, 200], steps = [0, 500, 1000]
        """
        volumes = list(map(float, self.config["VOLUME_CONV"]["volumes"].split(",")))
        steps = list(map(float, self.config["VOLUME_CONV"]["steps"].split(",")))
        return volumes, steps

    def parse_locations(self) -> dict[str, tuple[Coordinate, PlateParams | None]]:
        """Parse all coordinate and plate locations from configuration.

        Returns:
            Dictionary mapping location names to (Coordinate, PlateParams).
            For simple coordinates, PlateParams will be None.
            For plates, PlateParams contains plate configuration.

        Raises:
            ValueError: If invalid dipping strategy is specified.

        Example:
            >>> locations = manager.parse_locations()
            >>> for name, (coord, plate_params) in locations.items():
            ...     if plate_params is None:
            ...         print(f"{name}: simple coordinate")
            ...     else:
            ...         print(f"{name}: plate with {plate_params.num_row} rows")
        """
        locations: dict[str, tuple[Coordinate, PlateParams | None]] = {}

        # Helper to get required float value
        def get_required_float(section_dict: SectionProxy, key: str) -> float:
            """Get required float config value.

            Args:
                section_dict: ConfigParser section containing the key.
                key: Configuration key name.

            Returns:
                Float value from configuration.

            Raises:
                ValueError: If the key is missing or value is None.
            """
            value = section_dict.getfloat(key)
            if value is None:
                raise ValueError(f"Missing required coordinate value: {key}")
            return value

        # Define expected plate parameters with type converters
        plate_params_spec = {
            "type": (str, None),
            "row": (int, None),
            "col": (int, None),
            "spacing_row": (float, None),
            "spacing_col": (float, None),
            "dip_top": (float, None),
            "dip_btm": (float, None),
            "dip_func": (str, None),
            "well_diameter": (float, None),
        }

        # Required sections to skip
        required_sections = [section.value for section in ConfigSection]

        for section in set(self.config.sections()) - set(required_sections):
            # Only process coordinate and plate sections
            if not (section.startswith("COORDINATE ") or section.startswith("PLATE ")):
                continue

            try:
                _, name_loc = section.split(maxsplit=1)
                coord_section = self.config[section]
            except ValueError:
                logger.warning(f"Skipping malformed section: {section}")
                continue

            # Parse base coordinate
            coord = Coordinate(
                x=get_required_float(coord_section, "x"),
                y=get_required_float(coord_section, "y"),
                z=get_required_float(coord_section, "z"),
            )

            # If just a coordinate section, store with no plate params
            if section.startswith("COORDINATE "):
                locations[name_loc] = (coord, None)
                continue

            # Extract plate parameters
            params = {}
            for key, (converter, _) in plate_params_spec.items():
                if key in coord_section:
                    params[key] = converter(coord_section[key])

            # Validate dipping strategy
            dip_func_str: str = params.get("dip_func", "simple")
            if dip_func_str not in [strat.value for strat in StrategyType]:
                raise ValueError(
                    f"Strategy '{dip_func_str}' is not a valid dip strategy. "
                    f"Valid options: {[s.value for s in StrategyType]}"
                )

            # Create well template
            well = Well(
                coor=coord,
                dip_top=params.get("dip_top", 0),
                dip_btm=params.get("dip_btm", None),
                strategy_type=StrategyType(dip_func_str),
                well_diameter=params.get("well_diameter", None),
            )

            # Create plate parameters
            plate_params = PlateParams(
                plate_type=params.get("type", "singleton"),
                well_template=well,
                num_row=params.get("row", 1),
                num_col=params.get("col", 1),
                spacing_row=params.get("spacing_row", 0.0),
                spacing_col=params.get("spacing_col", 0.0),
            )

            locations[name_loc] = (coord, plate_params)

        return locations

    def get_all_sections_as_dict(self) -> dict[str, dict[str, str]]:
        """Get all configuration sections as nested dictionaries.

        Returns:
            Dictionary mapping section names to key-value dictionaries.

        Example:
            >>> sections = manager.get_all_sections_as_dict()
            >>> print(sections["SPEED"]["SPEED_XY"])
            '5000'
        """
        return {
            section: dict(self.config[section].items())
            for section in self.config.sections()
        }

    def update_value(self, section: str, key: str, value: str) -> None:
        """Update a configuration value.

        Args:
            section: Configuration section name.
            key: Configuration key name.
            value: New value (will be converted to string).

        Note:
            Changes are in memory only until save() is called.

        Example:
            >>> manager.update_value("SPEED", "SPEED_XY", "6000")
            >>> manager.save()
        """
        if not self.config.has_section(section):
            self.config.add_section(section)

        self.config.set(section, key, str(value))

#!/usr/bin/env python3
"""Constants and enumerations for the AutoPipette system.

This module defines all constant values, magic numbers, and enumerations
used throughout the pipette control system.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

__all__ = [
    "CoordinateSystem",
    "PlateType",
    "GCodeCommand",
    "PhysicalConstants",
    "DefaultFilenames",
    "DefaultPaths",
    "ConfigKey",
]


class CoordinateSystem(str, Enum):
    """Coordinate system modes for motion commands.

    Attributes:
        ABSOLUTE: Coordinates are absolute positions (G90).
        RELATIVE: Coordinates are offsets from current position (G91).

    Example:
        >>> mode = CoordinateSystem.ABSOLUTE
        >>> print(mode.value)  # "absolute"
    """

    ABSOLUTE = "absolute"
    RELATIVE = "relative"


class PlateType(str, Enum):
    """Special plate type identifiers.

    These types receive special handling during configuration.

    Attributes:
        WASTE_CONTAINER: Waste disposal location for used tips.
        TIPBOX: Tip storage for automatic tip pickup.
        ARRAY: Standard well plate or array.
    """

    WASTE_CONTAINER = "waste_container"
    TIPBOX = "tipbox"
    ARRAY = "array"


class GCodeCommand:
    """G-code command constants.

    Standard G-code commands used for pipette control.

    Example:
        >>> from pipette_constants import GCodeCommand
        >>> home_cmd = GCodeCommand.HOME_ALL
        >>> print(home_cmd)  # "G28"
    """

    # Coordinate systems
    ABSOLUTE_MODE = "G90"
    RELATIVE_MODE = "G91"

    # Homing
    HOME_ALL = "G28"
    HOME_X = "G28 X"
    HOME_Y = "G28 Y"
    HOME_Z = "G28 Z"

    # Movement
    LINEAR_MOVE = "G1"

    # Timing
    DWELL = "G4"

    # Display
    DISPLAY_MESSAGE = "M117"

    # Speed control
    SPEED_FACTOR = "M220"


class PhysicalConstants:
    """Physical measurement constants.

    Default values for movements and tolerances.

    Attributes:
        WIGGLE_OFFSET_MM: Offset for wiggle motion in millimeters.
        VOLUME_TOLERANCE_UL: Minimum significant volume in microliters.
    """

    WIGGLE_OFFSET_MM = 1.0  # Offset for wiggle motion in millimeters
    VOLUME_TOLERANCE_UL = 1e-6  # Minimum significant volume in microliters


class DefaultFilenames:
    """Default filenames for configuration files.

    These are the default names for configuration files if not specified
    by the user.

    Attributes:
        CONFIG_SYSTEM: Default system configuration filename.
        CONFIG_GANTRY: Default gantry configuration filename.
        CONFIG_PIPETTE: Default pipette configuration filename.
        CONFIG_LOCATIONS: Default locations configuration filename.
        CONFIG_LIQUIDS: Default liquids configuration filename.
    """

    CONFIG_SYSTEM = "default_system.json"
    CONFIG_GANTRY = "default_gantry.json"
    CONFIG_PIPETTE = "default_pipette.json"
    CONFIG_LOCATIONS = "default_locations.json"
    CONFIG_LIQUIDS = "default_liquids.json"


class DefaultPaths:
    """Default file paths for configuration and data.

    Attributes:
        CONFIG_DIR: Directory containing configuration files.
        DEFAULT_CONFIG: Default configuration filename.
    """

    DIR_SHELL: Path = Path(__file__).parent
    DIR_GCODE: Path = Path(__file__).parent.parent / "gcode"
    DIR_PROTOCOL: Path = Path(__file__).parent.parent / "protocols"
    DIR_CONFIG: Path = Path(__file__).parent.parent / "config/"
    DIR_CONFIG_SYSTEM: Path = DIR_CONFIG / "system/"
    DIR_CONFIG_GANTRY: Path = DIR_CONFIG / "gantry/"
    DIR_CONFIG_PIPETTE: Path = DIR_CONFIG / "pipettes/"
    DIR_CONFIG_LOCATIONS: Path = DIR_CONFIG / "locations/"
    DIR_CONFIG_LIQUIDS: Path = DIR_CONFIG / "liquids/"
    DIR_CONFIG_PLATES: Path = DIR_CONFIG / "plates/"


class ConfigKey:
    """Configuration file key names.

    Organized by section for easy reference. Use these constants
    instead of hardcoding configuration key strings.

    Example:
        >>> from pipette_constants import ConfigKey
        >>> speed_key = ConfigKey.Speed.XY
        >>> print(speed_key)  # "SPEED_XY"
    """

    class Network:
        """Network configuration keys."""

        IP = "IP"
        HOSTNAME = "HOSTNAME"

    class Name:
        """Motor name configuration keys."""

        PIPETTE_SERVO = "NAME_PIPETTE_SERVO"
        PIPETTE_STEPPER = "NAME_PIPETTE_STEPPER"

    class Speed:
        """Speed configuration keys."""

        XY = "SPEED_XY"
        Z = "SPEED_Z"
        PIPETTE_DOWN = "SPEED_PIPETTE_DOWN"
        PIPETTE_UP = "SPEED_PIPETTE_UP"
        PIPETTE_UP_SLOW = "SPEED_PIPETTE_UP_SLOW"
        MAX = "SPEED_MAX"
        FACTOR = "SPEED_FACTOR"
        VELOCITY_MAX = "VELOCITY_MAX"
        ACCEL_MAX = "ACCEL_MAX"

    class Servo:
        """Servo configuration keys."""

        ANGLE_RETRACT = "SERVO_ANGLE_RETRACT"
        ANGLE_EJECT = "SERVO_ANGLE_EJECT"

    class Wait:
        """Timing configuration keys."""

        EJECT = "WAIT_EJECT"
        MOVEMENT = "WAIT_MOVEMENT"
        ASPIRATE = "WAIT_ASPIRATE"

    class VolumeConv:
        """Volume conversion configuration keys."""

        MAX_VOL = "max_vol"
        VOLUMES = "volumes"
        STEPS = "steps"

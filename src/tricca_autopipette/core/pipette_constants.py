#!/usr/bin/env python3
"""Constants and enumerations for the AutoPipette system.

This module defines all constant values, magic numbers, and enumerations
used throughout the pipette control system.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

__all__ = [
    "ConfigKey",
    "CoordinateSystem",
    "DefaultFilenames",
    "DefaultPaths",
    "GCodeCommand",
    "HomingTargets",
    "PhysicalConstants",
    "PlateType",
    "TriggerChannels",
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


class HomingTargets:
    """Motor-name lookup tables for the ``home``/``init`` commands.

    Shared between ``commands/movement_commands.py`` (the cmd2 adapter) and
    ``daemon/service.py`` (``AutoPipetteService.home``/``init``, the
    business-logic owner) so both stay in sync without either importing
    from the other.

    Attributes:
        MOTOR_METHODS: Maps motor name to (output filename, ``AutoPipette``
            method name) for motors that map directly to a single method.
        MOTOR_SPECIAL: Motor names that don't map to a single method --
            ``"all"`` delegates to ``AutoPipette.init_pipette()`` instead.
        VALID_MOTORS: Combined set of all valid motor names, kept in sync
            with ``MOTOR_METHODS``/``MOTOR_SPECIAL`` manually.
    """

    MOTOR_METHODS: dict[str, tuple[str, str]] = {
        "x": ("home_x.gcode", "home_x"),
        "y": ("home_y.gcode", "home_y"),
        "z": ("home_z.gcode", "home_z"),
        "pipette": ("home_pipette.gcode", "home_pipette_motors"),
        "axis": ("home_axis.gcode", "home_axis"),
        "servo": ("home_servo.gcode", "home_servo"),
    }

    MOTOR_SPECIAL: dict[str, str] = {
        "all": "home_all.gcode",
    }

    VALID_MOTORS: frozenset[str] = frozenset({
        "x",
        "y",
        "z",
        "pipette",
        "axis",
        "servo",
        "all",
    })


class TriggerChannels:
    """Valid channel/state names for the (not-yet-implemented) ``trigger`` command.

    Shared between ``commands/utility_commands.py`` (the cmd2 adapter) and
    ``daemon/service.py`` (``AutoPipetteService.trigger``) for the same
    reason as :class:`HomingTargets`.
    """

    VALID_CHANNELS: frozenset[str] = frozenset({"air", "shake", "aux"})
    VALID_STATES: frozenset[str] = frozenset({"on", "off"})


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

    # Four levels up: core -> tricca_autopipette -> src -> repo root. Only
    # correct when running from a src-layout checkout; installed packages
    # (Nix, pip, wheel) drop the "src" segment, so this lands one directory
    # too high with no config/protocols/gcode underneath it. Override with
    # AUTOPIPETTE_REPO_ROOT wherever the package is actually installed.
    DIR_REPO_ROOT: Path = Path(
        os.environ.get("AUTOPIPETTE_REPO_ROOT", str(Path(__file__).parents[3]))
    )

    DIR_SHELL: Path = Path(__file__).parent
    DIR_GCODE: Path = DIR_REPO_ROOT / "gcode"
    DIR_PROTOCOL: Path = DIR_REPO_ROOT / "protocols"
    DIR_CONFIG: Path = DIR_REPO_ROOT / "config/"
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

#!/usr/bin/env python3
"""Constants and enumerations for the AutoPipette system.

This module defines all constant values, magic numbers, and enumerations
used throughout the pipette control system.
"""

from enum import Enum
from pathlib import Path


class CoordinateSystem(str, Enum):
    """Coordinate system modes for motion commands.

    Attributes:
        ABSOLUTE: Coordinates are absolute positions (G90).
        RELATIVE: Coordinates are offsets from current position (G91).
    """

    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    INCREMENTAL = "incremental"  # Alias for RELATIVE


class ConfigSection(str, Enum):
    """Required configuration file sections.

    These sections must be present in the configuration file for
    the pipette to initialize properly.
    """

    NETWORK = "NETWORK"
    NAME = "NAME"
    BOUNDARY = "BOUNDARY"
    SPEED = "SPEED"
    SERVO = "SERVO"
    WAIT = "WAIT"
    VOLUME_CONV = "VOLUME_CONV"


class PlateType(str, Enum):
    """Special plate type identifiers.

    These types receive special handling during configuration.
    """

    WASTE_CONTAINER = "waste_container"
    TIPBOX = "tipbox"
    ARRAY = "array"


# G-code Commands
class GCodeCommand:
    """G-code command constants.

    Standard G-code commands used for pipette control.
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


# Physical Constants
class PhysicalConstants:
    """Physical measurement constants.

    Default values for movements and tolerances.
    """

    WIGGLE_OFFSET_MM = 1.0  # Offset for wiggle motion in millimeters
    VOLUME_TOLERANCE_UL = 1e-6  # Minimum significant volume in microliters


# File Paths
class DefaultPaths:
    """Default file paths for configuration and data.

    Attributes:
        CONFIG_DIR: Directory containing configuration files.
        DEFAULT_CONFIG: Default configuration filename.
    """

    CONFIG_DIR = Path(__file__).parent.parent / "conf"
    DEFAULT_CONFIG = "autopipette.conf"


# Configuration Keys
class ConfigKey:
    """Configuration file key names.

    Organized by section for easy reference.
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
        ANGLE_READY = "SERVO_ANGLE_READY"

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

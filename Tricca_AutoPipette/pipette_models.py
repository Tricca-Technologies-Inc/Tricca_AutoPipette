#!/usr/bin/env python3
"""Data models for AutoPipette configuration and state.

This module contains Pydantic models and dataclasses for pipette configuration
parameters and runtime state tracking.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


class PipetteParams(BaseModel):
    """Pipette configuration parameters with validation.

    Validates all pipette operational parameters including speeds, servo
    angles, timing, and capacity limits. Uses Pydantic for automatic
    validation and type checking.

    Attributes:
        name_pipette_servo: Servo motor identifier for tip ejection.
        name_pipette_stepper: Stepper motor identifier for plunger control.
        speed_xy: Horizontal movement speed in mm/min.
        speed_z: Vertical movement speed in mm/min.
        speed_pipette_down: Plunger descending speed in steps/s.
        speed_pipette_up: Plunger ascending speed in steps/s.
        speed_pipette_up_slow: Slow plunger ascension speed in steps/s.
        speed_max: Maximum system speed in mm/s.
        speed_factor: Speed multiplier factor (1-200%).
        velocity_max: Maximum velocity limit in mm/s.
        accel_max: Maximum acceleration limit in mm/s².
        servo_angle_retract: Retracted servo position in degrees (20-160°).
        servo_angle_eject: Ready servo position in degrees (20-160°).
        wait_eject: Ejection dwell time in milliseconds.
        wait_movement: Movement stabilization time in milliseconds.
        wait_aspirate: Aspiration dwell time in milliseconds.
        max_vol: Maximum pipette volume capacity in microliters.

    Example:
        >>> params = PipetteParams(
        ...     name_pipette_servo="tip_servo",
        ...     name_pipette_stepper="plunger_motor",
        ...     speed_xy=5000,
        ...     speed_z=2000,
        ...     # ... other required params
        ... )
    """

    # Motor identifiers
    name_pipette_servo: str = Field(
        default="pipette_servo",
        min_length=1,
        description="Servo motor identifier for tip ejection",
    )
    name_pipette_stepper: str = Field(
        default="pipette_stepper",
        min_length=1,
        description="Stepper motor identifier for plunger control",
    )

    # Speed parameters (mm/s or steps/s)
    speed_xy: int = Field(
        default=2500, gt=0, description="Horizontal movement speed in mm/s"
    )
    speed_z: int = Field(
        default=10000, gt=0, description="Vertical movement speed in mm/s"
    )
    speed_pipette_down: int = Field(
        default=200, gt=0, description="Plunger descending speed in steps/s"
    )
    speed_pipette_up: int = Field(
        default=200, gt=0, description="Plunger ascending speed in steps/s"
    )
    speed_pipette_up_slow: int = Field(
        default=30, gt=0, description="Slow plunger ascension speed in steps/s"
    )
    speed_max: int = Field(
        default=99999, gt=0, description="Maximum system speed in mm/s"
    )

    # Configuration parameters
    speed_factor: int = Field(
        default=100, ge=1, le=200, description="Speed multiplier factor (1-200%)"
    )
    velocity_max: int = Field(
        default=40000, gt=0, description="Maximum velocity limit in mm/s"
    )
    accel_pipette_home: int = Field(
        default=800, gt=0, description="Acceleration when homing."
    )
    accel_pipette_move: int = Field(
        default=800, gt=0, description="Acceleration when moving the pipette."
    )
    accel_gantry_max: int = Field(
        default=40000, gt=0, description="Maximum acceleration limit in mm/s²"
    )

    # Servo parameters (degrees)
    servo_angle_retract: int = Field(
        default=60,
        ge=20,
        le=160,
        description="Retracted servo position in degrees (20-160°)",
    )
    servo_angle_eject: int = Field(
        default=60,
        ge=20,
        le=160,
        description="Ready servo position in degrees (20-160°)",
    )

    # Timing parameters (milliseconds)
    wait_eject: int = Field(
        default=200, ge=0, description="Ejection dwell time in milliseconds"
    )
    wait_movement: int = Field(
        default=100, ge=0, description="Movement stabilization time in milliseconds"
    )
    wait_aspirate: int = Field(
        default=100, ge=0, description="Aspiration dwell time in milliseconds"
    )

    # Capacity parameters
    max_vol: int = Field(
        default=100, gt=0, description="Maximum pipette volume capacity in microliters"
    )


@dataclass
class PipetteState:
    """Runtime state of the pipette system.

    Tracks the current operational state of the pipette including tip
    attachment, liquid presence, and homing status.

    Attributes:
        has_tip: Whether a tip is currently attached.
        has_liquid: Whether liquid is currently in the tip.
        homed: Whether the pipette has been homed.

    Example:
        >>> state = PipetteState()
        >>> state.has_tip = True
        >>> state.homed = True
    """

    has_tip: bool = False
    has_liquid: bool = False
    homed: bool = False

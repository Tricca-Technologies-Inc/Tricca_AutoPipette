"""Data models for AutoPipette JSON configuration.

This module defines Pydantic models for the JSON-based configuration system,
including gantry kinematics, pipette models, liquid profiles, and system-wide
configuration.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic.dataclasses import dataclass


class TipState(str, Enum):
    """State of tip attachment.

    Attributes:
        ATTACHED: Tip is confirmed to be attached.
        DETACHED: Tip is confirmed to be detached.
        UNKNOWN: Tip state is unknown (e.g., after power on, manual intervention).
    """

    ATTACHED = "attached"
    DETACHED = "detached"
    UNKNOWN = "unknown"


@dataclass
class PipetteState:
    """Runtime state of the pipette system.

    Tracks the current operational state of the pipette including tip
    attachment, liquid presence, and homing status.

    Attributes:
        tip_state: Current tip attachment state.
        has_liquid: Whether liquid is currently in the tip.
        homed: Whether the pipette has been homed.

    Example:
        >>> state = PipetteState()
        >>> state.tip_state = TipState.ATTACHED
        >>> state.homed = True
        >>>
        >>> if state.tip_state == TipState.UNKNOWN:
        ...     print("Tip state uncertain, recommend manual check")
    """

    tip_state: TipState = TipState.UNKNOWN
    has_liquid: bool = False
    homed: bool = False

    # Helper properties for backwards compatibility
    @property
    def has_tip(self) -> bool:
        """Check if tip is attached (True if ATTACHED, False otherwise).

        Returns:
            True if tip_state is ATTACHED, False otherwise.

        Note:
            This treats UNKNOWN as False for safety.
        """
        return self.tip_state == TipState.ATTACHED

    @has_tip.setter
    def has_tip(self, value: bool) -> None:
        """Set tip state using boolean value.

        Args:
            value: True for ATTACHED, False for DETACHED.
        """
        self.tip_state = TipState.ATTACHED if value else TipState.DETACHED


class FluidDisplacement(IntEnum):
    """Direction of fluid flow in pipetting operations.

    Used to indicate whether the pipette is drawing in or expelling liquid.
    The integer values are used as multipliers in motor step calculations.

    Attributes:
        aspiration: Drawing liquid into the tip (value: 1).
        dispense: Expelling liquid from the tip (value: -1).

    Example:
        >>> direction = FluidDisplacement.aspiration
        >>> print(direction.value)
        1
        >>> steps = 100 * direction  # steps = 100

        >>> direction = FluidDisplacement.dispense
        >>> print(direction.value)
        -1
        >>> steps = 100 * direction  # steps = -100
    """

    aspiration = 1
    dispense = -1


# ============================================================================
# GANTRY CONFIGURATION
# ============================================================================


class GantryKinematics(BaseModel):
    """Gantry motion system configuration.

    Defines all parameters for the XYZ motion system including speeds,
    accelerations, and coordinate system limits.

    Attributes:
        speed_xy: Horizontal (XY) movement speed in mm/min.
        speed_z: Vertical (Z) movement speed in mm/min.
        speed_max: Maximum gantry speed in mm/min.
        accel_xy: XY acceleration in mm/s².
        accel_z: Z acceleration in mm/s².
        accel_max: Maximum gantry acceleration in mm/s².

    Example:
        >>> gantry = GantryKinematics(speed_xy=6000.0, accel_xy=3500.0)
        >>> print(gantry.speed_xy)
        6000.0
    """

    # Speed parameters (mm/min)
    speed_xy: float = Field(
        default=5000.0, gt=0, description="Horizontal (XY) movement speed in mm/min"
    )
    speed_z: float = Field(
        default=2000.0, gt=0, description="Vertical (Z) movement speed in mm/min"
    )
    speed_max: float = Field(
        default=10000.0, gt=0, description="Maximum gantry speed in mm/min"
    )

    # Acceleration parameters (mm/s²)
    accel_xy: float = Field(
        default=3000.0, gt=0, description="XY acceleration in mm/s²"
    )
    accel_z: float = Field(default=1000.0, gt=0, description="Z acceleration in mm/s²")
    accel_max: float = Field(
        default=5000.0, gt=0, description="Maximum gantry acceleration in mm/s²"
    )

    # Coordinate limits (mm)
    # x_min: float = Field(default=0.0, description="Minimum X coordinate")
    # x_max: float = Field(default=300.0, gt=0, description="Maximum X coordinate")
    # y_min: float = Field(default=0.0, description="Minimum Y coordinate")
    # y_max: float = Field(default=200.0, gt=0, description="Maximum Y coordinate")
    # z_min: float = Field(default=0.0, description="Minimum Z coordinate")
    # z_max: float = Field(default=100.0, gt=0, description="Maximum Z coordinate")

    # Homing configuration
    # home_z_first: bool = Field(
    #     default=True, description="Home Z axis before XY to prevent collisions"
    # )


class ServoConfig(BaseModel):
    """Tip ejection servo configuration.

    Defines servo motor parameters for the tip ejection mechanism.

    Attributes:
        name: Servo motor identifier.
        angle_retract: Retracted position in degrees (tip held).
        angle_eject: Eject position in degrees (tip released).
        wait_ms: Wait time after servo movement in milliseconds.

    Example:
        >>> servo = ServoConfig(angle_retract=160, angle_eject=90)
        >>> print(servo.name)
        'pipette_servo'
    """

    name: str = Field(
        default="pipette_servo", min_length=1, description="Servo motor identifier"
    )

    angle_retract: int = Field(
        default=160, ge=0, le=180, description="Retracted position (tip held)"
    )

    angle_eject: int = Field(
        default=90, ge=0, le=180, description="Eject position (tip released)"
    )

    wait_ms: int = Field(
        default=200, ge=0, description="Wait time after servo movement (milliseconds)"
    )


# ============================================================================
# PIPETTE SYRINGE CONFIGURATION
# ============================================================================


class PipetteSyringeKinematics(BaseModel):
    """Syringe plunger kinematics for a specific pipette model.

    Defines how the plunger motor moves to aspirate and dispense liquid.
    Can be customized per liquid type for optimal accuracy.

    Attributes:
        syringe_model: Physical syringe model placed in the pipette device.
        stepper_name: Stepper motor identifier.
        motor_orientation: Motor direction (1 for normal, -1 for reversed).
        max_volume_ul: Maximum pipette volume in microliters.
        min_volume_ul: Minimum reliable volume in microliters.
        calibration_volumes: Calibration volume points in µL.
        calibration_steps: Corresponding motor steps.
        speed_aspirate: Aspiration speed in steps/s.
        speed_dispense: Dispense speed in steps/s.
        speed_blowout: Blowout speed for residual liquid in steps/s.
        accel_home: Homing acceleration in mm/s².
        accel_move: Movement acceleration in mm/s².
        wait_aspirate_ms: Wait after aspiration in milliseconds.
        wait_dispense_ms: Wait after dispense in milliseconds.

    Example:
        >>> syringe = PipetteSyringeKinematics(
        ...     max_volume_ul=1000.0,
        ...     calibration_volumes=[0, 100, 500, 1000],
        ...     calibration_steps=[0, 4800, 24000, 48000]
        ... )
        >>> print(syringe.max_volume_ul)
        1000.0
    """

    # Syringe Model in device
    syringe_model: str | None = Field(
        default=None,
        description="Physical syringe model placed in the pipette device (optional)",
    )

    # Motor configuration
    stepper_name: str = Field(
        default="pipette_stepper", min_length=1, description="Stepper motor identifier"
    )

    motor_orientation: Literal[1, -1] = Field(
        default=1, description="Motor direction: 1 for normal, -1 for reversed"
    )

    # Volume capacity
    max_volume_ul: float = Field(
        default=100.0, gt=0, description="Maximum pipette volume in microliters"
    )

    min_volume_ul: float = Field(
        default=0.0, gt=0, description="Minimum reliable volume in microliters"
    )

    # Volume Curve
    calibration_volumes: list[float] | None = Field(
        default=None,
        description="Calibration volume points in µL (overrides pipette default)",
    )

    calibration_steps: list[float] | None = Field(
        default=None,
        description="Corresponding motor steps (overrides pipette default)",
    )

    # Speed parameters (steps/s)
    speed_aspirate: float = Field(
        default=200.0, gt=0, description="Aspiration speed in steps/s"
    )

    speed_dispense: float = Field(
        default=200.0, gt=0, description="Dispense speed in steps/s"
    )

    speed_blowout: float = Field(
        default=50.0, gt=0, description="Blowout speed for residual liquid in steps/s"
    )

    # Acceleration (mm/s²)
    accel_home: float = Field(
        default=800.0, gt=0, description="Homing acceleration in mm/s²"
    )

    accel_move: float = Field(
        default=800.0, gt=0, description="Movement acceleration in mm/s²"
    )

    # Timing parameters (milliseconds)
    wait_aspirate_ms: int = Field(
        default=500, ge=0, description="Wait after aspiration for liquid to settle"
    )

    wait_dispense_ms: int = Field(
        default=200, ge=0, description="Wait after dispense for droplet formation"
    )

    def model_post_init(self, __context: Any) -> None:  # noqa: ANN401
        """Validate calibration data after initialization.

        Raises:
            ValueError: If calibration_volumes and calibration_steps are not
                both provided or both omitted, if they have different lengths,
                or if fewer than 2 calibration points are provided.
        """
        _ = __context
        # If one is provided, both must be provided
        has_volumes = self.calibration_volumes is not None
        has_steps = self.calibration_steps is not None

        if has_volumes != has_steps:
            raise ValueError(
                "Both calibration_volumes and calibration_steps must be "
                "provided together, or both omitted to use pipette defaults"
            )

        # If provided, they must have the same length
        if has_volumes and has_steps:
            if len(self.calibration_volumes) != len(self.calibration_steps):  # type: ignore
                raise ValueError(
                    f"calibration_volumes ({len(self.calibration_volumes)}) and "  # type: ignore
                    f"calibration_steps ({len(self.calibration_steps)}) "  # type: ignore
                    f"must have the same length"
                )

            # Must have at least 2 points for interpolation
            if len(self.calibration_volumes) < 2:  # type: ignore
                raise ValueError("calibration_volumes must have at least 2 points")


class PipetteModel(BaseModel):
    """Complete pipette hardware model definition.

    Combines physical design, syringe kinematics, and servo configuration
    into a complete pipette model specification.

    Attributes:
        name: Pipette model name (e.g., 'P1000_Vertical').
        manufacturer: Pipette manufacturer.
        description: Human-readable description.
        design_type: Physical orientation of pipette ('vertical' or 'horizontal').
        syringe: Syringe plunger kinematics configuration.
        servo: Tip ejection servo configuration.
        compatible_tips: List of compatible tip types.

    Example:
        >>> pipette = PipetteModel(
        ...     name="P1000_Vertical",
        ...     design_type="vertical",
        ...     syringe=PipetteSyringeKinematics(max_volume_ul=1000.0),
        ...     servo=ServoConfig()
        ... )
        >>> print(pipette.name)
        'P1000_Vertical'
    """

    # Metadata
    name: str = Field(description="Pipette model name (e.g., 'P1000_Vertical')")

    manufacturer: str = Field(default="Tricca", description="Pipette manufacturer")

    description: str = Field(default="", description="Human-readable description")

    # Physical design - TODO make more general
    design_type: Literal["vertical", "horizontal"] = Field(
        default="vertical", description="Physical orientation of pipette"
    )

    # Components
    syringe: PipetteSyringeKinematics = Field(description="Syringe plunger kinematics")

    servo: ServoConfig = Field(description="Tip ejection servo configuration")

    # Supported tips (optional)
    compatible_tips: list[str] = Field(
        default_factory=list, description="List of compatible tip types"
    )


# ============================================================================
# LIQUID PROFILES
# ============================================================================


class LiquidProfile(BaseModel):
    """Liquid-specific pipetting parameters.

    Overrides default syringe kinematics for optimal handling of
    specific liquid types (water, DMSO, glycerol, etc.). Each liquid
    can have custom calibration curves and timing parameters.

    Attributes:
        name: Liquid profile name (e.g., 'water', 'dmso', 'glycerol').
        description: Human-readable description.
        viscosity_cP: Dynamic viscosity in centipoise (optional).
        density_g_ml: Density in g/mL (optional).
        speed_aspirate: Override aspiration speed in steps/s.
        speed_dispense: Override dispense speed in steps/s.
        wait_aspirate_ms: Override aspiration wait time in milliseconds.
        wait_dispense_ms: Override dispense wait time in milliseconds.
        prewet_recommended: Whether pre-wetting is recommended.
        prewet_cycles: Recommended number of prewet cycles.
        air_gap_ul: Recommended air gap to prevent dripping in µL.
        blowout_recommended: Whether blowout is recommended.
        calibration_volumes: Calibration volume points in µL (overrides pipette).
        calibration_steps: Corresponding motor steps (overrides pipette).

    Example:
        >>> water = LiquidProfile(name="water", viscosity_cP=1.0)
        >>> glycerol = LiquidProfile(
        ...     name="glycerol",
        ...     viscosity_cP=1400.0,
        ...     speed_aspirate=50.0,
        ...     prewet_recommended=True
        ... )
        >>> print(glycerol.prewet_recommended)
        True
    """

    # Metadata
    name: str = Field(
        description="Liquid profile name (e.g., 'water', 'dmso', 'glycerol')"
    )

    description: str = Field(default="", description="Human-readable description")

    # Physical properties (for reference/documentation)
    viscosity_cP: float | None = Field(
        default=None, ge=0, description="Dynamic viscosity in centipoise (optional)"
    )

    density_g_ml: float | None = Field(
        default=None, gt=0, description="Density in g/mL (optional)"
    )

    # Pipetting overrides (None = use pipette defaults)
    speed_aspirate: float | None = Field(
        default=None, gt=0, description="Override aspiration speed in steps/s"
    )

    speed_dispense: float | None = Field(
        default=None, gt=0, description="Override dispense speed in steps/s"
    )

    wait_aspirate_ms: int | None = Field(
        default=None, ge=0, description="Override aspiration wait time in milliseconds"
    )

    wait_dispense_ms: int | None = Field(
        default=None, ge=0, description="Override dispense wait time in milliseconds"
    )

    # Advanced techniques
    prewet_recommended: bool = Field(
        default=False, description="Whether pre-wetting is recommended for this liquid"
    )

    prewet_cycles: int = Field(
        default=1, ge=0, description="Recommended number of prewet cycles"
    )

    air_gap_ul: float = Field(
        default=0.0, ge=0, description="Recommended air gap to prevent dripping (µL)"
    )

    blowout_recommended: bool = Field(
        default=False, description="Whether blowout is recommended"
    )

    # Volume Curve
    calibration_volumes: list[float] | None = Field(
        default=None,
        description="Calibration volume points in µL (overrides pipette default)",
    )

    calibration_steps: list[float] | None = Field(
        default=None,
        description="Corresponding motor steps (overrides pipette default)",
    )

    def model_post_init(self, __context: Any) -> None:  # noqa: ANN401
        """Validate calibration data after initialization.

        Raises:
            ValueError: If calibration_volumes and calibration_steps are not
                both provided or both omitted, if they have different lengths,
                or if fewer than 2 calibration points are provided.
        """
        _ = __context
        # If one is provided, both must be provided
        has_volumes = self.calibration_volumes is not None
        has_steps = self.calibration_steps is not None

        if has_volumes != has_steps:
            raise ValueError(
                "Both calibration_volumes and calibration_steps must be "
                "provided together, or both omitted to use pipette defaults"
            )

        # If provided, they must have the same length
        if has_volumes and has_steps:
            if len(self.calibration_volumes) != len(self.calibration_steps):  # type: ignore
                raise ValueError(
                    f"calibration_volumes ({len(self.calibration_volumes)}) and "  # type: ignore
                    f"calibration_steps ({len(self.calibration_steps)}) "  # type: ignore
                    f"must have the same length"
                )

            # Must have at least 2 points for interpolation
            if len(self.calibration_volumes) < 2:  # type: ignore
                raise ValueError("calibration_volumes must have at least 2 points")


# ============================================================================
# COMPLETE SYSTEM CONFIGURATION
# ============================================================================


class SystemConfig(BaseModel):
    """Complete autopipette system configuration.

    Top-level configuration that ties together all components including
    gantry, pipette model, liquid profiles, and network settings.

    Attributes:
        version: Configuration schema version.
        system_name: System identifier.
        gantry: Gantry motion system configuration.
        pipette: Currently active pipette model.
        liquids: Available liquid profiles keyed by name.
        network: Network connection settings (hostname and port).

    Example:
        >>> config = SystemConfig(
        ...     system_name="Lab_AutoPipette_1",
        ...     gantry=GantryKinematics(),
        ...     pipette=PipetteModel(name="P1000_Vertical", ...)
        ... )
        >>> print(config.system_name)
        'Lab_AutoPipette_1'
    """

    # System info
    version: str = Field(default="1.0", description="Configuration schema version")

    system_name: str = Field(default="AutoPipette", description="System identifier")

    # Components
    gantry: GantryKinematics = Field(description="Gantry motion system configuration")

    pipette: PipetteModel = Field(description="Currently active pipette model")

    # Available liquid profiles
    liquids: dict[str, LiquidProfile] = Field(
        default_factory=dict, description="Available liquid profiles keyed by name"
    )

    # Network (for Moonraker connection)
    network: dict[str, str] = Field(
        default_factory=lambda: {"hostname": "localhost", "port": "7125"},
        description="Network connection settings",
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Enums
    "TipState",
    "FluidDisplacement",
    # Gantry
    "GantryKinematics",
    "ServoConfig",
    # Pipette
    "PipetteSyringeKinematics",
    "PipetteModel",
    # Liquids
    "LiquidProfile",
    # System
    "SystemConfig",
    # State
    "PipetteState",
]

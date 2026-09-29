"""Data models for AutoPipette JSON configuration.

This module defines Pydantic models for the JSON-based configuration system,
including gantry kinematics, pipette models, liquid profiles, and system-wide
configuration.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, model_validator
from pydantic.dataclasses import dataclass


class TipState(StrEnum):
    """State of tip attachment.

    Attributes:
        ATTACHED: Tip is confirmed to be attached.
        DETACHED: Tip is confirmed to be detached.
        UNKNOWN: Tip state is unknown (e.g., after power on, manual intervention).
    """

    ATTACHED = "attached"
    DETACHED = "detached"
    UNKNOWN = "unknown"


class TipSlotState(StrEnum):
    """What one tipbox position holds (see "Tip state" in ``CONTEXT.md``).

    Attributes:
        AVAILABLE: An unused tip, safe for ``next_tip`` to hand out.
        USED: A used tip returned to its origin position. Never handed out
            again automatically -- only an operator's ``set_tips``/
            ``reset_tips`` makes it available.
        EMPTY: No tip; the one that was here went to waste.
    """

    AVAILABLE = "available"
    USED = "used"
    EMPTY = "empty"


#: Where a tip goes once a transfer is done with it: stay on the pipette,
#: into the waste container, or back into the tipbox slot it came from.
TipEnd = Literal["keep", "waste", "return"]


@dataclass
class PipetteState:
    """Runtime state of the pipette system.

    Tracks the current operational state of the pipette including tip
    attachment, liquid presence, and homing status.

    Attributes:
        tip_state: Current tip attachment state.
        has_liquid: Whether liquid is currently in the tip.
        homed: Whether the pipette has been homed.
        tip_origin: ``(tipbox name, flat well index)`` the attached tip was
            picked up from, or None when no tip is attached or its origin
            is unknown (e.g. a tip still on after a daemon restart). What
            lets a used tip go back to its own slot.

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
    tip_origin: tuple[str, int] | None = None

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
        >>> travel_mm = 100 * direction  # travel_mm = 100

        >>> direction = FluidDisplacement.dispense
        >>> print(direction.value)
        -1
        >>> travel_mm = 100 * direction  # travel_mm = -100
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
        pipette_servo
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
        capacity_margin_ul: Headroom kept below ``max_volume_ul`` in μL.
        max_travel_mm: Manufacturer-stated plunger travel (scale length) in
            mm. Required -- homing and ``clear_syringe`` drive the plunger
            up to twice this toward its endstop.
        calibration_volumes: Calibration volume points in μL.
        calibration_mm: Corresponding plunger travel in mm, as fed to
            Klipper's ``MANUAL_STEPPER ... MOVE=``.
        speed_aspirate: Aspiration speed in mm/s.
        speed_dispense: Dispense speed in mm/s.
        accel_home: Homing acceleration in mm/s².
        accel_move: Movement acceleration in mm/s².
        wait_aspirate_ms: Wait after aspiration in milliseconds.
        wait_dispense_ms: Wait after dispense in milliseconds.
        prewet_cycles: Default prewet cycles before aspirating.
        prewet_vol_ul: Default volume drawn per prewet cycle in μL.
        pre_air_gap_ul: Default air drawn before the liquid in μL.
        post_air_gap_ul: Default air drawn after the liquid in μL.

    Example:
        >>> syringe = PipetteSyringeKinematics(
        ...     max_volume_ul=1000.0,
        ...     max_travel_mm=60.0,
        ...     calibration_volumes=[0, 100, 500, 1000],
        ...     calibration_mm=[0, 4800, 24000, 48000],
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

    capacity_margin_ul: float = Field(
        default=2.0,
        ge=0,
        description=(
            "Headroom kept below max_volume_ul so a full aspirate never "
            "drives the plunger to its hard stop"
        ),
    )

    # Required, no default: homing drives the plunger 2x this toward its
    # endstop, so a guessed value is unsafe (issue #29).
    max_travel_mm: float = Field(
        gt=0,
        description=(
            "Manufacturer-stated plunger travel (scale length) in mm; "
            "homing moves up to twice this toward the endstop"
        ),
    )

    # Volume Curve
    calibration_volumes: list[float] | None = Field(
        default=None,
        description="Calibration volume points in μL (overrides pipette default)",
    )

    calibration_mm: list[float] | None = Field(
        default=None,
        description="Corresponding plunger travel in mm (overrides pipette default)",
    )

    # Speed parameters (mm/s -- these reach Klipper's MANUAL_STEPPER SPEED=)
    speed_aspirate: float = Field(
        default=200.0, gt=0, description="Aspiration speed in mm/s"
    )

    speed_dispense: float = Field(
        default=200.0, gt=0, description="Dispense speed in mm/s"
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

    # Default technique, overridable per liquid and again per command
    prewet_cycles: int = Field(
        default=0, ge=0, description="Prewet cycles to run before aspirating"
    )

    prewet_vol_ul: float = Field(
        default=10.0, ge=0, description="Volume drawn per prewet cycle (μL)"
    )

    pre_air_gap_ul: float = Field(
        default=0.0,
        ge=0,
        description="Air drawn before the liquid, as a trailing cushion (μL)",
    )

    post_air_gap_ul: float = Field(
        default=0.0,
        ge=0,
        description="Air drawn after the liquid, to stop it dripping (μL)",
    )

    def model_post_init(self, __context: Any) -> None:  # ruff:ignore[any-type]
        """Validate calibration data after initialization.

        Raises:
            ValueError: If calibration_volumes and calibration_mm are not
                both provided or both omitted, if they have different lengths,
                or if fewer than 2 calibration points are provided.
        """
        _ = __context
        # If one is provided, both must be provided
        has_volumes = self.calibration_volumes is not None
        has_mm = self.calibration_mm is not None

        if has_volumes != has_mm:
            raise ValueError(
                "Both calibration_volumes and calibration_mm must be "
                "provided together, or both omitted to use pipette defaults"
            )

        # If provided, they must have the same length
        if has_volumes and has_mm:
            if len(self.calibration_volumes) != len(self.calibration_mm):  # type: ignore
                raise ValueError(
                    f"calibration_volumes ({len(self.calibration_volumes)}) and "  # type: ignore
                    f"calibration_mm ({len(self.calibration_mm)}) "  # type: ignore
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
        ...     syringe=PipetteSyringeKinematics(
        ...         max_volume_ul=1000.0, max_travel_mm=60.0
        ...     ),
        ...     servo=ServoConfig(),
        ... )
        >>> print(pipette.name)
        P1000_Vertical
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
        speed_aspirate: Override aspiration speed in mm/s.
        speed_dispense: Override dispense speed in mm/s.
        wait_aspirate_ms: Override aspiration wait time in milliseconds.
        wait_dispense_ms: Override dispense wait time in milliseconds.
        prewet_cycles: Prewet cycles to run before aspirating, or None.
        prewet_vol_ul: Volume drawn per prewet cycle in μL, or None.
        pre_air_gap_ul: Air drawn before the liquid in μL, or None.
        post_air_gap_ul: Air drawn after the liquid in μL, or None.
        calibration_volumes: Calibration volume points in μL (overrides pipette).
        calibration_mm: Corresponding plunger travel in millimetres
            (overrides pipette default).

    Example:
        >>> water = LiquidProfile(name="water", viscosity_cP=1.0)
        >>> glycerol = LiquidProfile(
        ...     name="glycerol",
        ...     viscosity_cP=1400.0,
        ...     speed_aspirate=50.0,
        ...     prewet_cycles=2,
        ... )
        >>> print(glycerol.prewet_cycles)
        2
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
        default=None, gt=0, description="Override aspiration speed in mm/s"
    )

    speed_dispense: float | None = Field(
        default=None, gt=0, description="Override dispense speed in mm/s"
    )

    wait_aspirate_ms: int | None = Field(
        default=None, ge=0, description="Override aspiration wait time in milliseconds"
    )

    wait_dispense_ms: int | None = Field(
        default=None, ge=0, description="Override dispense wait time in milliseconds"
    )

    # Advanced techniques (None = use the pipette's default)
    prewet_cycles: int | None = Field(
        default=None,
        ge=0,
        description="Prewet cycles to run before aspirating this liquid",
    )

    prewet_vol_ul: float | None = Field(
        default=None, ge=0, description="Volume drawn per prewet cycle (μL)"
    )

    pre_air_gap_ul: float | None = Field(
        default=None,
        ge=0,
        description="Air drawn before the liquid, as a trailing cushion (μL)",
    )

    post_air_gap_ul: float | None = Field(
        default=None,
        ge=0,
        description="Air drawn after the liquid, to stop it dripping (μL)",
    )

    # Volume Curve
    calibration_volumes: list[float] | None = Field(
        default=None,
        description="Calibration volume points in μL (overrides pipette default)",
    )

    calibration_mm: list[float] | None = Field(
        default=None,
        description="Corresponding plunger travel in mm (overrides pipette default)",
    )

    def model_post_init(self, __context: Any) -> None:  # ruff:ignore[any-type]
        """Validate calibration data after initialization.

        Raises:
            ValueError: If calibration_volumes and calibration_mm are not
                both provided or both omitted, if they have different lengths,
                or if fewer than 2 calibration points are provided.
        """
        _ = __context
        # If one is provided, both must be provided
        has_volumes = self.calibration_volumes is not None
        has_mm = self.calibration_mm is not None

        if has_volumes != has_mm:
            raise ValueError(
                "Both calibration_volumes and calibration_mm must be "
                "provided together, or both omitted to use pipette defaults"
            )

        # If provided, they must have the same length
        if has_volumes and has_mm:
            if len(self.calibration_volumes) != len(self.calibration_mm):  # type: ignore
                raise ValueError(
                    f"calibration_volumes ({len(self.calibration_volumes)}) and "  # type: ignore
                    f"calibration_mm ({len(self.calibration_mm)}) "  # type: ignore
                    f"must have the same length"
                )

            # Must have at least 2 points for interpolation
            if len(self.calibration_volumes) < 2:  # type: ignore
                raise ValueError("calibration_volumes must have at least 2 points")


# ============================================================================
# LOCATIONS
# ============================================================================


class LocationsConfig(BaseModel):
    """The deck layout a system config declares, as an ordered source list.

    A protocol's system file names the plates and coordinates it needs, so one
    editable file describes a run. The ``locations`` key accepts three shapes,
    all normalized here to an ordered list of sources:

    ```json
    "locations": "deck_a.json"
    "locations": { "coordinates": [...], "plates": [...] }
    "locations": ["standard_deck.json", { "plates": [...] }]
    ```

    Sources are applied in order and later ones win on a name collision, so a
    protocol can pull in a shared deck file and then override one plate inline.

    Note:
        Entries are kept unresolved and unparsed on purpose. Filenames stay
        filenames so `LocationManager` can record where each location came from
        for its duplicate-name warnings, and inline payloads stay raw dicts so
        `LocationManager` remains the single parser for plate geometry --
        duplicating that parsing into pydantic models here would create two
        sources of truth for what a plate entry may contain.

    Attributes:
        sources: Ordered locations sources -- each a filename (resolved against
            ``config/locations/``) or an inline payload.

    Example:
        >>> LocationsConfig.model_validate("deck_a.json").sources
        ['deck_a.json']
    """

    sources: list[str | dict[str, Any]] = Field(
        default_factory=list[str | dict[str, Any]],
        description="Ordered locations sources: filenames or inline payloads",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: object) -> dict[str, Any]:
        """Accept a filename, an inline payload, or a list of either.

        Args:
            value: The raw ``locations`` value from JSON.

        Returns:
            A mapping with a normalized ``sources`` list.

        Raises:
            ValueError: If the value is neither a filename, a mapping, nor a
                list of those.
        """
        if value is None:
            return {"sources": []}
        if isinstance(value, str):
            return {"sources": [value]}
        if isinstance(value, list):
            return {"sources": cast("list[Any]", value)}
        if isinstance(value, dict):
            typed = cast("dict[str, Any]", value)
            # An empty mapping means "nothing declared". Treating it as one
            # empty inline source would make `is_empty` False and silently
            # suppress the caller's default-locations fallback.
            if not typed:
                return {"sources": []}
            # Already-normalized form, e.g. re-validating a dumped model.
            if set(typed) == {"sources"}:
                return typed
            return {"sources": [typed]}
        raise ValueError(
            f"'locations' must be a filename, an object, or a list of those, "
            f"got {type(value).__name__}"
        )

    def is_empty(self) -> bool:
        """Report whether any locations source was declared.

        Returns:
            True if there is nothing to load, so callers can fall back to the
            default locations file.
        """
        return not self.sources


# ============================================================================
# COMPLETE SYSTEM CONFIGURATION
# ============================================================================


class SystemConfig(BaseModel):
    """Complete autopipette system configuration.

    Top-level configuration that ties together all components including
    gantry, pipette model, liquid profiles, locations, and network settings.

    Attributes:
        version: Configuration schema version.
        system_name: System identifier.
        gantry: Gantry motion system configuration.
        pipette: Currently active pipette model.
        liquids: Available liquid profiles keyed by name.
        locations: Deck layout for this system/protocol.
        network: Network connection settings (hostname and port).
        trigger_pins: Trigger channel alias (``air``, ``shake``, ...) to the
            Klipper ``[output_pin]`` it drives, for the ``trigger`` command.

    Example:
        >>> config = SystemConfig(
        ...     system_name="Lab_AutoPipette_1",
        ...     gantry=GantryKinematics(),
        ...     pipette=PipetteModel(
        ...         name="P1000_Vertical",
        ...         syringe=PipetteSyringeKinematics(
        ...             max_volume_ul=1000.0, max_travel_mm=60.0
        ...         ),
        ...         servo=ServoConfig(),
        ...     ),
        ... )
        >>> print(config.system_name)
        Lab_AutoPipette_1
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

    # Deck layout (see LocationsConfig for the accepted shapes)
    locations: LocationsConfig = Field(
        default_factory=LocationsConfig, description="Deck layout for this system"
    )

    # Network (for Moonraker connection)
    network: dict[str, str] = Field(
        default_factory=lambda: {"hostname": "localhost", "port": "7125"},
        description="Network connection settings",
    )

    # Machine wiring for the ``trigger`` command (aux hardware)
    trigger_pins: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Trigger channel alias -> Klipper [output_pin] name; a channel "
            "is valid only if it's a key here"
        ),
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [  # ruff:ignore[unsorted-dunder-all]  (grouped by domain, which reads better than sorted)
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
    # Locations
    "LocationsConfig",
    # System
    "SystemConfig",
    # State
    "PipetteState",
]

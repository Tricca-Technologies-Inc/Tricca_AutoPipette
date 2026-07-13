"""AutoPipette controller and configuration management.

This module provides the main AutoPipette class for controlling automated
pipetting operations with JSON-based configuration.

The AutoPipette class manages:
- JSON configuration loading and validation
- G-code command generation and buffering
- Location and plate management
- Pipetting operations (aspirate, dispense, tip handling)
- Volume calculations and transfer chunking
- Multi-liquid protocol support

Example:
    >>> from pathlib import Path
    >>> pipette = AutoPipette(Path("config/system/system.json"))
    >>> pipette.init_pipette()
    >>>
    >>> # Switch liquids during protocol
    >>> pipette.switch_liquid("water")
    >>> pipette.pipette(vol_ul=100, source="plate_a", dest="plate_b")
    >>>
    >>> pipette.switch_liquid("methanol")
    >>> pipette.pipette(vol_ul=50, source="plate_c", dest="plate_d")
"""

from __future__ import annotations

import logging

from coordinate import Coordinate
from gcode_buffer import GCodeBuffer
from json_config_manager import JsonConfigManager
from location_manager import LocationManager
from pipette_constants import (
    CoordinateSystem,
    GCodeCommand,
    PhysicalConstants,
)
from pipette_exceptions import (
    NoTipboxError,
    TipAlreadyOnError,
)
from pipette_models import (
    FluidDisplacement,
    GantryKinematics,
    PipetteModel,
    PipetteState,
    PipetteSyringeKinematics,
    SystemConfig,
    TipState,
)
from plates import Plate
from volume_converter import VolumeConverter


class AutoPipette:
    """Main controller class for automated pipette operations.

    Manages all aspects of pipette control including JSON configuration
    loading, G-code generation, location management, and pipetting operations.
    Supports multi-liquid protocols with dynamic liquid switching.

    Attributes:
        logger: Logger instance for debugging and error tracking.
        config_manager: JSON configuration manager.
        system_config: Complete system configuration.
        gantry: Gantry kinematics configuration.
        pipette: Pipette model configuration.
        syringe: Active syringe kinematics (merged with liquid overrides).
        active_liquid: Name of currently active liquid profile.
        volume_converter: Converts between volumes and motor steps.
        location_manager: Manages named locations and plates.
        state: Current pipette state (tip, liquid, homed).
        gcode_buffers: G-code command buffer.

    Example:
        >>> pipette = AutoPipette(Path("config/system.json"))
        >>> pipette.init_pipette()
        >>>
        >>> # Multi-liquid protocol
        >>> pipette.switch_liquid("water")
        >>> pipette.pipette(vol_ul=100, source="plate_a", dest="plate_b")
        >>>
        >>> pipette.switch_liquid("glycerol")
        >>> pipette.pipette(vol_ul=50, source="plate_c", dest="plate_d")
    """

    def __init__(
        self,
        json_config_manager: JsonConfigManager,
        location_manager: LocationManager,
    ) -> None:
        """Initialize pipette controller with JSON configuration.

        Loads configuration from JSON file, initializes buffers, and sets up
        volume conversion. Does not home or initialize hardware - call
        init_pipette() for that.

        Args:
            json_config_manager: Config manager instance that loads JSON configuration.
            location_manager: Location manager instance that loads locations and plates.

        Example:
            >>> pipette = AutoPipette()
            >>> pipette = AutoPipette(Path("config/system/system.json"))
        """
        # Logging
        self.logger = logging.getLogger(__name__)

        self.config_manager = json_config_manager
        self.system_config: SystemConfig = self.config_manager.get_system_config()

        # Extract configuration components
        self.gantry: GantryKinematics = self.system_config.gantry
        self.pipette_model: PipetteModel = self.system_config.pipette

        # Active liquid tracking
        self.active_liquid: str = "water"  # Default liquid

        # Get merged syringe parameters (pipette + liquid overrides)
        self._update_syringe_params()

        # Location management
        self.location_manager = location_manager

        # Components
        self.volume_converter: VolumeConverter = VolumeConverter()

        # State tracking
        self.state = PipetteState()

        # G-code management
        self.gcode_buffers = GCodeBuffer()

        # Initialize from loaded config
        self._initialize_from_config()

    def _update_syringe_params(self) -> None:
        """Update syringe parameters with active liquid overrides.

        Merges pipette default parameters with liquid-specific overrides
        to get effective syringe kinematics.
        """
        merged = self.config_manager.get_merged_syringe_params(self.active_liquid)

        # Create a syringe kinematics object with merged parameters
        self.syringe = PipetteSyringeKinematics(
            stepper_name=merged["stepper_name"],
            motor_orientation=merged["motor_orientation"],
            max_volume_ul=merged["max_volume_ul"],
            min_volume_ul=merged["min_volume_ul"],
            calibration_volumes=merged["calibration_volumes"],
            calibration_steps=merged["calibration_steps"],
            speed_aspirate=merged["speed_aspirate"],
            speed_dispense=merged["speed_dispense"],
            wait_aspirate_ms=merged["wait_aspirate_ms"],
            wait_dispense_ms=merged["wait_dispense_ms"],
        )

    def switch_liquid(self, liquid_name: str) -> None:
        """Switch to a different liquid profile.

        Updates the active liquid and reloads syringe parameters with
        liquid-specific overrides. Essential for multi-liquid protocols.

        Args:
            liquid_name: Name of liquid profile to activate.

        Raises:
            ValueError: If liquid not found in system config.

        Example:
            >>> # Multi-liquid protocol
            >>> pipette.switch_liquid("water")
            >>> pipette.pipette(100, "water_source", "plate_a")
            >>>
            >>> pipette.switch_liquid("methanol")
            >>> pipette.pipette(100, "methanol_source", "plate_b")
            >>>
            >>> pipette.switch_liquid("water")
            >>> pipette.pipette(50, "water_source", "plate_c")
        """
        if liquid_name not in self.system_config.liquids:
            available = list(self.system_config.liquids.keys())
            raise ValueError(
                f"Liquid '{liquid_name}' not found. " f"Available liquids: {available}"
            )

        self.active_liquid = liquid_name
        self._update_syringe_params()
        self._init_volume_converter()  # Reload with new calibration

        self.logger.info(f"Switched to liquid: {liquid_name}")

    def _initialize_from_config(self) -> None:
        """Initialize pipette from loaded configuration.

        Extracts parameters, parses locations, initializes volume converter,
        and builds G-code header.
        """
        # Initialize volume converter with active liquid calibration
        self._init_volume_converter()

        # Build G-code header
        self._build_header()

    def _build_header(self) -> None:
        """Generate G-code header with configuration summary.

        Creates a commented header containing all configuration settings
        for documentation and debugging purposes.

        Note:
            Clears any existing header before rebuilding.
        """
        # Build header from system config
        header_lines = [
            "; AutoPipette Configuration\n",
            f"; System: {self.system_config.system_name}\n",
            f"; Version: {self.system_config.version}\n",
            ";\n",
            f"; Pipette: {self.pipette_model.name}\n",
            f"; Manufacturer: {self.pipette_model.manufacturer}\n",
            f"; Design: {self.pipette_model.design_type}\n",
            f"; Max Volume: {self.syringe.max_volume_ul} µL\n",
            ";\n",
            f"; Active Liquid: {self.active_liquid}\n",
            ";\n",
            "; Gantry Settings:\n",
            f";   Speed XY: {self.gantry.speed_xy} mm/min\n",
            f";   Speed Z: {self.gantry.speed_z} mm/min\n",
            f";   Accel XY: {self.gantry.accel_xy} mm/s²\n",
            f";   Accel Z: {self.gantry.accel_z} mm/s²\n",
            ";\n",
        ]

        # Clear and add header
        self.gcode_buffers.clear_header()
        for line in header_lines:
            self.gcode_buffers.add_header(line)

    def _init_volume_converter(self) -> None:
        """Initialize volume-to-steps converter from active liquid calibration.

        Uses liquid-specific calibration if available, otherwise falls back
        to pipette default calibration.

        Raises:
            RuntimeError: If calibration_volumes or calibration_steps are not provided.

        Note:
            Volume converter is required for all pipetting operations.
        """
        volumes = self.syringe.calibration_volumes
        steps = self.syringe.calibration_steps

        if volumes is None or steps is None:
            raise RuntimeError(
                "No calibration data available for volume converter. "
                f"Check pipette '{self.pipette_model.name}'"
                f" and liquid '{self.active_liquid}' configs."
            )

        self.volume_converter = VolumeConverter(volumes, steps)

        self.logger.debug(
            f"Initialized volume converter for liquid '{self.active_liquid}': "
            f"{len(volumes)} calibration points"
        )

    def init_pipette(self) -> None:
        """Initialize all pipette systems and perform homing sequence.

        Performs complete initialization including:
        1. Set coordinate system to absolute mode
        2. Configure speed parameters
        3. Home XYZ axes
        4. Home pipette motors (stepper and servo)

        This should be called once after creating an AutoPipette instance
        and before performing any operations.

        Note:
            Sets the homed flag to True upon successful completion.

        Example:
            >>> pipette = AutoPipette()
            >>> pipette.init_pipette()
            >>> # Now ready for pipetting operations
        """
        self.set_coor_sys(CoordinateSystem.ABSOLUTE)
        self.init_speed()
        self.home_axis()
        self.home_pipette_motors()
        self.state.homed = True

    def init_speed(self) -> None:
        """Configure speed and acceleration parameters.

        Sets gantry speed and acceleration from configuration.

        Example:
            >>> pipette.init_speed()
        """
        self.set_speed_factor(100)  # Default speed factor
        self.set_max_velocity(self.gantry.speed_max)
        self.set_max_accel(self.gantry.accel_max)

    def set_coor_sys(self, mode: str | CoordinateSystem) -> None:
        """Set the coordinate system mode for motion commands.

        Args:
            mode: Either "absolute" or "relative" (case-insensitive).

        Raises:
            ValueError: If an invalid mode is provided.

        Note:
            - Absolute (G90): Coordinates are absolute positions
            - Relative (G91): Coordinates are offsets from current position

        Example:
            >>> pipette.set_coor_sys("absolute")
            >>> pipette.move_to(Coordinate(x=10, y=10, z=5))
        """
        # Convert enum to string if needed
        if isinstance(mode, CoordinateSystem):
            mode_str = mode.value
        else:
            mode_str = mode.lower()

        if mode_str == CoordinateSystem.ABSOLUTE.value:
            self.gcode_buffers.add(f"{GCodeCommand.ABSOLUTE_MODE}\n")
        elif mode_str == CoordinateSystem.RELATIVE.value:
            self.gcode_buffers.add(f"{GCodeCommand.RELATIVE_MODE}\n")
        else:
            raise ValueError(
                f"Invalid coordinate system mode: '{mode}'. "
                f"Expected 'absolute' or 'relative'."
            )

    def set_speed_factor(self, factor: float) -> None:
        """Set the speed multiplication factor.

        Args:
            factor: Speed multiplier percentage (1-200).

        Note:
            100 = normal speed, 200 = double speed, 50 = half speed.

        Example:
            >>> pipette.set_speed_factor(150)  # 1.5x speed
        """
        self.gcode_buffers.add(f"{GCodeCommand.SPEED_FACTOR} S{factor}\n")

    def set_max_velocity(self, velocity: float) -> None:
        """Set the maximum velocity limit.

        Args:
            velocity: Maximum velocity in mm/s.

        Example:
            >>> pipette.set_max_velocity(5000)
        """
        self.gcode_buffers.add(f"SET_VELOCITY_LIMIT VELOCITY={velocity}\n")

    def set_max_accel(self, accel: float) -> None:
        """Set the maximum acceleration limit.

        Args:
            accel: Maximum acceleration in mm/s².

        Example:
            >>> pipette.set_max_accel(3000)
        """
        self.gcode_buffers.add(f"SET_VELOCITY_LIMIT ACCEL={accel}\n")

    def home_axis(self) -> None:
        """Home all axes (X, Y, and Z).

        Example:
            >>> pipette.home_axis()
        """
        self.gcode_buffers.add(f"{GCodeCommand.HOME_ALL}\n")

    def home_x(self) -> None:
        """Home X axis only."""
        self.gcode_buffers.add(f"{GCodeCommand.HOME_X}\n")

    def home_y(self) -> None:
        """Home Y axis only."""
        self.gcode_buffers.add(f"{GCodeCommand.HOME_Y}\n")

    def home_z(self) -> None:
        """Home Z axis only."""
        self.gcode_buffers.add(f"{GCodeCommand.HOME_Z}\n")

    def home_pipette_motors(self) -> None:
        """Home all pipette-specific motors."""
        self.home_servo()
        self.home_pipette_stepper()

    def home_servo(self) -> None:
        """Retract the tip ejection servo to home position."""
        self.set_servo_angle(self.pipette_model.servo.angle_retract)
        self.gcode_wait(self.pipette_model.servo.wait_ms)

    def home_pipette_stepper(
        self,
        stepper: str | None = None,
        speed: float | None = None,
        accel: float | None = None,
    ) -> None:
        """Home the pipette plunger stepper motor.

        Args:
            stepper: Name of stepper, or None to use configured stepper.
            speed: Homing speed in steps/s, or None for default.
            accel: Homing acceleration in mm/s², or None for default.
        """
        if stepper is None:
            stepper = self.syringe.stepper_name
        if speed is None:
            speed = self.syringe.speed_dispense  # Use dispense speed for homing
        if accel is None:
            accel = self.syringe.accel_home

        # Twice the max distance ensures homing
        distance = self.volume_converter.vol_to_steps(2 * self.syringe.max_volume_ul)
        distance *= FluidDisplacement.dispense
        distance *= self.syringe.motor_orientation
        opposite_distance = distance * -1

        self.gcode_buffers.add(
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0 "
            f"MOVE={distance} SPEED={speed} ACCEL={accel} "
            f"STOP_ON_ENDSTOP=1\n"
            f"MANUAL_STEPPER STEPPER={stepper} "
            f"MOVE={opposite_distance} SPEED={speed} ACCEL={accel} "
            f"STOP_ON_ENDSTOP=-1\n"
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n"
        )

    def move_to(self, coordinate: Coordinate) -> None:
        """Move the pipette to the specified coordinate.

        Args:
            coordinate: Target position in 3D space.
        """
        speed_xy = self.gantry.speed_xy
        speed_z = self.gantry.speed_z
        self.gcode_buffers.add(
            f"{GCodeCommand.LINEAR_MOVE} X{coordinate.x} Y{coordinate.y} F{speed_xy}\n"
        )
        self.gcode_buffers.add(
            f"{GCodeCommand.LINEAR_MOVE} Z{coordinate.z} F{speed_z}\n"
        )

    def move_to_x(self, coordinate: Coordinate) -> None:
        """Move only in X direction."""
        speed = self.gantry.speed_xy
        self.gcode_buffers.add(f"{GCodeCommand.LINEAR_MOVE} X{coordinate.x} F{speed}\n")

    def move_to_y(self, coordinate: Coordinate) -> None:
        """Move only in Y direction."""
        speed = self.gantry.speed_xy
        self.gcode_buffers.add(f"{GCodeCommand.LINEAR_MOVE} Y{coordinate.y} F{speed}\n")

    def move_to_z(self, coordinate: Coordinate) -> None:
        """Move only in Z direction."""
        speed = self.gantry.speed_z
        self.gcode_buffers.add(f"{GCodeCommand.LINEAR_MOVE} Z{coordinate.z} F{speed}\n")

    def set_servo_angle(self, angle: float) -> None:
        """Set the tip ejection servo to a specific angle.

        Args:
            angle: Target angle in degrees.
        """
        servo = self.pipette_model.servo.name
        self.gcode_buffers.add(f"SET_SERVO SERVO={servo} ANGLE={angle}\n")

    def move_pipette_stepper(
        self,
        distance: float,
        stepper: str | None = None,
        speed: float | None = None,
        accel: float | None = None,
    ) -> None:
        """Move the plunger stepper motor a specific distance.

        Args:
            distance: Distance to move in motor steps.
            stepper: Name of stepper, or None for configured stepper.
            speed: Movement speed in steps/s, or None for default.
            accel: Movement acceleration in mm/s², or None for default.
        """
        if stepper is None:
            stepper = self.syringe.stepper_name
        if speed is None:
            speed = self.syringe.speed_dispense
        if accel is None:
            accel = self.syringe.accel_move

        self.gcode_buffers.add(
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0 "
            f"SPEED={speed} MOVE={distance} ACCEL={accel} "
            f"STOP_ON_ENDSTOP=2\n"
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n"
        )

    def gcode_wait(self, milliseconds: float) -> None:
        """Insert a dwell/pause command in the G-code.

        Args:
            milliseconds: Duration to wait in milliseconds.
        """
        self.gcode_buffers.add(f"{GCodeCommand.DWELL} P{milliseconds}\n")

    def gcode_print(self, msg: str) -> None:
        """Send a message to be displayed on the controller screen.

        Args:
            msg: Message string to display.
        """
        self.gcode_buffers.add(f"{GCodeCommand.DISPLAY_MESSAGE} {msg}\n")

    def get_gcode(self) -> list[str]:
        """Retrieve buffered G-code commands and clear the buffer.

        Returns:
            List of G-code command strings.
        """
        return self.gcode_buffers.get_commands()

    def get_header(self) -> list[str]:
        """Retrieve the configuration header.

        Returns:
            List of commented G-code lines describing the configuration.
        """
        return self.gcode_buffers.get_header()

    def next_tip(self) -> None:
        """Pick up the next available tip from the configured tipbox.

        Raises:
            NoTipboxError: If no tipbox has been configured.
            TipAlreadyOnError: If a tip is already attached.
        """
        if self.location_manager.tipboxes is None:
            raise NoTipboxError()
        if self.state.tip_state == TipState.ATTACHED:
            raise TipAlreadyOnError()

        loc_tip = self.location_manager.tipboxes.next()
        self.move_to(loc_tip)
        self.dip_z_down(
            loc_tip, self.location_manager.tipboxes.get_dip_distance(vol=None)
        )
        self.dip_z_return(loc_tip)
        self.state.tip_state = TipState.ATTACHED

    def eject_tip(self) -> None:
        """Eject the current pipette tip."""
        angle_retract = self.pipette_model.servo.angle_retract
        angle_eject = self.pipette_model.servo.angle_eject
        wait_eject = self.pipette_model.servo.wait_ms

        self.set_servo_angle(angle_retract)
        self.set_servo_angle(angle_eject)
        self.gcode_wait(wait_eject)
        self.set_servo_angle(angle_retract)
        self.gcode_wait(wait_eject)

        self.state.tip_state = TipState.DETACHED

    def dispose_tip(self) -> None:
        """Eject the current tip into the waste container.

        Raises:
            RuntimeError: If no waste container is configured.
        """
        if self.location_manager.waste_container is None:
            raise RuntimeError("No waste container configured")

        curr_coor = self.location_manager.waste_container.next()
        self.move_to(curr_coor)
        self.dip_z_down(
            curr_coor, self.location_manager.waste_container.get_dip_distance(vol=None)
        )
        self.eject_tip()
        self.dip_z_return(curr_coor)

    def dip_z_down(self, curr_coor: Coordinate, distance: float) -> None:
        """Lower the pipette tip down by a specified distance.

        Args:
            curr_coor: Current XY position.
            distance: Distance to move down in Z axis.
        """
        coor_dip = Coordinate(x=curr_coor.x, y=curr_coor.y, z=distance)
        self.move_to_z(coor_dip)
        self.gcode_wait(100)  # Default wait

    def dip_z_return(self, curr_coor: Coordinate) -> None:
        """Return the pipette to the original Z height.

        Args:
            curr_coor: Original coordinate to return to.
        """
        self.move_to_z(curr_coor)
        self.gcode_wait(100)  # Default wait

    def operate_syringe(
        self,
        direction: FluidDisplacement,
        vol_ul: float,
        stepper: str | None = None,
        speed: float | None = None,
        accel: float | None = None,
    ) -> None:
        """Move syringe to aspirate or dispense a volume.

        Args:
            direction: Direction to move the syringe plunger.
            vol_ul: Volume to aspirate or dispense in microliters.
            stepper: Name of stepper, or None for configured stepper.
            speed: Plunger movement speed in steps/s, or None for default.
            accel: Plunger movement acceleration, or None for default.
        """
        if stepper is None:
            stepper = self.syringe.stepper_name
        if speed is None:
            if direction == FluidDisplacement.aspiration:
                speed = self.syringe.speed_aspirate
            else:
                speed = self.syringe.speed_dispense
        if accel is None:
            accel = self.syringe.accel_move

        steps = self.volume_converter.vol_to_steps(vol_ul)
        steps *= direction
        steps *= self.syringe.motor_orientation
        self.move_pipette_stepper(steps, stepper, speed, accel)

    def clear_syringe(
        self,
        stepper: str | None = None,
        speed: float | None = None,
        accel: float | None = None,
    ) -> None:
        """Move the pipette syringe to the endstop.

        Args:
            stepper: Name of stepper, or None for configured stepper.
            speed: Homing speed in steps/s, or None for default.
            accel: Homing acceleration, or None for default.
        """
        if stepper is None:
            stepper = self.syringe.stepper_name
        if speed is None:
            speed = self.syringe.speed_dispense
        if accel is None:
            accel = self.syringe.accel_home

        distance = self.volume_converter.vol_to_steps(2 * self.syringe.max_volume_ul)
        distance *= FluidDisplacement.dispense
        distance *= self.syringe.motor_orientation

        self.gcode_buffers.add(
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0 "
            f"MOVE={distance} SPEED={speed} ACCEL={accel} "
            f"STOP_ON_ENDSTOP=1\n"
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n"
        )

    def wiggle(self, curr_coor: Coordinate, dip_distance: float) -> None:
        """Shake the pipette tip to dislodge residual liquid droplets.

        Args:
            curr_coor: Current coordinate position.
            dip_distance: Z-axis position where shaking occurs.
        """
        base_coor = Coordinate(x=curr_coor.x, y=curr_coor.y, z=dip_distance)
        shake_offset = PhysicalConstants.WIGGLE_OFFSET_MM

        movement_pattern = [
            (shake_offset, 0),
            (-shake_offset, 0),
            (-shake_offset, 0),
            (shake_offset, 0),
            (0, shake_offset),
            (0, -shake_offset),
            (0, -shake_offset),
            (0, shake_offset),
        ]

        for dx, dy in movement_pattern:
            target = base_coor.generate_offset(dx, dy, 0)
            self.move_to(target)

    def aspirate_volume(
        self,
        volume: float,
        source: str,
        src_row: int | None = None,
        src_col: int | None = None,
        pre_aspirate_air: float = 0.0,
        post_aspirate_air: float = 0.0,
        prewet: int = 0,
        prewet_vol: float = 10.0,
    ) -> None:
        """Aspirate liquid from a source location into the pipette tip.

        Args:
            volume: Volume to aspirate in microliters.
            source: Name of source location or plate.
            src_row: Row index for plate wells, or None for next well.
            src_col: Column index for plate wells, or None for next well.
            pre_aspirate_air: Volume of air to aspirate before liquid.
            post_aspirate_air: Volume of air to aspirate after liquid.
            prewet: Number of prewet cycles before aspiration.
            prewet_vol: Volume to use for prewet cycles.

        Raises:
            ValueError: If source is not a plate with dipping strategy.
        """
        coor_source = self.location_manager.get_coordinate(source, src_row, src_col)
        loc_source = self.location_manager.locations[source]

        if isinstance(loc_source, Coordinate):
            raise ValueError(
                f"Source '{source}' is a coordinate, not a plate. "
                f"Aspiration requires a plate with dipping strategy."
            )

        if not isinstance(loc_source, Plate):
            raise ValueError(
                f"Source '{source}' has invalid type. "
                f"Expected Plate, got {type(loc_source).__name__}."
            )

        self.move_to(coor_source)
        self.home_pipette_stepper()

        if pre_aspirate_air:
            self.operate_syringe(FluidDisplacement.aspiration, pre_aspirate_air)

        self.dip_z_down(coor_source, loc_source.get_dip_distance(volume))

        # Prewetting cycle
        if prewet:
            for _ in range(prewet):
                self.operate_syringe(FluidDisplacement.aspiration, prewet_vol)
                self.gcode_wait(self.syringe.wait_aspirate_ms)
                self.operate_syringe(FluidDisplacement.dispense, prewet_vol)
                self.gcode_wait(self.syringe.wait_aspirate_ms)

        # Aspirate liquid
        self.operate_syringe(FluidDisplacement.aspiration, volume)
        self.state.has_liquid = True
        self.gcode_wait(self.syringe.wait_aspirate_ms)

        self.dip_z_return(coor_source)

        if post_aspirate_air:
            self.operate_syringe(FluidDisplacement.aspiration, post_aspirate_air)

    def dispense_volume(
        self,
        dest: str,
        dest_row: int | None = None,
        dest_col: int | None = None,
        volume: float | None = None,
        wiggle: bool = False,
        touch: bool = False,
    ) -> None:
        """Dispense liquid from the pipette tip into a destination.

        Args:
            dest: Name of destination location or plate.
            dest_row: Row index for plate wells, or None for next well.
            dest_col: Column index for plate wells, or None for next well.
            volume: Volume to dispense, or None for all.
            wiggle: If True, shake tip to dislodge residual droplets.
            touch: If True, touch tip to well side after dispensing.

        Raises:
            ValueError: If destination is not a plate with dipping strategy.
        """
        coor_dest = self.location_manager.get_coordinate(dest, dest_row, dest_col)
        loc_dest = self.location_manager.locations[dest]

        if isinstance(loc_dest, Coordinate):
            raise ValueError(
                f"Destination '{dest}' is a coordinate, not a plate. "
                f"Dispensing requires a plate with dipping strategy."
            )

        if not isinstance(loc_dest, Plate):
            raise ValueError(
                f"Destination '{dest}' has invalid type. "
                f"Expected Plate, got {type(loc_dest).__name__}."
            )

        self.move_to(coor_dest)
        self.dip_z_down(coor_dest, loc_dest.get_dip_distance(volume))

        if volume:
            self.operate_syringe(FluidDisplacement.dispense, volume)
        else:
            self.clear_syringe()

        self.gcode_wait(self.syringe.wait_dispense_ms)

        if wiggle:
            self.wiggle(coor_dest, loc_dest.get_dip_distance(volume))

        if touch:
            pass  # TODO: Implement touch-off

        self.state.has_liquid = False
        self.dip_z_return(coor_dest)

        if not volume:
            self.home_pipette_stepper()

    def pipette(
        self,
        vol_ul: float,
        source: str,
        dest: str,
        disp_vol_ul: float | None = None,
        src_row: int | None = None,
        src_col: int | None = None,
        dest_row: int | None = None,
        dest_col: int | None = None,
        tipbox_name: str | None = None,
        pre_aspirate_air: float = 0.0,
        post_aspirate_air: float = 0.0,
        prewet: int = 0,
        prewet_vol: float = 10.0,
        wiggle: bool = False,
        touch: bool = False,
        keep_tip: bool = False,
    ) -> None:
        """Transfer liquid between locations.

        High-level method that handles complete liquid transfer including:
        - Automatic volume chunking for volumes exceeding max capacity
        - Optional tip retention
        - Optional prewetting for accuracy
        - Optional wiggling for complete dispensing

        Args:
            vol_ul: Volume to transfer in microliters (must be positive).
            source: Name of source location/plate.
            dest: Name of destination location/plate.
            disp_vol_ul: Volume to dispense (if different from aspirate).
            src_row: Source plate row index (0-based).
            src_col: Source plate column index (0-based).
            dest_row: Destination plate row index (0-based).
            dest_col: Destination plate column index (0-based).
            tipbox_name: Name of specific tipbox to use.
            pre_aspirate_air: Volume of air to aspirate before liquid.
            post_aspirate_air: Volume of air to aspirate after liquid.
            prewet: Number of prewet cycles.
            prewet_vol: Volume in µL to prewet the tip with.
            wiggle: If True, shake tip during dispensing.
            touch: If True, touch tip to side after dispensing.
            keep_tip: If True, retain tip after operation.

        Raises:
            ValueError: If requested volume is negative.

        Example:
            >>> # Simple transfer
            >>> pipette.pipette(vol_ul=100, source="plate_a", dest="plate_b")

            >>> # Multi-liquid protocol
            >>> pipette.switch_liquid("water")
            >>> pipette.pipette(vol_ul=100, source="water_res", dest="plate")
            >>>
            >>> pipette.switch_liquid("methanol")
            >>> pipette.pipette(vol_ul=50, source="methanol_res", dest="plate")

            >>> # Large volume (automatically chunked)
            >>> pipette.pipette(vol_ul=500, source="a", dest="b")
        """
        if vol_ul < 0:
            raise ValueError(f"Invalid volume: {vol_ul}µL. Volume must be positive.")

        # Pick up tip if needed
        if self.state.tip_state == TipState.DETACHED:
            _ = tipbox_name
            self.next_tip()  # TODO: Pass in preferred tipbox

        # Calculate transfer chunks based on max pipette capacity
        max_vol = self.syringe.max_volume_ul
        chunks = int(vol_ul // max_vol)
        remainder = vol_ul - (chunks * max_vol)
        transfer_volumes: list[float] = [float(max_vol)] * chunks

        # Add remainder if significant
        if remainder > PhysicalConstants.VOLUME_TOLERANCE_UL:
            transfer_volumes.append(remainder)

        # Execute transfer sequence
        for pip_vol in transfer_volumes:
            self.aspirate_volume(
                pip_vol,
                source,
                src_row=src_row,
                src_col=src_col,
                pre_aspirate_air=pre_aspirate_air,
                post_aspirate_air=post_aspirate_air,
                prewet=prewet,
                prewet_vol=prewet_vol,
            )

            # Only dispense the passed in amount if present
            if disp_vol_ul:
                self.dispense_volume(
                    dest,
                    dest_row=dest_row,
                    dest_col=dest_col,
                    volume=disp_vol_ul,
                    wiggle=wiggle,
                    touch=touch,
                )
                break
            else:
                self.dispense_volume(
                    dest,
                    dest_row=dest_row,
                    dest_col=dest_col,
                    wiggle=wiggle,
                    touch=touch,
                )

        # Dispose of tip unless explicitly keeping it
        if not keep_tip:
            self.dispose_tip()

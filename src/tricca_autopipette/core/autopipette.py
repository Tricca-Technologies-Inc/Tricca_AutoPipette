"""AutoPipette controller and configuration management.

This module provides the main AutoPipette class for controlling automated
pipetting operations with JSON-based configuration.

The AutoPipette class manages:
- G-code command generation and buffering
- Location and plate management
- Pipetting operations (aspirate, dispense, tip handling)
- Volume calculations and transfer chunking
- Multi-liquid protocol support

JSON configuration loading and validation is the job of ``JsonConfigManager``,
injected into the constructor rather than performed by ``AutoPipette`` itself.

Example:
    >>> from tricca_autopipette.core.json_config_manager import JsonConfigManager
    >>> from tricca_autopipette.core.location_manager import LocationManager
    >>> pipette = AutoPipette(JsonConfigManager(), LocationManager())  # doctest: +SKIP
    >>> pipette.init_pipette()  # doctest: +SKIP
    >>>
    >>> # Switch liquids during protocol
    >>> pipette.switch_liquid("water")  # doctest: +SKIP
    >>> pipette.pipette(vol_ul=100, source="plate_a", dest="plate_b")  # doctest: +SKIP
    >>>
    >>> pipette.switch_liquid("methanol")  # doctest: +SKIP
    >>> pipette.pipette(vol_ul=50, source="plate_c", dest="plate_d")  # doctest: +SKIP
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.gcode_buffer import GCodeBuffer
from tricca_autopipette.core.json_config_manager import JsonConfigManager
from tricca_autopipette.core.location_manager import LocationManager
from tricca_autopipette.core.pipette_constants import (
    CoordinateSystem,
    GCodeCommand,
    PhysicalConstants,
)
from tricca_autopipette.core.pipette_exceptions import (
    NotALocationError,
    NoWasteContainerError,
    TipAlreadyOnError,
    VolumeCapacityError,
)
from tricca_autopipette.core.pipette_models import (
    FluidDisplacement,
    GantryKinematics,
    PipetteModel,
    PipetteState,
    PipetteSyringeKinematics,
    SystemConfig,
    TipState,
)
from tricca_autopipette.core.splits import LeftoverAction, Split
from tricca_autopipette.core.traversal import well_id_to_rc
from tricca_autopipette.core.volume_converter import VolumeConverter


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
        volume_converter: Converts between volumes and plunger-travel
            millimetres (the field is still named "steps" -- see issue #29).
        location_manager: Manages named locations and plates.
        state: Current pipette state (tip, liquid, homed).
        gcode_buffers: G-code command buffer.

    Example:
        >>> from tricca_autopipette.core.json_config_manager import JsonConfigManager
        >>> from tricca_autopipette.core.location_manager import LocationManager
        >>> pipette = AutoPipette(
        ...     JsonConfigManager(), LocationManager()
        ... )  # doctest: +SKIP
        >>> pipette.init_pipette()  # doctest: +SKIP
        >>>
        >>> # Multi-liquid protocol
        >>> pipette.switch_liquid("water")  # doctest: +SKIP
        >>> pipette.pipette(
        ...     vol_ul=100, source="plate_a", dest="plate_b"
        ... )  # doctest: +SKIP
        >>>
        >>> pipette.switch_liquid("glycerol")  # doctest: +SKIP
        >>> pipette.pipette(
        ...     vol_ul=50, source="plate_c", dest="plate_d"
        ... )  # doctest: +SKIP
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
            >>> from tricca_autopipette.core.json_config_manager import (
            ...     JsonConfigManager,
            ... )
            >>> from tricca_autopipette.core.location_manager import LocationManager
            >>> pipette = AutoPipette(
            ...     JsonConfigManager(), LocationManager()
            ... )  # doctest: +SKIP
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
            capacity_margin_ul=merged["capacity_margin_ul"],
            calibration_volumes=merged["calibration_volumes"],
            calibration_steps=merged["calibration_steps"],
            speed_aspirate=merged["speed_aspirate"],
            speed_dispense=merged["speed_dispense"],
            wait_aspirate_ms=merged["wait_aspirate_ms"],
            wait_dispense_ms=merged["wait_dispense_ms"],
            prewet_cycles=merged["prewet_cycles"],
            prewet_vol_ul=merged["prewet_vol_ul"],
            pre_air_gap_ul=merged["pre_air_gap_ul"],
            post_air_gap_ul=merged["post_air_gap_ul"],
        )
        self._technique_provenance = self._compute_technique_provenance()

    def _compute_technique_provenance(self) -> dict[str, str]:
        """Tag each merged technique default with where it came from.

        Mirrors ``JsonConfigManager.get_merged_syringe_params``'s own
        liquid-overrides-pipette merge (``is not None`` wins), but records
        *which* tier supplied the value instead of the value itself, for
        ``resolve_technique``/``note_action`` to report alongside the
        resolved numbers.

        Returns:
            Mapping of ``pre_air_gap_ul``/``post_air_gap_ul``/
            ``prewet_cycles``/``prewet_vol_ul`` to either
            ``"liquid:<name>"`` or ``"pipette default"``.
        """
        liquid = self.system_config.liquids[self.active_liquid]
        fields = ("pre_air_gap_ul", "post_air_gap_ul", "prewet_cycles", "prewet_vol_ul")
        return {
            field: (
                f"liquid:{self.active_liquid}"
                if getattr(liquid, field) is not None
                else "pipette default"
            )
            for field in fields
        }

    def note_action(self, message: str) -> None:
        """Record one logical action via both the run log and the G-code.

        Logs ``message`` at INFO and, using the exact same string, adds a
        matching G-code comment immediately ahead of the action's commands
        -- the run log and the G-code file can therefore never end up
        describing an action differently. Also used directly by
        ``AutoPipetteService`` (``daemon/service.py``) for the handful of
        actions -- plain moves, individual-motor homing -- that don't
        already flow through one of this class's own action methods.

        Args:
            message: Human-readable description of the action, e.g.
                ``"Aspirating 50.0μL from 'plate_a'"``.
        """
        self.logger.info(message)
        self.gcode_buffers.add_comment(message)

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
            >>> pipette.switch_liquid("water")  # doctest: +SKIP
            >>> pipette.pipette(100, "water_source", "plate_a")  # doctest: +SKIP
            >>>
            >>> pipette.switch_liquid("methanol")  # doctest: +SKIP
            >>> pipette.pipette(100, "methanol_source", "plate_b")  # doctest: +SKIP
            >>>
            >>> pipette.switch_liquid("water")  # doctest: +SKIP
            >>> pipette.pipette(50, "water_source", "plate_c")  # doctest: +SKIP
        """
        if liquid_name not in self.system_config.liquids:
            available = list(self.system_config.liquids.keys())
            raise ValueError(
                f"Liquid '{liquid_name}' not found. Available liquids: {available}"
            )

        self.active_liquid = liquid_name
        self._update_syringe_params()
        self._init_volume_converter()  # Reload with new calibration

        self.note_action(f"Switched to liquid: {liquid_name}")

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
            f"; Max Volume: {self.syringe.max_volume_ul} μL\n",
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
            >>> pipette = AutoPipette()  # doctest: +SKIP
            >>> pipette.init_pipette()  # doctest: +SKIP
            >>> # Now ready for pipetting operations
        """
        self.set_coor_sys(CoordinateSystem.ABSOLUTE)
        self.init_speed()
        self.home_axis()
        self.home_pipette_motors()
        self.state.homed = True
        self.note_action(
            "Pipette initialized: absolute coordinates, speed configured, "
            "XYZ and pipette motors homed"
        )

    def init_speed(self) -> None:
        """Configure speed and acceleration parameters.

        Sets gantry speed and acceleration from configuration.

        Example:
            >>> pipette.init_speed()  # doctest: +SKIP
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
            >>> pipette.set_coor_sys("absolute")  # doctest: +SKIP
            >>> pipette.move_to(Coordinate(x=10, y=10, z=5))  # doctest: +SKIP
        """
        # Convert enum to string if needed
        mode_str = mode.value if isinstance(mode, CoordinateSystem) else mode.lower()

        if mode_str == CoordinateSystem.ABSOLUTE.value:
            self.logger.debug("Coordinate system: absolute")
            self.gcode_buffers.add(f"{GCodeCommand.ABSOLUTE_MODE}\n")
        elif mode_str == CoordinateSystem.RELATIVE.value:
            self.logger.debug("Coordinate system: relative")
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
            >>> pipette.set_speed_factor(150)  # doctest: +SKIP
        """
        self.logger.debug("Speed factor: %s%%", factor)
        self.gcode_buffers.add(f"{GCodeCommand.SPEED_FACTOR} S{factor}\n")

    def set_max_velocity(self, velocity: float) -> None:
        """Set the maximum velocity limit.

        Args:
            velocity: Maximum velocity in mm/s.

        Example:
            >>> pipette.set_max_velocity(5000)  # doctest: +SKIP
        """
        self.logger.debug("Max velocity: %s mm/s", velocity)
        self.gcode_buffers.add(f"SET_VELOCITY_LIMIT VELOCITY={velocity}\n")

    def set_max_accel(self, accel: float) -> None:
        """Set the maximum acceleration limit.

        Args:
            accel: Maximum acceleration in mm/s².

        Example:
            >>> pipette.set_max_accel(3000)  # doctest: +SKIP
        """
        self.logger.debug("Max acceleration: %s mm/s²", accel)
        self.gcode_buffers.add(f"SET_VELOCITY_LIMIT ACCEL={accel}\n")

    def home_axis(self) -> None:
        """Home all axes (X, Y, and Z).

        Example:
            >>> pipette.home_axis()  # doctest: +SKIP
        """
        self.note_action("Homing all axes (X, Y, Z)")
        self.gcode_buffers.add(f"{GCodeCommand.HOME_ALL}\n")

    def home_x(self) -> None:
        """Home X axis only."""
        self.note_action("Homing X axis")
        self.gcode_buffers.add(f"{GCodeCommand.HOME_X}\n")

    def home_y(self) -> None:
        """Home Y axis only."""
        self.note_action("Homing Y axis")
        self.gcode_buffers.add(f"{GCodeCommand.HOME_Y}\n")

    def home_z(self) -> None:
        """Home Z axis only."""
        self.note_action("Homing Z axis")
        self.gcode_buffers.add(f"{GCodeCommand.HOME_Z}\n")

    def home_pipette_motors(self) -> None:
        """Home all pipette-specific motors."""
        self.note_action("Homing pipette motors (servo + stepper)")
        self.home_servo()
        self.home_pipette_stepper()

    def home_servo(self) -> None:
        """Retract the tip ejection servo to home position."""
        self.note_action("Homing servo (retract to home position)")
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
            speed: Homing speed in mm/s, or None for default.
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

        self.logger.debug(
            "MANUAL_STEPPER %s homing: distance=%s speed=%s accel=%s",
            stepper,
            distance,
            speed,
            accel,
        )
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
        self.logger.debug(
            "G-code move: X=%s Y=%s Z=%s (speed_xy=%s speed_z=%s)",
            coordinate.x,
            coordinate.y,
            coordinate.z,
            speed_xy,
            speed_z,
        )
        self.gcode_buffers.add(
            f"{GCodeCommand.LINEAR_MOVE} X{coordinate.x} Y{coordinate.y} F{speed_xy}\n"
        )
        self.gcode_buffers.add(
            f"{GCodeCommand.LINEAR_MOVE} Z{coordinate.z} F{speed_z}\n"
        )

    def move_to_z(self, coordinate: Coordinate) -> None:
        """Move only in Z direction."""
        speed = self.gantry.speed_z
        self.logger.debug("G-code move: Z=%s (speed=%s)", coordinate.z, speed)
        self.gcode_buffers.add(f"{GCodeCommand.LINEAR_MOVE} Z{coordinate.z} F{speed}\n")

    def set_servo_angle(self, angle: float) -> None:
        """Set the tip ejection servo to a specific angle.

        Args:
            angle: Target angle in degrees.
        """
        servo = self.pipette_model.servo.name
        self.logger.debug("SET_SERVO %s: angle=%s", servo, angle)
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
            distance: Distance to move in millimetres.
            stepper: Name of stepper, or None for configured stepper.
            speed: Movement speed in mm/s, or None for default.
            accel: Movement acceleration in mm/s², or None for default.
        """
        if stepper is None:
            stepper = self.syringe.stepper_name
        if speed is None:
            speed = self.syringe.speed_dispense
        if accel is None:
            accel = self.syringe.accel_move

        self.logger.debug(
            "MANUAL_STEPPER %s move: distance=%s speed=%s accel=%s",
            stepper,
            distance,
            speed,
            accel,
        )
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
        self.logger.debug("Dwell: %s ms", milliseconds)
        self.gcode_buffers.add(f"{GCodeCommand.DWELL} P{milliseconds}\n")

    def gcode_print(self, msg: str) -> None:
        """Send a message to be displayed on the controller screen.

        Args:
            msg: Message string to display.
        """
        self.note_action(f"Displaying message: {msg}")
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

    def next_tip(self, tipbox_name: str | None = None) -> None:
        """Pick up the next available tip from the configured tipboxes.

        Boxes are drawn from in the order they appear in the locations config,
        each in its own traversal order, and a consumed position is never
        offered again -- unless `tipbox_name` requests a specific box.

        Args:
            tipbox_name: If given, draw only from this box instead of the
                registration-order default.

        Raises:
            NoTipboxError: If no tipbox has been configured.
            NotALocationError: If `tipbox_name` is given but no box is
                configured under that name.
            OutOfTipsError: If every tried tipbox is exhausted. Reload the
                boxes and run ``reset_tips`` rather than reusing a tip.
            TipAlreadyOnError: If a tip is already attached.
        """  # ruff: ignore[docstring-extraneous-exception]
        if self.state.tip_state == TipState.ATTACHED:
            raise TipAlreadyOnError()

        # The supplying box comes back with the coordinate: boxes may sit at
        # different heights, so the dip distance must come from *that* box.
        name, box, loc_tip = self.location_manager.tipbox_manager.next_tip(
            name=tipbox_name
        )
        self.note_action(
            f"Picking up tip from '{name}' at (X:{loc_tip.x:.2f}, Y:{loc_tip.y:.2f})"
        )
        self.move_to(loc_tip)
        self.dip_z_down(loc_tip, box.get_dip_distance(vol=None))
        self.dip_z_return(loc_tip)
        self.state.tip_state = TipState.ATTACHED

    def eject_tip(self) -> None:
        """Eject the current pipette tip."""
        self.note_action("Ejecting tip")
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
            NoWasteContainerError: If no waste container is configured.
        """
        if self.location_manager.waste_container is None:
            raise NoWasteContainerError()

        self.note_action("Disposing tip to waste container")
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
        self.logger.debug("Dipping down to Z=%s", distance)
        coor_dip = Coordinate(x=curr_coor.x, y=curr_coor.y, z=distance)
        self.move_to_z(coor_dip)
        self.gcode_wait(100)  # Default wait

    def dip_z_return(self, curr_coor: Coordinate) -> None:
        """Return the pipette to the original Z height.

        Args:
            curr_coor: Original coordinate to return to.
        """
        self.logger.debug("Returning to Z=%s", curr_coor.z)
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
            speed: Plunger movement speed in mm/s, or None for default.
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
        self.logger.debug(
            "Syringe %s: %s μL (%s mm plunger travel)",
            "aspiration" if direction == FluidDisplacement.aspiration else "dispense",
            vol_ul,
            steps,
        )
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
            speed: Homing speed in mm/s, or None for default.
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

        self.logger.debug(
            "MANUAL_STEPPER %s clear: distance=%s speed=%s accel=%s",
            stepper,
            distance,
            speed,
            accel,
        )
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
        self.logger.debug(
            "Wiggling at Z=%s to dislodge residual droplets", dip_distance
        )
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

    def resolve_technique(
        self,
        pre_air_gap_ul: float | None = None,
        post_air_gap_ul: float | None = None,
        prewet_cycles: int | None = None,
        prewet_vol_ul: float | None = None,
    ) -> tuple[float, float, int, float]:
        """Fill unset technique parameters in from the active liquid profile.

        Resolution order is **explicit argument > active liquid profile >
        pipette default**, with the last two already merged onto
        ``self.syringe`` by ``_update_syringe_params``. ``None`` means
        "unset"; an explicit ``0`` is a real value and overrides a non-zero
        profile default, which is why these are ``| None`` rather than
        zero-defaulted floats.

        Args:
            pre_air_gap_ul: Air before the liquid in μL, or None.
            post_air_gap_ul: Air after the liquid in μL, or None.
            prewet_cycles: Number of prewet cycles, or None.
            prewet_vol_ul: Volume per prewet cycle in μL, or None.

        Returns:
            The resolved ``(pre_air_gap_ul, post_air_gap_ul, prewet_cycles,
            prewet_vol_ul)``.

        Example:
            >>> pipette.switch_liquid("methanol")  # doctest: +SKIP
            >>> pipette.resolve_technique()[0]  # doctest: +SKIP
            5.0
            >>> pipette.resolve_technique(pre_air_gap_ul=0.0)[0]  # doctest: +SKIP
            0.0
        """
        return (
            self.syringe.pre_air_gap_ul if pre_air_gap_ul is None else pre_air_gap_ul,
            self.syringe.post_air_gap_ul
            if post_air_gap_ul is None
            else post_air_gap_ul,
            self.syringe.prewet_cycles if prewet_cycles is None else prewet_cycles,
            self.syringe.prewet_vol_ul if prewet_vol_ul is None else prewet_vol_ul,
        )

    def _technique_sources(
        self,
        pre_air_gap_ul: float | None,
        post_air_gap_ul: float | None,
        prewet_cycles: int | None,
        prewet_vol_ul: float | None,
    ) -> tuple[str, str, str, str]:
        """Tag each technique argument with where its resolved value came from.

        Mirrors ``resolve_technique``'s own explicit-argument > liquid-profile
        > pipette-default precedence, but reports *which* tier won instead of
        the value. Must be called with the same pre-resolution arguments
        (before ``resolve_technique`` overwrites them with resolved values),
        since a caller that reassigns its locals in place loses the
        "was this explicit" information otherwise.

        Args:
            pre_air_gap_ul: Requested pre-aspirate air gap, or None.
            post_air_gap_ul: Requested post-aspirate air gap, or None.
            prewet_cycles: Requested prewet cycle count, or None.
            prewet_vol_ul: Requested prewet volume, or None.

        Returns:
            Source tags for ``(pre_air_gap_ul, post_air_gap_ul,
            prewet_cycles, prewet_vol_ul)`` -- each either
            ``"explicit flag"`` or the matching entry from
            ``self._technique_provenance``.
        """
        provenance = self._technique_provenance
        return (
            "explicit flag"
            if pre_air_gap_ul is not None
            else provenance["pre_air_gap_ul"],
            "explicit flag"
            if post_air_gap_ul is not None
            else provenance["post_air_gap_ul"],
            "explicit flag"
            if prewet_cycles is not None
            else provenance["prewet_cycles"],
            "explicit flag"
            if prewet_vol_ul is not None
            else provenance["prewet_vol_ul"],
        )

    def usable_capacity_ul(self) -> float:
        """Return the volume the syringe may hold, less its safety margin.

        Returns:
            ``max_volume_ul - capacity_margin_ul`` in microliters, floored at
            zero.
        """
        return max(0.0, self.syringe.max_volume_ul - self.syringe.capacity_margin_ul)

    def fit_air_volumes(
        self, volume: float, pre_air_gap_ul: float, post_air_gap_ul: float
    ) -> tuple[float, float]:
        """Shrink air gaps so liquid plus air fits inside the syringe.

        The post-aspirate gap is fitted first: it is the anti-drip cushion
        that sits at the tip orifice, so it is the one worth preserving when
        headroom is tight. Whatever headroom survives goes to the
        pre-aspirate gap.

        Reducing a gap is logged at WARNING naming requested versus applied,
        rather than being applied silently -- a quietly shortened air cushion
        changes transfer technique without the operator knowing.

        Args:
            volume: The liquid volume to be aspirated, in microliters.
            pre_air_gap_ul: Requested air volume before the liquid, in μL.
            post_air_gap_ul: Requested air volume after the liquid, in μL.

        Returns:
            The ``(pre_air_gap_ul, post_air_gap_ul)`` volumes that
            actually fit, in microliters.

        Raises:
            VolumeCapacityError: If the liquid alone exceeds usable capacity.
                Shrinking air cannot rescue this case, and silently
                aspirating less liquid would deliver the wrong amount.

        Example:
            >>> # 100 μL syringe, 2 μL margin, 90 μL of liquid requested
            >>> pipette.fit_air_volumes(90.0, 30.0, 2.0)  # doctest: +SKIP
            (6.0, 2.0)
        """
        usable = self.usable_capacity_ul()
        headroom = usable - volume

        if headroom < -PhysicalConstants.VOLUME_TOLERANCE_UL:
            raise VolumeCapacityError(volume, usable)

        headroom = max(0.0, headroom)

        fitted_post = min(post_air_gap_ul, headroom)
        fitted_pre = min(pre_air_gap_ul, headroom - fitted_post)

        if post_air_gap_ul - fitted_post > PhysicalConstants.VOLUME_TOLERANCE_UL:
            self.logger.warning(
                f"post_air_gap reduced from {post_air_gap_ul} μL to "
                f"{fitted_post} μL: {volume} μL of liquid leaves only "
                f"{headroom} μL of headroom in a {usable} μL usable syringe."
            )
        if pre_air_gap_ul - fitted_pre > PhysicalConstants.VOLUME_TOLERANCE_UL:
            self.logger.warning(
                f"pre_air_gap reduced from {pre_air_gap_ul} μL to "
                f"{fitted_pre} μL: {volume} μL of liquid leaves only "
                f"{headroom} μL of headroom in a {usable} μL usable syringe."
            )

        return fitted_pre, fitted_post

    def aspirate_volume(
        self,
        volume: float,
        source: str,
        src_row: int | None = None,
        src_col: int | None = None,
        pre_air_gap_ul: float | None = None,
        post_air_gap_ul: float | None = None,
        prewet_cycles: int | None = None,
        prewet_vol_ul: float | None = None,
    ) -> None:
        """Aspirate liquid from a source location into the pipette tip.

        Args:
            volume: Volume to aspirate in microliters.
            source: Name of source location or plate.
            src_row: Row index for plate wells, or None for next well.
            src_col: Column index for plate wells, or None for next well.
            pre_air_gap_ul: Air before the liquid in μL, or None to take
                the active liquid profile's value.
            post_air_gap_ul: Air after the liquid in μL, or None to take
                the active liquid profile's value.
            prewet_cycles: Number of prewet cycles, or None for the profile's value.
            prewet_vol_ul: Volume per prewet cycle in μL, or None for the
                profile's value.

        Raises:
            ValueError: If source is not a plate with dipping strategy.
            VolumeCapacityError: If ``volume`` alone exceeds usable syringe
                capacity.
            NotALocationError: If ``source`` is not a defined location.
        """  # ruff: ignore[docstring-extraneous-exception]
        coor_source = self.location_manager.get_coordinate(source, src_row, src_col)
        loc_source = self.location_manager.locations[source]

        if isinstance(loc_source, Coordinate):
            raise ValueError(
                f"Source '{source}' is a coordinate, not a plate. "
                f"Aspiration requires a plate with dipping strategy."
            )

        sources = self._technique_sources(
            pre_air_gap_ul, post_air_gap_ul, prewet_cycles, prewet_vol_ul
        )
        pre_air_gap_ul, post_air_gap_ul, prewet_cycles, prewet_vol_ul = (
            self.resolve_technique(
                pre_air_gap_ul, post_air_gap_ul, prewet_cycles, prewet_vol_ul
            )
        )
        pre_air_gap_ul, post_air_gap_ul = self.fit_air_volumes(
            volume, pre_air_gap_ul, post_air_gap_ul
        )
        # A prewet cycle draws on top of the pre-aspirate gap already in the
        # tip, so it gets the headroom left over from that -- not the whole
        # syringe.
        prewet_vol_ul = min(prewet_vol_ul, self.usable_capacity_ul() - pre_air_gap_ul)

        well = (
            source
            if src_row is None or src_col is None
            else f"{source}[{src_row},{src_col}]"
        )
        self.note_action(
            f"Aspirating {volume:g}μL from '{well}' "
            f"(pre_air_gap={pre_air_gap_ul:g}μL[{sources[0]}], "
            f"post_air_gap={post_air_gap_ul:g}μL[{sources[1]}], "
            f"prewet={prewet_cycles}x{prewet_vol_ul:g}μL[{sources[2]}/{sources[3]}])"
        )

        self.move_to(coor_source)
        self.home_pipette_stepper()

        if pre_air_gap_ul:
            self.operate_syringe(FluidDisplacement.aspiration, pre_air_gap_ul)

        self.dip_z_down(coor_source, loc_source.get_dip_distance(volume))

        # Prewetting cycle
        if prewet_cycles and prewet_vol_ul > PhysicalConstants.VOLUME_TOLERANCE_UL:
            for _ in range(prewet_cycles):
                self.operate_syringe(FluidDisplacement.aspiration, prewet_vol_ul)
                self.gcode_wait(self.syringe.wait_aspirate_ms)
                self.operate_syringe(FluidDisplacement.dispense, prewet_vol_ul)
                self.gcode_wait(self.syringe.wait_aspirate_ms)

        # Aspirate liquid
        self.operate_syringe(FluidDisplacement.aspiration, volume)
        self.state.has_liquid = True
        self.gcode_wait(self.syringe.wait_aspirate_ms)

        self.dip_z_return(coor_source)

        if post_air_gap_ul:
            self.operate_syringe(FluidDisplacement.aspiration, post_air_gap_ul)

    def dispense_volume(
        self,
        dest: str,
        dest_row: int | None = None,
        dest_col: int | None = None,
        volume: float | None = None,
        wiggle: bool = False,
        purge_air_gap_ul: float = 0.0,
        empties_tip: bool = True,
    ) -> None:
        """Dispense liquid from the pipette tip into a destination.

        Args:
            dest: Name of destination location or plate.
            dest_row: Row index for plate wells, or None for next well.
            dest_col: Column index for plate wells, or None for next well.
            volume: Volume to dispense, or None for all.
            wiggle: If True, shake tip to dislodge residual droplets.
            purge_air_gap_ul: Extra plunger travel in μL to push out a
                post-aspirate air cushion ahead of the liquid. Ignored when
                `volume` is None, since that path empties the tip anyway.
            empties_tip: Whether this dispense leaves the tip empty. False
                for a partial dispense that will be followed by more, so
                ``state.has_liquid`` stays true.

        Raises:
            ValueError: If destination is not a plate with dipping strategy.
            NotALocationError: If ``dest`` is not a defined location.
        """  # ruff: ignore[docstring-extraneous-exception]
        coor_dest = self.location_manager.get_coordinate(dest, dest_row, dest_col)
        loc_dest = self.location_manager.locations[dest]

        if isinstance(loc_dest, Coordinate):
            raise ValueError(
                f"Destination '{dest}' is a coordinate, not a plate. "
                f"Dispensing requires a plate with dipping strategy."
            )

        well = (
            dest
            if dest_row is None or dest_col is None
            else f"{dest}[{dest_row},{dest_col}]"
        )
        vol_desc = f"{volume:g}μL" if volume else "remaining volume"
        self.note_action(f"Dispensing {vol_desc} to '{well}'")

        self.move_to(coor_dest)
        self.dip_z_down(coor_dest, loc_dest.get_dip_distance(volume))

        if volume:
            # The post-aspirate cushion sits between the liquid and the tip
            # orifice, so it has to be driven out ahead of the liquid or the
            # well receives `purge_air_gap_ul` less than it was asked for.
            self.operate_syringe(FluidDisplacement.dispense, volume + purge_air_gap_ul)
        else:
            self.clear_syringe()

        self.gcode_wait(self.syringe.wait_dispense_ms)

        if wiggle:
            self.wiggle(coor_dest, loc_dest.get_dip_distance(volume))

        self.state.has_liquid = not empties_tip
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
        pre_air_gap_ul: float | None = None,
        post_air_gap_ul: float | None = None,
        prewet_cycles: int | None = None,
        prewet_vol_ul: float | None = None,
        wiggle: bool = False,
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
            pre_air_gap_ul: Air before the liquid in μL, or None to take
                the active liquid profile's value.
            post_air_gap_ul: Air after the liquid in μL, or None to take
                the active liquid profile's value.
            prewet_cycles: Number of prewet cycles, or None for the profile's value.
            prewet_vol_ul: Volume per prewet cycle in μL, or None for the
                profile's value.
            wiggle: If True, shake tip during dispensing.
            keep_tip: If True, retain tip after operation.

        Raises:
            ValueError: If requested volume is negative.
            VolumeCapacityError: If the air gaps leave no room for liquid.
            NotALocationError: If ``source``/``dest`` is not a defined
                location.
            NoTipboxError: If a tip pickup is needed but no tipbox is
                configured.
            OutOfTipsError: If a tip pickup is needed and every configured
                tipbox is exhausted.
            NoWasteContainerError: If the transfer disposes of its tip
                (``keep_tip`` is False) and no waste container is configured.

        Example:
            >>> # Simple transfer
            >>> pipette.pipette(
            ...     vol_ul=100, source="plate_a", dest="plate_b"
            ... )  # doctest: +SKIP

            >>> # Multi-liquid protocol
            >>> pipette.switch_liquid("water")  # doctest: +SKIP
            >>> pipette.pipette(
            ...     vol_ul=100, source="water_res", dest="plate"
            ... )  # doctest: +SKIP
            >>>
            >>> pipette.switch_liquid("methanol")  # doctest: +SKIP
            >>> pipette.pipette(
            ...     vol_ul=50, source="methanol_res", dest="plate"
            ... )  # doctest: +SKIP

            >>> # Large volume (automatically chunked)
            >>> pipette.pipette(vol_ul=500, source="a", dest="b")  # doctest: +SKIP
        """  # ruff: ignore[docstring-extraneous-exception]
        if vol_ul < 0:
            raise ValueError(f"Invalid volume: {vol_ul}μL. Volume must be positive.")

        # Resolve here as well as in aspirate_volume: chunking below needs the
        # real air overhead, and passing the resolved values down keeps every
        # chunk on the same technique even if the liquid were switched.
        pre_air_gap_ul, post_air_gap_ul, prewet_cycles, prewet_vol_ul = (
            self.resolve_technique(
                pre_air_gap_ul, post_air_gap_ul, prewet_cycles, prewet_vol_ul
            )
        )

        # Pick up tip if needed
        if self.state.tip_state == TipState.DETACHED:
            self.next_tip(tipbox_name=tipbox_name)

        # Calculate transfer chunks based on max pipette capacity. The air
        # gaps ride along inside the same syringe, so they come out of the
        # per-chunk budget -- chunking on max_volume_ul alone would overflow
        # by exactly the air overhead on every full chunk.
        max_vol = self.usable_capacity_ul() - pre_air_gap_ul - post_air_gap_ul
        if max_vol <= PhysicalConstants.VOLUME_TOLERANCE_UL:
            raise VolumeCapacityError(vol_ul, self.usable_capacity_ul())

        chunks = int(vol_ul // max_vol)
        remainder = vol_ul - (chunks * max_vol)
        transfer_volumes: list[float] = [float(max_vol)] * chunks

        # Add remainder if significant
        if remainder > PhysicalConstants.VOLUME_TOLERANCE_UL:
            transfer_volumes.append(remainder)

        self.note_action(
            f"Transferring {vol_ul:g}μL from '{source}' to '{dest}' "
            f"({len(transfer_volumes)} chunk(s))"
        )

        # Execute transfer sequence
        for pip_vol in transfer_volumes:
            self.aspirate_volume(
                pip_vol,
                source,
                src_row=src_row,
                src_col=src_col,
                pre_air_gap_ul=pre_air_gap_ul,
                post_air_gap_ul=post_air_gap_ul,
                prewet_cycles=prewet_cycles,
                prewet_vol_ul=prewet_vol_ul,
            )

            # Only dispense the passed in amount if present
            if disp_vol_ul:
                self.dispense_volume(
                    dest,
                    dest_row=dest_row,
                    dest_col=dest_col,
                    volume=disp_vol_ul,
                    wiggle=wiggle,
                    purge_air_gap_ul=post_air_gap_ul,
                )
                break
            self.dispense_volume(
                dest,
                dest_row=dest_row,
                dest_col=dest_col,
                wiggle=wiggle,
            )

        # Dispose of tip unless explicitly keeping it
        if not keep_tip:
            self.dispose_tip()

    def resolve_splits(
        self, vol_ul: float, splits: Sequence[Split], leftover: LeftoverAction | None
    ) -> list[tuple[Split, int | None, int | None]]:
        """Validate a parsed splits spec against the deck.

        Runs every check that can be made without moving, so a bad spec is
        rejected before a single G-code line is emitted rather than stranding
        a half-dispensed tip partway through a plate. This mirrors
        ``LocationManager.load_from_json``'s parse-everything-then-apply rule.

        Args:
            vol_ul: The volume that will be aspirated once, in microliters.
            splits: The parsed splits, in dispense order.
            leftover: What to do with liquid remaining after the last split,
                or None if the caller did not say.

        Returns:
            One ``(split, dest_row, dest_col)`` triple per split. The row and
            column are None where the split named no well, meaning the
            plate's own traversal order picks it.

        Raises:
            ValueError: If `splits` is empty, a destination is not a plate,
                a well ID is outside its plate, the splits together exceed
                `vol_ul`, or liquid would be left over without `leftover`
                saying what to do with it.
            NoWasteContainerError: If `leftover` is ``"waste"`` and no waste
                container is configured. Checked here rather than at the end
                of the run, so the failure surfaces before any liquid moves.
            VolumeCapacityError: If `vol_ul` exceeds usable syringe capacity.
            NotALocationError: If a split's destination is not a defined
                location.
        """  # ruff: ignore[docstring-extraneous-exception]
        if not splits:
            raise ValueError("No splits given.")

        resolved: list[tuple[Split, int | None, int | None]] = []
        for split in splits:
            if not self.location_manager.has_location(split.dest):
                raise NotALocationError(split.dest)

            loc = self.location_manager.locations[split.dest]
            if isinstance(loc, Coordinate):
                raise ValueError(
                    f"Split destination '{split.dest}' is a coordinate, not a "
                    f"plate. Dispensing requires a plate with dipping strategy."
                )

            if split.well_id is None:
                resolved.append((split, None, None))
                continue

            # Raises ValueError naming the plate's dimensions if out of range.
            row, col = well_id_to_rc(split.well_id, loc.num_row, loc.num_col)
            resolved.append((split, row, col))

        total = sum(split.vol_ul for split in splits)
        if total - vol_ul > PhysicalConstants.VOLUME_TOLERANCE_UL:
            raise ValueError(
                f"Split volumes total {total} μL, which exceeds the "
                f"{vol_ul} μL aspirated."
            )

        # Confirm the aspirate itself is physically possible before moving.
        self.fit_air_volumes(vol_ul, 0.0, 0.0)

        remaining = vol_ul - total
        if remaining > PhysicalConstants.VOLUME_TOLERANCE_UL:
            if leftover is None:
                raise ValueError(
                    f"Splits dispense {total} μL of the {vol_ul} μL aspirated, "
                    f"leaving {remaining} μL in the tip. Pass --leftover keep "
                    f"or --leftover waste to say what should happen to it."
                )
            if leftover == "waste" and self.location_manager.waste_container is None:
                raise NoWasteContainerError()

        return resolved

    def pipette_splits(
        self,
        vol_ul: float,
        source: str,
        splits: Sequence[Split],
        src_row: int | None = None,
        src_col: int | None = None,
        tipbox_name: str | None = None,
        pre_air_gap_ul: float | None = None,
        post_air_gap_ul: float | None = None,
        prewet_cycles: int | None = None,
        prewet_vol_ul: float | None = None,
        wiggle: bool = False,
        leftover: LeftoverAction | None = None,
        keep_tip: bool = False,
    ) -> None:
        """Aspirate once, then dispense to several destinations in turn.

        Saves a tip pickup and a trip to the source per destination compared
        with one ``pipette`` call per well, which matters most when the
        source is a shared reagent reservoir.

        Unlike ``pipette``, this never chunks: the whole `vol_ul` must fit in
        the syringe at once, since the point is a single aspirate.

        Args:
            vol_ul: Volume to aspirate once, in microliters.
            source: Name of source location/plate.
            splits: Destinations and their volumes, in dispense order.
            src_row: Source plate row index (0-based).
            src_col: Source plate column index (0-based).
            tipbox_name: Name of specific tipbox to use.
            pre_air_gap_ul: Air before the liquid in μL, or None for the
                active liquid profile's value.
            post_air_gap_ul: Air after the liquid in μL, or None for the
                active liquid profile's value.
            prewet_cycles: Number of prewet cycles, or None for the profile's value.
            prewet_vol_ul: Volume per prewet cycle in μL, or None for the
                profile's value.
            wiggle: If True, shake tip during each dispense.
            leftover: What to do with liquid remaining after the last split.
                Required when the splits do not consume the whole aspirate.
            keep_tip: If True, retain tip after the operation. A tip still
                holding liquid (``leftover="keep"``) is always retained
                regardless, rather than being discarded with liquid inside.

        Raises:
            ValueError: If `vol_ul` is not positive, or the spec fails
                validation -- see ``resolve_splits``.
            NoWasteContainerError: If the tip or its leftover must go to
                waste and no waste container is configured.
            VolumeCapacityError: If `vol_ul` exceeds usable syringe capacity.
            NotALocationError: If a split's destination is not a defined
                location (see ``resolve_splits``).
            NoTipboxError: If a tip pickup is needed but no tipbox is
                configured.
            OutOfTipsError: If a tip pickup is needed and every configured
                tipbox is exhausted.

        Example:
            >>> # 12 μL to plate_a's A1 and 8 μL to plate_b's C3, one aspirate
            >>> pipette.pipette_splits(  # doctest: +SKIP
            ...     vol_ul=20,
            ...     source="reservoir",
            ...     splits=parse_splits_spec("plate_a:12@A1;plate_b:8@C3"),
            ... )
        """  # ruff: ignore[docstring-extraneous-exception]
        if vol_ul <= 0:
            raise ValueError(f"Invalid volume: {vol_ul}μL. Volume must be positive.")

        resolved = self.resolve_splits(vol_ul, splits, leftover)

        pre_air_gap_ul, post_air_gap_ul, prewet_cycles, prewet_vol_ul = (
            self.resolve_technique(
                pre_air_gap_ul, post_air_gap_ul, prewet_cycles, prewet_vol_ul
            )
        )

        if self.state.tip_state == TipState.DETACHED:
            self.next_tip(tipbox_name=tipbox_name)

        destinations = ", ".join(f"{s.dest}:{s.vol_ul:g}μL" for s in splits)
        self.note_action(
            f"Aspirating {vol_ul:g}μL from '{source}' for {len(splits)} split(s) "
            f"({destinations})"
        )
        self.aspirate_volume(
            vol_ul,
            source,
            src_row=src_row,
            src_col=src_col,
            pre_air_gap_ul=pre_air_gap_ul,
            post_air_gap_ul=post_air_gap_ul,
            prewet_cycles=prewet_cycles,
            prewet_vol_ul=prewet_vol_ul,
        )
        # fit_air_volumes may have shrunk the cushion during the aspirate; the
        # first dispense has to purge exactly what actually went in.
        _, applied_post_air = self.fit_air_volumes(
            vol_ul, pre_air_gap_ul, post_air_gap_ul
        )

        dispensed = 0.0
        for index, (split, dest_row, dest_col) in enumerate(resolved):
            dispensed += split.vol_ul
            self.dispense_volume(
                split.dest,
                dest_row=dest_row,
                dest_col=dest_col,
                volume=split.vol_ul,
                wiggle=wiggle,
                purge_air_gap_ul=applied_post_air if index == 0 else 0.0,
                empties_tip=False,
            )

        remaining = vol_ul - dispensed
        has_leftover = remaining > PhysicalConstants.VOLUME_TOLERANCE_UL

        if has_leftover and leftover == "waste":
            self.empty_tip_to_waste()
            has_leftover = False

        self.state.has_liquid = has_leftover

        # Never send a tip holding liquid to the bin: `leftover="keep"` is an
        # explicit instruction to hang on to it, so it outranks keep_tip.
        if not keep_tip and not has_leftover:
            self.dispose_tip()

    def empty_tip_to_waste(self) -> None:
        """Expel whatever is left in the tip into the waste container.

        Leaves the tip attached -- disposal is a separate decision, made by
        the caller.

        Raises:
            NoWasteContainerError: If no waste container is configured.
        """
        waste = self.location_manager.waste_container
        if waste is None:
            raise NoWasteContainerError()

        self.note_action("Emptying leftover tip contents to waste container")
        curr_coor = waste.next()
        self.move_to(curr_coor)
        self.dip_z_down(curr_coor, waste.get_dip_distance(vol=None))
        self.clear_syringe()
        self.gcode_wait(self.syringe.wait_dispense_ms)
        self.dip_z_return(curr_coor)
        self.home_pipette_stepper()
        self.state.has_liquid = False

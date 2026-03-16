"""AutoPipette controller and configuration management.

This module provides the main AutoPipette class for controlling automated
pipetting operations, along with supporting models and custom exceptions.

The AutoPipette class manages:
- Configuration loading and validation
- G-code command generation and buffering
- Location and plate management
- Pipetting operations (aspirate, dispense, tip handling)
- Volume calculations and transfer chunking

Example:
    >>> pipette = AutoPipette("custom_config.conf")
    >>> pipette.init_pipette()
    >>> pipette.pipette(vol_ul=100, source="plate_a", dest="plate_b")
"""

from __future__ import annotations

import logging

from config_manager import ConfigManager
from coordinate import Coordinate
from gcode_buffer import GCodeBuffer
from location_manager import LocationManager
from pipette_constants import (
    ConfigSection,
    CoordinateSystem,
    DefaultPaths,
    GCodeCommand,
    PhysicalConstants,
)
from pipette_exceptions import (
    NoTipboxError,
    TipAlreadyOnError,
)
from pipette_models import FluidDisplacement, PipetteModel, PipetteParams, PipetteState
from plates import Plate
from volume_converter import VolumeConverter


class AutoPipette:
    """Main controller class for automated pipette operations.

    Manages all aspects of pipette control including configuration loading,
    G-code generation, location management, and pipetting operations. Each
    instance maintains independent state and configuration.

    Attributes:
        logger: Logger instance for debugging and error tracking.
        config: Loaded configuration settings from INI file.
        volume_converter: Converts between volumes and motor steps.
        waste_container: Designated waste disposal location.
        tipboxes: Available tip container(s).
        locations: Dictionary of named coordinates and plates.
        pipette_params: Validated pipette configuration parameters.
        has_tip: Current tip attachment status.
        has_liquid: Current liquid presence in tip.
        homed: Whether pipette has been homed.
        DEFAULT_CONFIG: Default configuration filename.
        CONFIG_PATH: Directory containing configuration files.
        NECESSARY_CONFIG_SECTIONS: Required configuration sections.

    Example:
        >>> pipette = AutoPipette("my_config.conf")
        >>> pipette.init_pipette()
        >>> pipette.pipette(vol_ul=100, source="plate_a", dest="plate_b")
        >>> gcode = pipette.get_gcode()
    """

    # Class-level constants
    DEFAULT_CONFIG = DefaultPaths.DEFAULT_CONFIG
    CONFIG_PATH = DefaultPaths.CONFIG_DIR
    NECESSARY_CONFIG_SECTIONS = [section.value for section in ConfigSection]

    def __init__(self, config_file: str | None = None) -> None:
        """Initialize pipette controller with configuration.

        Loads configuration from file, initializes buffers, and sets up
        volume conversion. Does not home or initialize hardware - call
        init_pipette() for that.

        Args:
            config_file: Path to configuration file, or None for default
                        (autopipette.conf).

        Example:
            >>> # Default configuration
            >>> pipette = AutoPipette()

            >>> # Custom configuration
            >>> pipette = AutoPipette("custom.conf")
        """
        # Logging
        self.logger = logging.getLogger(__name__)

        # Configuration
        self.config_manager = ConfigManager(
            config_path=self.CONFIG_PATH, config_file=config_file or self.DEFAULT_CONFIG
        )
        self.pipette_params: PipetteParams = (
            self.config_manager.get_default_pipette_params()
        )

        # Location management - now using LocationManager
        self.location_manager = LocationManager(self.config_manager)

        # Components
        self.volume_converter: VolumeConverter = VolumeConverter()

        # State tracking
        self.state = PipetteState()

        # Physical design parameters
        self.model = PipetteModel()

        # G-code management
        self.gcode_buffers = GCodeBuffer()

        # Initialize from loaded config
        self._initialize_from_config()

    def _initialize_from_config(self) -> None:
        """Initialize pipette from loaded configuration.

        Extracts parameters, parses locations, initializes volume converter,
        and builds G-code header.
        """
        # Extract pipette parameters
        self.pipette_params = self.config_manager.get_pipette_params()

        # Parse and set up locations
        self._parse_config_locations()

        # Initialize volume converter
        self._init_volume_converter()

        # Initialize model dependent variables
        self._init_model_params()

        # Build G-code header
        self._build_header()

    def _build_header(self) -> None:
        """Generate G-code header with configuration summary.

        Creates a commented header containing all configuration settings
        for documentation and debugging purposes.

        Note:
            Clears any existing header before rebuilding.
        """
        sections = self.config_manager.get_all_sections_as_dict()
        self.gcode_buffers.build_header_from_config(
            self.config_manager.config_file or "unknown", sections
        )

    def load_config_file(self, filename: str) -> None:
        """Load a new configuration file and reinitialize.

        Args:
            filename: Name of configuration file (relative to CONFIG_PATH).

        Example:
            >>> pipette = AutoPipette()
            >>> pipette.load_config_file("alternate.conf")
        """
        self.config_manager.load(filename)
        self._initialize_from_config()

    def save_config_file(self, filename: str | None = None) -> None:
        """Save current configuration to a file.

        Configs are saved under the conf/ folder located in the root of the
        project.

        Args:
            filename: The filename to save the config as, or None to use
                     the current config filename with '-test' suffix.

        Note:
            Currently does not save dynamically added locations or updated
            coordinates. This is a known limitation.

        Todo:
            - Save new locations when added
            - Save updated location coordinates
            - Add location removal support

        Example:
            >>> pipette.save_config_file("backup.conf")
        """
        self.config_manager.save(filename)

    def _parse_config_locations(self) -> None:
        """Parse coordinate and plate configurations from loaded config.

        Loads all locations from the configuration manager into the
        location manager.

        Note:
            Clears existing locations before parsing.
        """
        self.location_manager.load_from_config(self.config_manager)

    def _init_volume_converter(self) -> None:
        """Initialize volume-to-steps converter from configuration.

        Creates a VolumeConverter instance using calibration data from the
        configuration.

        Note:
            Volume converter is required for all pipetting operations.
        """
        volumes, steps = self.config_manager.get_volume_calibration()
        self.volume_converter = VolumeConverter(volumes, steps)
        self.logger.debug(
            f"Initialized volume converter: {len(volumes)} calibration points"
        )

    def _init_model_params(self) -> None:
        """Initialize autopipette model dependent variables.

        TODO Load a JSON file that contains the relevant variables for every physical
        parameter that affects the functioning of the pipette.
        """
        if self.pipette_params.model == "verticle":
            self.model.pipette_motor_orientation = -1
            if self.location_manager.tipboxes is not None:
                self.location_manager.tipboxes.wells.reverse()
        elif self.pipette_params.model == "horizontal":
            self.model.pipette_motor_orientation = 1
        else:
            self.model.pipette_motor_orientation = 1

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

    def init_speed(self) -> None:
        """Configure speed and acceleration parameters.

        Sets three critical motion parameters:
        - SPEED_FACTOR: Multiplier for calculated speeds (1-200%)
        - MAX_VELOCITY: Maximum possible velocity in mm/s
        - MAX_ACCEL: Maximum possible acceleration in mm/s²

        Values are read from pipette_params which were loaded from
        configuration file.

        Example:
            >>> pipette.init_speed()  # Uses config values
            >>> # Or modify before init:
            >>> pipette.pipette_params.speed_factor = 150
            >>> pipette.init_speed()
        """
        self.set_speed_factor(self.pipette_params.speed_factor)
        self.set_max_velocity(self.pipette_params.velocity_max)
        self.set_max_accel(self.pipette_params.accel_gantry_max)

    def set_coor_sys(self, mode: str | CoordinateSystem) -> None:
        """Set the coordinate system mode for motion commands.

        Args:
            mode: Either "absolute" or "incremental"/"relative" (case-insensitive).

        Raises:
            ValueError: If an invalid mode is provided.

        Note:
            - Absolute (G90): Coordinates are absolute positions
            - Relative (G91): Coordinates are offsets from current position

        Example:
            >>> pipette.set_coor_sys("absolute")
            >>> pipette.move_to(Coordinate(10, 10, 5))  # Move to X=10, Y=10, Z=5

            >>> pipette.set_coor_sys("relative")
            >>> pipette.move_to(Coordinate(5, 0, 0))  # Move 5mm in X direction
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
            Updates both the config and pipette_params to keep them in sync.
            100 = normal speed, 200 = double speed, 50 = half speed.

        Example:
            >>> pipette.set_speed_factor(150)  # 1.5x speed
        """
        self.config_manager.update_value("SPEED", "SPEED_FACTOR", str(factor))
        self.pipette_params.speed_factor = int(factor)
        self.gcode_buffers.add(f"{GCodeCommand.SPEED_FACTOR} S{factor}\n")

    def set_max_velocity(self, velocity: float) -> None:
        """Set the maximum velocity limit.

        Args:
            velocity: Maximum velocity in mm/s.

        Note:
            Updates both the config and pipette_params to keep them in sync.

        Example:
            >>> pipette.set_max_velocity(5000)  # 5000 mm/s max
        """
        self.config_manager.update_value("SPEED", "VELOCITY_MAX", str(velocity))
        self.pipette_params.velocity_max = int(velocity)
        self.gcode_buffers.add(f"SET_VELOCITY_LIMIT VELOCITY={velocity}\n")

    def set_max_accel(self, accel: float) -> None:
        """Set the maximum acceleration limit.

        Args:
            accel: Maximum acceleration in mm/s².

        Note:
            Updates both the config and pipette_params to keep them in sync.

        Example:
            >>> pipette.set_max_accel(3000)  # 3000 mm/s² max
        """
        self.config_manager.update_value("SPEED", "ACCEL_GANTRY_MAX", str(accel))
        self.pipette_params.accel_gantry_max = int(accel)
        self.gcode_buffers.add(f"SET_VELOCITY_LIMIT ACCEL={accel}\n")

    def home_axis(self) -> None:
        """Home all axes (X, Y, and Z).

        Homes Z axis first to prevent collisions, then homes X and Y axes.
        This is the standard homing sequence for safety.

        Note:
            The G28 command without parameters homes all axes in the safe
            order defined by the firmware.

        Example:
            >>> pipette.home_axis()
            >>> # All axes are now at home position
        """
        self.gcode_buffers.add(f"{GCodeCommand.HOME_ALL}\n")

    def home_x(self) -> None:
        """Home X axis only.

        Example:
            >>> pipette.home_x()
        """
        self.gcode_buffers.add(f"{GCodeCommand.HOME_X}\n")

    def home_y(self) -> None:
        """Home Y axis only.

        Example:
            >>> pipette.home_y()
        """
        self.gcode_buffers.add(f"{GCodeCommand.HOME_Y}\n")

    def home_z(self) -> None:
        """Home Z axis only.

        Note:
            Homing Z first is recommended to avoid collisions with plates
            or other objects on the bed.

        Example:
            >>> pipette.home_z()
        """
        self.gcode_buffers.add(f"{GCodeCommand.HOME_Z}\n")

    def home_pipette_motors(self) -> None:
        """Home all pipette-specific motors.

        Homes the servo (tip ejection mechanism) and the stepper motor
        (plunger control) in the correct sequence.

        Note:
            This is part of the full initialization sequence and should be
            called after homing the axes.

        Example:
            >>> pipette.home_axis()
            >>> pipette.home_pipette_motors()
        """
        self.home_servo()
        self.home_pipette_stepper()

    def home_servo(self) -> None:
        """Retract the tip ejection servo to home position.

        Sets servo to retracted angle and waits for movement to complete.
        This ensures tips won't be accidentally ejected during operation.

        Example:
            >>> pipette.home_servo()
        """
        self.set_servo_angle(self.pipette_params.servo_angle_retract)
        self.gcode_wait(self.pipette_params.wait_movement)

    def home_pipette_stepper(
        self,
        stepper: str | None = None,
        speed: float | None = None,
        accel: float | None = None,
    ) -> None:
        """Home the pipette plunger stepper motor.

        Moves the stepper until it hits the endstop, then sets that position
        as zero. This establishes the reference point for volume measurements.

        Args:
            stepper: Name of the stepper motor to home, or None to use configured
                     stepper.
            speed: Homing speed in steps/s, or None to use configured slow speed.
            accel: Homing acceleration in mm/min, or None to use configured homing
                   acceleration.

        Note:
            Uses slow speed and homing acceleration by default to prevent damage when
            hitting endstop.
            Function also used to clear pipette of fluid.

        Example:
            >>> pipette.home_pipette_stepper()
            >>> # Or with custom speed:
            >>> pipette.home_pipette_stepper(speed=100)
        """
        if stepper is None:
            stepper = self.pipette_params.name_pipette_stepper
        if speed is None:
            speed = self.pipette_params.speed_pipette_up_slow
        if accel is None:
            accel = self.pipette_params.accel_pipette_home
        # Twice the max distance means the pipette is guaranteed to home
        distance = self.volume_converter.vol_to_steps(2 * self.pipette_params.max_vol)
        # Assume stepper moves in the dispensing direction
        distance *= FluidDisplacement.dispense
        # Ensure motor move in the correct direction despite its orientation
        distance *= self.model.pipette_motor_orientation
        # Create a distance with flipped direction to move motor beyond triggering home
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
        """Move the pipette toolhead to the specified coordinate.

        Moves in XY plane first at horizontal speed, then moves Z axis
        at vertical speed. This is safer than diagonal moves.

        Args:
            coordinate: Target position in 3D space.

        Note:
            Movement uses speeds from pipette_params (speed_xy and speed_z).
            Coordinate system (absolute/relative) affects interpretation.

        Example:
            >>> pipette.move_to(Coordinate(x=100, y=50, z=10))
        """
        speed_xy = self.pipette_params.speed_xy
        speed_z = self.pipette_params.speed_z
        self.gcode_buffers.add(
            f"{GCodeCommand.LINEAR_MOVE} X{coordinate.x} Y{coordinate.y} F{speed_xy}\n"
        )
        self.gcode_buffers.add(
            f"{GCodeCommand.LINEAR_MOVE} Z{coordinate.z} F{speed_z}\n"
        )

    def move_to_x(self, coordinate: Coordinate) -> None:
        """Move only in the X direction to coordinate's X position.

        Args:
            coordinate: Coordinate containing the target X position.

        Note:
            Y and Z positions remain unchanged.

        Example:
            >>> pipette.move_to_x(Coordinate(x=100, y=0, z=0))
            >>> # Only X moves to 100, Y and Z stay at current position
        """
        speed = self.pipette_params.speed_xy
        self.gcode_buffers.add(f"{GCodeCommand.LINEAR_MOVE} X{coordinate.x} F{speed}\n")

    def move_to_y(self, coordinate: Coordinate) -> None:
        """Move only in the Y direction to coordinate's Y position.

        Args:
            coordinate: Coordinate containing the target Y position.

        Note:
            X and Z positions remain unchanged.

        Example:
            >>> pipette.move_to_y(Coordinate(x=0, y=50, z=0))
            >>> # Only Y moves to 50, X and Z stay at current position
        """
        speed = self.pipette_params.speed_xy
        self.gcode_buffers.add(f"{GCodeCommand.LINEAR_MOVE} Y{coordinate.y} F{speed}\n")

    def move_to_z(self, coordinate: Coordinate) -> None:
        """Move only in the Z direction to coordinate's Z position.

        Args:
            coordinate: Coordinate containing the target Z position.

        Note:
            X and Y positions remain unchanged.

        Example:
            >>> pipette.move_to_z(Coordinate(x=0, y=0, z=10))
            >>> # Only Z moves to 10, X and Y stay at current position
        """
        speed = self.pipette_params.speed_z
        self.gcode_buffers.add(f"{GCodeCommand.LINEAR_MOVE} Z{coordinate.z} F{speed}\n")

    def set_servo_angle(self, angle: float) -> None:
        """Set the tip ejection servo to a specific angle.

        Args:
            angle: Target angle in degrees (typically 20-160°).

        Note:
            Valid angle range depends on servo configuration. Typical values:
            - Retracted: ~160° (tip held firmly)
            - Ready: ~90° (ready to eject)

        Example:
            >>> pipette.set_servo_angle(90)  # Ready position
            >>> pipette.set_servo_angle(160)  # Retracted position
        """
        servo = self.pipette_params.name_pipette_servo
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
            distance: Distance to move in motor steps (positive values).
            stepper: Name of the stepper to move, or None for configured stepper.
            speed: Movement speed in steps/s, or None for configured slow speed.
            accel: Movement acceleration in mm/min, or None for configured acceleration.

        Note:
            Distance is converted to negative in G-code (plunger convention).
            Used for aspirating and dispensing liquid.

        Example:
            >>> # Move plunger down 100 steps
            >>> pipette.move_pipette_stepper(100)

            >>> # With custom speed
            >>> pipette.move_pipette_stepper(100, speed=500)
        """
        if stepper is None:
            stepper = self.pipette_params.name_pipette_stepper
        if speed is None:
            speed = self.pipette_params.speed_pipette_up_slow
        if accel is None:
            accel = self.pipette_params.accel_pipette_move
        self.gcode_buffers.add(
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0 "
            f"SPEED={speed} MOVE={distance} ACCEL={accel} "
            f"STOP_ON_ENDSTOP=2 \n"
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n"
        )

    def gcode_wait(self, milliseconds: float) -> None:
        """Insert a dwell/pause command in the G-code.

        Args:
            milliseconds: Duration to wait in milliseconds.

        Note:
            Used to allow time for:
            - Liquid to settle after aspiration
            - Servo movements to complete
            - System stabilization

        Example:
            >>> pipette.gcode_wait(500)  # Wait 0.5 seconds
        """
        self.gcode_buffers.add(f"{GCodeCommand.DWELL} P{milliseconds}\n")

    def gcode_print(self, msg: str) -> None:
        """Send a message to be displayed on the printer/controller screen.

        Args:
            msg: Message string to display.

        Note:
            Useful for debugging and providing user feedback during
            long-running protocols.

        Example:
            >>> pipette.gcode_print("Starting protocol...")
            >>> pipette.gcode_print("Aspirating from plate A")
        """
        self.gcode_buffers.add(f"{GCodeCommand.DISPLAY_MESSAGE} {msg}\n")

    def get_gcode(self) -> list[str]:
        r"""Retrieve buffered G-code commands and clear the buffer.

        Returns:
            List of G-code command strings that were buffered.

        Note:
            This is destructive - the buffer is cleared after retrieval.
            Call this after completing a sequence of operations to get
            the generated G-code.

        Example:
            >>> pipette.home_axis()
            >>> pipette.move_to(Coordinate(10, 10, 5))
            >>> commands = pipette.get_gcode()
            >>> # commands = ['G28\\n', 'G1 X10 Y10 F5000\\n', ...]
        """
        return self.gcode_buffers.get_commands()

    def get_header(self) -> list[str]:
        r"""Retrieve the configuration header.

        Returns:
            List of commented G-code lines describing the configuration.

        Note:
            Unlike get_gcode(), this does NOT clear the header buffer.
            The header can be retrieved multiple times.

        Example:
            >>> header = pipette.get_header()
            >>> # header = ['; Configuration: autopipette.conf\\n', ...]
        """
        return self.gcode_buffers.get_header()

    def next_tip(self) -> None:
        """Pick up the next available tip from the configured tipbox.

        Moves to the next tip position, dips down to attach the tip,
        and returns to safe Z height.

        Raises:
            NoTipboxError: If no tipbox has been configured.
            TipAlreadyOnError: If a tip is already attached.

        Note:
            Updates has_tip state to True.
            Tipbox automatically tracks which tip is next.

        Example:
            >>> pipette.next_tip()
            >>> # Tip is now attached and ready for use
        """
        if self.location_manager.tipboxes is None:
            raise NoTipboxError()
        if self.state.has_tip:
            raise TipAlreadyOnError()

        # Get next tip position from tipbox
        loc_tip = self.location_manager.tipboxes.next()

        # Move to tip and pick it up
        self.move_to(loc_tip)
        self.dip_z_down(
            loc_tip, self.location_manager.tipboxes.get_dip_distance(vol=None)
        )
        self.dip_z_return(loc_tip)

        self.state.has_tip = True

    def eject_tip(self) -> None:
        """Eject the current pipette tip.

        Performs a servo sequence to mechanically eject the tip:
        1. Retract servo (pushes ejector sleeve down)
        2. Return to ready position
        3. Wait for ejection to complete
        4. Return to retracted position

        Note:
            Updates has_tip state to False.
            Tip should be positioned over waste or tip disposal location.

        Example:
            >>> pipette.next_tip()  # Pick up tip
            >>> # ... perform operations ...
            >>> pipette.eject_tip()  # Drop tip in place
        """
        angle_retract = self.pipette_params.servo_angle_retract
        angle_ready = self.pipette_params.servo_angle_eject
        wait_eject = self.pipette_params.wait_eject
        wait_movement = self.pipette_params.wait_movement

        self.set_servo_angle(angle_retract)
        self.set_servo_angle(angle_ready)
        self.gcode_wait(wait_eject)
        self.set_servo_angle(angle_retract)
        self.gcode_wait(wait_movement)

        self.state.has_tip = False

    def dispose_tip(self) -> None:
        """Eject the current tip into the waste container.

        Moves to the waste container, dips down, ejects the tip,
        and returns to safe height.

        Raises:
            RuntimeError: If no waste container is configured.

        Note:
            Updates has_tip state to False.
            Waste container automatically tracks position for next disposal.

        Example:
            >>> pipette.dispose_tip()
            >>> # Tip is now in waste container
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
            curr_coor: Current XY position (Z will be modified).
            distance: Distance to move down in the Z axis (positive value).

        Note:
            Waits for movement to stabilize after dipping.
            Used for tip pickup, aspiration, and dispensing.

        Example:
            >>> current = Coordinate(x=100, y=100, z=50)
            >>> pipette.dip_z_down(current, distance=10)
            >>> # Moves to Z=10 (50 - 10 = 40 below current)
        """
        coor_dip = Coordinate(x=curr_coor.x, y=curr_coor.y, z=distance)
        self.move_to_z(coor_dip)
        self.gcode_wait(self.pipette_params.wait_movement)

    def dip_z_return(self, curr_coor: Coordinate) -> None:
        """Return the pipette to the original Z height.

        Args:
            curr_coor: Original coordinate to return to.

        Note:
            Waits for movement to stabilize after returning.
            Always called after dip_z_down to return to safe height.

        Example:
            >>> original = Coordinate(x=100, y=100, z=50)
            >>> pipette.dip_z_down(original, distance=10)
            >>> # ... perform operation ...
            >>> pipette.dip_z_return(original)
            >>> # Back at Z=50
        """
        self.move_to_z(curr_coor)
        self.gcode_wait(self.pipette_params.wait_movement)

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
            stepper: Name of the stepper to move, or None for configured stepper.
            speed: Plunger movement speed in steps/s, or None for configured speed.
            accel: Plunger movement acceleration in mm/min, or None for configured
                   acceleration.

        Note:
            Converts volume to motor steps using the volume converter.

        Example:
            >>> # Pull syringe for 100µL aspiration
            >>> pipette.operate_syringe(FluidDisplacement.aspirate, 100)
        """
        if stepper is None:
            stepper = self.pipette_params.name_pipette_stepper
        if speed is None:
            if direction is FluidDisplacement.aspiration:
                speed = self.pipette_params.speed_pipette_up
            else:  # direction is FluidDisplacement.dispense:
                speed = (self.pipette_params.speed_pipette_up if serum_speed else self.pipette_params.speed_pipette_down)
                
                #self.pipette_params.speed_pipette_down
        if accel is None:
            accel = self.pipette_params.accel_pipette_move
        steps = self.volume_converter.vol_to_steps(vol_ul)
        # Make sure the syringe moves in either the aspirate or dispense direction
        steps *= direction
        # Make sure the syringe moves in the assumed orientation of the motor
        steps *= self.model.pipette_motor_orientation
        self.move_pipette_stepper(steps, stepper, speed, accel)

    def clear_syringe(
        self,
        stepper: str | None = None,
        speed: float | None = None,
        accel: float | None = None,
    ) -> None:
        """Move the pipette syringe to the endstop.

        Moves the stepper until it hits the endstop, then sets that position
        as zero. This clears the pipette of any fluid.

        Args:
            stepper: Name of the stepper motor to home, or None to use configured
                     stepper.
            speed: Homing speed in steps/s, or None to use configured slow speed.
            accel: Homing acceleration in mm/min, or None to use configured homing
                   acceleration.

        Note:
            Uses slow speed and homing acceleration by default to prevent damage when
            hitting endstop.
            Function also used to clear pipette of fluid.

        Example:
            >>> pipette.clear_syringe()
            >>> # Or with custom speed:
            >>> pipette.clear_syringe(speed=100)
        """
        if stepper is None:
            stepper = self.pipette_params.name_pipette_stepper
        if speed is None:
            speed = self.pipette_params.speed_pipette_down
        if accel is None:
            accel = self.pipette_params.accel_pipette_home
        # Twice the max distance means the pipette is guaranteed to hit the endstop
        distance = self.volume_converter.vol_to_steps(2 * self.pipette_params.max_vol)
        # Assume stepper moves in the dispensing direction
        distance *= FluidDisplacement.dispense
        # Ensure motor move in the correct direction despite its orientation
        distance *= self.model.pipette_motor_orientation
        self.gcode_buffers.add(
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0 "
            f"MOVE={distance} SPEED={speed} ACCEL={accel} "
            f"STOP_ON_ENDSTOP=1\n"
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n"
        )

    def wiggle(self, curr_coor: Coordinate, dip_distance: float) -> None:
        """Shake the pipette tip to dislodge residual liquid droplets.

        Performs a series of small XY movements while maintaining Z position.
        The movement pattern returns to the original position.

        Args:
            curr_coor: Current coordinate position.
            dip_distance: Z-axis position where shaking occurs (depth in well).

        Note:
            Movement pattern:
            - Left-right oscillation (±1mm)
            - Forward-backward oscillation (±1mm)
            - Returns to center position

        Example:
            >>> current = Coordinate(x=100, y=100, z=50)
            >>> pipette.wiggle(current, dip_distance=10)
            >>> # Shakes at Z=10, returns to original XY position
        """
        base_coor = Coordinate(x=curr_coor.x, y=curr_coor.y, z=dip_distance)
        shake_offset = PhysicalConstants.WIGGLE_OFFSET_MM

        # Movement pattern: left, right, right, center, forward, back, back, center
        movement_pattern = [
            (shake_offset, 0),  # Left
            (-shake_offset, 0),  # Right
            (-shake_offset, 0),  # Right
            (shake_offset, 0),  # Back to center
            (0, shake_offset),  # Forward
            (0, -shake_offset),  # Backward
            (0, -shake_offset),  # Backward
            (0, shake_offset),  # Back to center
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
        extra_air: bool = False,
        after_air: bool = False,
        serum_speed: bool = False,
        aspirate_air: float = 0.0,
        prewet: int = 0,
        prewet_vol: float = 10.0,
    ) -> None:
        """Aspirate liquid from a source location into the pipette tip.

        Performs complete aspiration sequence:
        1. Pick up tip if needed
        2. Move to source location
        3. Lower plunger to create space
        4. Dip into liquid
        5. Optionally prewet tip
        6. Release plunger to aspirate
        7. Wait for liquid to settle
        8. Return to safe height

        Args:
            volume: Volume to aspirate in microliters.
            source: Name of source location or plate.
            src_row: Row index for plate wells, or None for next well.
            src_col: Column index for plate wells, or None for next well.
            aspirate_air: If non-zero, aspirate this amount of uL of air before
                          aspirating from a well.
            prewet: If non-zero, perform prewetting a prewet number of cycles before
                    aspiration.
            prewet_vol: If prewet-ing, prewet with this volume.

        Raises:
            ValueError: If source is a simple coordinate (not a plate with
                       dipping strategy).

        Note:
            - Automatically picks up a tip if one is not attached
            - Prewetting improves accuracy by coating the tip interior
            - Updates has_liquid state to True
            - Uses configured speeds and wait times

        Example:
            >>> pipette.aspirate_volume(100, "plate_a")
            >>> # Aspirates 100µL from next well in plate_a

            >>> pipette.aspirate_volume(50, "plate_b", src_row=2, src_col=3)
            >>> # Aspirates 50µL from well C4 (row 2, col 3)

            >>> pipette.aspirate_volume(100, "reservoir", prewet=True)
            >>> # Prewets tip then aspirates 100µL
        """
        # Get source coordinate and location object
        coor_source = self.location_manager.get_coordinate(source, src_row, src_col)
        loc_source = self.location_manager.locations[source]

        # Validate that source is a plate (not a simple coordinate)
        if isinstance(loc_source, Coordinate):
            raise ValueError(
                f"Source '{source}' is a coordinate, not a plate. "
                f"Aspiration requires a plate with dipping strategy."
            )

        # Type check - ensure it's a Plate
        if not isinstance(loc_source, Plate):
            raise ValueError(
                f"Source '{source}' has invalid type. "
                f"Expected Plate, got {type(loc_source).__name__}."
            )

        # Move to source, clear plunger, and aspirate air if needed
        self.move_to(coor_source)
        self.home_pipette_stepper()
        aft_vol = self.pipette_params.aft_air if after_air else 0
        if (self.pipette_params.ext_air+volume+aft_vol >= self.pipette_params.max_vol):
            ext_vol = self.pipette_params.max_vol - (volume+aft_vol+2)
        else:
            ext_vol = self.pipette_params.ext_air
        tot_vol = volume+aft_vol+ext_vol
        
        if aspirate_air:
            self.operate_syringe(FluidDisplacement.aspiration, aspirate_air)
      

        # Prewetting cycle (if requested)
        if prewet:
            AIR_CUSHION_UL = ext_vol
            self.operate_syringe(FluidDisplacement.aspiration, AIR_CUSHION_UL)
            self.gcode_wait(self.pipette_params.wait_aspirate)
            
            for _ in range(prewet):
                self.operate_syringe(FluidDisplacement.aspiration, prewet_vol)
                self.gcode_wait(self.pipette_params.wait_aspirate)
                self.operate_syringe(FluidDisplacement.dispense, prewet_vol)
                self.gcode_wait(self.pipette_params.wait_aspirate)

            dip_z = loc_source.get_dip_distance(tot_vol)
            raise_z = dip_z - 30
            self.move_to_z(Coordinate(
                x=coor_source.x,
                y=coor_source.y,
                z=raise_z
            ))    
            self.operate_syringe(FluidDisplacement.dispense, AIR_CUSHION_UL)
              
        if extra_air:
            AIR_CUSHION_UL = ext_vol
            self.operate_syringe(FluidDisplacement.aspiration, AIR_CUSHION_UL)
            self.gcode_wait(self.pipette_params.wait_aspirate)

        # dip down into the liquid
        self.dip_z_down(coor_source, loc_source.get_dip_distance(volume))    
        
        # Aspirate liquid
        self.operate_syringe(FluidDisplacement.aspiration, volume)
        self.state.has_liquid = True
        self.gcode_wait(self.pipette_params.wait_aspirate)

        # Return to safe height
        self.dip_z_return(coor_source)

        # If you want air afterwards to prevent dripping...
        if after_air:
            
            self.operate_syringe(FluidDisplacement.aspiration, aft_vol)
            self.gcode_wait(self.pipette_params.wait_aspirate)
        # Wait after things are picked up so that we can see if it stays
        self.gcode_wait(500)
    
    def dispense_volume(
        self,
        dest: str,
        dest_row: int | None = None,
        dest_col: int | None = None,
        volume: float | None = None,
        wiggle: bool = False,
        serum_speed = False,
        touch: bool = False,
    ) -> None:
        """Dispense liquid from the pipette tip into a destination.

        Performs complete dispensing sequence:
        1. Move to destination location
        2. Dip into well
        3. Dispense liquid by pushing plunger
        4. Optionally wiggle to dislodge droplets
        5. Optionally touch tip to side
        6. Wait for dispensing to complete
        7. Return to safe height
        8. Home plunger

        Args:
            volume: Volume to dispense in microliters.
            dest: Name of destination location or plate.
            dest_row: Row index for plate wells, or None for next well.
            dest_col: Column index for plate wells, or None for next well.
            wiggle: If True, shake tip to dislodge residual droplets.
            touch: If True, touch tip to well side after dispensing.

        Raises:
            ValueError: If destination is a simple coordinate (not a plate with
                       dipping strategy).

        Note:
            - Updates has_liquid state to False
            - Wiggling helps ensure complete liquid transfer
            - Touch reduces droplets hanging from tip

        Example:
            >>> pipette.dispense_volume(100, "plate_a")
            >>> # Dispenses 100µL into next well

            >>> pipette.dispense_volume(50, "plate_b", dest_row=0, dest_col=0)
            >>> # Dispenses 50µL into well A1

            >>> pipette.dispense_volume(100, "plate_c", wiggle=True, touch=True)
            >>> # Dispenses with wiggle and touch for better accuracy
        """
        # Get destination coordinate and location object
        coor_dest = self.location_manager.get_coordinate(dest, dest_row, dest_col)
        loc_dest = self.location_manager.locations[dest]

        # Validate that destination is a plate (not a simple coordinate)
        if isinstance(loc_dest, Coordinate):
            raise ValueError(
                f"Destination '{dest}' is a coordinate, not a plate. "
                f"Dispensing requires a plate with dipping strategy."
            )

        # Type check - ensure it's a Plate
        if not isinstance(loc_dest, Plate):
            raise ValueError(
                f"Destination '{dest}' has invalid type. "
                f"Expected Plate, got {type(loc_dest).__name__}."
            )

        # Move to destination and dispense
        self.move_to(coor_dest)
        self.dip_z_down(coor_dest, loc_dest.get_dip_distance(volume))
        if volume:
            self.operate_syringe(FluidDisplacement.dispense, volume)
        else:
            self.clear_syringe()
        self.gcode_wait(self.pipette_params.wait_aspirate)  # TODO Add wait_dispense

        # Optional wiggle to dislodge droplets
        if wiggle:
            self.wiggle(coor_dest, loc_dest.get_dip_distance(volume))

        # Optional touch tip to side
        if touch:
            self.gcode_wait(1500) # 1.5 second hold
            self.move_to_z(Coordinate(x=coor_dest.x, y=coor_dest.y, z=5))
            self.move_to(Coordinate(x=150, y=150, z=5))
            # home z
            self.home_z()

        self.state.has_liquid = False

        # Return to safe height, and return syringe to homed position if no volume
        # Homing done to ensure most accurate pipetting, but can't be done everytime if
        # we want to do mulitple dispenses
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
        aspirate_air: float = 0.0,
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
        - Split dispensing to multiple destinations (if specified)

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
            aspirate_air: How much air to aspirate before aspirating.
            prewet: If True, perform pre-wetting cycle.
            prewet_vol: Volume in uL to prewet the tip with.
            wiggle: If True, shake tip during dispensing.
            touch: If True, touch tip to side after dispensing.
            keep_tip: If True, retain tip after operation.

        Raises:
            ValueError: If requested volume is negative.

        Note:
            - Automatically splits large volumes into multiple transfers
            - Each transfer uses up to pipette_params.max_vol
            - Tip is disposed unless keep_tip=True
            - Prewetting improves accuracy for viscous liquids

        Example:
            >>> # Simple transfer
            >>> pipette.pipette(vol_ul=100, source="plate_a", dest="plate_b")

            >>> # Transfer with prewetting and wiggle
            >>> pipette.pipette(
            ...     vol_ul=50,
            ...     source="reservoir",
            ...     dest="plate_a",
            ...     prewet=True,
            ...     wiggle=True
            ... )

            >>> # Large volume (automatically chunked)
            >>> pipette.pipette(vol_ul=500, source="a", dest="b")
            >>> # If max_vol=200, performs 3 transfers: 200, 200, 100

            >>> # Keep tip for multiple operations
            >>> pipette.pipette(vol_ul=100, source="a", dest="b", keep_tip=True)
            >>> pipette.pipette(vol_ul=100, source="c", dest="d", keep_tip=True)
            >>> pipette.dispose_tip()
        """
        if vol_ul < 0:
            raise ValueError(f"Invalid volume: {vol_ul}µL. Volume must be positive.")

        # Pick up tip if needed
        if not self.state.has_tip:
            _ = tipbox_name
            self.next_tip()  # TODO pass in preffered tipbox

        # Calculate transfer chunks based on max pipette capacity
        max_vol = self.pipette_params.max_vol
        chunks = int(vol_ul // max_vol)
        remainder = vol_ul - (chunks * max_vol)
        transfer_volumes: list[float] = [float(max_vol)] * chunks

        # Add remainder if significant (> 0.000001 µL)
        if remainder > PhysicalConstants.VOLUME_TOLERANCE_UL:
            transfer_volumes.append(remainder)

        # Execute transfer sequence using calculated volumes
        for pip_vol in transfer_volumes:
            self.aspirate_volume(
                pip_vol,
                source,
                src_row=src_row,
                src_col=src_col,
                aspirate_air=aspirate_air,
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


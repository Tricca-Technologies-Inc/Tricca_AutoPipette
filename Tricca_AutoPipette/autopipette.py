"""
Module containing the AutoPipette class and related error classes.

The AutoPipette class manages pipette operations including movement commands,
tip handling, and protocol execution. It follows the Singleton pattern to
ensure a single instance controls hardware resources.

TODO Add Logger obj
"""
from __future__ import annotations
import logging
from typing import Optional
from pathlib import Path
from configparser import ConfigParser, ExtendedInterpolation
from pydantic import BaseModel, conint, Field, validator

from .coordinate import Coordinate
from .plates import Plate, WasteContainer, TipBox, PlateFactory, PlateParams
from .well import Well, WellParams
from .volume_converter import VolumeConverter


class TipAlreadyOnError(Exception):
    """Raised when trying to attach a tip on when one is already attached."""

    def __init__(self) -> None:
        """Initialize error."""
        super().__init__("Tip already attached. Eject current tip first.")


class NotALocationError(Exception):
    """Raised when accessing an undefined location."""

    def __init__(self, location) -> None:
        """Initialize error."""
        self.location = location
        super().__init__(f"{location} is not a named location.")


class NoTipboxError(Exception):
    """Raised when no tipbox is configured."""

    def __init__(self) -> None:
        """Initialize error."""
        super().__init__("No tipbox configured.")


class MissingConfigError(Exception):
    """Raised when required configuration sections are missing."""

    def __init__(self, section, conf_path) -> None:
        """Initialize error."""
        super().__init__(f"Missing section {section!r} in config: {conf_path}")


class NotADipStrategyError(Exception):
    """Raised when an invalid dipping strategy is specified."""

    def __init__(self, strategy) -> None:
        """Initialize error."""
        super().__init__(f"Invalid dip strategy {strategy!r}. " +
                         f"Valid options: {Well.STRATEGIES}")


class PipetteParams(BaseModel):
    """Pipette configuration parameters with validation."""
    safe_altitude: conint(gt=0) = Field(
        ...,
        description="safe Z height")
    # Required parameters
    name_pipette_servo: str = Field(
        ...,
        min_length=1,
        description="Servo motor identifier")
    name_pipette_stepper: str = Field(
        ...,
        min_length=1,
        description="Stepper motor identifier")

    # Speed parameters (mm/s or steps/s)
    speed_xy: conint(gt=0) = Field(
        ...,
        description="Horizontal movement speed")
    speed_z: conint(gt=0) = Field(
        ...,
        description="Vertical movement speed")
    speed_pipette_down: conint(gt=0) = Field(
        ...,
        description="Pipette descending speed")
    speed_pipette_up: conint(gt=0) = Field(
        ...,
        description="Pipette ascending speed")
    speed_pipette_up_slow: conint(gt=0) = Field(
        ...,
        description="Pipette slow ascension speed")
    speed_max: conint(gt=0) = Field(..., description="Maximum system speed")

    # Configuration parameters
    speed_factor: conint(ge=1, le=200) = Field(
        default=100,
        description="Speed multiplier factor (1-200%)"
    )
    velocity_max: conint(gt=0) = Field(..., description="Maximum velocity")
    accel_max: conint(gt=0) = Field(..., description="Maximum acceleration")

    # Servo parameters (degrees)
    servo_angle_retract: conint(ge=20, le=160) = Field(
        ...,
        description="Retracted position angle (20-160°)"
    )
    servo_angle_ready: conint(ge=20, le=160) = Field(
        ...,
        description="Ready position angle (20-160°)"
    )

    # Timing parameters (milliseconds)
    wait_eject: conint(ge=0) = Field(
        ...,
        description="Ejection dwell time")
    wait_movement: conint(ge=0) = Field(
        ...,
        description="Movement stabilization time")
    wait_aspirate: conint(ge=0) = Field(
        ...,
        description="Aspiration dwell time")

    # Capacity parameters
    max_vol: conint(gt=0) = Field(
        ...,
        description="Maximum pipette volume (µL)")

    class Config:
        """Config class."""

        extra = "forbid"
        validate_assignment = True

    @validator("speed_pipette_up_slow")
    def validate_slow_speed(cls, v, values):
        """Ensure slow speed is slower than the regular speed."""
        if "speed_pipette_up" in values and v >= values["speed_pipette_up"]:
            raise ValueError(
                "Slow speed must be less than normal ascension speed")
        return v

    @validator("servo_angle_ready")
    def validate_servo_angles(cls, v, values):
        """Ensure ready angle is less than the retract angle."""
        if "servo_angle_retract" in values \
           and v >= values["servo_angle_retract"]:
            raise ValueError(
                "Ready angle must be less than retracted angle")
        return v


class AutoPipetteMeta(type):
    """Metaclass implementing the Singleton Pattern."""

    _instances: dict[type, AutoPipette] = {}

    def __call__(cls, *args, **kwargs):
        """Ensure only one instance exists."""
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class AutoPipette(metaclass=AutoPipetteMeta):
    """Main controller class for automated pipette operations.

    Attributes:
        logger:
        config: Loaded configuration settings
        volume_converter: Volume-to-movement calculator
        waste_container: Waste disposal location
        tipboxes: Available tip containers
    """

    def __init__(self, config_file: str | None = None) -> None:
        """Initialize pipette controller with configuration."""
        self.logger = logging.getLogger(__name__)
        self.config = ConfigParser(interpolation=ExtendedInterpolation())
        self.volume_converter: VolumeConverter | None = None
        self.waste_container: WasteContainer | None = None
        self.tipboxes: TipBox | None = None
        self.locations: dict[str, Coordinate | Plate] = {}
        self.pipette_params: PipetteParams | None = None

        self.DEFAULT_CONFIG = "autopipette.conf"
        self.CONFIG_PATH = Path(__file__).parent.parent.parent / "backend" / "conf"

        self.has_tip: bool = False
        self.has_liquid: bool = False
        self.homed: bool = False

        self.NECESSARY_CONFIG_SECTIONS = ["NETWORK", "NAME", "BOUNDARY",
                                          "SPEED", "SERVO", "WAIT",
                                          "VOLUME_CONV"]
        # G-code buffers
        self._header_buffer: list[str] = []
        self._gcode_buffer: list[str] = []
        self._current_as_header = False

        self._config_file = config_file or self.DEFAULT_CONFIG
        self.load_config_file(self._config_file)

    def _buffer_command(self, command: str) -> None:
        """Add command to active buffer."""
        target = self._header_buffer if self._current_as_header \
            else self._gcode_buffer
        target.append(command)

    def load_config_file(self, filename: str) -> None:
        """Load a config file to set passed in values."""
        
        # Figure out the real path:
        fn = Path(filename)
        if fn.is_absolute() and fn.exists():
            config_path = fn
        else:
            config_path = self.CONFIG_PATH / filename

        # Start from scratch so no old values stay
        self.config = ConfigParser(interpolation=ExtendedInterpolation())
        self._config_file = config_path.name

        try:
            with config_path.open("r") as f:
                self.config.read_file(f)
        except FileNotFoundError as e:
            self.logger.critical("Missing configuration file: %s", config_path)
            raise RuntimeError(
                f"Configuration file not found: {config_path}") from e

        missing = list(set(self.NECESSARY_CONFIG_SECTIONS)
                       - set(self.config.sections()))
        if missing:
            raise MissingConfigError(missing.pop(), config_path)
        self.pipette_params = \
            PipetteParams(
                name_pipette_servo=self.config["NAME"]["NAME_PIPETTE_SERVO"],
                name_pipette_stepper=self.config["NAME"]["NAME_PIPETTE_STEPPER"],
                speed_xy=self.config["SPEED"].getint("SPEED_XY"),
                speed_z=self.config["SPEED"].getint("SPEED_Z"),
                speed_pipette_down=self.config["SPEED"].getint("SPEED_PIPETTE_DOWN"),
                speed_pipette_up=self.config["SPEED"].getint("SPEED_PIPETTE_UP"),
                speed_pipette_up_slow=self.config["SPEED"].getint("SPEED_PIPETTE_UP_SLOW"),
                speed_max=self.config["SPEED"].getint("SPEED_MAX"),
                speed_factor=self.config["SPEED"].getint("SPEED_FACTOR"),
                velocity_max=self.config["SPEED"].getint("VELOCITY_MAX"),
                accel_max=self.config["SPEED"].getint("ACCEL_MAX"),
                servo_angle_retract=self.config["SERVO"].getint("SERVO_ANGLE_RETRACT"),
                servo_angle_ready=self.config["SERVO"].getint("SERVO_ANGLE_READY"),
                wait_eject=self.config["WAIT"].getint("WAIT_EJECT"),
                wait_movement=self.config["WAIT"].getint("WAIT_MOVEMENT"),
                wait_aspirate=self.config["WAIT"].getint("WAIT_ASPIRATE"),
                max_vol=self.config["VOLUME_CONV"].getint("max_vol"),
                safe_altitude=self.config["BOUNDARY"].getfloat("safe_altitude")
                )
        self.locations = {}
        self._parse_config_locations()
        self._init_volume_converter()
        self._build_header()

    def save_config_file(self, filename: str = None) -> None:
        """Save a the config to a file.

        Configs are saved under the conf/ folder located in the root of the
        project.

        TODO Save new locations in this file as well
        TODO Save locations when added and add location removal
        TODO Save old and new locations with updated coors

        Args:
            filename (str): The filename to save the config as.
        """
        if filename is None:
            filename = self._config_file + "-test"
        conf_path = self.CONF_PATH / filename
        with open(conf_path, 'w') as fp:
            self.config.write(fp)

    def _parse_config_locations(self) -> None:
        """Parse coordinate and plate configurations from INI sections.

        Processes configuration sections starting with 'COORDINATE', creating
        location entries and specialized Plate objects when type specifications
        are present.

        Args:
            ignore_sections: Configuration sections to exclude from processing

        Raises:
            NotADipStrategyError: For invalid dipping function names
            NotAPlateTypeError: For unrecognized plate type specification
        """
        # Delete previous location in case we are loading a new config
        self.locations.clear()
        plate_params_iter = {
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

        for section in set(self.config.sections()) \
                - set(self.NECESSARY_CONFIG_SECTIONS):
            if not (section.startswith("COORDINATE ")
                    or section.startswith("PLATE ")):
                continue
            try:
                _, name_loc = section.split(maxsplit=1)
                coord_section = self.config[section]
            except ValueError:
                continue

            # Validate the numbers as Coordinate, set Coordinate as a location
            loc_coor = Coordinate(
                x=coord_section.getfloat("x"),
                y=coord_section.getfloat("y"),
                z=coord_section.getfloat("z"))
            self.set_location_coordinate(name_loc, loc_coor)
            # If we have a coordinate section, we don't need plate params
            if section.startswith("COORDINATE "):
                continue
            # Extract plate parameters with type conversion
            params = {}
            for key, (conv, default) in plate_params_iter.items():
                if key in coord_section:
                    params[key] = conv(coord_section[key])

            dip_func_str = params.get("dip_func", "simple")
            if dip_func_str not in Well.STRATEGIES:
                raise ValueError(
                    f"Strategy {dip_func_str} is not a valid dip strategy.")

            config_well = WellParams(
                coor=loc_coor,
                dip_top=params.get("dip_top"),
                dip_btm=params.get("dip_btm", None),
                dip_func=Well.NAME_TO_STRAT[dip_func_str],
                well_diameter=params.get("well_diameter", None),
            )
            well = Well(
                coor=config_well.coor,
                dip_top=config_well.dip_top,
                dip_btm=config_well.dip_btm,
                dip_func=config_well.dip_func,
                diameter=config_well.well_diameter,)
            plate_params = PlateParams(
                plate_type=params.get("type"),
                well_template=well,
                row=params.get("row", None),
                col=params.get("col", None),
                spacing_row=params.get("spacing_row", None),
                spacing_col=params.get("spacing_col", None)
            )
            self.set_location_plate(name_loc, plate_params)

    def _build_header(self) -> None:
        """Generate a G-code header with configuration summary."""
        self._header_buffer.clear()
        self._header_buffer.append(f"; Configuration: {self._config_file}\n")
        self._header_buffer.append("; Settings:\n")
        for section in self.config.sections():
            self._header_buffer.append(f"; [{section}]\n")
            for key, val in self.config[section].items():
                self._header_buffer.append(f";\t {key} = {val}\n")

    def _init_volume_converter(self) -> None:
        """Generate the VolumeConverter based on passed in values."""
        volumes = list(map(float,
                           self.config["VOLUME_CONV"]["volumes"].split(",")))
        steps = list(map(float,
                         self.config["VOLUME_CONV"]["steps"].split(",")))
        self.volume_converter = VolumeConverter(volumes, steps)

    def init_pipette(self) -> None:
        """Initialize all relevant aspects of the pipette.

        Set the speed parameters, home all axis, and home the pipette.
        """
        self.set_coor_sys("absolute")
        self.init_speed()
        self.home_axis()
        self.home_pipette_motors()

    def init_speed(self) -> None:
        """Set the speed parameters.

        SPEED_FACTOR: multiplies with calculated speed for a corrected value.

        MAX_VELOCITY: the maximum possible velocity (mm/sec).

        MAX_ACCEL: the maximum possible acceleration (mm/sec^2).
        """
        self.set_speed_factor(self.pipette_params.speed_factor)
        self.set_max_velocity(self.pipette_params.velocity_max)
        self.set_max_accel(self.pipette_params.accel_max)

    def set_coor_sys(self, mode) -> None:
        """Return the G-code command for the specified coordinate system mode.

        Args:
        mode (str): Either "absolute" or "incremental" (case-insensitive).

        Returns:
        str: "G90" for absolute, "G91" for incremental.

        Raises:
        ValueError: If an invalid mode is provided.

        TODO Proper errors, enum, switch func
        """
        mode = mode.lower()  # Make comparison case-insensitive

        if mode == "absolute":
            self._buffer_command("G90\n")
        elif mode in ("incremental", "relative"):  # Accepts both terms
            self._buffer_command("G91\n")
        else:
            raise ValueError(
                f"Invalid coordinate system mode: '{mode}'." +
                "Expected 'absolute' or 'incremental'.")

    def set_speed_factor(self, factor: float) -> str:
        """Set the speed factor using gcode.

        Args:
            factor (float): The speed multiple to be set.
        """
        self.config["SPEED"]["SPEED_FACTOR"] = str(factor)
        self.pipette_params.speed_factor = factor
        self._buffer_command(f"M220 S{factor}\n")

    def set_max_velocity(self, velocity: float) -> str:
        """Set the max velocity using gcode.

        Args:
            velocity (float): The maximum velocity the pipette will travel.
        """
        self.config["SPEED"]["VELOCITY_MAX"] = str(velocity)
        self.pipette_params.velocity_max = velocity
        self._buffer_command(f"SET_VELOCITY_LIMIT VELOCITY={velocity}\n")

    def set_max_accel(self, accel: float) -> str:
        """Set the max acceleration using gcode.

        Args:
            accel (float): The maximum acceleration the pipette will travel.
        """
        self.config["SPEED"]["ACCEL_MAX"] = str(accel)
        self.pipette_params.accel_max = accel
        self._buffer_command(f"SET_VELOCITY_LIMIT ACCEL={accel}\n")

    def home_axis(self) -> str:
        """Home x, y, and z axis.

        Home z axis first to prevent collisions then home the x and y axis.
        """
        self._buffer_command("G28\n")

    def home_x(self) -> str:
        """Home x axis."""
        self._buffer_command("G28 X\n")

    def home_y(self) -> str:
        """Home y axis."""
        self._buffer_command("G28 Y\n")

    def home_z(self) -> str:
        """Home z axis."""
        self._buffer_command("G28 Z\n")

    def home_pipette_motors(self) -> None:
        """Home motors associated with the pipette toolhead.

        Retract the servo that dispenses pipette tips and home the pipette
        stepper.
        """
        self.home_servo()
        self.home_pipette_stepper()

    def home_servo(self) -> None:
        """Retract the servo that dispenses pipette tips."""
        self.set_servo_angle(self.pipette_params.servo_angle_retract)
        self.gcode_wait(self.pipette_params.wait_movement)

    def home_pipette_stepper(self, speed: float = None) -> str:
        """Home the pipette stepper.

        Args:
            speed (float): The speed to home the pipette.
        """
        if speed is None:
            speed = self.pipette_params.speed_pipette_up_slow
        stepper = self.pipette_params.name_pipette_stepper
        self._buffer_command(
            f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} "
            "MOVE=50 STOP_ON_ENDSTOP=1 SET_POSITION=0 ACCEL=1000\n"
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n")

    def get_gcode(self) -> list[str]:
        """Return the gcode that's been added to the buffer and clear it."""
        temp = self._gcode_buffer
        self._gcode_buffer = []
        return temp

    def get_header(self) -> list[str]:
        """Return the header which is the configurations used to generate Gcode."""
        return self._header_buffer

    def move_to(self, coordinate: Coordinate) -> str:
        """Move the pipette toolhead to the coordinate.

        Args:
            coordinate (Coordinate): The place to move to.
        """
        speed_xy = self.pipette_params.speed_xy
        speed_z = self.pipette_params.speed_z
        self._buffer_command(
            f"G1 X{coordinate.x} Y{coordinate.y} F{speed_xy}\n")
        self._buffer_command(
            f"G1 Z{coordinate.z} F{speed_z}\n")

    def move_to_x(self, coordinate: Coordinate) -> str:
        """Move the pipette toolhead to the coordinate x position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate (Coordinate): Holds the x location to move to.
        """
        speed = self.pipette_params.speed_xy
        self._buffer_command(f"G1 X{coordinate.x} F{speed}\n")

    def move_to_y(self, coordinate: Coordinate) -> str:
        """Move the pipette toolhead to the coordinate y position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate (Coordinate): Holds the y location to move to.
        """
        speed = self.pipette_params.speed_xy
        self._buffer_command(f"G1 Y{coordinate.y} F{speed}\n")

    def move_to_z(self, coordinate: Coordinate) -> str:
        """Move the pipette toolhead to the coordinate z position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate (Coordinate): Holds the z location to move to.
        """
        speed = self.pipette_params.speed_z
        self._buffer_command(f"G1 Z{coordinate.z} F{speed}\n")

    def eject_tip(self) -> None:
        """Eject the pipette tip."""
        angle_retract = self.pipette_params.servo_angle_retract
        angle_ready = self.pipette_params.servo_angle_ready
        wait_eject = self.pipette_params.wait_eject
        wait_movement = self.pipette_params.wait_movement
        self.set_servo_angle(angle_retract)
        self.set_servo_angle(angle_ready)
        self.gcode_wait(wait_eject)
        self.set_servo_angle(angle_retract)
        self.gcode_wait(wait_movement)
        self.has_tip = False

    def set_servo_angle(self, angle: float) -> str:
        """Set the servo angle.

        Args:
            angle (float): The angle to set the tip servo to.
        """
        servo = self.pipette_params.name_pipette_servo
        self._buffer_command(f"SET_SERVO SERVO={servo} ANGLE={angle}\n")

    def move_pipette_stepper(self,
                             distance: float,
                             speed: float = None) -> str:
        """Move the stepper associated with the pipette toolhead.

        Args:
            distance (float): Distance to move the plunger.
            speed (float): Speed to move the plunger.
        """
        if speed is None:
            speed = self.pipette_params.speed_pipette_up_slow
        stepper = self.pipette_params.name_pipette_stepper
        self._buffer_command(
            f"MANUAL_STEPPER STEPPER={stepper} "
            f"SPEED={speed} MOVE=-{distance} ACCEL=300\n")

    def gcode_wait(self, mil: float) -> str:
        """Send a gcode command to wait for mil amount of milliseconds.

        Args:
           mil (float): Number of milliseconds the machine should wait.
        """
        self._buffer_command(f"G4 P{mil}\n")

    def gcode_print(self, msg: str) -> str:
        """Send a gcode command to print a message to screen."""
        self._buffer_command(f"M117 {msg}\n")

    def dip_z_down(self, curr_coor: Coordinate, distance: float) -> None:
        """Dip the pipette toolhead down a set distance.

        Args:
            curr_coor (Coordinate): The coordinate to move from.
            distance (float): Distance to move in the z axis.
        """
        coor_dip = Coordinate(
            x=curr_coor.x,
            y=curr_coor.y,
            z=distance)
        self.move_to_z(coor_dip)
        self.gcode_wait(self.pipette_params.wait_movement)

    def dip_z_return(self, curr_coor: Coordinate) -> None:
        """Bring up the pipette toolhead a set distance.

        Args:
            curr_coor (Coordinate): The coordinate to move from.
            distance (float): Distance to move in the z axis.
        """
        self.move_to_z(curr_coor)
        self.gcode_wait(self.pipette_params.wait_movement)

    def set_location_coordinate(self, name_loc: str, coor: Coordinate) -> None:
        """Create a Coordinate and associate with a name.

        Args:
            name_loc (str): The name to give to the coordinate.
            coor (Coordinate): An object representing a point in space.
        """
        self.locations[name_loc] = coor
        conf_key = f"COORDINATE {name_loc}"
        # Update config
        if not self.config.has_section(conf_key):
            self.config.add_section(conf_key)
        self.config.set(conf_key, "x", str(coor.x))
        self.config.set(conf_key, "y", str(coor.y))
        self.config.set(conf_key, "z", str(coor.z))

    def is_location(self, name_loc: str) -> bool:
        """Return True if name_loc is a location, false otherwise.

        Args:
            name_loc (str): The possible name of Coordinate.
        """
        return name_loc in self.locations.keys()

    def set_location_plate(self,
                           name_loc: str,
                           plate_params: PlateParams) -> None:
        """Create a plate from an existing location name.

        Args:
            name_loc (str): The name of a location.
            config_plate (ConfigPlate): A data validator that holds the various
                                        plate variables.
        """
        # Get rid of any existing locations with the same name
        self.locations.pop(name_loc, None)
        self.locations[name_loc] = PlateFactory.create(plate_params)
        # Update config
        # Get rid of any existing Coordinate section with the same name
        self.config.pop(f"COORDINATE {name_loc}", None)
        conf_key = f"PLATE {name_loc}"
        self.config.set(conf_key, "x", str(plate_params.well_template.coor.x))
        self.config.set(conf_key, "y", str(plate_params.well_template.coor.y))
        self.config.set(conf_key, "z", str(plate_params.well_template.coor.z))
        self.config.set(conf_key, "type", str(plate_params.plate_type))
        self.config.set(conf_key, "row", str(plate_params.num_row))
        self.config.set(conf_key, "col", str(plate_params.num_col))
        self.config.set(conf_key, "spacing_row", str(plate_params.spacing_row))
        self.config.set(conf_key, "spacing_col", str(plate_params.spacing_col))
        self.config.set(conf_key,
                        "dip_top",
                        str(plate_params.well_template.dip_top))
        self.config.set(conf_key,
                        "dip_btm",
                        str(plate_params.well_template.dip_btm))
        self.config.set(conf_key,
                        "dip_func",
                        str(Well.STRAT_TO_NAME[
                            plate_params.well_template.dip_func]))
        # Set waste location if plate type is WasteContainer.
        if (plate_params.plate_type == "waste_container"):
            self.waste_container = self.locations[name_loc]
            self.locations["waste_container"] = self.waste_container
        # Set tip box location if plate type is TipBox
        elif (plate_params.plate_type == "tipbox"):
            if (self.tipboxes is None):
                self.tipboxes = self.locations[name_loc]
            else:
                tipbox = self.locations[name_loc]
                self.tipboxes.append_box(tipbox)

    def get_plate_locations(self) -> list:
        """Return a list of locations that are plates."""
        plates: list = []
        for location in self.locations:
            if isinstance(self.locations[location], Plate):
                plates.append(location)
        return plates

    def get_location_coor(self, name_loc: str,
                          row: int = None, col: int = None) -> Coordinate:
        """Return a Coordinate from a location name.

        Args:
            name_loc (str): The name of a particular location.
            row (int): A row on a plate.
            col (int): A column on a plate.
        """
        # If name_loc doesn't exist as a location, do nothing
        if (name_loc not in self.locations.keys()):
            raise NotALocationError(name_loc)
        # If the returned location is a coordinate, return it.
        # Otherwise, if it is a plate, next() is called and returned
        loc = self.locations[name_loc]
        if (isinstance(loc, Plate)):
            if row is None and col is None:
                return loc.next()
            else:
                return loc.get_coor(row, col)
        elif (isinstance(loc, Coordinate)):
            return loc
        else:
            raise NotALocationError(name_loc)

    def next_tip(self) -> None:
        """Grab the next tip in the tip box."""
        if self.tipboxes is None:
            raise NoTipboxError()
        if self.has_tip:
            raise TipAlreadyOnError()
        loc_tip = self.tipboxes.next()
        self.move_to(loc_tip)
        self.dip_z_down(loc_tip, self.tipboxes.get_dip_distance())
        self.dip_z_return(loc_tip)
        self.has_tip = True

    def plunge_down(self, vol_ul: float, speed: float = None) -> None:
        """Move pipette plunger down.

        Args:
            vol_ul (float): The volume in microliters to be pipetted.
            speed (float): The speed to move the plunger.
        """
        if speed is None:
            speed = self.pipette_params.speed_pipette_up_slow
        self.move_pipette_stepper(self.volume_converter.vol_to_steps(vol_ul),
                                  speed)

    def clear_pipette(self,
                      volume: Optional[float] = None,
                      speed: float = None) -> None:
        """Expell any liquid in tip.

        Args:
            speed (float): The speed to move the plunger.
        """
        if speed is None:
            speed = self.pipette_params.speed_pipette_up_slow

        if volume is None:
            # original “dump all” distance
            steps = self.volume_converter.dist_disp
        else:
            # exact-volume behavior
            steps = self.volume_converter.vol_to_steps(volume)

        self.move_pipette_stepper(steps, speed)

    def wiggle(self, curr_coor: Coordinate, dip_distance: float) -> None:
        """Shake the pipette to dislodge residual liquid.

        Moves back and forth in the X and Y axis with no movement in the Z axis.
        Pattern should always return to the original location.

        Args:
            curr_coor: Starting coordinate position
            dip_distance: Z-axis position where shaking motions happens
        """
        base_coor = Coordinate(
            x=curr_coor.x,
            y=curr_coor.y,
            z=dip_distance)
        shake_offset = 1.0  # mm
        movement_pattern = [
            (shake_offset, 0),   # Left
            (-shake_offset, 0),  # Right
            (-shake_offset, 0),  # Right
            (shake_offset, 0),   # Back to center
            (0, shake_offset),   # Forward
            (0, -shake_offset),  # Backward
            (0, -shake_offset),  # Backward
            (0, shake_offset),   # Back to center
        ]
        for dx, dy in movement_pattern:
            target = base_coor.generate_offset(dx, dy, 0)
            self.move_to(target)

    def aspirate_volume(self,
                        volume: float,
                        source: str,
                        src_row: Optional[int] = None,
                        src_col: Optional[int] = None,
                        prewet: bool = False) -> None:
        """Dip into a well and take in some liquid."""
        coor_source = self.get_location_coor(source, src_row, src_col)
        loc_source = self.locations[source]
        # Pickup a tip
        if not self.has_tip:
            self.next_tip()
        # Maybe check if we have liquid in tip already?
        # Pickup liquid
        self.move_to(coor_source)
        self.move_pipette_stepper(self.volume_converter.vol_to_steps(3),speed=self.pipette_params.speed_pipette_down)
        self.dip_z_down(coor_source, loc_source.get_dip_distance(volume))
        self.plunge_down(volume, self.pipette_params.speed_pipette_down)
        # If True, aspirate small amount of liquid 1 time to wet tip
        if prewet:
            for _ in range(1):
                self.home_pipette_stepper(
                    self.pipette_params.speed_pipette_up_slow)
                self.gcode_wait(self.pipette_params.wait_aspirate)
                self.plunge_down(volume,
                                 self.pipette_params.speed_pipette_down)
                self.gcode_wait(self.pipette_params.wait_aspirate)
        # Release plunger to aspirate measured amount
        # self.home_pipette_stepper(self.pipette_params.speed_pipette_up_slow)
        # Give time for the liquid to enter the tip
        self.gcode_wait(self.pipette_params.wait_aspirate)
        self.dip_z_return(coor_source)
        self.has_liquid = True

    def dispense_volume(self,
                        volume: float,
                        dest: str,
                        dest_row: Optional[int] = None,
                        dest_col: Optional[int] = None,
                        disp_vol_ul: float | None = None,
                        wiggle: bool = False):
        """Dip into a well and expel some liquid."""
        coor_dest = self.get_location_coor(dest, dest_row, dest_col)
        loc_dest = self.locations[dest]
        # Dropoff liquid
        self.move_to(coor_dest)
        self.dip_z_down(coor_dest, loc_dest.get_dip_distance(volume))

        self.clear_pipette(volume=disp_vol_ul,speed=self.pipette_params.speed_pipette_down)

        if wiggle:
            self.wiggle(coor_dest, loc_dest.get_dip_distance(volume))
        
        self.gcode_wait(self.pipette_params.wait_aspirate)
        self.dip_z_return(coor_dest)
        self.home_pipette_stepper(self.pipette_params.speed_pipette_up)
        self.has_liquid = False

    def dispose_tip(self):
        """Eject a tip into a waste container."""
        curr_coor = self.waste_container.next()
        self.move_to(curr_coor)
        self.dip_z_down(curr_coor, self.waste_container.get_dip_distance())
        self.eject_tip()
        self.dip_z_return(curr_coor)

    def pipette(self,
                vol_ul: float,
                source: str,
                dest: str,
                disp_vol_ul: float | None = None,
                src_row: Optional[int] = None,
                src_col: Optional[int] = None,
                dest_row: Optional[int] = None,
                dest_col: Optional[int] = None,
                keep_tip: bool = False,
                prewet: bool = False,
                wiggle: bool = False
                ) -> None:
        """Transfer liquid between locations.

        Tip retention and pre-wetting is optional.

        Args:
            vol_ul: Volume to transfer in microliters (must be positive)
            source: Name of source location/plate
            dest: Name of destination location/plate
            src_row: Source plate row index (if applicable)
            src_col: Source plate column index (if applicable)
            dest_row: Destination plate row index (if applicable)
            dest_col: Destination plate column index (if applicable)
            keep_tip: Maintain tip attachment after operation
            prewet: Perform pre-wetting aspiration cycle
            wiggle: Add positional jitter during dispensing

        Raises:
            ValueError: If requested volume is negative
            RuntimeError: If required locations aren't configured
        """
        if vol_ul < 0:
            raise ValueError(f"Invalid volume: {vol_ul}μL")

        # Calculate transfer chunks
        max_vol = self.pipette_params.max_vol
        chunks = int(vol_ul // max_vol)
        remainder = vol_ul - (chunks * max_vol)
        transfer_volumes = [max_vol] * chunks
        # TODO Figure out how precise we actually want to be
        if remainder > 1e-6:
            transfer_volumes.append(remainder)

        # Execute transfer sequence
        for pip_vol in transfer_volumes:
            self.aspirate_volume(vol_ul, source, src_row, src_col, prewet)
            self.dispense_volume(vol_ul, dest, dest_row, dest_col, disp_vol_ul, wiggle)

        # Eject tip
        if not keep_tip:
            self.dispose_tip()

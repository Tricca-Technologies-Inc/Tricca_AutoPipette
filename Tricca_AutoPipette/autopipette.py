"""
Module containing the AutoPipette class and related error classes.

The AutoPipette class manages pipette operations including movement commands,
tip handling, and protocol execution. It follows the Singleton pattern to
ensure a single instance controls hardware resources.

TODO Add Logger obj
"""
from __future__ import annotations
import logging
from typing import Optional, Sequence, NamedTuple, cast
from pathlib import Path
from configparser import ConfigParser, ExtendedInterpolation
from pydantic import BaseModel, conint, Field, validator

from coordinate import Coordinate
from plates import Plate, WasteContainer, TipBox, PlateFactory, PlateParams
from well import Well, WellParams
from volume_converter import VolumeConverter

import copy

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
    aft_air: conint(gt=0) = Field(
        ...,
        description="air pocket added after aspirating (µL)")
    ext_air: conint(gt=0) = Field(
        ...,
        description="air pocket added before aspirating ((µL)")

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

class Split(NamedTuple):
    dest: str
    vol_ul: float
    dest_row: Optional[int] = None
    dest_col: Optional[int] = None

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
        self.tipboxes_map: dict[str, TipBox] = {}
        self.active_tipbox_name: str | None = None
        self.pooled_tipbox: TipBox | None = None
        self.locations: dict[str, Coordinate | Plate] = {}
        self.pipette_params: PipetteParams | None = None

        self.DEFAULT_CONFIG = "autopipette.conf"
        self.CONFIG_PATH = Path(__file__).parent.parent / 'conf'

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

    def _reset_runtime_state(self) -> None:
        """Clear all state that depends on the loaded profile."""
        # locations/containers
        self.locations.clear()
        self.waste_container = None
        self.tipboxes = None
        self.tipboxes_map = {}
        self.active_tipbox_name = None
        # tip/liquid state (safer to force fresh start on profile change)
        self.has_tip = False
        self.has_liquid = False
        # gcode buffers
        self._gcode_buffer = []
        # (keep header; it will be rebuilt after load)
        
    def load_config_file(self, filename: str) -> None:
        """Load a config file (absolute path or from self.CONFIG_PATH)."""
        # Resolve path (abs path is used as-is; otherwise join with CONFIG_PATH)
        p = Path(filename)
        config_path = p if p.is_absolute() else (self.CONFIG_PATH / filename)

        # fully reset any old profile state so nothing leaks across
        self._reset_runtime_state()

        # Re-init the ConfigParser to avoid stale sections carrying over
        self.config = ConfigParser(interpolation=ExtendedInterpolation())

        try:
            with config_path.open("r") as f:
                self.config.read_file(f)
        except FileNotFoundError as e:
            self.logger.critical("Missing configuration file: %s", config_path)
            raise RuntimeError(f"Configuration file not found: {config_path}") from e

        # Keep track of the active file for UI/diagnostics
        self._config_file = str(config_path)

        # Validate required sections
        missing = list(set(self.NECESSARY_CONFIG_SECTIONS) - set(self.config.sections()))
        if missing:
            raise MissingConfigError(missing.pop(), config_path)

        # Build validated params
        self.pipette_params = PipetteParams(
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
            aft_air=self.config["WAIT"].getint("aft_air"),
            ext_air=self.config["WAIT"].getint("ext_air"),
        )

        # Re-parse locations/plates and converter
        self._parse_config_locations()
        self._init_volume_converter()
        self._build_header()
        self._init_triggers()

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
        """Parse coordinate and plate configurations from INI sections."""
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

        def _maybe_convert(val: str, conv):
            """Convert unless val is '', 'None' (any case) or None."""
            if val is None:
                return None
            s = str(val).strip()
            if not s or s.lower() == "none":
                return None
            return conv(s)

        for section in set(self.config.sections()) - set(self.NECESSARY_CONFIG_SECTIONS):
            if not (section.startswith("COORDINATE ") or section.startswith("PLATE ")):
                continue

            try:
                _, name_loc = section.split(maxsplit=1)
                coord_section = self.config[section]
            except ValueError:
                continue

            # Base coordinate (required)
            loc_coor = Coordinate(
                x=coord_section.getfloat("x"),
                y=coord_section.getfloat("y"),
                z=coord_section.getfloat("z"),
            )
            self.set_location_coordinate(name_loc, loc_coor)

            # pure coordinate → done
            if section.startswith("COORDINATE "):
                continue

            # Gather optional plate params safely
            params: dict[str, object] = {}
            for key, (conv, _default) in plate_params_iter.items():
                if key in coord_section:
                    try:
                        v = _maybe_convert(coord_section.get(key), conv)
                    except Exception as e:
                        raise ValueError(
                            f"Invalid value for '{key}' in [{section}]: {coord_section.get(key)!r}"
                        ) from e
                    if v is not None:
                        params[key] = v

            dip_func_str = (params.get("dip_func") or "simple")
            if dip_func_str not in Well.STRATEGIES:
                raise ValueError(f"Strategy {dip_func_str} is not a valid dip strategy.")

            config_well = WellParams(
                coor=loc_coor,
                dip_top=params.get("dip_top"),
                dip_btm=params.get("dip_btm"),
                dip_func=Well.NAME_TO_STRAT[dip_func_str],
                well_diameter=params.get("well_diameter"),
            )
            well = Well(
                coor=config_well.coor,
                dip_top=config_well.dip_top,
                dip_btm=config_well.dip_btm,
                dip_func=config_well.dip_func,
                diameter=config_well.well_diameter,
            )
            plate_params = PlateParams(
                plate_type=params.get("type"),
                well_template=well,
                row=params.get("row"),
                col=params.get("col"),
                spacing_row=params.get("spacing_row"),
                spacing_col=params.get("spacing_col"),
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
        self._init_triggers()
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
        self._buffer_command(f"M600 S{factor}\n")

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
            "MOVE=300 STOP_ON_ENDSTOP=1 SET_POSITION=0 ACCEL=800\n"
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n")

    def home_pipette_stepper_disp(self, volume: float, speed: float = None) -> str:
        """Home the pipette stepper.

        Args:
            speed (float): The speed to home the pipette.
        """
        if speed is None:
            speed = self.pipette_params.speed_pipette_up_slow
        stepper = self.pipette_params.name_pipette_stepper

        total_ul = volume + 10
        stepsq = self.volume_converter.vol_to_steps(total_ul)

        self._buffer_command(
            f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} "
            f"MOVE={stepsq} STOP_ON_ENDSTOP=1 SET_POSITION=0 ACCEL=800\n"
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

    def set_trigger_signal(self, value: int) -> str:
        """Send a signal to the Arduino trigger pin.

        Args:
            value (int): 0 to turn OFF (0 V), 1 to turn ON (3.3 V).
        """
        pin_name = "arduino_trigger"  # hardcoded for now
        self._buffer_command(f"SET_PIN PIN={pin_name} VALUE={value}\n")

    def _init_triggers(self) -> None:
        """Load trigger alias→pin mapping from [TRIGGERS] if present, else defaults."""
        self.trigger_pins: dict[str, str] = {}
        if self.config.has_section("TRIGGERS"):
            for alias, pin in self.config["TRIGGERS"].items():
                self.trigger_pins[alias.strip().lower()] = pin.strip()
        else:
            # sensible defaults you can change later in the config
            self.trigger_pins = {
                "air":   "arduino_trigger_air",
                "shake": "arduino_trigger_shake",
                "aux":   "arduino_trigger_aux",
            }

    @staticmethod
    def _to_digital(value) -> int:
        """Normalize many truthy/falsey forms to 1/0."""
        if isinstance(value, (int, float)):
            return 1 if value > 0 else 0
        s = str(value).strip().lower()
        if s in {"1","on","high","true","t","yes","y"}:  return 1
        if s in {"0","off","low","false","f","no","n"}:  return 0
        raise ValueError("state must be one of: on/off/1/0/high/low/true/false")

    def set_trigger(self, channel: str, state) -> None:
        """
        Drive a named trigger via Klipper SET_PIN.
        Example: channel='air'/'shake'/'aux', state='on'/'off'/1/0/...
        """
        alias = str(channel).strip().lower()
        pin = self.trigger_pins.get(alias)
        if not pin:
            raise ValueError(
                f"Unknown trigger '{channel}'. Available: {', '.join(self.trigger_pins.keys())}"
            )
        val = self._to_digital(state)
        self._buffer_command(f"SET_PIN PIN={pin} VALUE={val}\n")
        self._buffer_command("M400\n")  # wait for completion


    def move_pipette_stepper(self, distance: float, speed: float = None) -> str:
        """Move the plunger by 'distance' steps (caller handles vol→steps)."""
        if speed is None:
            speed = self.pipette_params.speed_pipette_up_slow
        stepper = self.pipette_params.name_pipette_stepper
        self._buffer_command(
            f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} MOVE=-{distance} ACCEL=800\n"
        )

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
        elif plate_params.plate_type == "tipbox":
            tb = self.locations[name_loc]           # TipBox created by PlateFactory
            assert isinstance(tb, TipBox)
            self.tipboxes_map[name_loc] = tb        # keep named box as-is

            if self.pooled_tipbox is None:
                # make an independent pooled copy starting with this box
                self.pooled_tipbox = copy.deepcopy(tb)
            else:
                # append wells into the pooled copy (do NOT touch the original tb)
                self.pooled_tipbox.wells += tb.wells


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

    def next_tip(self, from_box: Optional[str] = None) -> None:
        box = self._resolve_tipbox(from_box)
        loc_tip = box.next()
        self.move_to(loc_tip)
        self.dip_z_down(loc_tip, box.get_dip_distance())
        self.dip_z_return(loc_tip)
        self.has_tip = True

    def set_active_tipbox(self, name: str | None) -> None:
        if name is None:
            self.active_tipbox_name = None
            return
        if name not in self.tipboxes_map:
            raise NotALocationError(name)
        self.active_tipbox_name = name

    def _resolve_tipbox(self, from_box: str | None) -> TipBox:
        if from_box:
            tb = self.tipboxes_map.get(from_box)
            if not isinstance(tb, TipBox):
                raise NotALocationError(from_box)
            return tb
        if self.active_tipbox_name:
            tb = self.tipboxes_map.get(self.active_tipbox_name)
            if not isinstance(tb, TipBox):
                raise NotALocationError(self.active_tipbox_name)
            return tb
        if self.pooled_tipbox:
            return self.pooled_tipbox
        raise NoTipboxError()

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

    def wiggle(
        self,
        curr_coor: Coordinate,
        dip_distance: float,
        *,
        shake_offset: float = 2.0,   # mm each way
        cycles: int = 2,
        settle_ms: int | None = None
    ) -> None:
        """
        Z-axis shake around the dip depth (higher Z = deeper). Ends at dip Z.
        """
        if shake_offset <= 0:
            return
        if cycles < 1:
            cycles = 1

        wait_ms = self.pipette_params.wait_movement if settle_ms is None else int(settle_ms)

        # 1) Go to base dip Z
        base = Coordinate(x=curr_coor.x, y=curr_coor.y, z=dip_distance)
        self.move_to_z(base)
        self.gcode_wait(wait_ms)

        # Bounds: deeper = dip + offset; shallower = dip - offset but not above start Z
        z_deeper    = dip_distance + shake_offset
        z_shallower = max(dip_distance - shake_offset, curr_coor.z)

        # 2) Shake in Z
        for _ in range(cycles):
            self.move_to_z(Coordinate(x=curr_coor.x, y=curr_coor.y, z=z_deeper))
            self.gcode_wait(wait_ms)
            self.move_to_z(Coordinate(x=curr_coor.x, y=curr_coor.y, z=z_shallower))
            self.gcode_wait(wait_ms)

        # 3) Return to base dip Z
        self.move_to_z(base)
        self.gcode_wait(wait_ms)

    def aspirate_volume(self,
                        volume: float,
                        source: str,
                        src_row: Optional[int] = None,
                        src_col: Optional[int] = None,
                        prewet: bool = False,
                        extra_air: bool = False,
                        after_air: bool = False,
                        serum_speed: bool = False,
                        tipbox_name: str | None = None) -> None:
        """Dip into a well and take in some liquid."""
        coor_source = self.get_location_coor(source, src_row, src_col)
        loc_source = self.locations[source]
        # Pickup a tip
        if not self.has_tip:
            self.next_tip(from_box=tipbox_name)
        # Maybe check if we have liquid in tip already?
        # Pickup liquid
        self.move_to(coor_source)

        self.home_pipette_stepper(self.pipette_params.speed_pipette_up_slow)
        aft_vol = self.pipette_params.aft_air if after_air else 0
        ext_vol = self.pipette_params.ext_air if extra_air else 0
        tot_vol = volume+aft_vol

        if prewet:
            #dip_z = loc_source.get_dip_distance(volume)
            
            for _ in range(3):
                 # Dip into the liquid
                dip_dist = loc_source.get_dip_distance(volume)
                self.dip_z_down(coor_source, dip_dist)
                
                # Go aspirate
                self.plunge_down(tot_vol,
                                (self.pipette_params.speed_pipette_up_slow if serum_speed else self.pipette_params.speed_pipette_down))
                self.gcode_wait(self.pipette_params.wait_aspirate)
                

                
               # Raise Z by 20 mm (absolute move)
                #raise_z = dip_z - 20
                #self.move_to_z(Coordinate(
                #    x=coor_source.x,
                #    y=coor_source.y,
                #    z=raise_z
                #))
                self.gcode_wait(self.pipette_params.wait_aspirate)
                
                self.home_pipette_stepper_disp(tot_vol,
                    (self.pipette_params.speed_pipette_up_slow if serum_speed else self.pipette_params.speed_pipette_down))


                            
        if extra_air:
            if prewet:
                # Raise Z by 20 mm if prewet (absolute move)
                dip_z = loc_source.get_dip_distance(tot_vol)
                raise_z = dip_z - 30
                self.move_to_z(Coordinate(
                    x=coor_source.x,
                    y=coor_source.y,
                    z=raise_z
                ))
            # self.move_to(coor_source)
            AIR_CUSHION_UL = self.pipette_params.ext_air
            self.plunge_down(
                AIR_CUSHION_UL,
                self.pipette_params.speed_pipette_down
            )
            self.gcode_wait(self.pipette_params.wait_aspirate)

        # Dip into the liquid
        dip_dist = loc_source.get_dip_distance(volume)
        self.dip_z_down(coor_source, dip_dist)

        # Total aspirate = liquid + optional air cushion
        aspirate_amount = volume + (AIR_CUSHION_UL if extra_air else 0.0)

        # Aspirate from well
        self.plunge_down(
            aspirate_amount,
            (self.pipette_params.speed_pipette_up_slow if serum_speed else self.pipette_params.speed_pipette_down) 
        )
        
        
        # Release plunger to aspirate measured amount
        # self.home_pipette_stepper(self.pipette_params.speed_pipette_up_slow)
        # Give time for the liquid to enter the tip
        self.gcode_wait(self.pipette_params.wait_aspirate)
        self.dip_z_return(coor_source)
                            
        # If you want air afterwards to prevent dripping...
        if after_air:
            #5.0
            self.plunge_down(
                aspirate_amount+self.pipette_params.aft_air,
                self.pipette_params.speed_pipette_up_slow
            )
            self.gcode_wait(self.pipette_params.wait_aspirate)
        # Wait after things are picked up so that we can see if it stays
        self.gcode_wait(500)
        self.has_liquid = True

    def dispense_volume(self,
                        volume: float,
                        dest: str,
                        dest_row: Optional[int] = None,
                        dest_col: Optional[int] = None,
                        disp_vol_ul: float | None = None,
                        wiggle: bool = False,
                        serum_speed = False,
                        touch: bool = False) -> None:  
        """Dip into a well and expel some liquid."""
        coor_dest = self.get_location_coor(dest, dest_row, dest_col)
        loc_dest  = self.locations[dest]

        # 1) Move into the well and dip
        self.move_to(coor_dest)
        self.dip_z_down(coor_dest, loc_dest.get_dip_distance(volume))

        stepper = self.pipette_params.name_pipette_stepper
        speed   = (self.pipette_params.speed_pipette_up)

        if disp_vol_ul is not None:
            # ----- ABSOLUTE partial-dispense -----
            A = float(self.volume_converter.vol_to_steps(volume))
            D = float(self.volume_converter.vol_to_steps(disp_vol_ul))
            if D < 0.0: D = 0.0
            if D > A:   D = A
            target = -(A - D)               # ∈ [-A, 0]
            if abs(target) < 1e-9: target = 0.0  # avoid "-0.0"

            self._buffer_command(
                f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} MOVE={target} ACCEL=800\n"
            )
            # self._buffer_command("M400\n")  # wait for stepper to finish
        else:
            # ----- Full dump to 0 (legacy) -----
            self.home_pipette_stepper_disp(volume, self.pipette_params.speed_pipette_up)

        # 2) Optional wiggle
        if wiggle:
            self.wiggle(coor_dest, loc_dest.get_dip_distance(volume))

        # 3) Optional touch (a small single dip)
        if touch:
            touch_depth = loc_dest.get_dip_distance(volume) + 1
            self.gcode_wait(2000) # 1.5 second hold
            self.move_to_z(Coordinate(x=coor_dest.x, y=coor_dest.y, z=touch_depth))
            self.gcode_wait(3000) # 3 second hold
            self.move_to_z(Coordinate(x=coor_dest.x, y=coor_dest.y, z=loc_dest.get_dip_distance(volume)))
            self.gcode_wait(self.pipette_params.wait_movement)

        # 3) Settle & retract Z
        self.gcode_wait(self.pipette_params.wait_aspirate)
        self.dip_z_return(coor_dest)
        # wait for video of how much it emptied
        self.gcode_wait(500)                 

        fully_dispensed = (disp_vol_ul is None) or (abs(disp_vol_ul - volume) <= 1e-6)
        self.has_liquid = not fully_dispensed

    def dispose_tip(self):
        """Eject a tip into a waste container."""
        curr_coor = self.waste_container.next()
        self.move_to(curr_coor)
        self.dip_z_down(curr_coor, self.waste_container.get_dip_distance())
        self.eject_tip()
        self.dip_z_return(curr_coor)

    @staticmethod
    def _parse_splits_spec(spec: str) -> list[Split]:
        """
        Parse 'DEST:VOL[@ROW,COL];DEST2:VOL2[@ROW,COL]' -> List[Split].
        - DEST must match a configured location/plate name
        - VOL is float in µL
        - ROW,COL are optional ints
        """
        if not spec:
            raise ValueError("empty --splits spec")

        out: list[Split] = []
        for chunk in spec.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ":" not in chunk:
                raise ValueError(f"Invalid split '{chunk}': missing ':'")

            dest, rest = chunk.split(":", 1)
            dest = dest.strip()
            if not dest:
                raise ValueError(f"Invalid split '{chunk}': empty destination")

            if "@" in rest:
                vol_str, rc = rest.split("@", 1)
                vol = float(vol_str.strip())
                row_str, col_str = rc.split(",", 1)
                row = int(row_str.strip())
                col = int(col_str.strip())
                out.append(Split(dest=dest, vol_ul=vol, dest_row=row, dest_col=col))
            else:
                vol = float(rest.strip())
                out.append(Split(dest=dest, vol_ul=vol, dest_row=None, dest_col=None))

            if vol <= 0:
                raise ValueError(f"Invalid split volume in '{chunk}': must be > 0")

        if not out:
            raise ValueError("no valid entries in --splits")
        return out

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
                wiggle: bool = False,
                touch: bool = False,
                *,
                splits: Optional[str] = None,           # NEW
                leftover_action: str = "keep",            # NEW: "keep" or "waste"
                tipbox_name: Optional[str] = None,
                extra_air: bool = False,
                after_air: bool = False,
                serum_speed: bool = False,
                ) -> None:
        """Transfer liquid between locations.

        If 'splits' is provided, perform a single aspirate followed by
        multiple dispenses parsed from 'splits'. Otherwise, perform the
        original single-aspirate / single-dispense behavior.

        'splits' format: 'DEST:VOL[@ROW,COL];DEST2:VOL2[@ROW,COL];...'
        Example: 'A_plate:12@1,1;B_plate:8@1,2'
        """
        if vol_ul < 0:
            raise ValueError(f"Invalid volume: {vol_ul}μL")
        
        if vol_ul == 0:
            # Only advance the iterator when no explicit well is specified
            if dest_row is None and dest_col is None:
                try:
                    _ = self.get_location_coor(dest)   # advances Plate.next()
                    self._buffer_command(f"; SKIP: advance 1 well on {dest}\n")
                except NotALocationError:
                    raise
            else:
                self._buffer_command(f"; SKIP requested but explicit dest well given; no advance\n")
            return

        # ── New multi-dispense path ─────────────────────────────────────────
        if splits:
            split_list = self._parse_splits_spec(splits)
            total_split = sum(s.vol_ul for s in split_list)
            if total_split - vol_ul > 1e-6:
                raise ValueError(
                    f"Split volumes ({total_split}μL) exceed aspirate ({vol_ul}μL)"
                )

            self.pipette_splits(
                vol_ul=vol_ul,
                source=source,
                splits=split_list,
                src_row=src_row,
                src_col=src_col,
                keep_tip=keep_tip,
                prewet=prewet,
                wiggle=wiggle,
                leftover_action=leftover_action,
                tipbox_name=tipbox_name,
            )
            return

        # ── Original single-dispense path (unchanged behavior) ─────────────
        max_vol = self.pipette_params.max_vol
        chunks = int(vol_ul // max_vol)
        remainder = vol_ul - (chunks * max_vol)
        transfer_volumes = [max_vol] * chunks
        if remainder > 1e-6:
            transfer_volumes.append(remainder)

        for pip_vol in transfer_volumes:
            # BUGFIX: use 'pip_vol' (not 'vol_ul') for each chunk
            self.aspirate_volume(pip_vol, source, src_row, src_col, prewet, tipbox_name=tipbox_name, extra_air=extra_air, after_air=after_air, serum_speed=serum_speed)
            self.dispense_volume(pip_vol, dest, dest_row, dest_col, disp_vol_ul, wiggle=wiggle, serum_speed=serum_speed, touch=touch)

        if not keep_tip:
            self.dispose_tip()

    def pipette_splits(
        self,
        vol_ul: float,
        source: str,
        splits: Sequence[Split],
        *,
        src_row: Optional[int] = None,
        src_col: Optional[int] = None,
        keep_tip: bool = False,
        prewet: bool = False,
        wiggle: bool = False,
        touch: bool = False,
        leftover_action: str = "keep",  # "keep" or "waste"
        tipbox_name: str | None = None
    ) -> None:
        """
        Aspirate 'vol_ul' once from 'source', then dispense to multiple
        destinations in order, using absolute partial-dispense semantics.

        'splits' is a sequence of Split(dest, vol_ul, dest_row?, dest_col?).

        Example:
            splits = [Split("A_plate", 12), Split("B_plate", 8)]
            -> aspirate 20 uL, dispense 12 to A, 8 to B
        """
        if vol_ul <= 0:
            raise ValueError(f"Invalid volume: {vol_ul}μL")

        total_split = sum(s.vol_ul for s in splits)
        if total_split - vol_ul > 1e-6:
            raise ValueError(
                f"Split volumes ({total_split}μL) exceed aspirate ({vol_ul}μL)"
            )

        # 1) Aspirate once
        self.aspirate_volume(vol_ul, source, src_row, src_col, prewet, tipbox_name=tipbox_name)

        # 2) Sequential partial dispenses.
        #    dispense_volume expects 'volume' = the original aspirated amount,
        #    and 'disp_vol_ul' = cumulative dispensed so far (absolute target).
        disp_cum = 0.0
        for i, s in enumerate(splits, start=1):
            disp_cum += s.vol_ul
            self.dispense_volume(
                volume=vol_ul,
                dest=s.dest,
                dest_row=s.dest_row,
                dest_col=s.dest_col,
                disp_vol_ul=disp_cum,
                wiggle=wiggle,
                touch=touch
            )

        # 3) Leftover handling
        leftover = vol_ul - disp_cum
        if leftover > 1e-6:
            if leftover_action == "waste":
                if self.waste_container is None:
                    raise RuntimeError("No waste_container configured.")
                # finish the dump to 0 at the waste container
                self.dispense_volume(
                    volume=vol_ul,
                    dest="waste_container",
                    disp_vol_ul=vol_ul,   # absolute: empty the tip
                    wiggle=False,
                    touch=False
                )
                self.has_liquid = False
            else:  # "keep"
                self.has_liquid = True
                # keep_tip = False  # don't eject a tip with liquid still inside

        # 4) Eject tip if requested and empty
        if not keep_tip and not self.has_liquid:

            self.dispose_tip()





























































"""
Holds the AutoPipette class.

The AutoPipette class is responsible for functions relating to the AutoPipette.
This includes sending and receiving commands, managing different parameters
and managing the different states of the pipette.

TODO Add Logger obj
TODO Decorator refactor to remove header bool to append to file header
"""
from coordinate import Coordinate
from plates import PlateTypes
from plates import Plate
from plates import Garbage
from plates import TipBox
from volume_converter import VolumeConverter
from configparser import ConfigParser
from configparser import ExtendedInterpolation
from pathlib import Path


class AutoPipetteMeta(type):
    """Provides Singleton Pattern when inherited from."""

    _instances = {}

    def __call__(cls, *args, **kwargs):
        """Maintain one instance of our class."""
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class AutoPipette(metaclass=AutoPipetteMeta):
    """This class is responsible for functions relating to the auto pipette.

    Responsibilities include sending and receiving commands, managing different
    variables and managing the different states of the autopipette.
    """

    conf: ConfigParser = ConfigParser(interpolation=ExtendedInterpolation())
    CONF_PATH = Path(__file__).parent.parent / 'conf/'
    _conf_filename = ""
    has_tip: bool = False
    volconv: VolumeConverter = None
    garbage: Garbage = None
    tipboxes: TipBox = None
    _append_to_header: bool = False
    _header_buf: str = ""
    _gcode_buf: str = ""
    _locations: dict = {}

    def append_to_buf(func):
        """Control which buffer is appended to."""
        def wrapper(self, *args, **kwargs):
            # Directly access the attribute using self.attribute_name
            if self._append_to_header:
                self._header_buf += func(self, *args, **kwargs) + "\n"
            else:
                self._gcode_buf += func(self, *args, **kwargs) + "\n"
        return wrapper

    def __init__(self, conf_filename=None):
        """Initialize autopipette.

        Args:
            conf_filename (str): Name of the configuration file to use.
        """
        if conf_filename is None:
            self._conf_filename = "autopipette.conf"
        else:
            self._conf_filename = conf_filename
        self.load_config_file()

    def load_config_file(self):
        """Load a config file to set passed in values.

        TODO Raise a proper error
        """
        conf_path = self.CONF_PATH / self._conf_filename
        file = open(conf_path, mode='r')
        self.conf.read_file(file)
        # Ensure default sections exist
        def_sections = ["NAME", "BOUNDARY", "SPEED",
                        "SERVO", "WAIT", "VOLUME_CONV"]
        for section in def_sections:
            if section not in self.conf.sections():
                err_msg = f"{section} not in config file {conf_path}.\n"
                print(err_msg)
        self.generate_coordinates(def_sections)
        self.generate_file_header()
        self.generate_volume_converter()
        file.close()

    def save_config_file(self, filename: str = None):
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
            filename = self._conf_filename + "-test"
        conf_path = self.CONF_PATH / filename
        with open(conf_path, 'w') as fp:
            self.conf.write(fp)

    def generate_coordinates(self, ignore_sections: list[str]):
        """Generate the Coordinates, Locations and Plates from config file.

        Args:
            ignore_sections (list[str]): A list of configuration sections to ignore.
        """
        all_sections = self.conf.sections()
        coor_sections = \
            [item for item in all_sections if item not in ignore_sections]
        # Go through coordinate sections, turn locations into plates if needed
        for coor_section in coor_sections:
            # coordinate section should look like [COORDINATE name_loc]
            coor = coor_section.split()
            if coor[0] != "COORDINATE":
                pass
            name_loc = coor[1]
            options = self.conf[coor_section].keys()
            self.set_location(name_loc,
                              self.conf[coor_section].getfloat("x"),
                              self.conf[coor_section].getfloat("y"),
                              self.conf[coor_section].getfloat("z"))
            # Check for row, column, row spacing, col spacing, dip_distance, and type
            row = None
            col = None
            spacing_row = None
            spacing_col = None
            dip_distance = None
            if "row" in options:
                row = self.conf[coor_section].getint("row")
            if "col" in options:
                col = self.conf[coor_section].getint("col")
            if "spacing_row" in options:
                spacing_row = self.conf[coor_section].getfloat("spacing_row")
            if "spacing_col" in options:
                spacing_col = self.conf[coor_section].getfloat("spacing_col")
            if "dip_distance" in options:
                dip_distance = self.conf[coor_section].getfloat("dip_distance")
            if "type" in options:
                type = self.conf[coor_section]["type"]
                self.set_plate(name_loc, type, row, col,
                               spacing_row, spacing_col, dip_distance)

    def generate_file_header(self):
        """Generate a gcode string to set variables and home the motors."""
        self._header_buf += \
            f"; AutoPipette Settings loaded from {self._conf_filename}\n"
        all_sections = self.conf.sections()
        for section in all_sections:
            self._header_buf += f"; {section}\n"
            for option in self.conf[section].keys():
                val = self.conf[section][option]
                self._header_buf += f";\t {option}: {val}\n"
        self._append_to_header = True
        self.init_pipette()
        self._append_to_header = False

    def generate_volume_converter(self):
        """Generate the VolumeConverter based on passed in values."""
        volumes_str = self.conf["VOLUME_CONV"]["volumes"]
        steps_str = self.conf["VOLUME_CONV"]["steps"]
        volumes = list(map(float, volumes_str.split(",")))
        steps = list(map(float, steps_str.split(",")))
        self.volconv = VolumeConverter(x=volumes, y=steps)

    def init_pipette(self):
        """Initialize all relevant aspects of the pipette.

        Set the speed parameters, home all axis, and home the pipette.
        """
        self.init_speed()
        self.home_axis()
        self.home_pipette_motors()

    def init_speed(self):
        """Set the speed parameters.

        SPEED_FACTOR: multiplies with calculated speed for a corrected value.

        MAX_VELOCITY: the maximum possible velocity (mm/sec).

        MAX_ACCEL: the maximum possible acceleration (mm/sec^2).
        """
        factor = float(self.conf["SPEED"]["SPEED_FACTOR"])
        velocity = float(self.conf["SPEED"]["VELOCITY_MAX"])
        accel = float(self.conf["SPEED"]["ACCEL_MAX"])
        self.set_speed_factor(factor)
        self.set_max_velocity(velocity)
        self.set_max_accel(accel)

    @append_to_buf
    def set_speed_factor(self, factor: float) -> str:
        """Set the speed factor using gcode.

        Args:
            factor (float): The speed multiple to be set.
        """
        self.conf["SPEED"]["SPEED_FACTOR"] = str(factor)
        return f"M220 S{factor}"

    @append_to_buf
    def set_max_velocity(self, velocity: float) -> str:
        """Set the max velocity using gcode.

        Args:
            velocity (float): The maximum velocity the pipette will travel.
        """
        self.conf["SPEED"]["VELOCITY_MAX"] = str(velocity)
        return f"SET_VELOCITY_LIMIT VELOCITY={velocity}"

    @append_to_buf
    def set_max_accel(self, accel: float) -> str:
        """Set the max acceleration using gcode.

        Args:
            accel (float): The maximum acceleration the pipette will travel.
        """
        self.conf["SPEED"]["ACCEL_MAX"] = str(accel)
        return f"SET_VELOCITY_LIMIT ACCEL={accel}"

    @append_to_buf
    def home_axis(self) -> str:
        """Home x, y, and z axis.

        Home z axis first to prevent collisions then home the x and y axis.
        """
        return "G28"

    @append_to_buf
    def home_x(self) -> str:
        """Home x axis."""
        return "G28 X"

    @append_to_buf
    def home_y(self) -> str:
        """Home y axis."""
        return "G28 Y"

    @append_to_buf
    def home_z(self) -> str:
        """Home z axis."""
        return "G28 Z"

    def home_pipette_motors(self, speed: float = None):
        """Home motors associated with the pipette toolhead.

        Retract the servo that dispenses pipette tips and home the pipette
        stepper.
        """
        self.home_servo()
        self.home_pipette_stepper(speed)

    def home_servo(self):
        """Retract the servo that dispenses pipette tips."""
        self.set_servo_angle(self.conf["SERVO"]["SERVO_ANGLE_RETRACT"])
        self.gcode_wait(self.conf["WAIT"]["WAIT_TIME_MOVEMENT"])

    @append_to_buf
    def home_pipette_stepper(self, speed: float = None) -> str:
        """Home the pipette stepper.

        Args:
            speed (float): The speed to home the pipette.
        """
        # TODO Add accel as pass in value
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE_DOWN"]
        stepper = self.conf["NAME"]["NAME_PIPETTE_STEPPER"]
        gcode_command = \
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0 SPEED={speed} ACCEL=300 MOVE=-200 STOP_ON_ENDSTOP=1\n"
        gcode_command += \
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n"
        gcode_command += \
            f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} ACCEL=300 MOVE=20"
        return gcode_command

    @append_to_buf
    def clear_pipette(self, speed: float = None) -> str:
        """Clear the pipette of any liquid.

        Args:
            speed (float): The speed to clear the pipette.
        """
        # TODO Add accel as pass in value
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE_DOWN"]
        stepper = self.conf["NAME"]["NAME_PIPETTE_STEPPER"]
        gcode_command = \
            f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} ACCEL=300 FORCE_MOVE=1 MOVE=-200 STOP_ON_ENDSTOP=1\n"
        gcode_command += \
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0\n"
        return gcode_command

    def return_gcode(self):
        """Return the gcode that's been added to the buffer and clear it."""
        temp = self._gcode_buf
        self._gcode_buf = ""
        return temp

    def return_header(self):
        """Return the gcode that's been added to the header buffer and clear it."""
        temp = self._header_buf
        self._header_buf = ""
        return temp

    @append_to_buf
    def move_to(self, coordinate: Coordinate) -> str:
        """Move the pipette toolhead to the coordinate.

        Args:
            coordinate (Coordinate): The place to move to.
        """
        speed = self.conf["SPEED"]["SPEED_XY"]
        return f"G1 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} F{speed}"

    @append_to_buf
    def move_to_x(self, coordinate: Coordinate) -> str:
        """Move the pipette toolhead to the coordinate x position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate (Coordinate): Holds the x location to move to.
        """
        speed = self.conf["SPEED"]["SPEED_XY"]
        return f"G1 X{coordinate.x} F{speed}"

    @append_to_buf
    def move_to_y(self, coordinate: Coordinate) -> str:
        """Move the pipette toolhead to the coordinate y position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate (Coordinate): Holds the y location to move to.
        """
        speed = self.conf["SPEED"]["SPEED_XY"]
        return f"G1 Y{coordinate.y} F{speed}"

    @append_to_buf
    def move_to_z(self, coordinate: Coordinate) -> str:
        """Move the pipette toolhead to the coordinate z position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate (Coordinate): Holds the z location to move to.
        """
        speed = self.conf["SPEED"]["SPEED_Z"]
        return f"G1 Z{coordinate.z} F{speed}"

    def move_to_loc(self, loc: str):
        """Move the pipette toolhead to a location."""
        # TODO Throw errors
        if not self.is_location(loc):
            return
        self.move_to(self.get_location_coor(loc))

    def eject_tip(self):
        """Eject the pipette tip."""
        angle_retract = self.conf["SERVO"]["SERVO_ANGLE_RETRACT"]
        angle_ready = self.conf["SERVO"]["SERVO_ANGLE_EJECT"]
        wait_eject = self.conf["WAIT"]["WAIT_TIME_EJECT"]
        wait_movement = self.conf["WAIT"]["WAIT_TIME_MOVEMENT"]
        self.set_servo_angle(angle_retract)
        self.gcode_wait(wait_eject)
        self.set_servo_angle(angle_ready)
        self.gcode_wait(wait_eject)
        self.set_servo_angle(angle_retract)
        self.gcode_wait(wait_movement)
        self.has_tip = False

    @append_to_buf
    def set_servo_angle(self, angle: float) -> str:
        """Set the servo angle.

        Args:
            angle (float): The angle to set the tip servo to.
        """
        servo = self.conf["NAME"]["NAME_PIPETTE_SERVO"]
        return f"SET_SERVO SERVO={servo} ANGLE={angle}"

    @append_to_buf
    def move_pipette_stepper(self, distance: float, speed: float = None) -> str:
        """Move the stepper associated with the pipette toolhead.

        Args:
            distance (float): Distance to move the plunger.
            speed (float): Speed to move the plunger.
        """
        # TODO Add accel as a pass in value
        if distance > 0:
            speed_key = "SPEED_PIPETTE_UP"
        else:
            speed_key = "SPEED_PIPETTE_DOWN"
        if speed is None:
            speed = self.conf["SPEED"][speed_key]
        stepper = self.conf["NAME"]["NAME_PIPETTE_STEPPER"]
        return f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} ACCEL=200 SET_POSITION=0 MOVE={distance}"

    @append_to_buf
    def gcode_wait(self, mil: float) -> str:
        """Send a gcode command to wait for mil amount of milliseconds.

        Args:
           mil (float): Number of milliseconds the machine should wait.
        """
        return f"G4 P{mil}"

    def dip_z_down(self, curr_coor: Coordinate, distance: float):
        """Dip the pipette toolhead down a set distance.

        Args:
            curr_coor (Coordinate): The coordinate to move from.
            distance (float): Distance to move in the z axis.
        """
        curr_coor.z += distance
        self.move_to_z(curr_coor)
        self.gcode_wait(self.conf["WAIT"]["WAIT_TIME_MOVEMENT"])

    def dip_z_return(self, curr_coor: Coordinate, distance: float):
        """Bring up the pipette toolhead a set distance.

        Args:
            curr_coor (Coordinate): The coordinate to move from.
            distance (float): Distance to move in the z axis.
        """
        curr_coor.z -= distance
        self.move_to_z(curr_coor)
        self.gcode_wait(self.conf["WAIT"]["WAIT_TIME_MOVEMENT"])

    def set_location(self, name_loc: str, x: float, y: float, z: float):
        """Create a Coordinate and associate with a name.

        Args:
            name_loc (str): The name to give to the coordinate.
            x (float): Number representing location in x axis.
            y (float): Number representing location in y axis.
            z (float): Number representing location in z axis.
        """
        self._locations[name_loc] = Coordinate(x, y, z)
        conf_key = f"COORDINATE {name_loc}"
        # Update config
        if not self.conf.has_section(conf_key):
            self.conf.add_section(conf_key)
        self.conf.set(conf_key, "x", str(x))
        self.conf.set(conf_key, "y", str(y))
        self.conf.set(conf_key, "z", str(z))

    def is_location(self, name_loc: str):
        """Return True if name_loc is a location, false otherwise.

        Args:
            name_loc (str): The possible name of Coordinate.
        """
        return name_loc in self._locations.keys()

    def set_plate(self, name_loc: str, plate_type: str,
                  num_row: int = None, num_col: int = None,
                  spacing_row: float = None, spacing_col: float = None,
                  dip_distance: float = None):
        """Create a plate from an existing location name.

        Args:
            name_loc (str): The name of a location.
            plate_type (str): A string representing plate type to be set.
            num_row (int): The total number of rows on the plate. If None,
                use the default number for that plate type.
            num_col (int): The total number of columns on the plate. If None,
                use the default number for that plate type.
        """
        # TODO Throw errors
        # If name_loc doesn't exist as a location, do nothing
        if (name_loc not in self._locations.keys()):
            return
        # If plate_type doesn't match a type of plate, do nothing
        if (plate_type not in PlateTypes.TYPES.keys()):
            return
        coor = self._locations[name_loc]
        self._locations[name_loc] = \
            PlateTypes.TYPES[plate_type](coor, num_row, num_col,
                                         spacing_row, spacing_col,
                                         dip_distance)
        # Update config
        conf_key = f"COORDINATE {name_loc}"
        self.conf[conf_key]["type"] = plate_type
        if num_row is not None:
            self.conf[conf_key]["row"] = str(num_row)
        if num_col is not None:
            self.conf[conf_key]["col"] = str(num_col)
        if spacing_row is not None:
            self.conf[conf_key]["spacing_row"] = str(spacing_row)
        if spacing_col is not None:
            self.conf[conf_key]["spacing_col"] = str(spacing_col)
        if dip_distance is not None:
            self.conf[conf_key]["dip_distance"] = str(dip_distance)
        # Set garbage location if plate type is garbage.
        if (plate_type == Garbage.__repr__(None)):
            self.garbage = self._locations[name_loc]
            self._locations["garbage"] = self.garbage
        # Set tip box location if plate type is TipBox
        elif (plate_type == TipBox.__repr__(None)):
            if (self.tipboxes is None):
                self.tipboxes = self._locations[name_loc]
            else:
                tipbox = self._locations[name_loc]
                self.tipboxes.append_box(tipbox)

    def is_plate(self, name_loc: str):
        """Return True if name_loc is a plate, false otherwise.

        Args:
            name_loc (str): The possible name of a Plate.
        """
        if self.is_location(name_loc):
            plates = self.get_plate_locations()
            if name_loc in plates:
                return True
        else:
            return False

    def get_plate_locations(self) -> list:
        """Return a list of locations that are plates."""
        plates: list = []
        for location in self._locations:
            if self._locations[location].__repr__() \
               in PlateTypes.TYPES.keys():
                plates.append(location)
        return plates

    def get_location_coor(self, name_loc: str,
                          row: int = None, col: int = None):
        """Return a Coordinate from a location name.

        Args:
            name_loc (str): The name of a particular location.
            row (int): A row on a plate.
            col (int): A column on a plate.
        """
        # If name_loc doesn't exist as a location, do nothing
        if (name_loc not in self._locations.keys()):
            return
        # If the returned location is a coordinate, return it.
        # Otherwise, if it is a plate, next() is called and returned
        loc = self._locations[name_loc]
        if (isinstance(loc, Plate)):
            if row is None and col is None:
                return loc.next()
            else:
                return loc.get_coor(row, col)
        elif (isinstance(loc, Coordinate)):
            return loc
        else:
            return

    def next_tip(self):
        """Grab the next tip in the tip box."""
        if self.tipboxes is None:
            return
        if self.has_tip:
            return
        loc_tip = self.tipboxes.next()
        self.move_to(loc_tip)
        self.dip_z_down(loc_tip, self.tipboxes.dip_distance)
        self.dip_z_return(loc_tip, self.tipboxes.dip_distance)
        self.has_tip = True

    def wiggle(self, curr_coor: Coordinate):
        """Vigorously shake the pipette to drop liquid."""
        curr_coor.x += 1
        self.move_to(curr_coor)
        curr_coor.x -= 1
        self.move_to(curr_coor)
        curr_coor.x -= 1
        self.move_to(curr_coor)
        curr_coor.x += 1
        self.move_to(curr_coor)
        curr_coor.y += 1
        self.move_to(curr_coor)
        curr_coor.y -= 1
        self.move_to(curr_coor)
        curr_coor.y -= 1
        self.move_to(curr_coor)
        curr_coor.y += 1
        self.move_to(curr_coor)
        curr_coor.z += 1
        self.move_to(curr_coor)
        curr_coor.z -= 1
        self.move_to(curr_coor)
        curr_coor.z -= 1
        self.move_to(curr_coor)
        curr_coor.z += 1
        self.move_to(curr_coor)

    def pipette(self, vol_ul: float, source: str, dest: str,
                src_row: int = None, src_col: int = None,
                dest_row: int = None, dest_col: int = None,
                keep_tip: bool = False, aspirate: bool = False):
        """Pipette a volume of liquid from source to destination.

        Args:
            vol_ul (float): Volume to be pipetted in microliters
            source (str): The name of the location to be the source.
            dest (str): The name of the location to be the destination.
            src_row (int): The row on a plate.
            src_col (int): The column on a plate.
            dest_row (int): The row on a plate.
            dest_col (int): The column on a plate,
            keep_tip (bool): If true, keep the tip on after pipetting.
            aspirate (bool): If true, aspirate the liquid once before moving
                and dispensing.
        """
        coor_source = self.get_location_coor(source, src_row, src_col)
        coor_dest = self.get_location_coor(dest, dest_row, dest_col)
        loc_source = self._locations[source]
        loc_dest = self._locations[dest]
        time_aspirate = self.conf["WAIT"]["WAIT_TIME_ASPIRATE"]
        # TODO Raise error if not plate to plate
        if not self.is_plate(source):
            return
        if not self.is_plate(dest):
            return
        # Pickup a tip
        self.next_tip()
        remaining_vol = vol_ul
        while remaining_vol > 0:
            if remaining_vol >= 100:
                pip_vol = 100
                remaining_vol -= pip_vol
            else:
                pip_vol = remaining_vol
                remaining_vol -= pip_vol
            # Pickup liquid
            self.move_to(coor_source)
            self.home_pipette_motors()
            self.dip_z_down(coor_source, loc_source.dip_distance)
            # If True, aspirate small amount of liquid 3 times to wet tip
            if aspirate:
                for _ in range(1):
                    self.move_pipette_stepper(
                        self.volconv.vol_to_steps(pip_vol))
                    self.gcode_wait(time_aspirate)
                    self.dip_z_return(coor_source, loc_source.dip_distance/3)
                    self.clear_pipette()
                    self.wiggle(coor_source)
                    self.home_pipette_stepper()
                    self.gcode_wait(time_aspirate)
                    self.dip_z_down(coor_source, loc_source.dip_distance/3)
            # Release plunger to aspirate measured amount
            self.move_pipette_stepper(
                self.volconv.vol_to_steps(pip_vol))
            # Give time for the liquid to enter the tip
            self.gcode_wait(time_aspirate)
            self.dip_z_return(coor_source, loc_source.dip_distance)
            # Dropoff liquid
            self.move_to(coor_dest)
            self.dip_z_down(coor_dest, loc_dest.dip_distance)
            self.clear_pipette()
            self.dip_z_return(coor_dest, loc_dest.dip_distance)
            self.home_pipette_stepper()
        # Eject tip
        if not keep_tip:
            curr_coor = self.garbage.next()
            self.move_to(curr_coor)
            self.dip_z_down(curr_coor, self.garbage.dip_distance)
            self.eject_tip()
            self.dip_z_return(curr_coor, self.garbage.dip_distance)

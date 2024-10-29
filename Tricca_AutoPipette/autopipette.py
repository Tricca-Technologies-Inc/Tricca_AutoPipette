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

CONF_PATH = Path(__file__).parent.parent / 'conf/'


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
    has_tip: bool = False
    volconv: VolumeConverter = None
    garbage: Garbage = None
    tipboxes: TipBox = None
    file_header: str = ""
    _locations: dict = {}
    _gcode_buf: str = ""

    def __init__(self, conf_file=None):
        """Set autopipette variables to defaults or passed in value."""
        if conf_file is None:
            conf_file = "autopipette.conf"
        conf_path = CONF_PATH / conf_file
        file = open(conf_path, mode='r')
        self.conf.read_file(file)
        # Ensure default sections exist
        def_sections = ["NAME", "BOUNDARY", "SPEED",
                        "SERVO", "WAIT", "VOLUME_CONV"]
        for section in def_sections:
            if section not in self.conf.sections():
                err_msg = f"{section} not in config file {conf_path}.\n"
                print(err_msg)
        all_sections = self.conf.sections()
        coor_sections = \
            [item for item in all_sections if item not in def_sections]
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
            # Check for plate type, rows and columns
            row = None
            col = None
            if "row" in options:
                row = self.conf[coor_section].getint("row")
            if "col" in options:
                col = self.conf[coor_section].getint("col")
            if "type" in options:
                type = self.conf[coor_section]["type"]
                self.set_plate(name_loc, type, row, col)
        # Append all AutoPipette conf settings to gcode buf
        self.file_header += f"; AutoPipette Settings loaded from {conf_file}\n"
        for section in all_sections:
            self.file_header += f"; {section}\n"
            for option in self.conf[section].keys():
                val = self.conf[section][option]
                self.file_header += f";\t {option}: {val}\n"
        # Set all var on the pipette using gcode and place in known position
        # Append gcode to file header
        self.init_all(header=True)
        # Process volume conversion variables
        volumes_str = self.conf["VOLUME_CONV"]["volumes"]
        steps_str = self.conf["VOLUME_CONV"]["steps"]
        volumes = list(map(float, volumes_str.split(",")))
        steps = list(map(float, steps_str.split(",")))
        self.volconv = VolumeConverter(x=volumes, y=steps)

    def init_all(self, header=False):
        """Initialize all relevant aspects of the pipette.

        Set the speed parameters, home all axis, and home the pipette.
        """
        self.init_speed(header=header)
        self.home_axis(header=header)
        self.home_pipette_motors(header=header)

    def init_speed(self, header=False):
        """Set the speed parameters.

        SPEED_FACTOR: multiplies with calculated speed for a corrected value.

        MAX_VELOCITY: the maximum possible velocity (mm/sec).

        MAX_ACCEL: the maximum possible acceleration (mm/sec^2).
        """
        factor = float(self.conf["SPEED"]["SPEED_FACTOR"])
        velocity = float(self.conf["SPEED"]["VELOCITY_MAX"])
        accel = float(self.conf["SPEED"]["ACCEL_MAX"])
        self.set_speed_factor(factor, header)
        self.set_max_velocity(velocity, header)
        self.set_max_accel(accel, header)

    def set_speed_factor(self, factor, header=False):
        """Set the speed factor using gcode."""
        self.conf["SPEED"]["SPEED_FACTOR"] = str(factor)
        self.append_gcode(f"M220 S{factor}", header)

    def set_max_velocity(self, velocity, header=False):
        """Set the max velocity using gcode."""
        self.conf["SPEED"]["VELOCITY_MAX"] = str(velocity)
        self.append_gcode(f"SET_VELOCITY_LIMIT VELOCITY={velocity}", header)

    def set_max_accel(self, accel, header=False):
        """Set the max acceleration using gcode."""
        self.conf["SPEED"]["ACCEL_MAX"] = str(accel)
        self.append_gcode(f"SET_VELOCITY_LIMIT ACCEL={accel}", header)

    def home_axis(self, header=False):
        """Home x, y, and z axis.

        Home z axis first to prevent collisions then home the x and y axis.
        """
        self.append_gcode("G28 Z", header)  # Home Z first
        self.append_gcode("G28 X Y", header)

    def home_x(self):
        """Home x axis."""
        gcode_command = "G28 X"
        self.append_gcode(gcode_command)

    def home_y(self):
        """Home y axis."""
        gcode_command = "G28 Y"
        self.append_gcode(gcode_command)

    def home_z(self):
        """Home z axis."""
        gcode_command = "G28 Z"
        self.append_gcode(gcode_command)

    def home_pipette_motors(self, header=False):
        """Home motors associated with the pipette toolhead.

        Retract the servo that dispenses pipette tips and home the pipette
        stepper.
        """
        self.home_servo(header=header)
        self.home_pipette_stepper(header=header)

    def home_servo(self, header=False):
        """Retract the servo that dispenses pipette tips."""
        self.set_servo_angle(self.conf["SERVO"]["SERVO_ANGLE_RETRACT"], header)
        self.gcode_wait(self.conf["WAIT"]["WAIT_TIME_MOVEMENT"], header)

    def home_pipette_stepper(self, speed=None, header=False):
        """Home the pipette stepper."""
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE"]
        stepper = self.conf["NAME"]["NAME_PIPETTE_STEPPER"]
        gcode_command = \
            f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} MOVE=-50 STOP_ON_ENDSTOP=1"
        self.append_gcode(gcode_command, header)
        gcode_command = \
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0"
        self.append_gcode(gcode_command, header)

    def append_gcode(self, command, header=False):
        """Append gcode command to the buffer."""
        if header:
            self.file_header += command + "\n"
        else:
            self._gcode_buf += command + "\n"

    def return_gcode(self):
        """Return the gcode that's been added to the buffer and clear it."""
        temp = self._gcode_buf
        self._gcode_buf = ""
        return temp

    def move_to(self, coordinate: Coordinate):
        """Move the pipette toolhead to the coordinate.

        Args:
            coordinate
        """
        speed = self.conf["SPEED"]["SPEED_XY"]
        gcode_command = f"G1 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} F{speed}"
        self.append_gcode(gcode_command)

    def move_to_x(self, coordinate: Coordinate):
        """Move the pipette toolhead to the coordinate x position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        speed = self.conf["SPEED"]["SPEED_XY"]
        gcode_command = f"G1 X{coordinate.x} F{speed}"
        self.append_gcode(gcode_command)

    def move_to_y(self, coordinate: Coordinate):
        """Move the pipette toolhead to the coordinate y position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        speed = self.conf["SPEED"]["SPEED_XY"]
        gcode_command = f"G1 Y{coordinate.y} F{speed}"
        self.append_gcode(gcode_command)

    def move_to_z(self, coordinate: Coordinate):
        """Move the pipette toolhead to the coordinate z position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        speed = self.conf["SPEED"]["SPEED_Z"]
        gcode_command = f"G1 Z{coordinate.z} F{speed}"
        self.append_gcode(gcode_command)

    def eject_tip(self):
        """Eject the pipette tip."""
        angle_retract = self.conf["SERVO"]["SERVO_ANGLE_RETRACT"]
        angle_ready = self.conf["SERVO"]["SERVO_ANGLE_READY"]
        wait_eject = self.conf["WAIT"]["WAIT_TIME_EJECT"]
        wait_movement = self.conf["WAIT"]["WAIT_TIME_MOVEMENT"]
        self.set_servo_angle(angle_retract)
        self.set_servo_angle(angle_ready)
        self.gcode_wait(wait_eject)
        self.set_servo_angle(angle_retract)
        self.gcode_wait(wait_movement)
        self.has_tip = False

    def set_servo_angle(self, angle, header=False):
        """Set the servo angle.

        Args:
            angle
        """
        servo = self.conf["NAME"]["NAME_PIPETTE_SERVO"]
        gcode_command = f"SET_SERVO SERVO={servo} ANGLE={angle}"
        self.append_gcode(gcode_command, header)

    def move_pipette_stepper(self, distance, speed=None):
        """Move the stepper associated with the pipette toolhead.

        Args:
            distance
            speed
        """
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE"]
        stepper = self.conf["NAME"]["NAME_PIPETTE_STEPPER"]
        gcode_command = f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} MOVE={distance}"
        self.append_gcode(gcode_command)

    def gcode_wait(self, mil, header=False):
        """Send a gcode command to wait for mil amount of milliseconds.

        Args:
           mil
        """
        gcode_command = f"G4 P{mil}"
        self.append_gcode(gcode_command, header)

    def dip_z_down(self, coordinate, dip_dist):
        """Dip the pipette toolhead down a set distance.

        Args:
            coordinate
            dip_dist
        """
        coordinate.z += dip_dist
        self.move_to_z(coordinate)
        self.gcode_wait(self.conf["WAIT"]["WAIT_TIME_MOVEMENT"])

    def dip_z_return(self, coordinate, dip_dist):
        """Bring up the pipette toolhead a set distance.

        Args:
            coordinate
            dip_dist
        """
        coordinate.z -= dip_dist
        self.move_to_z(coordinate)
        self.gcode_wait(self.conf["WAIT"]["WAIT_TIME_MOVEMENT"])

    def set_location(self, name_loc: str, x: float, y: float, z: float):
        """Create a Coordinate and associate with a name."""
        self._locations[name_loc] = Coordinate(x, y, z)

    def is_location(self, name_loc: str):
        """Return True if name_loc is a location, false otherwise."""
        return name_loc in self._locations.keys()

    def set_plate(self, name_loc: str, plate_type: str,
                  num_row=None, num_col=None):
        """Create a plate from an existing location name."""
        # TODO Throw errors
        # If name_loc doesn't exist as a location, do nothing
        if (name_loc not in self._locations.keys()):
            return
        # If plate_type doesn't match a type of plate, do nothing
        if (plate_type not in PlateTypes.TYPES.keys()):
            return
        coor = self._locations[name_loc]
        self._locations[name_loc] = \
            PlateTypes.TYPES[plate_type](coor, num_row, num_col)
        # Set garbage location if plate type is garbage.
        if (plate_type == Garbage.__repr__()):
            self.garbage = self._locations[name_loc]
            self._locations["garbage"] = self.garbage
        # Set tip box location if plate type is TipBox
        elif (plate_type == TipBox.__repr__()):
            if (self.tipboxes is None):
                self.tipboxes = self._locations[name_loc]
            else:
                tipbox = self._locations[name_loc]
                self.tipboxes.append_box(tipbox)

    def get_location_coor(self, name_loc: str):
        """Return a Coordinate from a location name."""
        # If name_loc doesn't exist as a location, do nothing
        if (name_loc not in self._locations.keys()):
            return
        # If the returned location is a coordinate, return it.
        # Otherwise, if it is a plate, next() is called and returned
        loc = self._locations[name_loc]
        if (isinstance(loc, Plate)):
            return loc.next()
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
        self.dip_z_down(loc_tip, self.tipboxes.DIP_DISTANCE)
        self.dip_z_return(loc_tip, self.tipboxes.DIP_DISTANCE)
        self.has_tip = True

    def plunge_down(self, vol_ul, speed=None):
        """Move pipette plunger down."""
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE"]
        self.move_pipette_stepper(self.volconv.vol_to_steps(vol_ul), speed)

    def clear_pipette(self, speed=None):
        """Expell any liquid in tip."""
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE"]
        self.move_pipette_stepper(self.volconv.dist_disp, speed)

    def pipette(self, vol_ul, source: str, dest: str,
                keep_tip: bool = False, aspirate: bool = False):
        """Pipette a volume amount of liquid from source to dest.

        Tutorial to consistent pipetting:
        https://www.thermofisher.com/ca/en/home/life-science/lab-plasticware-supplies/lab-plasticware-supplies-learning-center/lab-plasticware-supplies-resource-library/fundamentals-of-pipetting/proper-pipetting-techniques/10-steps-to-improve-pipetting-accuracy.html
        """
        coor_source = self.get_location_coor(source)
        coor_dest = self.get_location_coor(dest)
        loc_source = self._locations[source]
        loc_dest = self._locations[dest]
        time_aspirate = self.conf["WAIT"]["WAIT_TIME_ASPIRATE"]
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
            self.plunge_down(pip_vol)
            self.dip_z_down(coor_source, loc_source.DIP_DISTANCE)
            # If True, aspirate small amount of liquid 3 times to wet tip
            if aspirate:
                for _ in range(1):
                    self.home_pipette_stepper()
                    self.gcode_wait(time_aspirate)
                    self.plunge_down(pip_vol)
                    self.gcode_wait(time_aspirate)
            # Release plunger to aspirate measured amount
            self.home_pipette_stepper()
            # Give time for the liquid to enter the tip
            self.gcode_wait(time_aspirate)
            self.dip_z_return(coor_source, loc_source.DIP_DISTANCE)
            # Dropoff liquid
            self.move_to(coor_dest)
            self.dip_z_down(coor_dest, loc_dest.DIP_DISTANCE)
            self.clear_pipette()
            self.dip_z_return(coor_dest, loc_dest.DIP_DISTANCE)
            self.home_pipette_stepper()
            self.append_gcode(f"; Moved {pip_vol} uL from {source} to {dest}")
        # Eject tip
        if not keep_tip:
            self.move_to(self.garbage.next())
            self.eject_tip()

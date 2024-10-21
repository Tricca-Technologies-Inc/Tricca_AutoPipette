"""
Holds the AutoPipette class.

The AutoPipette class is responsible for functions relating to the AutoPipette.
This includes sending and receiving commands, managing different parameters
and managing the different states of the pipette.

TODO Add Logger obj
"""
from Coordinate import Coordinate
from Plates import PlateTypes
from Plates import Plate
from Plates import Garbage
from Plates import TipBox
from volume_converter import VolumeConverter
from configparser import ConfigParser
from configparser import ExtendedInterpolation
from pathlib import Path

CONF_PATH = Path(__file__).parent.parent / 'conf/'


class AutoPipette:
    """This class is responsible for functions relating to the auto pipette.

    Responsibilities include sending and receiving commands, managing different
    variables and managing the different states of the autopipette.
    """

    conf = ConfigParser(interpolation=ExtendedInterpolation())
    has_tip = False
    volconv = VolumeConverter()
    garbage = None
    tipboxes = None
    _locations = {}
    _gcode_buf = ""

    def __init__(self, conf_file=None):
        """Set autopipette variables to defaults or passed in value."""
        if conf_file is None:
            conf_file = "autopipette.conf"
        conf_path = CONF_PATH / conf_file
        file = open(conf_path, mode='r')
        self.conf.read_file(file)
        # Ensure default sections exist
        def_sections = ["NAME", "BOUNDARY", "SPEED", "SERVO", "WAIT"]
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
        self._gcode_buf += f"; AutoPipette Settings loaded from {conf_file}\n"
        for section in all_sections:
            self._gcode_buf += f"; {section}\n"
            for option in self.conf[section].keys():
                val = self.conf[section][option]
                self._gcode_buf += f";\t {option}: {val}\n"

        # Set all var on the pipette using gcode and place in known position
        self.init_all()

    def init_all(self):
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

    def set_speed_factor(self, factor):
        """Set the speed factor using gcode."""
        self.conf["SPEED"]["SPEED_FACTOR"] = str(factor)
        self.append_gcode(f"M220 S{factor}")

    def set_max_velocity(self, velocity):
        """Set the max velocity using gcode."""
        self.conf["SPEED"]["VELOCITY_MAX"] = str(velocity)
        self.append_gcode(f"""SET_VELOCITY_LIMIT VELOCITY={velocity}""")

    def set_max_accel(self, accel):
        """Set the max acceleration using gcode."""
        self.conf["SPEED"]["ACCEL_MAX"] = str(accel)
        self.append_gcode(f"SET_VELOCITY_LIMIT ACCEL={accel}")

    def home_axis(self):
        """Home x, y, and z axis.

        Home z axis first to prevent collisions then home the x and y axis.
        """
        self.append_gcode("G28 Z")  # Home Z first
        self.append_gcode("G28 X Y")

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

    def home_pipette_motors(self):
        """Home motors associated with the pipette toolhead.

        Retract the servo that dispenses pipette tips and home the pipette
        stepper.
        """
        self.home_servo()
        self.home_pipette_stepper()

    def home_servo(self):
        """Retract the servo that dispenses pipette tips."""
        self.set_servo_angle(self.conf["SERVO"]["SERVO_ANGLE_RETRACT"])
        self.gcode_wait(self.conf["WAIT"]["WAIT_TIME_MOVEMENT"])

    def home_pipette_stepper(self, speed=None):
        """Home the pipette stepper."""
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE"]
        stepper = self.conf["NAME"]["NAME_PIPETTE_STEPPER"]
        gcode_command = \
            f"MANUAL_STEPPER STEPPER={stepper} SPEED={speed} MOVE=-30 STOP_ON_ENDSTOP=1"
        self.append_gcode(gcode_command)
        gcode_command = \
            f"MANUAL_STEPPER STEPPER={stepper} SET_POSITION=0"
        self.append_gcode(gcode_command)

    def append_gcode(self, command):
        """Append gcode command to the buffer."""
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

    def set_servo_angle(self, angle):
        """Set the servo angle.

        Args:
            angle
        """
        servo = self.conf["NAME"]["NAME_PIPETTE_SERVO"]
        gcode_command = f"SET_SERVO SERVO={servo} ANGLE={angle}"
        self.append_gcode(gcode_command)

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

    def gcode_wait(self, mil):
        """Send a gcode command to wait for mil amount of milliseconds.

        Args:
           mil
        """
        gcode_command = f"G4 P{mil}"
        self.append_gcode(gcode_command)

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
        """Move pipette plunger down to take in some microliters of liquid."""
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE"]
        self.move_pipette_stepper(self.volconv.vol_to_steps(vol_ul), speed)

    def clear_pipette(self, speed=None):
        """Expell any liquid in tip."""
        if speed is None:
            speed = self.conf["SPEED"]["SPEED_PIPETTE"]
        self.move_pipette_stepper(self.volconv.dist_disp, speed)

    def pipette(self, vol_ul, source: str, dest: str):
        """Pipette a volume amount of liquid from source to dest."""
        coor_source = self.get_location_coor(source)
        coor_dest = self.get_location_coor(dest)
        loc_source = self._locations[source]
        loc_dest = self._locations[dest]
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
            self.home_pipette_stepper()
            self.dip_z_return(coor_source, loc_source.DIP_DISTANCE)
            # Dropoff liquid
            self.move_to(coor_dest)
            self.dip_z_down(coor_dest, loc_dest.DIP_DISTANCE)
            self.clear_pipette()
            self.dip_z_return(coor_dest, loc_dest.DIP_DISTANCE)
            self.home_pipette_stepper()
            self.append_gcode(f"; Moved {pip_vol} uL from {source} to {dest}")
        # Eject tip
        self.move_to(self.garbage.next())
        self.eject_tip()

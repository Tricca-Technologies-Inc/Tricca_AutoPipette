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


class AutoPipette:
    """This class is responsible for functions relating to the auto pipette.

    Responsibilities include sending and receiving commands, managing different variables
    and managing the different sates of the auto pipette.
    """

    DEFAULT_SPEED_XY = 500  # For X Y Axis. Can be set when object created.
    DEFAULT_SPEED_Z = 500  # For Z Axis. Can be set when object created.
    DEFAULT_SPEED_PIPETTE = 45  # Speed the pipette plunger moves

    SERVO_ANGLE_RETRACT = 150
    SERVO_ANGLE_READY = 80

    WAIT_TIME_EJECT = 1000
    WAIT_TIME_MOVEMENT = 250

    MAX_SPEED = 99999  # Maximum possible speed the toolhead can move
    SPEED_FACTOR = 100  # Speed multiplier in percentage.
    MAX_VELOCITY = 4000  # Maximum possible velocity of toolhead.
    MAX_ACCEL = 4000  # Maximum possible acceleration of toolhead.

    volconv = VolumeConverter()
    garbage = None
    tipboxes = None
    _locations = {}
    _gcode_buf = ""

    def __init__(self,
                 default_speed_xy=DEFAULT_SPEED_XY,
                 default_speed_z=DEFAULT_SPEED_Z,
                 default_speed_pipette=DEFAULT_SPEED_PIPETTE,
                 servo_angle_retract=SERVO_ANGLE_RETRACT,
                 servo_angle_ready=SERVO_ANGLE_READY,
                 wait_time_eject=WAIT_TIME_EJECT,
                 wait_time_movement=WAIT_TIME_MOVEMENT,
                 max_speed=MAX_SPEED,
                 speed_factor=SPEED_FACTOR,
                 max_velocity=MAX_VELOCITY,
                 max_accel=MAX_ACCEL,
                 servo_name="my_servo",
                 stepper_name="lock_stepper"):
        """Set autopipette variables to defaults or passed in value."""
        self.DEFAULT_SPEED_XY = default_speed_xy
        self.DEFAULT_SPEED_Z = default_speed_z
        self.DEFAULT_SPEED_PIPETTE = default_speed_pipette
        self.SERVO_ANGLE_RETRACT = servo_angle_retract
        self.SERVO_ANGLE_READY = servo_angle_ready
        self.WAIT_TIME_EJECT = wait_time_eject
        self.WAIT_TIME_MOVEMENT = wait_time_movement
        self.MAX_SPEED = max_speed
        self.SPEED_FACTOR = speed_factor
        self.MAX_VELOCITY = max_velocity
        self.MAX_ACCEL = max_accel

        self.servo_name = servo_name
        self.stepper_name = stepper_name

        # A dict of the possible variables that can be changed.
        # Use this internally instead of the constants.
        # Used by set() in ProtocolCommands
        self.vars = {"DEFAULT_SPEED_XY": self.DEFAULT_SPEED_XY,
                     "DEFAULT_SPEED_Z": self.DEFAULT_SPEED_Z,
                     "DEFAULT_SPEED_PIPETTE": self.DEFAULT_SPEED_PIPETTE,
                     "SERVO_ANGLE_RETRACT": self.SERVO_ANGLE_RETRACT,
                     "SERVO_ANGLE_READY": self.SERVO_ANGLE_READY,
                     "WAIT_TIME_EJECT": self.WAIT_TIME_EJECT,
                     "WAIT_TIME_MOVEMENT": self.WAIT_TIME_MOVEMENT,
                     "MAX_SPEED": self.MAX_SPEED,
                     "SPEED_FACTOR": self.SPEED_FACTOR,
                     "MAX_VELOCITY": self.MAX_VELOCITY,
                     "MAX_ACCEL": self.MAX_ACCEL,
                     }

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
        self.set_speed_factor()
        self.set_max_velocity()
        self.set_max_accel()

    def set_speed_factor(self, factor):
        """Set the speed factor using gcode."""
        self.vars["SPEED_FACTOR"] = factor
        self.append_gcode(f"M220 S{factor}")

    def set_max_velocity(self, velocity):
        """Set the max velocity using gcode."""
        self.vars["MAX_VELOCITY"] = velocity
        self.append_gcode(f"""SET_VELOCITY_LIMIT VELOCITY={velocity}""")

    def set_max_accel(self, accel):
        """Set the max acceleration using gcode."""
        self.vars["MAX_ACCEL"] = accel
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
        self.set_servo_angle(self.vars["SERVO_ANGLE_RETRACT"])
        self.gcode_wait(self.vars["WAIT_TIME_MOVEMENT"])

    def home_pipette_stepper(self, speed=DEFAULT_SPEED_PIPETTE):
        """Home the pipette stepper."""
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED={speed} MOVE=-30 STOP_ON_ENDSTOP=1"
        self.append_gcode(gcode_command)
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SET_POSITION=0"
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
        speed = self.vars["DEFAULT_SPEED_XY"]
        gcode_command = f"G1 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} F{speed}"
        self.append_gcode(gcode_command)

    def move_to_x(self, coordinate: Coordinate):
        """Move the pipette toolhead to the coordinate x position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        speed = self.vars["DEFAULT_SPEED_XY"]
        gcode_command = f"G1 X{coordinate.x} F{speed}"
        self.append_gcode(gcode_command)

    def move_to_y(self, coordinate: Coordinate):
        """Move the pipette toolhead to the coordinate y position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        speed = self.vars["DEFAULT_SPEED_XY"]
        gcode_command = f"G1 Y{coordinate.y} F{speed}"
        self.append_gcode(gcode_command)

    def move_to_z(self, coordinate: Coordinate):
        """Move the pipette toolhead to the coordinate z position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        speed = self.vars["DEFAULT_SPEED_Z"]
        gcode_command = f"G1 Z{coordinate.z} F{speed}"
        self.append_gcode(gcode_command)

    def eject_tip(self):
        """Eject the pipette tip."""
        angle_retract = self.vars["SERVO_ANGLE_RETRACT"]
        angle_ready = self.vars["SERVO_ANGLE_READY"]
        wait_eject = self.vars["WAIT_TIME_EJECT"]
        wait_movement = self.vars["WAIT_TIME_MOVEMENT"]
        self.set_servo_angle(angle_retract)
        self.gcode_wait(wait_eject)
        self.set_servo_angle(angle_ready)
        self.gcode_wait(wait_eject)
        self.set_servo_angle(angle_retract)
        self.gcode_wait(wait_movement)

    def set_servo_angle(self, angle):
        """Set the servo angle.

        Args:
            angle
        """
        gcode_command = f"SET_SERVO SERVO={self.servo_name} ANGLE={angle}"
        self.append_gcode(gcode_command)

    def move_pipette_stepper(self, distance, speed=None):
        """Move the stepper associated with the pipette toolhead.

        Args:
            distance
            speed
        """
        if speed is None:
            speed = self.vars["DEFAULT_SPEED_PIPETTE"]
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED={speed} MOVE={distance}"
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
        self.gcode_wait(self.vars["WAIT_TIME_MOVEMENT"])

    def dip_z_return(self, coordinate, dip_dist):
        """Bring up the pipette toolhead a set distance.

        Args:
            coordinate
            dip_dist
        """
        coordinate.z -= dip_dist
        self.move_to_z(coordinate)
        self.gcode_wait(self.vars["WAIT_TIME_MOVEMENT"])

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
        # If num_row and num_col are passed in,
        # instantiate with them otherwise use neither
        if ((num_row is not None) and (num_col is not None)):
            self._locations[name_loc] = \
                PlateTypes.TYPES[plate_type](coor, num_row, num_col)
        else:
            self._locations[name_loc] = \
                PlateTypes.TYPES[plate_type](coor)
        # Set garbage location if plate type is garbage.
        if (plate_type == Garbage.__repr__()):
            self.garbage = self._locations[name_loc]
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
        if (self.tipboxes is None):
            return
        loc_tip = self.tipboxes.next()
        self.move_to(loc_tip)
        self.dip_z_down(loc_tip, self.tipboxes.DIP_DISTANCE)
        self.dip_z_return(loc_tip, self.tipboxes.DIP_DISTANCE)

    def plunge_down(self, vol_ul, speed=None):
        """Move pipette plunger down to take in some microliters of liquid."""
        if speed is None:
            speed = self.vars["DEFAULT_SPEED_PIPETTE"]
        self.move_pipette_stepper(self.volconv.vol_to_steps(vol_ul), speed)

    def clear_pipette(self, speed=None):
        """Expell any liquid in tip."""
        if speed is None:
            speed = self.vars["DEFAULT_SPEED_PIPETTE"]
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

"""
Holds the AutoPipette class.

The AutoPipette class is responsible for functions relating to the AutoPipette.
This includes sending and receiving commands, managing different parameters
and managing the different states of the pipette.

TODO Add Logger obj
"""
from Coordinate import Coordinate
from Coordinate import Location


# Classes for modularization
class AutoPipette:
    """
    This class is responsible for functions relating to the auto pipette.

    Responsibilities include sending and receiving commands, managing different
    variables and managing the different sates of the auto pipette.
    """

    DEFAULT_SPEED_XY = 500  # For X Y Axis. Can be set when object created.
    DEFAULT_SPEED_Z = 500  # For Z Axis. Can be set when object created.
    DEFAULT_SPEED_PIPETTE = 15  # Speed the pipette plunger moves

    SERVO_ANGLE_RETRACT = 150
    SERVO_ANGLE_READY = 80

    WAIT_TIME_EJECT = 1000
    WAIT_TIME_MOVEMENT = 250

    DIP_DISTANCE_TIP = 78.5
    DIP_DISTANCE_WELL = 35
    DIP_DISTANCE_VIAL = 55
    DIP_DISTANCE_TILTV = 30

    MAX_SPEED = 99999  # Maximum possible speed the toolhead can move
    SPEED_FACTOR = 100  # Speed multiplier in percentage.
    MAX_VELOCITY = 4000  # Maximum possible velocity of toolhead.
    MAX_ACCEL = 4000  # Maximum possible acceleration of toolhead.

    _gcode_buf = ""

    def __init__(self,
                 default_speed_xy=DEFAULT_SPEED_XY,
                 default_speed_z=DEFAULT_SPEED_Z,
                 default_speed_pipette=DEFAULT_SPEED_PIPETTE,
                 servo_angle_retract=SERVO_ANGLE_RETRACT,
                 servo_angle_ready=SERVO_ANGLE_READY,
                 wait_time_eject=WAIT_TIME_EJECT,
                 wait_time_movement=WAIT_TIME_MOVEMENT,
                 dip_distance_tip=DIP_DISTANCE_TIP,
                 dip_distance_well=DIP_DISTANCE_WELL,
                 dip_distance_vial=DIP_DISTANCE_VIAL,
                 dip_distance_tiltv=DIP_DISTANCE_TILTV,
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
        self.DIP_DISTANCE_TIP = dip_distance_tip
        self.DIP_DISTANCE_WELL = dip_distance_well
        self.DIP_DISTANCE_VIAL = dip_distance_vial
        self.DIP_DISTANCE_TILTV = dip_distance_tiltv
        self.MAX_SPEED = max_speed
        self.SPEED_FACTOR = speed_factor
        self.MAX_VELOCITY = max_velocity
        self.MAX_ACCEL = max_accel
        self.servo_name = servo_name
        self.stepper_name = stepper_name
       
        # A dict of the possible variables that can be changed.
        # Used by set() in ProtocolCommands
        self.vars = {"DEFAULT_SPEED_XY": self.DEFAULT_SPEED_XY,
                     "DEFAULT_SPEED_Z": self.DEFAULT_SPEED_Z,
                     "DEFAULT_SPEED_PIPETTE": self.DEFAULT_SPEED_PIPETTE,
                     "SERVO_ANGLE_RETRACT": self.SERVO_ANGLE_RETRACT,
                     "SERVO_ANGLE_READY": self.SERVO_ANGLE_READY,
                     "WAIT_TIME_EJECT": self.WAIT_TIME_EJECT,
                     "WAIT_TIME_MOVEMENT": self.WAIT_TIME_MOVEMENT,
                     "DIP_DISTANCE_TIP": self.DIP_DISTANCE_TIP,
                     "DIP_DISTANCE_WELL": self.DIP_DISTANCE_WELL,
                     "DIP_DISTANCE_VIAL": self.DIP_DISTANCE_VIAL,
                     "DIP_DISTANCE_TILTV": self.DIP_DISTANCE_TILTV,
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
        self.SPEED_FACTOR = factor
        self.append_gcode(f"M220 S{self.SPEED_FACTOR}")

    def set_max_velocity(self, velocity):
        """Set the max velocity using gcode."""
        self.MAX_VELOCITY = velocity
        self.append_gcode(f"SET_VELOCITY_LIMIT VELOCITY={self.MAX_VELOCITY}")

    def set_max_accel(self, accel):
        """Set the max acceleration using gcode."""
        self.MAX_ACCEL = accel
        self.append_gcode(f"SET_VELOCITY_LIMIT ACCEL={self.MAX_ACCEL}")

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
        self.set_servo_angle(self.SERVO_ANGLE_RETRACT)
        self.gcode_wait(self.WAIT_TIME_MOVEMENT)

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

    def move_to(self, coordinate):
        """Move the pipette toolhead to the coordinate.

        Args:
            coordinate
        """
        # F4850 is max when xyz move
        # F980 is max when only z moves
        # F6600 is max when only x/y moves
        # G1 X30 Y5 Z9 F27
        gcode_command = f"G1 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} F{coordinate.speed}"
        self.append_gcode(gcode_command)

    def move_to_x(self, coordinate):
        """Move the pipette toolhead to the coordinate x position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        gcode_command = f"G1 X{coordinate.x} F{coordinate.speed}"
        self.append_gcode(gcode_command)

    def move_to_y(self, coordinate):
        """Move the pipette toolhead to the coordinate y position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        gcode_command = f"G1 Y{coordinate.x} F{coordinate.speed}"
        self.append_gcode(gcode_command)

    def move_to_z(self, coordinate):
        """Move the pipette toolhead to the coordinate z position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        gcode_command = f"G1 Z{coordinate.x} F{coordinate.speed}"
        self.append_gcode(gcode_command)

    def eject_tip(self):
        """Eject the pipette tip."""
        self.set_servo_angle(self.SERVO_ANGLE_RETRACT)
        self.gcode_wait(self.WAIT_TIME_EJECT)
        self.set_servo_angle(self.SERVO_ANGLE_READY)
        self.gcode_wait(self.WAIT_TIME_MOVEMENT)
        self.set_servo_angle(self.SERVO_ANGLE_RETRACT)

    def set_servo_angle(self, angle):
        """Set the servo angle.

        Args:
            angle
        """
        gcode_command = f"SET_SERVO SERVO={self.servo_name} ANGLE={angle}"
        self.append_gcode(gcode_command)

    def move_pipette_stepper(self, distance, speed=30):
        """Move the stepper associated with the pipette toolhead.

        Args:
            distance
            speed
        """
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
        coordinate.speed = self.DEFAULT_SPEED_Z
        coordinate.z += dip_dist
        self.move_to(coordinate)
        self.gcode_wait(self.WAIT_TIME_MOVEMENT)

    def dip_z_return(self, coordinate, dip_dist):
        """Bring up the pipette toolhead a set distance.

        Args:
            coordinate
            dip_dist
        """
        coordinate.speed = self.DEFAULT_SPEED_Z
        coordinate.z -= dip_dist
        self.move_to(coordinate)
        self.gcode_wait(self.WAIT_TIME_MOVEMENT)

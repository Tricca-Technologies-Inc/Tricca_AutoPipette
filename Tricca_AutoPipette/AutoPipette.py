"""
Holds the AutoPipette class.

The AutoPipette class is responsible for functions relating to the AutoPipette.
This includes sending and receiving commands, managing different parameters
and managing the different states of the pipette.
"""
from Coordinate import Coordinate
from Coordinate import Location
import time
from VialHolder import VialHolder
from WellPlate import WellPlate
from TipBox import TipBox
import requests


# Classes for modularization
class AutoPipette:
    """
    This class is responsible for functions relating to the auto pipette.

    Responsibilities include sending and receiving commands, managing different
    variables and managing the different sates of the auto pipette.
    """

    # Constants
    SERVO_ANGLE_RETRACT = 150
    SERVO_ANGLE_READY = 80

    EJECT_WAIT_TIME = 1
    MOVEMENT_WAIT_TIME = 1

    TIP_DIP_DISTANCE = 78.5
    WELL_DIP_DISTANCE = 35
    VIAL_DIP_DISTANCE = 55
    TILTV_DIP = 30

    DEFAULT_SPEED = 500  # 10300 -- Old value, now passed in through cmd line
    MAX_SPEED = 1000

    DEFAULT_Z_SPEED = 500  # Maybe just use default speed
    PIPETTE_SPEED = 15  # Maybe just use default speed

    SPEED_FACTOR = 700  # Should be 1?...
    MAX_VELOCITY = 1500  # TODO Check
    MAX_ACCEL = 5500  # TODO Check

    def __init__(self, moonraker_url, default_speed=500,
                 servo_name="my_servo", stepper_name="lock_stepper"):
        """Initialize the AutoPipette object.

        Sets the moonraker url, the servo name, the stepper name, and creates
        various locations.
        """
        self.moonraker_url = \
            "http://" + moonraker_url + ":7125/printer/gcode/script"

        self.DEFAULT_SPEED = default_speed

        self.servo_name = servo_name
        self.stepper_name = stepper_name

        self.source_plate = WellPlate(Location.tip_s6)
        self.dest_tips = WellPlate(Location.tip_s4)
        self.dest_plate = WellPlate(Location.well_s5)

        self.tip_box = TipBox(Location.tip_s4, row_count=12, col_count=8)

        self.vial_holder_1 = VialHolder(Location.vial2)
        self.vial_holder_2 = VialHolder(Location.vial3,
                                        row_count=6, column_count=5)
        self.vial_holder_3 = VialHolder(Location.vial1)

        self.source_vial = self.vial_holder_1.get_coordinates() + \
            self.vial_holder_2.get_coordinates() + \
            self.vial_holder_3.get_coordinates()
        self.dest_vial = Coordinate(65, 109, 30, speed=self.DEFAULT_SPEED)

    def init_all(self):
        """Initialize all relevant aspects of the pipette.

        Set the speed parameters, home all axis, and home the pipette.
        """
        self.init_speed()
        self.home_axes()
        self.home_pipette_motors()

    def init_speed(self):
        """Set the speed parameters.

        SPEED_FACTOR: multiplies with calculated speed for a corrected value.

        MAX_VELOCITY: the maximum possible velocity (mm/sec).

        MAX_ACCEL: the maximum possible acceleration (mm/sec^2).
        """
        self.send_gcode(f"M220 S{self.SPEED_FACTOR}")
        self.send_gcode(f"SET_VELOCITY_LIMIT VELOCITY={self.MAX_VELOCITY}")
        self.send_gcode(f"SET_VELOCITY_LIMIT ACCEL={self.MAX_ACCEL}")

    def home_axes(self):
        """Home x, y, and z axis.

        Home z axis first to prevent collisions then home the x and y axis.
        """
        self.send_gcode("G28 Z")  # Home Z first
        self.send_gcode("G28 X Y")

    def home_x(self):
        """Home x axis."""
        gcode_command = "G28 X"
        self.send_gcode(gcode_command)

    def home_y(self):
        """Home y axis."""
        gcode_command = "G28 Y"
        self.send_gcode(gcode_command)

    def home_z(self):
        """Home z axis."""
        gcode_command = "G28 Z"
        self.send_gcode(gcode_command)

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
        time.sleep(1)

    def home_pipette_stepper(self, speed=PIPETTE_SPEED):
        """Home the pipette stepper."""
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} \
            SPEED={speed} MOVE=-30 STOP_ON_ENDSTOP=1"
        self.send_gcode(gcode_command)
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} \
            SET_POSITION=0"
        self.send_gcode(gcode_command)

    def send_gcode(self, command):
        """Send gcode to the pipette."""
        response = requests.post(self.moonraker_url, json={"script": command})
        if response.status_code == 200:
            print("Command sent successfully")
        else:
            print(f"Failed to send command: \
            {response.status_code}, {response.text}")

    def move_to(self, coordinate):
        """Move the pipette toolhead to the coordinate.

        Args:
            coordinate
        """
        # F4850 is max when xyz move
        # F980 is max when only z moves
        # F6600 is max when only x/y moves
        gcode_command = f"G1 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} \
            F{coordinate.speed}"
        self.send_gcode(gcode_command)

    def move_to_x(self, coordinate):
        """Move the pipette toolhead to the coordinate x position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        gcode_command = f"G1 X{coordinate.x} F{coordinate.speed}"
        self.send_gcode(gcode_command)

    def move_to_y(self, coordinate):
        """Move the pipette toolhead to the coordinate y position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        gcode_command = f"G1 Y{coordinate.x} F{coordinate.speed}"
        self.send_gcode(gcode_command)

    def move_to_z(self, coordinate):
        """Move the pipette toolhead to the coordinate z position.

        Use the Coordinate object to get the position and speed.

        Args:
            coordinate
        """
        gcode_command = f"G1 Z{coordinate.x} F{coordinate.speed}"
        self.send_gcode(gcode_command)

    def eject_tip(self):
        """Eject the pipette tip."""
        self.set_servo_angle(self.SERVO_ANGLE_RETRACT)
        self.gcode_wait_sec(self.EJECT_WAIT_TIME)
        self.set_servo_angle(self.SERVO_ANGLE_READY)
        self.gcode_wait_sec(self.MOVEMENT_WAIT_TIME)
        self.set_servo_angle(self.SERVO_ANGLE_RETRACT)

    def set_servo_angle(self, angle):
        """Set the servo angle.

        Args:
            angle
        """
        gcode_command = f"SET_SERVO SERVO={self.servo_name} ANGLE={angle}"
        self.send_gcode(gcode_command)

    def move_pipette_stepper(self, distance, speed=15):
        """Move the stepper associated with the pipette toolhead.

        Args:
            distance
            speed
        """
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} \
            SPEED={speed} MOVE={distance}"
        self.send_gcode(gcode_command)

    def pickupTip(self, tip_box):
        """Pickup the next available pipette tip.

        Args:
            tip_box
        """
        try:
            # Get the next available tip's position
            tip_position = tip_box.next_tip()

            tip_position.speed = self.DEFAULT_SPEED
            # Move to the tip's position
            self.move_to(tip_position)
            time.sleep(0.5)

            # Set the speed and dip down to pick up the tip
            tip_position.speed = self.DEFAULT_SPEED
            tip_position.z += self.TIP_DIP_DISTANCE
            self.move_to(tip_position)
            time.sleep(0.5)

            # Retract the pipette back up
            tip_position.z -= self.TIP_DIP_DISTANCE
            self.move_to(tip_position)

            print(f"Picked up tip from position: {tip_position}")

        except ValueError as e:
            print(e)

    def gcode_wait_sec(self, time):
        """Send a gcode command to wait for time amount of seconds.

        Args:
            time
        """
        gcode_command = f"G4 S{time}"
        self.send_gcode(gcode_command)

    def dip_z_down(self, coordinate, dip_dist):
        """Dip the pipette toolhead down a set distance.

        Args:
            coordinate
            dip_dist
        """
        coordinate.speed = self.DEFAULT_Z_SPEED
        coordinate.z += dip_dist
        self.move_to(coordinate)
        self.gcode_wait_sec(5)

    def dip_z_return(self, coordinate, dip_dist):
        """Bring up the pipette toolhead a set distance.

        Args:
            coordinate
            dip_dist
        """
        coordinate.speed = self.DEFAULT_Z_SPEED
        coordinate.z -= dip_dist
        self.move_to(coordinate)
        self.gcode_wait_sec(5)

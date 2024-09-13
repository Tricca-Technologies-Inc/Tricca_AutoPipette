from Coordinate import Coordinate
from Coordinate import Location
from Coordinate import *
import time
from volumes import *
from VialHolder import VialHolder
from WellPlate import WellPlate
from TipBox import TipBox
import requests


# Classes for modularization
class AutoPipette:
    # Constants
    SERVO_ANGLE_RETRACT = 150
    SERVO_ANGLE_READY = 80

    EJECT_WAIT_TIME = 1
    MOVEMENT_WAIT_TIME = 1

    TIP_DIP_DISTANCE = 78.5
    WELL_DIP_DISTANCE = 35
    VIAL_DIP_DISTANCE = 55
    TILTV_DIP = 30

    DEFAULT_SPEED = 10300
    DEFAULT_Z_SPEED = 1000
    PIPETTE_SPEED = 15

    SPEED_FACTOR = 700
    VELOCITY = 1500
    ACCEL = 5500

    # Usage
    source_plate = WellPlate(Location.tip_s6)
    dest_tips = WellPlate(Location.tip_s4)
    dest_plate = WellPlate(Location.well_s5)

    tip_box = TipBox(Location.tip_s4, row_count=12, col_count=8)

    # Initialize the vial holders
    vial_holder_1 = VialHolder(Location.vial2)
    vial_holder_2 = VialHolder(Location.vial3, row_count=6, column_count=5)
    vial_holder_3 = VialHolder(Location.vial1)

    # Combine all coordinates into a single list
    source_vial = vial_holder_1.get_coordinates() + vial_holder_2.get_coordinates() + vial_holder_3.get_coordinates()

    dest_vial = Coordinate(65, 109, 30, speed=DEFAULT_SPEED)

    def __init__(self, moonraker_url, servo_name="my_servo", stepper_name="lock_stepper"):
        self.moonraker_url = "http://" + moonraker_url + ":7125/printer/gcode/script"
        self.servo_name = servo_name
        self.stepper_name = stepper_name

    def send_gcode(self, command):
        #F4850 is max when xyz move
        #F980 is max when only z moves
        #F6600 is max when only x/y moves
        response = requests.post(self.moonraker_url, json={"script": command})
        if response.status_code == 200:
            print("Command sent successfully")
        else:
            print(f"Failed to send command: {response.status_code}, {response.text}")

    def move_to(self, coordinate):
        gcode_command = f"G1 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} F{coordinate.speed}"
        self.send_gcode(gcode_command)

    def moveX_to(self, coordinate):
        gcode_command = f"G1 X{coordinate.x} F{coordinate.speed}"
        self.send_gcode(gcode_command)

    def homeX(self):
        gcode_command = f"G28 X"
        self.send_gcode(gcode_command)

    def initSpeed(self):
        self.send_gcode(f"M220 S{self.SPEED_FACTOR}")
        self.send_gcode(f"SET_VELOCITY_LIMIT VELOCITY={self.VELOCITY}")
        self.send_gcode(f"SET_VELOCITY_LIMIT ACCEL={self.ACCEL}")

    def homeAxes(self):
        self.send_gcode(f"G28 Z") # Home Z first
        self.send_gcode(f"G28 X Y")

    def eject_tip(self):
        self.set_servo_angle(self.SERVO_ANGLE_RETRACT)
        time.sleep(self.EJECT_WAIT_TIME)
        self.set_servo_angle(self.SERVO_ANGLE_READY)
        time.sleep(self.MOVEMENT_WAIT_TIME)
        self.set_servo_angle(self.SERVO_ANGLE_RETRACT)

    def set_servo_angle(self, angle):
        gcode_command = f"SET_SERVO SERVO={self.servo_name} ANGLE={angle}"
        self.send_gcode(gcode_command)
    
    def home_stepper(self, speed=PIPETTE_SPEED):
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED={speed} MOVE=-30 STOP_ON_ENDSTOP=1"
        self.send_gcode(gcode_command)
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SET_POSITION=0"
        self.send_gcode(gcode_command)

    def move_stepper(self, distance, speed=15):
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED={speed} MOVE={distance}"
        self.send_gcode(gcode_command)

    def homeMotors(self):
        self.set_servo_angle(self.SERVO_ANGLE_RETRACT)
        time.sleep(1)
        self.home_stepper()

    def initAll(self):
        self.homeAxes()
        self.homeMotors()
        self.initSpeed()

    def pickupTip(self, tip_box):
        try:
            # Get the next available tip's position
            tip_position = tip_box.next_tip()

            tip_position.speed = self.DEFAULT_SPEED
            # Move to the tip's position
            self.move_to(tip_position)
            time.sleep(0.5)

            # Set the speed and dip down to pick up the tip
            tip_position.speed = 1100
            tip_position.z += self.TIP_DIP_DISTANCE
            self.move_to(tip_position)
            time.sleep(0.5)

            # Retract the pipette back up
            tip_position.z -= self.TIP_DIP_DISTANCE
            self.move_to(tip_position)

            print(f"Picked up tip from position: {tip_position}")

        except ValueError as e:
            print(e)

    def dipZ(self, coordinate, dip_dist):
        coordinate.speed = self.DEFAULT_Z_SPEED
        coordinate.z += dip_dist
        time.sleep(0.5)
        self.move_to(coordinate)

    def returnZ(self, coordinate, dip_dist):
        coordinate.speed = self.DEFAULT_Z_SPEED
        coordinate.z -= dip_dist
        time.sleep(0.5)
        self.move_to(coordinate)

from coordinates import *
from movement import *
import time
from volumes import *

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

# Classes for modularization
class PipetteController:
    def __init__(self, servo_name, stepper_name):
        self.servo_name = servo_name
        self.stepper_name = stepper_name
    
    def eject_tip(self):
        self.set_servo_angle(SERVO_ANGLE_RETRACT)
        time.sleep(EJECT_WAIT_TIME)
        self.set_servo_angle(SERVO_ANGLE_READY)
        time.sleep(MOVEMENT_WAIT_TIME)
        self.set_servo_angle(SERVO_ANGLE_RETRACT)

    def set_servo_angle(self, angle):
        gcode_command = f"SET_SERVO SERVO={self.servo_name} ANGLE={angle}"
        send_gcode(gcode_command)
    
    def home_stepper(self, speed=PIPETTE_SPEED):
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED={speed} MOVE=-30 STOP_ON_ENDSTOP=1"
        send_gcode(gcode_command)
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SET_POSITION=0"
        send_gcode(gcode_command)

    def move_stepper(self, distance, speed=15):
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED={speed} MOVE={distance}"
        send_gcode(gcode_command)

    def homeMotors(self):
        self.set_servo_angle(SERVO_ANGLE_RETRACT)
        time.sleep(1)
        self.home_stepper()

    def initAll(self):
        homeAxes()
        self.homeMotors()
        initSpeed()

class WellPlate:
    def __init__(self, start_coordinate, row_count=12, column_count=8, row_spacing=9, column_spacing=9):
        self.coordinates = self._generate_well_plate_coordinates(start_coordinate, row_count, column_count, row_spacing, column_spacing)
    
    def _generate_well_plate_coordinates(self, start_coordinate, row_count, column_count, row_spacing, column_spacing):
        coordinates_list = []
        x_start = start_coordinate.x
        y_start = start_coordinate.y
        z_start = start_coordinate.z

        for row in range(row_count):
            for col in range(column_count):
                x = x_start - (col * column_spacing)
                y = y_start + (row * row_spacing)
                z = z_start
                
                # Add the well coordinates
                coordinates_list.append(Coordinate(x, y, z, 6300))
                
        return coordinates_list

    def get_coordinates(self):
        return self.coordinates
    
class TipBox:
    def __init__(self, start_coordinate, row_count=12, col_count=8, row_spacing=9, col_spacing=9):
        self.coordinates = self._generate_tip_coordinates(start_coordinate, row_count, col_count, row_spacing, col_spacing)
        self.current_tip = 0
    
    def _generate_tip_coordinates(self, start_coordinate, row_count, col_count, row_spacing, col_spacing):
        coordinates_list = []
        x_start = start_coordinate.x
        y_start = start_coordinate.y
        z_start = start_coordinate.z

        for row in range(row_count):
            for col in range(col_count):
                x = x_start - (col * col_spacing)
                y = y_start + (row * row_spacing)
                z = z_start
                
                # Add the tip coordinates
                coordinates_list.append(Coordinate(x, y, z, start_coordinate.speed))
                
        return coordinates_list

    def next_tip(self):
        if self.current_tip < len(self.coordinates):
            tip_coordinate = self.coordinates[self.current_tip]
            self.current_tip += 1
            return tip_coordinate
        
        elif self.current_tip == len(self.coordinates):
            self.reset()

        else:
            self.reset()
            raise ValueError("No more tips available")

    def reset(self):
        """Reset the tip box to start picking tips from the beginning."""
        self.current_tip = 0
    
class VialHolder:
    def __init__(self, start_coordinate, row_count=7, column_count=5, row_spacing=18, column_spacing=18):
        self.coordinates = self._generate_vial_coordinates(start_coordinate, row_count, column_count, row_spacing, column_spacing)
    
    def _generate_vial_coordinates(self, start_coordinate, row_count, column_count, row_spacing, column_spacing):
        coordinates_list = []
        x_start = start_coordinate.x
        y_start = start_coordinate.y
        z_start = start_coordinate.z

        for row in range(row_count):
            for col in range(column_count):
                x = x_start - (col * column_spacing)
                y = y_start + (row * row_spacing)
                z = z_start
                
                # Add the well coordinates
                coordinates_list.append(Coordinate(x, y, z, 6300))
                
        return coordinates_list

    def get_coordinates(self):
        return self.coordinates

def PickupTip(tip_box):
    try:
        # Get the next available tip's position
        tip_position = tip_box.next_tip()
        
        tip_position.speed = DEFAULT_SPEED
        # Move to the tip's position
        move_to(tip_position)
        time.sleep(0.5)
        
        # Set the speed and dip down to pick up the tip
        tip_position.speed = 1100
        tip_position.z += TIP_DIP_DISTANCE
        move_to(tip_position)
        time.sleep(0.5)
        
        # Retract the pipette back up
        tip_position.z -= TIP_DIP_DISTANCE
        move_to(tip_position)
        
        print(f"Picked up tip from position: {tip_position}")
    
    except ValueError as e:
        print(e)

def dipZ(coordinate, dip_dist):
    coordinate.speed = DEFAULT_Z_SPEED
    coordinate.z += dip_dist
    time.sleep(0.5)
    move_to(coordinate)

def returnZ(coordinate, dip_dist):
    coordinate.speed = DEFAULT_Z_SPEED
    coordinate.z -= dip_dist
    time.sleep(0.5)
    move_to(coordinate)

# Usage
pipette = PipetteController("my_servo", "lock_stepper")
source_plate = WellPlate(tip_s6)
dest_tips = WellPlate(tip_s4)
dest_plate = WellPlate(well_s5)

tip_box = TipBox(tip_s4, row_count=12, col_count=8)

# Initialize the vial holders
vial_holder_1 = VialHolder(vial2)
vial_holder_2 = VialHolder(vial3, row_count=6, column_count=5)
vial_holder_3 = VialHolder(vial1)

# Combine all coordinates into a single list
source_vial = vial_holder_1.get_coordinates() + vial_holder_2.get_coordinates() + vial_holder_3.get_coordinates()

dest_vial = Coordinate(65, 109, 30, speed=DEFAULT_SPEED)

#sample_test(vial2, dest_plate, pipette)
#tip_test(source_plate, dest_plate, pipette)
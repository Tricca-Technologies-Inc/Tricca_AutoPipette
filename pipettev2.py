from coordinates import *
from movement import *
import time
from volumes import *

# Constants
SERVO_ANGLE_RETRACT = 160
SERVO_ANGLE_READY = 90

EJECT_WAIT_TIME = 3
MOVEMENT_WAIT_TIME = 2

TIP_DIP_DISTANCE = 54
WELL_DIP_DISTANCE = 15

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
    
    def home_stepper(self):
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED=5 MOVE=-10 STOP_ON_ENDSTOP=1"
        send_gcode(gcode_command)
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SET_POSITION=0"
        send_gcode(gcode_command)

    def move_stepper(self, distance, speed=20):
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED={speed} MOVE={distance}"
        send_gcode(gcode_command)

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
                coordinates_list.append(Coordinate(x, y, z, 4800))
                
        return coordinates_list

    def get_coordinates(self):
        return self.coordinates

# Refactored sampleTest and tipTest using the new classes
def sample_test(source, dest, pipette):
    well_coords = dest.get_coordinates()

    srcVial = source
    srcVial.speed = 3700
    move_to(srcVial)
    
    for coord in well_coords:
        if srcVial.z == coord.z:
            srcVial.speed = 6300
        else:
            srcVial.speed = 2000

        move_to(srcVial)
        pipette.move_stepper(v100.prep)

        srcVial.speed = 800
        srcVial.z += 25
        move_to(srcVial)
        pipette.move_stepper(v100.aspirate)

        time.sleep(1)

        srcVial.z -= 25
        move_to(srcVial)
        
        coord.speed = 6300
        move_to(coord)

        coord.speed = 800
        coord.z += 10
        move_to(coord)
        pipette.move_stepper(v100.dispense)

        time.sleep(1.5)
        coord.z -= 10
        move_to(coord)

        pipette.move_stepper(v100.aspirate)

def tip_test(source, dest, pipette):
    well_coords = dest.get_coordinates()
    tip_loc = source.get_coordinates()
    tip_s6.speed = 3700
    move_to(tip_s6)
    
    for i in range(len(well_coords)):
        if tip_loc[i].z == well_coords[i].z:
            tip_loc[i].speed = 6300
        else:
            tip_loc[i].speed = 2000

        move_to(tip_loc[i])

        tip_loc[i].speed = 800
        tip_loc[i].z += TIP_DIP_DISTANCE
        move_to(tip_loc[i])

        tip_loc[i].z -= TIP_DIP_DISTANCE
        move_to(tip_loc[i])

        time.sleep(1)
        move_to(well_coords[i])

        well_coords[i].speed = 800
        well_coords[i].z += WELL_DIP_DISTANCE
        move_to(well_coords[i])

        pipette.eject_tip()

        well_coords[i].z -= WELL_DIP_DISTANCE
        move_to(well_coords[i])

# Usage
pipette = PipetteController("my_servo", "lock_stepper")
source_plate = WellPlate(Coordinate(100, 100, 40))
dest_plate = WellPlate(Coordinate(200, 200, 40))

#sample_test(vial2, dest_plate, pipette)
#tip_test(source_plate, dest_plate, pipette)
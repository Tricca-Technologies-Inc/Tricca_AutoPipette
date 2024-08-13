from coordinates import *
from movement import *
import time
from volumes import *

# Constants
SERVO_ANGLE_RETRACT = 140
SERVO_ANGLE_READY = 85

EJECT_WAIT_TIME = 3
MOVEMENT_WAIT_TIME = 3

TIP_DIP_DISTANCE = 73
WELL_DIP_DISTANCE = 35

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
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED=5 MOVE=-30 STOP_ON_ENDSTOP=1"
        send_gcode(gcode_command)
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SET_POSITION=0"
        send_gcode(gcode_command)

    def move_stepper(self, distance, speed=20):
        gcode_command = f"MANUAL_STEPPER STEPPER={self.stepper_name} SPEED={speed} MOVE={distance}"
        send_gcode(gcode_command)

    def homeAll(self):
        self.set_servo_angle(SERVO_ANGLE_RETRACT)
        time.sleep(1)
        self.home_stepper()

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
    
class VialHolder:
    def __init__(self, start_coordinate, row_count=7, column_count=5, row_spacing=15, column_spacing=15):
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

# Refactored sampleTest (Program for Sample Prep.)
def sample_test(source, dest, pipette):
    well_coords = dest.get_coordinates()

    srcVial = source
    srcVial.speed = 3700
    move_to(srcVial)
    
    for coord in well_coords:
        if srcVial.z == coord.z:
            srcVial.speed = 6500
        else:
            srcVial.speed = 2000

        move_to(srcVial)
        pipette.move_stepper(v100.prep)

        srcVial.speed = 700
        srcVial.z += 25
        move_to(srcVial)
        pipette.move_stepper(v100.aspirate)

        time.sleep(1)

        srcVial.z -= 25
        move_to(srcVial)

        coord.speed = 6500
        move_to(coord)

        coord.speed = 700
        coord.z += 28
        move_to(coord)
        pipette.move_stepper(v100.dispense)

        time.sleep(1.5)
        coord.z -= 28
        move_to(coord)

        pipette.move_stepper(v100.aspirate)

# (Program for Kit Manufacturing)
def kitTest(source, dest, pipette):
    vial_coords = source.get_coordinates()

    destVial = dest
    destVial.speed = 3700
    move_to(destVial)
    
    for coord in vial_coords:
        if destVial.z == coord.z:
            destVial.speed = 6500
        else:
            destVial.speed = 2000

        move_to(coord)
        pipette.move_stepper(v100.prep)

        coord.speed = 800
        coord.z += 25
        move_to(coord)
        pipette.move_stepper(v100.aspirate)

        time.sleep(1)

        coord.z -= 25
        move_to(coord)

        destVial.speed = 6300
        move_to(destVial)

        destVial.speed = 800
        destVial.z += 10
        move_to(destVial)
        pipette.move_stepper(v100.dispense)

        time.sleep(1.5)
        destVial.z -= 10
        move_to(destVial)

        pipette.move_stepper(v100.aspirate)


def tip_test(source, dest, pipette):
    well_coords = dest.get_coordinates()
    tip_loc = source.get_coordinates()
    tip_s6.speed = 3700
    move_to(tip_s6)
    
    for i in range(len(well_coords)):
        if tip_loc[i].z == well_coords[i].z:
            tip_loc[i].speed = 6500
        else:
            tip_loc[i].speed = 2000

        move_to(tip_loc[i])

        tip_loc[i].speed = 700
        tip_loc[i].z += TIP_DIP_DISTANCE
        move_to(tip_loc[i])

        tip_loc[i].z -= TIP_DIP_DISTANCE
        move_to(tip_loc[i])

        time.sleep(1)
        move_to(well_coords[i])

        well_coords[i].speed = 700
        well_coords[i].z += WELL_DIP_DISTANCE
        move_to(well_coords[i])

        pipette.eject_tip()

        well_coords[i].z -= WELL_DIP_DISTANCE
        move_to(well_coords[i])

# Usage
pipette = PipetteController("my_servo", "lock_stepper")
source_plate = WellPlate(tip_s6)
dest_tips = WellPlate(tip_s4)
dest_plate = WellPlate(well_s5)
source_vial = VialHolder(vial2)

#sample_test(vial2, dest_plate, pipette)
#tip_test(source_plate, dest_plate, pipette)
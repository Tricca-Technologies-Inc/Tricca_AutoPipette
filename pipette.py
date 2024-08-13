from coordinates import *
from movement import *
import time
from volumes import *

#F4850 is max when xyz move
#F980 is max when only z moves
#F6600 is max when only x/y moves

def ejectTip():
    gcode_command = f"SET_SERVO SERVO=my_servo ANGLE=160"
    send_gcode(gcode_command)
    time.sleep(3)
    gcode_command = f"SET_SERVO SERVO=my_servo ANGLE=90"
    send_gcode(gcode_command)
    time.sleep(2)
    gcode_command = f"SET_SERVO SERVO=my_servo ANGLE=160"
    send_gcode(gcode_command)

def generate_well_plate_coordinates(start_coordinate, row_count=12, column_count=8, row_spacing=9, column_spacing=9):
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

#MANUAL_STEPPER STEPPER=lock_stepper SPEED=5 MOVE=-10 STOP_ON_ENDSTOP=1

def homeStep():
    gcode_command = f"MANUAL_STEPPER STEPPER=lock_stepper SPEED=5 MOVE=-10 STOP_ON_ENDSTOP=1"
    send_gcode(gcode_command)
    gcode_command = f"MANUAL_STEPPER STEPPER=lock_stepper SET_POSITION=0"
    send_gcode(gcode_command)


def aspirate(volume):
    gcode_command = f"MANUAL_STEPPER STEPPER=lock_stepper SPEED=20 MOVE={volume.aspirate}"
    send_gcode(gcode_command)


# Grab solution
def prepPipette(volume):
    gcode_command = f"MANUAL_STEPPER STEPPER=lock_stepper SPEED=20 MOVE={volume.prep}"
    send_gcode(gcode_command)


def dispense(volume):
    gcode_command = f"MANUAL_STEPPER STEPPER=lock_stepper SPEED=20 MOVE={volume.dispense}"
    send_gcode(gcode_command)


def sampleTest(source, dest):
    wellCoords = generate_well_plate_coordinates(dest)

    # Move to vials
    srcVial = vial2
    srcVial.speed = 3700
    move_to(srcVial)
    
    for i in range(len(wellCoords)):

        if (source.z == wellCoords[i].z):
            source.speed = 6300
        else:
            source.speed = 2000

        # Move to vials
        move_to(source)

        prepPipette(v100)

        # Dip down
        source.speed = 800
        source.z += 28
        move_to(source)

        aspirate(v100)

        time.sleep(1)

        # Go up
        source.z -= 28
        move_to(source)

        # Move to well
        move_to(wellCoords[i])
        
        wellCoords[i].speed = 800
        # Dip down
        wellCoords[i].z += 28
        move_to(wellCoords[i])

        dispense(v100)

        time.sleep(1.5)
        
        # Raise back up
        wellCoords[i].z -= 28
        move_to(wellCoords[i])

        aspirate(v100)


def tipTest(source, dest):
    wellCoords = generate_well_plate_coordinates(dest)
    tipLoc = generate_well_plate_coordinates(source)
    tip_s6.speed = 3700
    move_to(tip_s6)
    
    for i in range(len(wellCoords)):

        if (tipLoc[i].z == wellCoords[i].z):
            tipLoc[i].speed = 6300
        else:
            tipLoc[i].speed = 2000

        # Move to tips
        move_to(tipLoc[i])

        # Dip down
        tipLoc[i].speed = 800
        tipLoc[i].z += 54
        move_to(tipLoc[i])

        # Go up
        tipLoc[i].z -= 54
        move_to(tipLoc[i])

        time.sleep(1)

        # Move to well
        move_to(wellCoords[i])
        
        wellCoords[i].speed = 800

        # Dip down
        wellCoords[i].z += 15
        move_to(wellCoords[i])

        ejectTip()
        
        # Raise back up
        wellCoords[i].z -= 15
        move_to(wellCoords[i])
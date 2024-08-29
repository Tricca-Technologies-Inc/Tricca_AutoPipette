from coordinates import *
from movement import *
import time
from volumes import *
from pipettev2 import *

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
# Function to perform kit test with multiple vial holders
def kitTest(vial_coords, dest, pipette, tip_box, garbage_position, volumes):
    vial_coords = vial_coords[:50] ## PRIME KIT
    for coord, volumes in zip(vial_coords, volumes):
        try:
            # Attempt to pick up a tip
            PickupTip(tip_box)
        except:
            # If no more tips are available, reset the tip box and start from the beginning
            print("No more tips available, resetting tip box.")
            tip_box.reset()
            PickupTip(tip_box)  # Pick up the first tip after resetting

        transferLiq(coord, dest, volumes)

        # Eject the tip to the garbage position
        garbage_position.speed = DEFAULT_SPEED
        move_to(garbage_position)
        pipette.eject_tip()

def transferLiq(source, dest, volume):
    for _ in range(volume.multiplier):
        # Grab solution
        source.speed = DEFAULT_SPEED
        move_to(source)
        pipette.move_stepper(volume.prep)
        dipZ(source, VIAL_DIP_DISTANCE)
        pipette.home_stepper(speed=30)
        returnZ(source, VIAL_DIP_DISTANCE)

        # Dispense
        dest.speed = DEFAULT_SPEED
        move_to(dest)
        dipZ(dest, TILTV_DIP)
        pipette.move_stepper(volume.dispense)
        returnZ(dest,TILTV_DIP)
        pipette.home_stepper(speed=30)

def tip_test(source, dest, pipette):
    well_coords = dest.get_coordinates()
    tip_loc = source.get_coordinates()
    tip_s6.speed = 3700
    move_to(tip_s6)
    
    for i in range(len(well_coords)):
        if tip_loc[i].z == well_coords[i].z:
            tip_loc[i].speed = 7200
        else:
            tip_loc[i].speed = 2000

        move_to(tip_loc[i])

        tip_loc[i].speed = 1100
        tip_loc[i].z += TIP_DIP_DISTANCE
        move_to(tip_loc[i])

        tip_loc[i].z -= TIP_DIP_DISTANCE
        move_to(tip_loc[i])

        well_coords[i].speed = 7200
        time.sleep(1)
        move_to(well_coords[i])

        well_coords[i].speed = 1100
        well_coords[i].z += WELL_DIP_DISTANCE
        move_to(well_coords[i])

        pipette.eject_tip()

        well_coords[i].z -= WELL_DIP_DISTANCE
        move_to(well_coords[i])

def volumeTest(source, dest):
    # Move to source vial
    move_to(source)

    # Prep and aspirate
    pipette.move_stepper(v100.prep)
    source.speed = 1000
    source.z += 40
    move_to(source)
    pipette.move_stepper(v100.aspirate)

    # Return to original z position
    source.z -= 40
    time.sleep(2)
    move_to(source)

    # Move to destination vial
    dest.speed = DEFAULT_SPEED
    move_to(dest)

    # Dispense
    dest.speed = 1000
    dest.z += 30
    move_to(dest)
    pipette.move_stepper(v100.dispense)
    time.sleep(2)

    # Return to original z position
    dest.z -= 30
    move_to(dest)

    # Home the pipette motor
    pipette.home_stepper(speed=30)

    move_to(vial2)

def speedTest():
    gcode_command = f"G1 X{10} Y{10} Z{0} F{6500}"
    send_gcode(gcode_command)
    gcode_command = f"G1 X{300} Y{300} Z{0} F{6500}"
    send_gcode(gcode_command)
    gcode_command = f"G1 X{10} Y{300} Z{0} F{6500}"
    send_gcode(gcode_command)
    gcode_command = f"G1 X{300} Y{10} Z{0} F{6500}"
    send_gcode(gcode_command)

    gcode_command = f"G1 X{10} Y{10} Z{0} F{6500}"
    send_gcode(gcode_command)
    gcode_command = f"G1 X{150} Y{150} Z{0} F{6500}"
    send_gcode(gcode_command)
    gcode_command = f"G1 X{10} Y{150} Z{0} F{6500}"
    send_gcode(gcode_command)
    gcode_command = f"G1 X{300} Y{300} Z{0} F{6500}"
    send_gcode(gcode_command)


volumes_PRIME = [
    v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v25, v50, v50, v100,
    v50, v100, v400, v50, v250, v200, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v200, v50,
    v50, v100, v50, v100, v25, v160, v400, v400, v50, v50, v160
]
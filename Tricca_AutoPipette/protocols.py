"""This file contains all of the functions to perform an assay."""
from Coordinate import Coordinate
from Coordinate import Location
import time
from volumes import *
from AutoPipette import AutoPipette

# Refactored sampleTest (Program for Sample Prep.)
def sample_test(source, dest, pipette):
    well_coords = dest.get_coordinates()

    srcVial = source
    srcVial.speed = 3700
    pipette.move_to(srcVial)

    for coord in well_coords:
        if srcVial.z == coord.z:
            srcVial.speed = 6500
        else:
            srcVial.speed = 2000

        pipette.move_to(srcVial)
        pipette.move_pipette_stepper(v100.prep)

        srcVial.speed = 700
        srcVial.z += 25
        pipette.move_to(srcVial)
        pipette.move_pipette_stepper(v100.aspirate)

        time.sleep(1)

        srcVial.z -= 25
        pipette.move_to(srcVial)

        coord.speed = 6500
        pipette.move_to(coord)

        coord.speed = 700
        coord.z += 28
        pipette.move_to(coord)
        pipette.move_pipette_stepper(v100.dispense)

        time.sleep(1.5)
        coord.z -= 28
        pipette.move_to(coord)

        pipette.move_pipette_stepper(v100.aspirate)

# (Program for Kit Manufacturing)
# Function to perform kit test with multiple vial holders
def kitTest(vial_coords, dest, pipette, tip_box, garbage_position, volumes):
    vial_coords = vial_coords[:50] ## PRIME KIT change length based on how many vials to use
    for coord, volumes in zip(vial_coords, volumes):
        try:
            # Attempt to pick up a tip
            pipette.pickupTip(tip_box)
        except:
            # If no more tips are available, reset the tip box and start from the beginning
            print("No more tips available, resetting tip box.")
            tip_box.reset()
            pipette.pickupTip(tip_box)  # Pick up the first tip after resetting

        transferLiq(coord, dest, volumes, pipette)

        # Eject the tip to the garbage position
        garbage_position.speed = AutoPipette.DEFAULT_SPEED
        pipette.move_to(garbage_position)
        pipette.eject_tip()

def transferLiq(source, dest, volume, pipette):
    for _ in range(volume.multiplier):
        # Move to source
        source.speed = AutoPipette.DEFAULT_SPEED
        pipette.move_to(source)
        pipette.move_pipette_stepper(volume.prep)

        # Dip, pick-up liquid, and return
        pipette.dip_z_down(source, AutoPipette.VIAL_DIP_DISTANCE)
        pipette.home_pipette_stepper(speed=30)
        pipette.dip_z_return(source, AutoPipette.VIAL_DIP_DISTANCE)

        # Dispense
        dest.speed = AutoPipette.DEFAULT_SPEED
        pipette.move_to(dest)
        pipette.dip_z_down(dest, AutoPipette.TILTV_DIP)
        pipette.move_pipette_stepper(volume.dispense)
        pipette.dip_z_return(dest, AutoPipette.TILTV_DIP)
        pipette.home_pipette_stepper(speed=30)

def tip_test(source, dest, pipette):
    well_coords = dest.get_coordinates()
    tip_loc = source.get_coordinates()
    Location.tip_s6.speed = 3700
    pipette.move_to(Location.tip_s6)
    
    for i in range(len(well_coords)):
        if tip_loc[i].z == well_coords[i].z:
            tip_loc[i].speed = 7200
        else:
            tip_loc[i].speed = 2000

        pipette.move_to(tip_loc[i])

        tip_loc[i].speed = 1100
        tip_loc[i].z += AutoPipette.TIP_DIP_DISTANCE
        pipette.move_to(tip_loc[i])

        tip_loc[i].z -= AutoPipette.TIP_DIP_DISTANCE
        pipette.move_to(tip_loc[i])

        well_coords[i].speed = 7200
        time.sleep(1)
        pipette.move_to(well_coords[i])

        well_coords[i].speed = 1100
        well_coords[i].z += AutoPipette.WELL_DIP_DISTANCE
        pipette.move_to(well_coords[i])

        pipette.eject_tip()

        well_coords[i].z -= AutoPipette.WELL_DIP_DISTANCE
        pipette.move_to(well_coords[i])

def volumeTest(source, dest, pipette):
    # Move to source vial
    pipette.move_to(source)

    # Prep and aspirate
    pipette.move_stepper(v100.prep)
    source.speed = 1000
    source.z += 40
    pipette.move_to(source)
    pipette.move_stepper(v100.aspirate)

    # Return to original z position
    source.z -= 40
    time.sleep(2)
    pipette.move_to(source)

    # Move to destination vial
    dest.speed = AutoPipette.DEFAULT_SPEED
    pipette.move_to(dest)

    # Dispense
    dest.speed = 1000
    dest.z += 30
    pipette.move_to(dest)
    pipette.move_stepper(v100.dispense)
    time.sleep(2)

    # Return to original z position
    dest.z -= 30
    pipette.move_to(dest)

    # Home the pipette motor
    pipette.home_pipette_stepper(speed=30)

    pipette.move_to(vial2)

def speedTest(pipette):
    gcode_command = f"G1 X{10} Y{10} Z{0} F{6500}"
    pipette.send_gcode(gcode_command)
    gcode_command = f"G1 X{300} Y{300} Z{0} F{6500}"
    pipette.send_gcode(gcode_command)
    gcode_command = f"G1 X{10} Y{300} Z{0} F{6500}"
    pipette.send_gcode(gcode_command)
    gcode_command = f"G1 X{300} Y{10} Z{0} F{6500}"
    pipette.send_gcode(gcode_command)

    gcode_command = f"G1 X{10} Y{10} Z{0} F{6500}"
    pipette.send_gcode(gcode_command)
    gcode_command = f"G1 X{150} Y{150} Z{0} F{6500}"
    pipette.send_gcode(gcode_command)
    gcode_command = f"G1 X{10} Y{150} Z{0} F{6500}"
    pipette.send_gcode(gcode_command)
    gcode_command = f"G1 X{300} Y{300} Z{0} F{6500}"
    pipette.send_gcode(gcode_command)


volumes_PRIME = [
    v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v25, v50, v50, v100,
    v50, v100, v400, v50, v250, v200, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v50, v200, v50,
    v50, v100, v50, v100, v25, v160, v400, v400, v50, v50, v160
]

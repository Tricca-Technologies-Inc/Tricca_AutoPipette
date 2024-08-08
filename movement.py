import requests
#F4850 is max when xyz move
#F980 is max when only z moves
#F6600 is max when only x/y moves
# Moonraker API endpoint

MOONRAKER_URL = "http://192.168.39.14:7125/printer/gcode/script"

def send_gcode(command):
    response = requests.post(MOONRAKER_URL, json={"script": command})
    if response.status_code == 200:
        print("Command sent successfully")
    else:
        print(f"Failed to send command: {response.status_code}, {response.text}")

def move_to(coordinate):
    gcode_command = f"G1 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} F{coordinate.speed}"
    send_gcode(gcode_command)

def moveX_to(coordinate):
    gcode_command = f"G1 X{coordinate.x} F{coordinate.speed}"
    send_gcode(gcode_command)

def homeX():
    gcode_command = f"G28 X"
    send_gcode(gcode_command)

def kit_manufacturing():
    gcode_command = "GCODE_COMMAND_FOR_KIT_MANUFACTURING"
    send_gcode(gcode_command)

def sample_prep():
    gcode_command = "GCODE_COMMAND_FOR_SAMPLE_PREP"
    send_gcode(gcode_command)

def stop_operations():
    gcode_command = "GCODE_COMMAND_FOR_STOPPING"
    send_gcode(gcode_command)
import requests

# Moonraker API endpoint
MOONRAKER_URL = "http://192.168.13.14:7125/printer/gcode/script"

def send_gcode(command):
    response = requests.post(MOONRAKER_URL, json={"script": command})
    if response.status_code == 200:
        print("Command sent successfully")
    else:
        print(f"Failed to send command: {response.status_code}, {response.text}")

class Coordinate:
    def __init__(self, x=0, y=0, z=0, speed=1500):
        self.x = x
        self.y = y
        self.z = z
        self.speed = speed

    def __repr__(self):
        return f"Coordinate(x={self.x}, y={self.y}, z={self.z}, speed={self.speed})"

def move_to(coordinate):
    gcode_command = f"G1 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} F{coordinate.speed}"
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
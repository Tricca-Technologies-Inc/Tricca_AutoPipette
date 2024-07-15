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
    def __init__(self, x, y=0, z=0, speed=1500):
        self.x = x
        self.y = y
        self.z = z
        self.speed = speed

def move_to(coordinate):
    # Construct G-code command with speed (feed rate) parameter
    gcode_command = f"G0 X{coordinate.x} Y{coordinate.y} Z{coordinate.z} F{coordinate.speed}"
    
    # Send the G-code command
    send_gcode(gcode_command)
import requests
#F4850 is max when xyz move
#F980 is max when only z moves
#F6600 is max when only x/y moves
# Moonraker API endpoint

# Always make sure to change when web app IP is not working
# Use Angry IP checker to find correct IP address
MOONRAKER_URL = "http://192.168.73.14:7125/printer/gcode/script"

SPEED_FACTOR = 700
VELOCITY = 1500
ACCEL = 5500

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

def initSpeed():
    send_gcode(f"M220 S{SPEED_FACTOR}")
    send_gcode(f"SET_VELOCITY_LIMIT VELOCITY={VELOCITY}")
    send_gcode(f"SET_VELOCITY_LIMIT ACCEL={ACCEL}")

def homeAxes():
    send_gcode(f"G28 Z") # Home Z first
    send_gcode(f"G28 X Y")
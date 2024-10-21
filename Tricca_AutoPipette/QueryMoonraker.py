import requests
import json
import random

class QueryMoonraker:
    def __init__(self, moonraker_url):
        self.moonraker_url = moonraker_url
    
    def get_dummy_printer_coordinates(self):
        data = {
            'result': {
                'eventtime': 1548.978351988, 
                'status': {
                    'toolhead': {
                        'homed_axes': '', 
                        'axis_minimum': [0.0, 0.0, -5.0, 0.0], 
                        'axis_maximum': [340.0, 358.0, 130.0, 0.0], 
                        'print_time': 1258.4628876274999, 'stalls': 0, 'estimated_print_time': 1551.4001792875, 
                        'extruder': '', 
                        'position': [random.randint(1, 100), random.randint(1, 100), random.randint(1, 100), random.randint(1, 100)], 
                        'max_velocity': 4000.0, 
                        'max_accel': 4000.0, 'minimum_cruise_ratio': 0.5, 'square_corner_velocity': 5.0
                    }
                }
            }
        }

        position = data.get('result', {}).get('status', {}).get('toolhead', {}).get('position', [])

        coordinates = {
            'X': position[0],  # X coordinate
            'Y': position[1],  # Y coordinate
            'Z': position[2],   # Z coordinate
            'E': position[3]   # E coordinate
        }

        return coordinates

        

    def get_printer_coordinates(self):
        gcode_command = {"script": "M114"} # The G-code to request printer coordinates
    
        try:
            # Send a POST request to the Moonraker API
            response = requests.get(self.moonraker_url, json=gcode_command)
            if response.status_code == 200: # Check if the request was successful
                data = response.json() # Parse the response JSON
                print(data)
                print(response.status_code)
                print(response)
               
                # Extract position from the response
                position = data.get('result', {}).get('status', {}).get('toolhead', {}).get('position', [])
                
                # If position is found, store the X, Y, and Z coordinates
                if position:
                    coordinates = {
                        'X': position[0],  # X coordinate
                        'Y': position[1],  # Y coordinate
                        'Z': position[2],   # Z coordinate
                        'E': position[3]   # E coordinate
                    }
                    return coordinates

                else:
                    print("No position data found in the response")
            else:
                print(f"Error: Received status code {response.status_code}")

        except Exception as e:
            print(f"An error occurred: {e}")

        return None

      

# Example usage
if __name__ == "__main__":
    query_object = QueryMoonraker("http://192.168.247.14:7125/printer/objects/query?toolhead")

    # coordinates = query_object.get_printer_coordinates()
    coordinates = query_object.get_dummy_printer_coordinates()
    print(coordinates)

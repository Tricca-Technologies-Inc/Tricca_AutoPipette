import requests
import json

class QueryMoonraker:
    def __init__(self, moonraker_url):
        self.moonraker_url = moonraker_url

    def get_printer_coordinates(self):
        gcode_command = {"script": "M114"} # The G-code to request printer coordinates
    
        try:
            # Send a POST request to the Moonraker API
            response = requests.post(self.moonraker_url, json=gcode_command)
            if response.status_code == 200: # Check if the request was successful
                data = response.json() # Parse the response JSON

                # print(data)
                # Example Data
                # data = {
                #     result: 'X:100.0 Y:200.0 Z:150.0'
                # }

                result = data.get('result', '')
                if result: # Coordinates are returned in the result, so we need to parse it
                    coordinates = {}
                    raw_coordinate_list = result.split() #['X:100.0',  'Y:200.0', 'Z:150.0']
                    for item in raw_coordinate_list: 
                        if item[0] in ['X', 'Y', 'Z']:
                            temp = item.split(':') # ['X', '100.0']
                            coordinates[temp[0]] = float(temp[1])
                            return coordinate
                else:
                    print("No coordinates found in the response")
            else:
                print(f"Error: Received status code {response.status_code}")

        except Exception as e:
            print(f"An error occurred: {e}")

        return None

# Example usage
if __name__ == "__main__":
    query_object = QueryMoonraker("http://0.0.0.0:7125/printer/gcode/script")
    coordinates = query_object.get_printer_coordinates()
    print(coordinates)
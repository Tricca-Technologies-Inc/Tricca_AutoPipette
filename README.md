# Tricca AutoPipette

Tricca AutoPipette is an automated liquid handling system (ALHS) that uses the Voron 3D printer platform. The software system controls the pipette as well as handles the creation and execution of protocols for assays.

## Table of Contents

- [Files and Structure](#files-and-structure)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [Contributing](#contributing)
- [License](#license)

## Files and Structure

- **tricca_autopipette.py**  
  Main command-line entry point. Accepts IP address of the Manta board and optionally a `--conf` YAML file to load custom configuration. Example usage:

  ```bash
  python tricca_autopipette.py
  ```

  
  This script contains `do_` functions that execute pipetting tasks via HTTP POST requests to the Moonraker API:

  - `do_home` – Home motors (`x`, `y`, `z`, `pipette`, `axis`, `servo`, or `all`).
  - `do_set` – Set a variable, like `SPEED_FACTOR`, `VELOCITY_MAX`, or `ACCEL_MAX`.
  - `do_coor` – Define a named coordinate with X, Y, Z values.
  - `do_plate` – Assign a location to a plate type with specified rows and columns.
  - `do_pipette` – Move a volume of liquid between source and destination coordinates.
  - `do_move` – Move to an absolute X, Y, Z coordinate.
  - `do_move_loc` – Move to a predefined named location.
  - `do_move_rel` – Move relative to the current coordinate.
  - `do_next_tip` – Pick up the next available tip from a tip box.
  - `do_eject_tip` – Eject the currently held pipette tip.
  - `do_print` – Simple debug print command.
  - `do_run` – Run a protocol file from path.
  - `do_stop` – Send an emergency stop command.
  - `do_pause` – Pause a currently running protocol.
  - `do_resume` – Resume a paused protocol.
  - `do_cancel` – Cancel a running protocol.
  - `do_request` – Placeholder for manual HTTP requests.
  - `do_start_alerts` – Start the alerts system background task.
  - `do_stop_alerts` – Stop the alerts background task.
  - `do_save` – Save the current configuration to file.
  - `do_reset_plate` – Reset a plate's current position to 0.
  - `do_reset_plates` – Reset all plates to their starting positions.
  - `do_printer` – Print a test message and send a queued alert.
  - `do_vol_to_steps` – Convert volume to motor steps.
  - `do_break` – Pause script execution and wait for user input.
  - `do_webcam` – Open the Klipper webcam stream in a browser window. 

- **coordinates.py**  
  Defines the coordinate system and functions for generating well plate coordinates.

- **movement.py**  
  Contains functions for moving the machine to specific coordinates.

- **pipettev2.py**  
  An alternative or updated version of the `pipette.py` module with additional or modified functionality.

- **printer.cfg**  
  The configuration file for Klipper firmware, defining the hardware setup and motor configurations.

- **volumes.py**  
  Contains definitions for solution volumes used in pipetting protocols.

## Configuration
YAML-based configuration files that define protocol setup, speeds,  layout, etc. Edit or create a config file under the conf folder and pass it using the --conf flag when running the CMD line interface.

## Dependencies
Ensure that Python 3.x is installed on your system. You will also need to install the necessary Python packages. You can do this by running:

## How to run the machine
- **1.) Connecting to the board.**  
  On Code FAQ#9
  
- **2.) Setting up the software**  
  Git pull the repo to a folder. Use VS code

- **3.) Getting Started**  
  Change the IP addresses (from step 1) on the current code set. Run app.py and open the web app to run protocols

- **4.) Operation**  
  First, click 'initialize pipette' on the web app to home all motors and set the right speeds.
  Then, set the speed to 100% first before executing any protocols. Click 'kit manufacturing' to run the test. Once the protocol is ran, you can set the speed up to 800%. Finally, wait for the protocol to finish. Have Mainsail open for emergency stop, just in case the machine/program fails.

- **5.) Notes**
  Calibrate the coordinates manually using mainsail before executing protocols to prevent any collisions/problems.
  
## How to Run

### 1. Connect to the Board

### 2. Set Up the Code
Clone this repository and open it in VS Code:

```bash
git clone https://github.com/Tricca-Technologies-Inc/Tricca_AutoPipette.git
```

### 3. Update the IP Address (Optional)
Edit `tricca_autopipette.py` to use the IP address of the Manta board, or pass it via command line.

### 4. Launch  
Run the application via command line:

```bash
python tricca_autopipette.py 192.168.1.X

## Usage Notes

## Contributing

Make sure code style and docstrings follow PEP8.

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html).

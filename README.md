# Tricca AutoPipette

Tricca AutoPipette is an automated liquid handling system (ALHS) that uses the Voron 3D printer platform. The system controls a pipette and executes custom lab protocols via command line interface.

## Table of Contents

- [Files and Structure](#files-and-structure)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [How to Run](#how-to-run)
- [Usage Notes](#usage-notes)
- [Contributing](#contributing)
- [License](#license)

---

## Files and Structure

- **tricca_autopipette.py**  
  Main command-line entry point. Accepts IP address of the Manta board and optionally a `--conf` YAML file to load custom configuration. Example usage:

  ```bash
  python tricca_autopipette.py 192.168.1.100
  ```

  
  This script contains `do_` functions that execute pipetting tasks via HTTP POST requests to the Moonraker API:

  - `do_home` – Home motors (`x`, `y`, `z`, `axis`, `pipette`, `servo`, or `all`).
  - `do_set` – Set a configuration variable, like `SPEED_FACTOR`, `VELOCITY_MAX`, or `ACCEL_MAX`.
  - `do_coor` – Define a named coordinate with X, Y, Z values.
  - `do_plate` – Assign a location to a plate type with specified rows and columns.
  - `do_pipette` – Move a volume of liquid between source and destination coordinates.
  - `do_move` – Move to an absolute X, Y, Z coordinate.
  - `do_move_loc` – Move to a predefined named location.
  - `do_move_rel` – Move relative to the current coordinate.
  - `do_next_tip` – Pick up the next available tip from a tip box.
  - `do_eject_tip` – Eject the currently held pipette tip.
  - `do_print` – Simple debug print command.
  - `do_run` – Run a protocol file from disk.
  - `do_stop` – Send an emergency stop command.
  - `do_pause` – Pause a currently running protocol.
  - `do_resume` – Resume a paused protocol.
  - `do_cancel` – Cancel a running protocol.
  - `do_request` – Placeholder for manual HTTP requests.
  - `do_start_alerts` – Start the alerts system background task.
  - `do_stop_alerts` – Stop the alerts background task.
  - `do_save` – Save the current configuration to file.
  - `do_reset_plate` – Reset a single plate's current position to 0.
  - `do_reset_plates` – Reset all plates to their starting positions.
  - `do_printer` – Print a test message and send a queued alert.
  - `do_vol_to_steps` – Convert a given volume to motor steps.
  - `do_break` – Pause script execution and wait for user input.
  - `do_webcam` – Open the Klipper webcam stream in a browser window.

- **coordinates.py**  
  Holds 'Coordinate' class used for pipette positioning

- **moonraker_requests.py**  
  Handles requests using moonraker

- **plates.py**  
  Holds classes for different types of plates (i.e. Tipboxes, Well plates, falcon tubes)

- **tap_cmd_parsers.py**  
  Holds the TAPCmdParsers data class used for TAP commands

- **tap_screen_printer.py**  
  Hold the TAPScreenPrinter Class

- **tap_web_utils.py**  
  Holds classes and methods for web based activity in the shell.
---

## Configuration

### `conf/config_name.conf`

YAML-based configuration files that define protocol setup, speeds,  layout, etc. Edit or create a config file under the conf folder and pass it using the --conf flag.


---

## Dependencies

Make sure Python 3.x is installed. Then, install the required packages using:

```bash
pip install -r requirements.txt
```

---

## How to Run

### 1. Connect to the Board  

### 2. Set Up the Code  
Clone this repository and open it in VS Code:

```bash
git clone https://github.com/your-org/tricca_autopipette.git  
cd Tricca_autopipette
```

### 3. Update the IP Address  
Edit `tricca_autopipette.py` to use the IP address of the Manta board, or pass it via command line.

### 4. Launch  
Run the application via command line:

```bash
python tricca_autopipette.py 192.168.1.X
```

---

## Usage Notes


---

## Contributing

Make sure code style and docstrings follow PEP8.

---

## License

open-source

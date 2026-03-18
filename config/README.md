# AutoPipette Configuration Files

This directory contains JSON configuration files for the Tricca AutoPipette system.

## Directory Structure
```
config/
├── system/
│   └── system.json          # Main system configuration (references other configs)
├── gantry/
│   └── gantry_default.json  # Gantry kinematics settings
├── pipettes/
│   ├── p100_vertical.json   # 100µL vertical pipette (TAP-Tyson specific)
│   └── default_p100.json    # Default 100µL pipette configuration
├── liquids/
│   ├── water.json           # Aqueous solutions
│   └── methanol.json        # Organic solvents
├── locations/
│   └── default_locations.json  # Plate and coordinate locations
└── plates/
    └── 96_well_standard.json   # 96-well plate template
```

## Configuration Files

### `system/system.json`
Main configuration file that ties together all components. References:
- Gantry settings (inline)
- Pipette model (by name: "p100_vertical")
- Liquid profiles (inline definitions)
- Network settings

### `pipettes/*.json`
Pipette model definitions including:
- Syringe kinematics (speeds, accelerations, calibration)
- Servo configuration (angles, timing)
- Volume capacity and motor orientation

### `liquids/*.json`
Liquid-specific parameters that override pipette defaults:
- Physical properties (viscosity, density)
- Speed and timing adjustments
- Recommended techniques (prewet, air gap, blowout)
- Optional custom calibration curves

### `locations/default_locations.json`
User-defined locations including:
- Simple coordinates
- Plate positions (references plate definitions)
- Special plates (tipbox, waste container)

### `plates/*.json`
Reusable plate templates with:
- Dimensions and well layout
- Dipping strategies
- Physical parameters

## Usage

Load the system configuration in your Python code:
```python
from pathlib import Path
from autopipette import AutoPipette

# Load main configuration
pipette = AutoPipette(Path("config/system/system.json"))
pipette.init_pipette()

# Switch between liquids
pipette.switch_liquid("water")
pipette.pipette(100, "start_vials_1ace", "end_vial")

pipette.switch_liquid("methanol")
pipette.pipette(50, "start_vials_2bd", "end_vial")
```

## Customization

1. **Create a new pipette**: Copy `default_p100.json` and adjust calibration
2. **Add a liquid**: Copy `water.json` and modify parameters
3. **Define locations**: Edit `default_locations.json` with your setup
4. **Update system**: Reference new configs in `system.json`

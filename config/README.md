# AutoPipette Configuration Files

This directory contains JSON configuration files for the Tricca AutoPipette system.

## Directory Structure
```
config/
├── system/
│   └── system.json          # Main system configuration (references other configs)
├── gantry/
│   └── default_gantry.json  # Gantry kinematics settings
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
- Locations, i.e. the deck layout (see "Per-protocol configs" below)
- Network settings

Note the file loaded by default is `default_system.json`
(`DefaultFilenames.CONFIG_SYSTEM`); `system.json` is only used when passed
explicitly via `tapd --config system.json`.

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

Point the daemon at a system config; everything else is resolved from it:

```bash
tapd --config assay_a.json      # resolved under config/system/
```

## Per-protocol configs

A protocol usually differs from the machine's standing config only in its deck
layout. `extends` lets it inherit the rest, so gantry, network, and pipette
settings live in one place instead of being copied per protocol and drifting:

```json
{
  "extends": "default_system.json",
  "locations": [
    "standard_deck.json",
    {
      "plates": [
        {
          "name": "tipbox_a",
          "plate_file": "tipbox_96.json",
          "x": 10, "y": 20, "z": 5,
          "order": "column_from_bottom_right",
          "tips": { "consumed": ["A1:C12"] }
        }
      ]
    }
  ]
}
```

`extends` merges shallowly, per top-level key: a child's `gantry` block
replaces the parent's wholesale rather than merging field by field. Cycles and
chains deeper than 10 are rejected.

### The `locations` section

Accepts three shapes, all meaning "an ordered list of sources":

```json
"locations": "deck_a.json"                        // one file
"locations": { "coordinates": [...], "plates": [] }  // inline
"locations": ["standard_deck.json", { "plates": [] }]  // both, in order
```

Sources are applied in order and **later ones win** on a name collision, so a
protocol can pull in a shared deck file and override one plate inline. A
collision is logged at WARNING naming both source files.

If a system config declares no `locations`, `default_locations.json` is loaded
instead. `tapd --config-locations <file>` layers a file on top of whatever the
system config produced, rather than replacing it.

### Plate options

Beyond geometry, each plate entry accepts:

| Key | Meaning |
|---|---|
| `order` | Traversal order: a preset name or an inline descriptor. Default `row_major`, which is the historical A1→A12→B1 behavior. |
| `mask` | `{"include": [...], "exclude": [...]}` of well ranges, restricting the plate to a sub-region. |
| `on_exhaust` | `"wrap"` (default) or `"error"`, once every eligible well has been visited. Tipboxes always use `"error"`. |
| `tips` | Tipboxes only: `{"consumed": ["A1:C12"]}` declares a partially-used box. |

Traversal presets: `row_major`, `column_major`, `column_from_bottom_right`,
`row_from_bottom_right`, `row_serpentine`, `column_serpentine`. Any combination
outside those can be spelled out inline:

```json
"order": { "major": "column", "col_dir": "right_left", "row_dir": "bottom_up" }
```

Well ranges use lab notation -- `A1`, `H12`, or a rectangular block `A1:D6`
(corners may be given in either order). Rows are `A`-`Z`, capping plates at 26
rows.

### Tipboxes

Multiple tipboxes stay independent objects, drawn from in the order they appear
in the config. Each tracks which of its positions still hold a tip, and running
out raises rather than silently reissuing a used tip. That per-position state
persists to Moonraker's database across daemon restarts, so after physically
reloading a box, tell the daemon:

```
tips                      # ASCII map of what the daemon believes
tips tipbox_a --db        # compare against the persisted state
reset_tips tipbox_a       # a fresh box was loaded
reset_tips_all
set_tips tipbox_a A1:C12  # declare exactly which positions are used
```

## Customization

1. **Create a new pipette**: Copy `default_p100.json` and adjust calibration
2. **Add a liquid**: Copy `water.json` and modify parameters
3. **Define locations**: Edit `default_locations.json` with your setup
4. **Update system**: Reference new configs in `system.json`
5. **Add a protocol**: Copy a system config, replace its body with
   `"extends"` + `"locations"`, and run `tapd --config <it>`

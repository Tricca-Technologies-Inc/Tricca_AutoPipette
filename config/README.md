# AutoPipette Configuration Files

This directory contains JSON configuration files for the Tricca AutoPipette system.

## Directory Structure
```
config/
├── system/
│   └── default_system.json  # Copy-from template only -- see "Shared repo vs.
│                             # local per-machine config" below. Never loaded live.
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

## Shared repo vs. local per-machine config

`config/` (this directory) is the **shared code repo** -- checked into git,
identical across every physical rig. Real per-machine data (a rig's actual
hostname, its deck layout, its own protocols) belongs instead in a **local
config root**: a second directory, outside this repo entirely, that the
operator manages as its own git repo by hand -- `tapd`/`tap` never shell out
to git for it. It defaults to `$XDG_CONFIG_HOME/tricca-autopipette` (falling
back to `~/.config/tricca-autopipette`), overridable via
`$AUTOPIPETTE_LOCAL_DIR`. It mirrors this directory's six categories directly
as children -- `$AUTOPIPETTE_LOCAL_DIR/{gantry,pipettes,liquids,locations,plates,protocols}/`
-- plus `system/`, which behaves differently (see below).

In practice, "its own git repo by hand" is usually one shared repo across all
rigs, `tricca-autopipette-local-config`, with **one branch per physical
machine** -- e.g. `murphy` -- forked from a `main` that just holds the same
generic `default_*`/example files this directory ships, so a rig can
periodically `git merge main` to pick up shared template updates without
disturbing its own data. A machine's local config root is a clone of that
repo, permanently checked out on its own branch. This isn't required (a rig
can just as well be its own standalone repo), but it's the setup in use.

Two merge mechanisms, by category shape:

- **`gantry/`, `pipettes/`, `liquids/`, `locations/`, `plates/`, `protocols/`**
  -- "the more entries the merrier": the shared and local directories are
  unioned. The same filename in both roots means the local file wins
  (whole-file replace, not a field-by-field merge); a filename that exists in
  only one root is included as-is. This is why `tapd --config-gantry
  <file>`/`load_liquid <file>`/etc. and a protocol's `locations` entries all
  resolve the same way regardless of which root the file actually lives in.
- **`system/`** -- a "pick exactly one active file" selector, not a union:
  100% local at load time. `config/system/default_system.json` in this
  shared repo is a **copy-from template only**, never consulted live once a
  local file exists -- see the next section.

This split is deliberately provisional for all six union categories except
`locations/`/`protocols/` -- real per-rig divergence in `gantry/`/`pipettes/`/
`plates/` is not yet well understood, and a future pass may cull those back
to shared-only. Don't read the current scope as a permanent shape.

### Runtime writes always land in the local root

`tap`'s `set_config <category> <file> <key.path> <value>` (RPC
`config.set_value`) edits one value in one file. If that file currently
exists only in this shared repo, it is first copied into the local root and
the copy is edited -- the shared file is never touched. The edit is made on
the file's raw JSON, so every other field, `extends`, and `plate_file`
reference is kept; a value that would leave the file unloadable is refused
and nothing is written. So is a *new* key the file's model doesn't define
(e.g. a misspelt `speed_aspirat`), for `system`/`gantry`/`pipettes`/`liquids`;
keys already in a file stay editable. High-risk pipette and gantry values
(speeds, accelerations, syringe volumes and travel, servo angles) are also
refused outside a fixed range (`HIGH_RISK_BOUNDS` in `core/config_writer.py`;
e.g. `max_travel_mm` 1-60). `tap`'s `settings`, and the kiosk's Settings
page, list every editable value with its range and the file an edit goes to.
`save_locations` likewise writes to the
local `locations/`, saving file-loaded entries back as they were loaded. Both
writes are atomic.

### Changes apply live, but not during a run

A `set_config` write takes effect in the running `tapd` at once, no restart:

- `system`/`gantry`/`pipettes`/`liquids`: the live config is rebuilt from the
  files (active system profile and its `extends` chain, plus whatever was
  loaded/unloaded at runtime). If the system profile's `locations` changed,
  the deck is rebuilt from it.
- `locations`: a file the deck holds entries from is re-read (entries it no
  longer lists are unloaded); a file that isn't loaded changes nothing live.
- `plates`: every loaded locations file is re-read.

Tip consumption and plate positions carry over a reload (a box whose shape
changed starts full). Network settings are the exception: the Moonraker
connection is not re-opened, so a `network` edit needs a `tapd` restart.

**Re-homing.** If the effective pipette or gantry changed, or the system
profile was switched, the machine counts as unhomed until the next `init`
or `home all`, whatever Moonraker says: the mechanical limits may have
changed.

**Runtime load/unload.** A file existing doesn't make it active:

- `unload_liquid <name>` / `load_liquid <file>`: every liquid file is loaded
  at startup; unload takes one out (not the active one) until loaded again.
- `load_pipette <file>`: makes a pipette profile the active pipette.
  There is always exactly one, so there is no unload.
- `switch_system <file>`: switches the active local system profile (e.g.
  `murphy_100.json` ↔ `murphy_1000.json`) and re-points `system/active.json`,
  as a fresh start with `--config` would. Runtime loads/unloads are dropped.
- `load_locations`/`unload_locations` work as before.

**Run-lock.** While a protocol run is active, `set_config`, `load_pipette`,
`unload_liquid` and `switch_system` are refused with `ok=False` and
`data={"reason": "run_active"}`, and `run.status`/`notify_run_status` carry
`config_locked: true`. None of these is a protocol-file command.
`load_liquid`/`load_locations`/`unload_locations` stay protocol commands and
are not locked.

## Configuration Files

### `system/` -- local-only, one active profile

Unlike every other category, `system/` config is **never** read from this
shared repo at runtime. `tapd` resolves it entirely against the local config
root's `system/` directory:

- **No local system config yet** -- `tapd` warns and auto-copies
  `config/system/default_system.json` (from *this* shared repo) into the
  local root as a starting point.
- **`tapd --init-local-config [NAME]`** does that copy on demand, as
  `NAME.json` (default `default_system`), and exits without starting the
  daemon -- refuses to overwrite an existing profile.
- **Exactly one local system config** -- loaded as-is.
- **More than one, no explicit `--config`, and a real terminal** -- prompts
  interactively, defaulting to whichever was last loaded (bare Enter
  confirms it).
- **More than one, no explicit `--config`, no terminal** (the normal systemd
  case) -- hard-fails at startup naming the available profiles, rather than
  guessing or hanging waiting on input that will never arrive. Give a
  multi-profile machine (e.g. a rig with interchangeable pipette models, see
  "Per-protocol configs") an explicit `--config` in its unit file.
- **`tapd --config <name>`** always resolves under the local `system/`
  directory (never this shared repo), bypassing the discovery/prompt flow
  entirely.

Whichever file is actually loaded, `system/active.json` in the local root is
(re)pointed at it as a plain symlink -- not a separate state file, so
`ls -l`/`ln -sf` on the physical rig is enough to inspect or set "what loads
next" by hand.

A loaded system config references:
- Gantry settings (inline)
- Pipette model (by name: "p100_vertical")
- Liquid profiles (inline definitions)
- Locations, i.e. the deck layout (see "Per-protocol configs" below)
- Network settings
- Trigger pins (`trigger_pins`, see below)

#### `trigger_pins` -- auxiliary hardware wiring

Maps each `trigger` channel alias to the Klipper `[output_pin <name>]` it
drives on *this* machine:

```json
"trigger_pins": { "air": "air_valve", "shake": "shaker" }
```

A channel is valid only if it's a key here, so `trigger lid on` fails on a
machine with no `lid` entry, and an empty map (the default) rejects every
channel. `trigger <channel> on|off` emits `M400` (wait for queued moves)
then `SET_PIN PIN=<pin> VALUE=1|0`. The pin itself must be declared in the
machine's Klipper `printer.cfg`. Nothing tracks the last commanded state or
turns a trigger off at the end of a protocol.

### `pipettes/*.json`
Pipette model definitions including:
- Syringe kinematics (speeds, accelerations, calibration as
  `calibration_volumes` µL / `calibration_mm` plunger travel)
- `syringe.max_travel_mm` (**required**): the syringe's manufacturer-stated
  plunger travel in mm. Homing drives up to twice this toward the endstop.
  A pipette file without it fails to load, naming the field.
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

Point the daemon at a local system config profile by name; everything else
is resolved from it:

```bash
tapd --config assay_a.json      # resolved under the local root's system/, not this directory
```

Omit `--config` and `tapd` figures out which profile to load itself -- see
"`system/` -- local-only, one active profile" above.

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
chains deeper than 10 are rejected. Both the child and every ancestor in the
chain resolve against the local config root's `system/` directory -- `system/`
being local-only (see above) applies to `extends` targets too.

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

Per-machine additions (a new pipette calibration, a liquid, a deck, a system
profile) belong in the **local config root**, not this shared repo -- see
"Shared repo vs. local per-machine config" above.

1. **Create a new pipette**: Copy `default_p100.json` into the local root's
   `pipettes/` and adjust calibration
2. **Add a liquid**: Copy `water.json` into the local root's `liquids/` and
   modify parameters
3. **Define locations**: Add a deck file under the local root's `locations/`
4. **Bootstrap a system profile**: `tapd --init-local-config <name>`, then
   edit the copy under the local root's `system/`
5. **Add a protocol**: Copy a system profile, replace its body with
   `"extends"` + `"locations"`, save it under the local root's `system/`, and
   run `tapd --config <it>`

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

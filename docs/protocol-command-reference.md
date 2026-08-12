<!--
  GENERATED FILE -- do not edit by hand.
  Produced by scripts/generate_protocol_reference.py from
  commands/tap_cmd_parsers.py's TAPCmdParsers. Regenerate with:

      python scripts/generate_protocol_reference.py

  tests/docs/test_protocol_reference_freshness.py fails CI if this file
  drifts from the generator's output.
-->

# Protocol command reference

Every command a `.pipette` protocol file may use, one per line, in the
order `tap`'s `run <path>`/the daemon's protocol replay dispatch them.
This is the generated syntax reference; for a task-oriented walkthrough of
writing a protocol file, see
[`protocol-authoring.md`](protocol-authoring.md).

### `init`

```
Usage: init

Initialise the pipette: set the coordinate system and speed, then home every motor. Exempt from the homed-safety interlock -- this is what performs homing.
```

### `home`

```
Usage: home [-h] motors

Home motors on the pipette.

Positional Arguments:
  motors      Motors to home: x, y, z, pipette, axis, all, servo

Options:
  -h, --help  show this help message and exit
```

### `move`

```
Usage: move [-h] x y z

Move to absolute XYZ coordinates.

Positional Arguments:
  x           X-coordinate in mm
  y           Y-coordinate in mm
  z           Z-coordinate in mm

Options:
  -h, --help  show this help message and exit
```

### `move_loc`

```
Usage: move_loc [-h] [--row ROW] [--col COL] name_loc

Move to a named location.

Positional Arguments:
  name_loc    Location name

Options:
  -h, --help  show this help message and exit
  --row ROW   Row index (for plate locations)
  --col COL   Column index (for plate locations)
```

### `move_rel`

```
Usage: move_rel [-h] [--x X] [--y Y] [--z Z]

Move relative to the current position.

Options:
  -h, --help  show this help message and exit
  --x X       X-axis offset in mm (default: 0)
  --y Y       Y-axis offset in mm (default: 0)
  --z Z       Z-axis offset in mm (default: 0)
```

### `aspirate`

```
Usage: aspirate [-h] [--src_row SRC_ROW] [--src_col SRC_COL]
                [--pre_air_gap PRE_AIR_GAP_UL]
                [--post_air_gap POST_AIR_GAP_UL] [--prewet PREWET_CYCLES]
                [--prewet_vol PREWET_VOL_UL]
                vol_ul source

Aspirate liquid from a source location.

Positional Arguments:
  vol_ul                Volume to aspirate in microliters
  source                Source location name

Options:
  -h, --help            show this help message and exit
  --src_row SRC_ROW     Source row index (for plate locations)
  --src_col SRC_COL     Source column index (for plate locations)
  --pre_air_gap PRE_AIR_GAP_UL
                        Air drawn before the liquid in μL (default: active
                        liquid profile)
  --post_air_gap POST_AIR_GAP_UL
                        Air drawn after the liquid in μL (default: active
                        liquid profile)
  --prewet PREWET_CYCLES
                        Prewet cycles before aspirating (default: active
                        liquid profile)
  --prewet_vol PREWET_VOL_UL
                        Volume per prewet cycle in μL (default: active liquid
                        profile)
```

### `dispense`

```
Usage: dispense [-h] [--volume VOLUME] [--dest_row DEST_ROW]
                [--dest_col DEST_COL] [--wiggle]
                dest

Dispense liquid to a destination location.

Positional Arguments:
  dest                  Destination location name

Options:
  -h, --help            show this help message and exit
  --volume, -v VOLUME   Volume to dispense in μL (default: all remaining
                        liquid)
  --dest_row DEST_ROW   Destination row index (for plate locations)
  --dest_col DEST_COL   Destination column index (for plate locations)
  --wiggle              Wiggle tip during dispensing to dislodge residual
                        droplets
```

### `pipette`

```
Usage: pipette [-h] [--dispense_vol DISP_VOL_UL] [--src_row SRC_ROW]
               [--src_col SRC_COL] [--dest_row DEST_ROW] [--dest_col DEST_COL]
               [--tipbox TIPBOX_NAME] [--pre_air_gap PRE_AIR_GAP_UL]
               [--post_air_gap POST_AIR_GAP_UL] [--prewet PREWET_CYCLES]
               [--prewet_vol PREWET_VOL_UL] [--wiggle] [--keep_tip]
               [--splits SPLITS] [--leftover {keep,waste}]
               vol_ul source dest

Transfer liquid from source to destination.

Positional Arguments:
  vol_ul                Volume to aspirate in microliters
  source                Source location name
  dest                  Destination location name

Options:
  -h, --help            show this help message and exit
  --dispense_vol, -d DISP_VOL_UL
                        Volume to dispense if different from the aspirate
                        volume
  --src_row SRC_ROW     Source row index (for plate locations)
  --src_col SRC_COL     Source column index (for plate locations)
  --dest_row DEST_ROW   Destination row index (for plate locations)
  --dest_col DEST_COL   Destination column index (for plate locations)
  --tipbox TIPBOX_NAME  Name of the tipbox to draw from (e.g. tipbox, tipbox2)
  --pre_air_gap PRE_AIR_GAP_UL
                        Air drawn before the liquid in μL (default: active
                        liquid profile)
  --post_air_gap POST_AIR_GAP_UL
                        Air drawn after the liquid in μL (default: active
                        liquid profile)
  --prewet PREWET_CYCLES
                        Prewet cycles before aspirating (default: active
                        liquid profile)
  --prewet_vol PREWET_VOL_UL
                        Volume per prewet cycle in μL (default: active liquid
                        profile)
  --wiggle              Wiggle tip during dispensing to dislodge residual
                        droplets
  --keep_tip            Keep tip attached after the operation (default: eject
                        tip)
  --splits SPLITS       Multi-dispense from one aspirate:
                        'DEST:VOL[@WELL];...', e.g.
                        'plate_a:12@A1;plate_b:8@C3'. Overrides the dest
                        argument.
  --leftover {keep,waste}
                        What to do with liquid left after --splits dispense.
                        Required when the splits do not consume the whole
                        aspirated volume.
```

### `next_tip`

```
Usage: next_tip

Pick up the next available tip from the configured tipbox(es), drawing in registration order.
```

### `eject_tip`

```
Usage: eject_tip

Eject the current tip in place -- unlike dispose_tip, this does not move to the waste container first.
```

### `dispose_tip`

```
Usage: dispose_tip

Move to the configured waste container and eject the current tip into it.
```

### `change_tip`

```
Usage: change_tip

Dispose the current tip (if any) and pick up a fresh one.
```

### `switch_liquid`

```
Usage: switch_liquid <liquid_name>

Switch the active liquid profile to an already-loaded one (see load_liquid). Affects the technique -- speeds, waits, prewet, air gaps -- used by subsequent aspirate/dispense/pipette commands.
```

### `load_liquid`

```
Usage: load_liquid <filename>

Load a new liquid profile from config/liquids/. Does not activate it -- follow with switch_liquid.
```

### `set`

```
Usage: set [-h] var value

Set a configuration variable to a new value.

Positional Arguments:
  var         Variable name: SPEED_FACTOR, VELOCITY_MAX, ACCEL_MAX
  value       Numeric value to assign

Options:
  -h, --help  show this help message and exit
```

### `coor`

```
Usage: coor [-h] name x y z

Define a named coordinate location.

Positional Arguments:
  name        Name for the location
  x           X-coordinate in mm
  y           Y-coordinate in mm
  z           Z-coordinate in mm

Options:
  -h, --help  show this help message and exit
```

### `plate`

```
Usage: plate [-h] [--dip_top DIP_TOP] [--dip_btm DIP_BTM]
             [--dip_func DIP_FUNC] [--well_diameter WELL_DIAMETER]
             [--spacing_row SPACING_ROW] [--spacing_col SPACING_COL]
             name plate_type num_row num_col x y z

Define a plate at a named location.

Positional Arguments:
  name                  Name for the plate location
  plate_type            Plate type: array, singleton, tipbox, waste_container
  num_row               Number of rows
  num_col               Number of columns
  x                     X-coordinate of first well in mm
  y                     Y-coordinate of first well in mm
  z                     Z-coordinate of first well in mm

Options:
  -h, --help            show this help message and exit
  --dip_top DIP_TOP     Z distance above well to begin dipping in mm (default:
                        0.0)
  --dip_btm DIP_BTM     Z distance for full-depth dip in mm (enables linear
                        strategy)
  --dip_func DIP_FUNC   Dipping strategy: simple, linear (default: simple)
  --well_diameter WELL_DIAMETER
                        Well diameter in mm (required for some dipping
                        strategies)
  --spacing_row SPACING_ROW
                        Row-to-row spacing in mm (default: 9.0)
  --spacing_col SPACING_COL
                        Column-to-column spacing in mm (default: 9.0)
```

### `reset_plate`

```
Usage: reset_plate [-h] name

Reset a plate's current position to the origin well.

Positional Arguments:
  name        Plate name

Options:
  -h, --help  show this help message and exit
```

### `reset_plates`

```
Usage: reset_plates

Reset every plate's traversal cursor to its first well.
```

### `del_loc`

```
Usage: del_loc [-h] name

Delete a named location or plate.

Positional Arguments:
  name        Name of the location to delete

Options:
  -h, --help  show this help message and exit
```

### `clear_locs`

```
Usage: clear_locs

Delete every location on the deck.
```

### `load_locations`

```
Usage: load_locations [-h] [--replace] filename

Load locations from a file. Adds to the deck by default so groups compose; use
--replace to clear it first.

Positional Arguments:
  filename    Locations file under config/locations/

Options:
  -h, --help  show this help message and exit
  --replace   Clear all existing locations before loading
```

### `unload_locations`

```
Usage: unload_locations [-h] name

Unload a single location from the deck by name.

Positional Arguments:
  name        Name of the location to unload

Options:
  -h, --help  show this help message and exit
```

### `save_locations`

```
Usage: save_locations [filename]

Save the current deck to config/locations/. filename defaults to 'custom_locations.json' when omitted on a protocol-file line.
```

### `reset_tips`

```
Usage: reset_tips [-h] name

Mark a tipbox as full, after physically reloading it.

Positional Arguments:
  name        Tipbox location name

Options:
  -h, --help  show this help message and exit
```

### `reset_tips_all`

```
Usage: reset_tips_all

Mark every configured tipbox as full.
```

### `set_tips`

```
Usage: set_tips [-h] [--available] name ranges [ranges ...]

Declare which tip positions of a box are consumed (or, with --available, which
still hold a tip). Replaces the box's current state rather than adding to it.

Positional Arguments:
  name         Tipbox location name
  ranges       Well IDs and/or ranges, e.g. A1 or A1:D6

Options:
  -h, --help   show this help message and exit
  --available  Treat the ranges as the positions that still hold a tip
```

### `tips`

```
Usage: tips [-h] [--db] [name]

Show tip availability, as a per-box map.

Positional Arguments:
  name        Tipbox to report on (default: all)

Options:
  -h, --help  show this help message and exit
  --db        Also show the state persisted in Moonraker's database
```

### `wait`

```
Usage: wait [-h] ms

Insert a timed pause into the G-code output.

Positional Arguments:
  ms          Duration to wait in milliseconds

Options:
  -h, --help  show this help message and exit
```

### `trigger`

```
Usage: trigger [-h] channel state

Control auxiliary triggers (air, shake, aux). Stub: validates the
channel/state and always reports 'not yet implemented' -- see issue #16.

Positional Arguments:
  channel     Trigger channel: air, shake, aux
  state       Desired state: on, off

Options:
  -h, --help  show this help message and exit
```

### `gcode_print`

```
Usage: gcode_print [-h] msg

Send a message to be displayed on the pipette screen.

Positional Arguments:
  msg         Message to display

Options:
  -h, --help  show this help message and exit
```

### `vol_to_steps`

```
Usage: vol_to_steps [-h] vol

Convert a volume in μL to motor steps.

Positional Arguments:
  vol         Volume in microliters

Options:
  -h, --help  show this help message and exit
```

### `break`

```
Usage: break

Pause the running protocol and wait for an operator (or remote client) to confirm continue/abort -- not a real AutoPipetteService method, handled specially by the protocol dispatch loop. Choosing abort raises ProtocolAbortedError and stops the rest of the file from running.
```

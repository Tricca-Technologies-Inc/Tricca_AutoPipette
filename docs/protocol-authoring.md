# Writing a protocol file

A `.pipette` file is plain text: one shell command per line, blank lines
allowed, `#` starts a comment. Its grammar is exactly `tap`'s own shell
grammar — anything you can type at the `tap` prompt, you can put in a
protocol file — so `run <path>` inside `tap` replays the file one line at a
time, buffers the resulting G-code, and uploads/executes it as a single job
on the pipette.

This is a task-oriented walkthrough. For the full syntax of every command a
protocol file can use, see
[`protocol-command-reference.md`](protocol-command-reference.md), generated
from the same parsers the shell itself uses.

## Before you start

- **The daemon must be running.** `tap` (and the kiosk) are thin clients of
  `tapd` and do nothing on their own — start `tapd` first.
- **Home the machine once.** Most commands (`move`, `pipette`,
  `aspirate`/`dispense`, tip handling, …) are gated behind a homed-safety
  interlock and raise `NotHomedError` if the machine hasn't been homed
  since the daemon started. A protocol file is *not* expected to home
  itself — do it once via `tap`'s `init` (or `home all`), or the kiosk's
  Home button, before running any protocol. `homed_axes` then stays true
  for the rest of the daemon's uptime, so you don't need to repeat it
  between runs.
- **Five runnable examples live under `protocols/examples/`.** They aren't
  reachable from the kiosk's protocol picker (its `/protocols` listing is
  non-recursive) — run them from `tap` with `run examples/<name>.pipette`.
  Every example below is one of them, referenced by name so you can open it
  alongside this guide.

## Your first protocol: homing and movement

[`examples/home_and_move.pipette`](../protocols/examples/home_and_move.pipette):

```
load_locations examples_deck.json --replace
init
move 50 50 30
move_loc example_source
```

- `load_locations <file> --replace` loads a deck layout from
  `config/locations/`. Every example starts with this line, loading the
  same small `examples_deck.json` deck (a tipbox, a waste container, and
  two small plates — see "The example deck" below), so each one is
  runnable standalone with zero setup. `--replace` wipes whatever else was
  loaded first; without it, `load_locations` is *additive* — a second file
  adds to the deck rather than replacing it, which is how a real protocol
  composes a deck from reusable groups.
- `init` sets the coordinate system and speed, then homes every motor —
  along with `home`, the only commands exempt from the homed-safety
  interlock, since they're what performs homing.
- `move x y z` is an absolute move in millimetres.
- `move_loc <name>` moves to a named location instead of bare coordinates.
  For a plate, omitting `--row`/`--col` moves to its *next* well in
  traversal order (the same cursor `pipette`/`aspirate` advance) rather
  than a fixed position.

## The example deck

`config/locations/examples_deck.json` defines four locations, deliberately
small:

| Name | Type | Layout |
|---|---|---|
| `example_tipbox` | `tipbox` | 2×5 = 10 tip positions |
| `example_waste` | `waste_container` | 1×1 |
| `example_source` | `array` | 1×4 wells |
| `example_dest` | `array` | 2×3 wells (`A1`…`B3`) |

Because `LocationManager.set_plate` always removes-then-recreates a plate
on load, running `load_locations examples_deck.json --replace` resets
every well/tip position to fresh — each example is deterministic and
repeatable on every run, not just the first.

## A real transfer: tip, pipette, dispose

[`examples/simple_transfer.pipette`](../protocols/examples/simple_transfer.pipette):

```
load_locations examples_deck.json --replace
next_tip
pipette 20 example_source example_dest --keep_tip
dispose_tip
```

`pipette <vol_ul> <source> <dest>` is the main command: it aspirates from
`source` and dispenses into `dest`, picking up a tip automatically if none
is attached and disposing of it into the waste container when it's done.
That means the minimal version of this protocol is really just

```
load_locations examples_deck.json --replace
pipette 20 example_source example_dest
```

The example spells out `next_tip`/`dispose_tip` explicitly (with
`--keep_tip` on the `pipette` line, so there's still a tip on when
`dispose_tip` runs) to make the three steps of a transfer visible. Reach
for the explicit form when you need to hold a tip across more than one
`aspirate`/`dispense` pair — see `splits.pipette` below — or want a
specific tipbox via `--tipbox`.

⚠️ **A deck needs a waste container.** `dispose_tip` (and `pipette`'s
default tip-disposal at the end of a transfer) raise `NoWasteContainerError`
if none is configured. Every example deck includes one
(`example_waste`) for exactly this reason.

## Multiple liquids

[`examples/multi_liquid.pipette`](../protocols/examples/multi_liquid.pipette):

```
load_locations examples_deck.json --replace
switch_liquid water
pipette 20 example_source example_dest
load_liquid methanol.json
switch_liquid methanol
pipette 15 example_source example_dest
```

The active liquid profile (`config/liquids/*.json`) drives technique —
aspirate/dispense speed, waits, prewet cycles, and the pre/post air gaps
that keep liquid from dripping or contaminating the syringe. `"water"` is
the built-in default and is already active when a protocol starts;
`load_liquid <file>` registers another profile from `config/liquids/`
without activating it, and `switch_liquid <name>` makes a registered
profile active. Technique resolves **explicit command flag > active
liquid profile > pipette default**, so e.g. `pipette 20 a b --pre_air_gap
5` overrides the active liquid's value for just that one call without
switching liquids.

## Multi-dispense: one aspirate, several destinations

[`examples/splits.pipette`](../protocols/examples/splits.pipette):

```
load_locations examples_deck.json --replace
pipette 25 example_source example_dest --splits 'example_dest:12@A1;example_dest:8@B2' --leftover waste
```

`--splits 'DEST:VOL[@WELL];...'` aspirates once and then dispenses to each
listed destination in turn — one syringe fill instead of one `pipette` call
per well, which saves a tip pickup and a trip to the source every time.
`@WELL` (e.g. `@A1`) is optional; omitting it lets the destination plate's
own traversal order pick the well, the same as a plain `pipette` without
`--dest_row`/`--dest_col`. Unlike a plain `pipette`, splits never chunk —
the whole aspirate volume must fit in the syringe at once, since a single
aspirate is the point.

Here the splits (12 + 8 = 20μL) don't consume the whole 25μL aspirated, so
`--leftover` is required to say what happens to the remaining 5μL:
`keep` retains it in the tip, `waste` verifies a waste container up front
and disposes of the leftover (and the tip) there. Omitting `--leftover`
when there's a remainder is an error rather than a silent default, since
"keep the leftover" and "throw it out" are both real, different choices a
protocol author has to make explicitly.

## Pausing for an operator

[`examples/breakpoint.pipette`](../protocols/examples/breakpoint.pipette):

```
load_locations examples_deck.json --replace
next_tip
move_loc example_source
break
pipette 20 example_source example_dest --keep_tip
dispose_tip
```

A bare `break` line pauses the run right there and waits for a human (or a
remote client) to say whether it should continue. In `tap`, a paused run
shows up via `continue`/`abort`; the kiosk surfaces the same pause as a
breakpoint prompt in the UI. Use it for a manual check partway through a
run — confirming a reagent is loaded, a plate is seated correctly, before
committing to the rest of the file. Answering "continue" resumes on the
next line exactly where it left off; answering "abort" raises
`ProtocolAbortedError` and stops the rest of the file from running (any
lines already executed are not undone).

## Things to know before you improvise

- **Tip disposal without a waste container is currently unsafe.** If a
  deck has no `waste_container` configured, a transfer that tries to
  dispose its tip aborts mid-run with a tip still attached — see issue #15
  in the project backlog. Always configure a waste container.
- **`trigger` is a stub.** It validates its channel/state and always
  reports "not yet implemented" — auxiliary hardware (air, shake, lid)
  can't be driven from a protocol yet (issue #16).
- **There's no blowout or touch-off support.** Neither exists in this
  codebase; don't write a protocol assuming either is available.
- **A recognized command that fails aborts the rest of the file** — an
  exception (a not-homed error, an out-of-tips error, a bad `--splits`
  spec, …) from a real command stops the run there. An *unrecognized*
  command name (a typo) is more forgiving: it's reported as a failure for
  that line but does not stop the rest of the file, matching older
  protocol files' behavior. Don't rely on that tolerance — fix typos
  rather than assume they'll be silently skipped forever.

## Next steps

- [`protocol-command-reference.md`](protocol-command-reference.md) — every
  protocol-file command, generated from the real argument parsers.
- [`config/README.md`](../config/README.md) — the full deck/locations JSON
  schema (traversal order, well masks, tip inventory) for building a real
  deck beyond the example one here.
- `CLAUDE.md` at the repo root — architecture, the daemon's dispatch model,
  and the pipetting-technique resolution rules in more depth.

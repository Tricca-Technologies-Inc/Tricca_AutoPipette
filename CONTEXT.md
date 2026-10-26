# Tricca AutoPipette

Controls a single automated liquid-handling rig (Voron/Klipper-based gantry,
syringe pump, tip-ejection servo) through one long-running daemon per rig. See
`CLAUDE.md` for the system as it currently is; this file is the glossary of
domain terms, kept separate from that implementation description.

## Language

**Rig**:
One physical pipetting machine — gantry, syringe pump, servo, controller
board — and everything mounted on its deck. A rig is served by exactly one
`tapd` process for its whole lifetime; see ADR-0001.
_Avoid_: machine (too generic — use "rig" for the physical unit, "host" for the
computer running `tapd`).

**Technical operator**:
A person who runs protocols and drives the machine via `tap`'s full command
surface — developers and lab staff comfortable with a shell, raw `move`,
WebSocket diagnostics, and protocol authoring. `tap` is built for this persona
and must always expose every capability the daemon offers, with no exceptions.
_Avoid_: power user.

**Non-technical operator**:
A person who runs canned `.pipette` protocols from the kiosk touchscreen
without shell access or hardware-level commands. The kiosk is built for this
persona: it only needs to be easy to use, not complete — the client-parity rule
(#28) requires every capability to be *reachable from `tap`*, not that the
kiosk renders it too.
_Avoid_: end user, layperson.

**Tip state**:
The occupancy/history of one tipbox position, tracked by `TipBoxManager`/`TipBox`.
Three distinct states, not two (`TipSlotState` in code):
- **available** — never used, safe for `next_tip` to hand out.
- **used** — a used tip returned to its origin position (rather than
  wasted) after a transfer (`--tip_end return`, or `waste` with no waste
  container). Excluded from `next_tip` permanently; reusable only
  via an explicit operator action (`set_tips --available`, a kiosk tap,
  `reset_tips`), never automatically, even for the same liquid. See #15.
- **empty** — the tip went to waste; the position is empty until the box is
  physically reloaded and reset (`reset_tips`/`reset_tips_all`).
_Avoid_: "contaminated"/"disposed" (earlier names for used/empty), and
describing this as a boolean "present/absent" — that conflates
"never used" with "used but returned," which is the exact gap #15 exists to
close.

### Axis expansion (planned)

These terms come from the axis-expansion plan (`docs/plans/axis-expansion/`;
the 2026-10-26 addendum wins over Rev L). The plate and P-axis code doesn't
exist yet (TAP-1…TAP-9); see ADR-0004.

**Plate / drawer**:
One of six belt-driven drawers that carry a plate in and out of the rig, each
an extra G-code axis owned by the Klipper config: `plate1`…`plate6` on axes
**U V W A B C**. Position 0 is fully **in** (at the home switch); positive
positions are **out**, up to `position_max` (350 mm). Commands address a
plate by name, with the axis letter accepted as an unambiguous alias (D41).
"Drawer" is the mechanism; "plate" names the axis.
_Avoid_: confusing this with a deck plate (a `Plate` from `config/plates/` at
a fixed XYZ location); a deck location may link to a drawer stop (D40).

**Stop**:
A named position along one drawer's travel (name → mm), defined in `tapd`'s
`config/locations/*.json` `drawers` block (D37/D38). Stops can be inside the
machine (pipetting positions) or outside it (operator load/unload, handoff to
other equipment, a covered spot against evaporation). Klipper knows no stop
names; moving to a stop sends its mm value.

**Pipetting stop**:
A stop listed in its drawer's `pipetting` subset: a position the tip may
descend over. At connect `tapd` refuses any pipetting stop that isn't within
`park_tol` of one of that plate's tip-safe positions (D39).

**Tip-safe position**:
A plate position, from Klipper's per-plate list in `_PLATE_CFG` (default
`[0, position_max]`), at which the tip may go below `z_safe`. Klipper refuses
to lower the tip below `z_safe` unless every plate is homed and within
`park_tol` of one of its own tip-safe positions (interlock rule I2, D39).
Klipper's list is the authority; `tapd`'s pipetting stops are checked against
it. The two ends of travel are simply **in** (0) and **out** (`position_max`).
_Avoid_: "parked". Rev L defined it as within `park_tol` of 0 or
`position_max`, which D39 made narrower than the rule I2 actually checks; the
term is dropped (D45). Say "at a tip-safe position", or "in"/"out" for the
ends.

**`z_safe`**:
The highest raw Z (closest to 0) at which the tip clears every plate and
drawer. The tip is safe when raw Z ≤ `z_safe`. Defaults to 0.0 (D18). Owned
by the Klipper config.

**P axis**:
The pipette plunger (`pipette_stepper`) bound as G-code axis **P**, homed
with `G28 P` and, in stage 2, moved with absolute `G1 P…`, alone or together
with X/Y/Z (R3a). Stays on the M8P for now; the EBB42 move is deferred (D35,
D36).

**Stage 1 / stage 2**:
The two configuration stages of the plan, switched by `variable_stage` in
`_PIPETTE_CFG` (D28). Stage 1: the new Klipper config works with today's
`tapd` plunger commands. Stage 2: `tapd` drives the plunger with `G28 P` and
absolute `G1 P` (TAP-6), and Klipper enforces plunger soft limits (−60…0).
_Avoid_: "phase" — phases are the plan's rollout steps (umbrella §7.1).

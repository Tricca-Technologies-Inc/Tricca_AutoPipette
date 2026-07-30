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
Three distinct states, not two:
- **available** — never used, safe for `next_tip` to hand out.
- **contaminated** — a used tip returned to its origin position (rather than
  wasted) after a transfer. Excluded from `next_tip` permanently; reusable only
  via an explicit operator action (`set_tips`) or an explicit function call,
  never automatically, even for the same liquid. See #15.
- **disposed** — ejected to waste; the position is empty until the box is
  physically reloaded and reset (`reset_tips`/`reset_tips_all`).
_Avoid_: describing this as a boolean "present/absent" — that conflates
"never used" with "used but returned," which is the exact gap #15 exists to
close.

# Klipper owns the plate and plunger axes; `tapd` discovers them, and the kiosk lags behind `tap` for a while

**Status:** accepted

The axis-expansion plan (`docs/plans/axis-expansion/`, Rev L plus the owner
addendum of 2026-10-26, which wins where they disagree) adds six plate drawers
as extra G-code axes **U V W A B C** and binds the pipette plunger to axis
**P**. This ADR records the decisions that shape how `tapd` relates to those
axes (issue #153, TAP-11).

**1. Klipper's config owns the axes; `tapd` discovers them (R16).** The plate
and plunger axis letters, travel limits (`position_min`/`position_max`) and
interlock parameters (`z_safe`, `park_tol`, the stage-2 plunger limits) are
defined once, in the Klipper config. `tapd` reads them from Moonraker at
connect and after a Klipper restart (`_PLATE_CFG`, `_PIPETTE_CFG`, and the
`configfile` settings, umbrella §6.3; TAP-2) and never keeps its own copy in
JSON, which would drift. A machine whose Klipper config has no plates or P
axis is "not configured": every plate/P command refuses, and existing behavior
is unchanged.

The one deliberate exception is **drawer stop names** (addendum D37–D39).
Klipper knows no stop names, only millimetres: `PLATE_MOVE POS=` takes a mm
value. The named stops of each drawer (`stops`: name → mm, plus the
`pipetting` subset) live in `tapd`'s `config/locations/*.json` under a
`drawers` block, per machine and loaded additively like the deck (D38;
TAP-12, #142). Klipper keeps its own per-plate **tip-safe list** in
`_PLATE_CFG` (default `[0, position_max]`), and at connect `tapd` refuses any
stop marked `pipetting` that isn't within `park_tol` of a position on that
list (D39). So the positions exist in both configs on purpose: Klipper's copy
is the safety authority, and `tapd` validates its copy against it.

**2. `tapd`'s checks are early refusals; Klipper's interlock is the
authority** (umbrella §6.2; WP4 TAP-3). `tapd` will gate plate and plunger
commands on live Moonraker state in the same style as `require_homed`, and
protocol validation will report likely refusals before upload (R17, TAP-8).
Those checks exist to give the operator a clear, early message. They are not
what keeps the tip off a moving drawer: Klipper's macros enforce the interlock
(I1–I6) on every motion path, whatever sent the G-code. A `tapd` check must
never be the only guard, and `tapd` must never send the commands that bypass
Klipper's interlock (`G1.1`, `G0.1`, `*_BASE`, `M84.1`, `M18.1`,
`_PLATE_INTERNAL`, or `SET_GCODE_VARIABLE` on the interlock's state macros).

**3. A time-boxed client-parity exception (D30).** The client-parity rule in
`CLAUDE.md` says neither client may be the only way to do something. For this
plan the owner scoped `tapd`'s work to the daemon, `tap` and protocol-file
commands; the kiosk gets no plate, stop or plunger UI yet (umbrella §1, D30,
R15; risk K-SW-04). So for a while these capabilities are reachable from `tap`
but not from the kiosk. This is a recorded exception, not a precedent. Its
limits:

- No kiosk-only or `tap`-only *logic*: every capability still lands as an
  `AutoPipetteService` method plus a `ControlRequests` builder, so the kiosk
  can later add routing-only wrappers over the same RPCs.
- The mechanical guards still pass: `ControlRequests` ↔ `tap`
  (`tests/cli/test_remote_shell_dispatch_completeness.py`) and kiosk route →
  RPC (`tests/kiosk/test_route_rpc_parity.py`). The gap is only that some RPCs
  have no kiosk route, which those tests don't check.
- It closes when TAP-10 (#152, kiosk support for plates, stops and plunger)
  lands. That issue then removes this exception, and this ADR gets amended to
  say so.

**4. Context: the EBB42 toolboard is deferred (addendum D35).** Rev L moved
the plunger and servo onto an EBB42 CAN board. The owner deferred that: the
plunger (`pipette_stepper`) and servo stay on the M8P on today's pins, with no
CAN bus. The P axis stays in scope anyway (D36), since the binding is done by
Klipper macros and doesn't depend on which board drives the stepper. None of
the decisions above depend on where the plunger is wired. If the EBB42 work
resumes, `tapd` should still only see an axis that Klipper's config describes.

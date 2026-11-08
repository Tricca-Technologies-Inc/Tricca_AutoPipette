# Phase 0 Survey — per Machine (plan Rev J)

| Field    | Value |
|----------|-------|
| Status   | Form; fill one per machine before any change |
| Revision | J |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Parent   | `00-umbrella-plan.md` (Phase 0) |
| Date     | 2026-10-20 |

---

## 1. Purpose & Scope

This survey records how each machine is **today**, before anything is rewired or reflashed. Later steps depend on it:

| Used by | What it needs from here |
|---|---|
| M-01, M-14 (pipette regression, same zero) | §5 plunger direction, distance per move, homing direction, servo positions |
| M-12 (gravimetric regression) | §5.4 baseline |
| VR-19 (tip ejection) | §5.5 baseline |
| `home_dir` (VR-21) | §5.2 |
| RB1 §3 (migration path A or B) | §3 config state |
| WP1 §4 and R7 (load ⛔: typical > 50% or peak > 70% of the PSU rating) | §6 |
| Cable BOM (VR-12) | §7 |

**Rules:**
- **Read-only.** No config edits, flashing or rewiring. The only motion is the tests in §5.
- **No tip and no liquid** on the pipette, except in §5.4 and §5.5.
- **Don't record MCU serial IDs or CAN UUIDs** on this form. They live only in the machine's `printer.cfg` and its backup (D34).
- **Where to file it:** save the completed survey with the machine record (`docs/machines/<host>.md`, RB1 §6), minus any IDs.

| Machine (hostname) | | Surveyor | | Date | |
|---|---|---|---|---|---|

## 2. Software Versions

| ✓ | Item | How | Value |
|---|---|---|---|
| ☐ | cb1-autopipette generation | `system-manager` generation / repo rev deployed | |
| ☐ | Klipper version | First lines of `klippy.log` | |
| ☐ | `printer-cfgs` rev the config was seeded from | Machine record, or the flake pin at first deploy | |
| ☐ | tapd (`Tricca_AutoPipette`) rev | Deployed pin | |
| ☐ | Current M8P firmware store path (for rollback) | `flash-manta` / `mantaFirmware` path | |

## 3. Config State (decides RB1 Path A or B)

| ✓ | Item | Value |
|---|---|---|
| ☐ | Backup taken now (RB1 §2); tarball name | |
| ☐ | `diff` of each `/var/lib/moonraker/config/*.cfg` against the seeded rev: any changes besides the bootstrap `[mcu]` block? | none / list: |
| ☐ | `SAVE_CONFIG` block at the end of `printer.cfg`? | yes / no |
| ☐ | **Path:** A (re-seed: no local edits and no `SAVE_CONFIG`) or B (hand merge) | A / B |

## 4. Hardware As Built (compare with umbrella §5.1)

**⛔ STOP** and tell the owner if any answer differs from the plan's expectation.

| ✓ | Item | Plan expects | Found |
|---|---|---|---|
| ☐ | Controller | Manta M8P **V2.0** + CB1 | |
| ☐ | Gantry motors / slots | X, Y, Z×4 on 6 slots; pipette on a 7th; 1 spare | |
| ☐ | Run currents in `tricca-autopipette.cfg` | X/Y 0.8 A; Z 0.65 A; pipette 0.65 A | |
| ☐ | Pipette endstop | `^!PB10` | |
| ☐ | Servo | MG996R, signal on PE9 | |
| ☐ | Servo supply | Separate 24 → 6 V converter. **Record its rated current** (needs ≥ 3 A to be reused, D29) | A |
| ☐ | PSU label | 24 V, ≥ 200 W | V / W |
| ☐ | E-stop | Cuts all machine power | |
| ☐ | Electronics location | Top of the machine | |
| ☐ | Space in the top bay for the Octopus V1.1, fuse block and wiring | Yes | |
| ☐ | Octopus label and chip marking | "Octopus V1.1", STM32F446 (an F429 needs a different firmware file: ⛔ tell the owner) | |
| ☐ | Octopus SD card: copy its current `FIRMWARE.CUR`/`firmware.bin` off (rollback) | Saved | |
| ☐ | Photos of the M8P wiring and the pipette head, before changes | Taken | |

## 5. Pipette Reference (the baseline for M-01, M-12, M-14)

Do these with **today's** firmware and tapd, through the Mainsail console or tapd as noted.

### 5.1 Homing

| ✓ | Step | Record |
|---|---|---|
| ☐ | Home the plunger with tapd as usual | Plunger moved **up / down** while seeking the switch |
| ☐ | Mark or photograph the plunger position after homing (switch released = zero) | Photo ref: |

### 5.2 Direction and distance (also measures `home_dir`)

1. After homing, send `MANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0`.
2. Send `MANUAL_STEPPER STEPPER=pipette_stepper MOVE=-1 SPEED=5`.
3. Watch the direction.
   - If the plunger moved **toward** the switch, stop. Record `home_dir = −1` and skip step 4.
   - If it moved **away** from the switch, `home_dir = +1` (the plan's assumption). Continue.
4. Send `MOVE=-10 SPEED=5`, measure the plunger travel with calipers, then send `MOVE=0`.

| ✓ | Result | Value |
|---|---|---|
| ☐ | `MOVE=-1` moved the plunger | toward / away from the switch |
| ☐ | `home_dir` | +1 / −1 |
| ☐ | Measured travel for 10 mm commanded | mm |

### 5.3 Servo positions

| ✓ | Item | Value |
|---|---|---|
| ☐ | Angles tapd commands for tip-eject and rest (from tapd's config, or `SET_SERVO` in its logs) | eject: ° rest: ° |
| ☐ | Photo of the horn at each angle | refs: |

### 5.4 Gravimetric baseline (for M-12)

Water at room temperature, the volume you use most, 10 dispenses onto a balance.

| ✓ | Item | Value |
|---|---|---|
| ☐ | Volume | µL |
| ☐ | Mean mass / standard deviation | mg / mg |
| ☐ | Balance model and readability | |

### 5.5 Tip ejection baseline (for VR-19)

| ✓ | Item | Value |
|---|---|---|
| ☐ | Ejections attempted / clean ejections | 20 / |
| ☐ | Tip type | |

## 6. Load Check (WP1 §4)

| ✓ | Item | Value |
|---|---|---|
| ☐ | Run currents match §4 of this form | yes / no |
| ☐ | PSU rating from its label (§4) | W |
| ☐ | Typical load (WP1 §4, recomputed if currents differ) ≤ 50% of rating; servo-stall peak < 70% (R7). **⛔ STOP** if not | W / W |

## 7. Cable Lengths (VR-12)

Measure along the real route, then add 20%.

| ✓ | Run | Length (m) |
|---|---|---|
| ☐ | Top bay → drawer 1 motor / switch | / |
| ☐ | Top bay → drawer 2 motor / switch | / |
| ☐ | Top bay → drawer 3 motor / switch | / |
| ☐ | Top bay → drawer 4 motor / switch | / |
| ☐ | Top bay → drawer 5 motor / switch | / |
| ☐ | Top bay → drawer 6 motor / switch | / |
| ☐ | M8P → pipette head through the cable chain (CAN) | |
| ☐ | CB1 → Octopus USB | |

## 8. Sign-off

Survey complete and every ⛔ resolved: ______________________  Date: __________

## 9. Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| I | 2026-10-20 | James / Claude | New: the Phase 0 form the plan referred to but didn't define |
| J | 2026-10-21 | James / Claude | Load check per R7 against the PSU's label rating; no IDs on the form (D34) |
| L | 2026-10-22 | James / Claude | Octopus V1.1 checks: chip marking, save its current firmware |

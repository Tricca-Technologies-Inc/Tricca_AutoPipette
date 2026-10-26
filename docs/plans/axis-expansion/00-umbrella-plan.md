# AutoPipette Axis Expansion — Umbrella Plan

| Field    | Value |
|----------|-------|
| Status   | **Draft for review.** On approval, Phases 0–3 may start. Phase 4 onward is blocked on WP3 (cb1-autopipette) |
| Revision | L |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Date     | 2026-10-22 |

**Approval**

| Role | Name | Date | Signature / note |
|---|---|---|---|
| Author | Claude (drafted for the owner) | 2026-10-20 | — |
| Reviewer | _TBD_ | | |
| Approver | James | | |

**Change control.**
- Every change is a new revision with a row in §15.
- Values marked `PROPOSED` (§8) may only be changed or confirmed by the owner, and the confirmation is recorded in §15.
- IDs are stable across revisions; a retired ID is never reused.

---

## 1. Purpose & Scope

Upgrade the AutoPipette with:
1. **Six belt-driven plate drawers** (350 mm travel each) as extra G-code axes **U V W A B C**, on a second controller (BTT Octopus V1.1, non-Pro, STM32F446: the owner's existing board).
2. **The pipette plunger and tip-eject servo moved to a BTT EBB42 CAN toolboard**, with the plunger bound to G-code axis **P** so it can move in coordination with the gantry where a protocol benefits.
3. **A collision interlock, soft limits and homing** for the new axes in Klipper.
4. **Daemon and command support in tapd** for the new axes (no kiosk UI yet).
5. **Deployment support** in cb1-autopipette (firmware builds, flashing, CAN interface, MCU detection).

**Document set.** This umbrella holds the system design, decisions, cross-repo interfaces, phase order, integration tests, traceability, hazards and risks. Each work package (WP) holds the detail for one area. Software WPs are written as GitHub issues for the implementing agent to file and complete.

| Doc | Scope | Implemented in |
|---|---|---|
| `00-umbrella-plan.md` | This document | — |
| `WP1-hardware-firmware.md` | Components, power, wiring, BOM, firmware build environment, bench prep, install, electrical tests | Bench / machine |
| `WP2-klipper-config.md` | Klipper config, interlock, homing, offline tests. Issues **CFG-1…CFG-3** | `Tricca_Autopipette_Configs` |
| `WP3-cb1-deployment.md` | Firmware derivations, flash helpers, `can0`, bootstrap, pins, docs. Issues **CB1-1…CB1-7** | `cb1-autopipette` |
| `WP4-tapd.md` | Daemon, `tap` and protocol-file commands. Issues **TAP-1…TAP-11** | `Tricca_AutoPipette` |
| `RB1-migration-and-operations.md` | Per-machine migration, rollback, operator notes, E-stop recovery | Machines nick, marie |
| `reference/klipper/*`, `reference/firmware/*` | Reference config and Kconfig files (WP2/WP3 commit these) | — |
| `reference/tests/*` | Offline Klipper test harness, fixture builder and the Rev J results (CFG-2 commits it) | — |
| `reviews/` | Independent reviews of Rev I and Rev J, with the author responses (Rev J, Rev K) | — |
| `verification-register.md` | Everything verified so far and everything still to verify, with who closes it | — |
| `SUMMARY.md`, `diagrams.md`, `phase0-survey.md`, `commissioning-sheet.md`, `review-checklist.md` | One-page summary, diagrams, per-machine Phase 0 form and sign-off sheet, reviewer checklist | — |

**Out of scope**
- Kiosk UI for plates/plunger. Deferred to TAP-10; see D30 for the client-parity exception.
- Mechanical design of the drawers beyond the interfaces in WP1.

**Agent rules (all WPs)**
- Read each repo's `CLAUDE.md`, `CONTEXT.md` and `docs/adr/` before working in it. They are binding.
- Where a doc says **verify**, check the cited source, the pinned Klipper source, or the physical board. Never substitute values from memory.
- Stop and ask the owner at every **⛔ STOP**, and whenever reality differs from the plan.
- Repo work goes on a branch + PR; never a direct push to `main`.
- Never write MCU serial IDs or CAN UUIDs into a repo.
- Never touch a live machine's `/var/lib/moonraker/config/` except via RB1.

---

## 2. Units, Conventions & IDs

| Quantity | Unit |
|---|---|
| Position, travel | mm |
| Speed in config and `MANUAL_STEPPER SPEED=` | mm/s |
| Speed in G-code `F` | **mm/min** (whole-move speed) |
| Acceleration | mm/s² |
| Current | A RMS (TMC run current) |
| Power | W |

| Convention | Meaning |
|---|---|
| Z0 | Tip fully raised; larger Z lowers the tip |
| Plate position 0 | Drawer fully **in** (at the home switch); +position = **out** |
| P0 | Plunger at the switch-release point after homing (same zero as tapd today) |

| ID | Meaning | Where |
|---|---|---|
| R-n | Requirement | §4 |
| D-n | Decision | §5 |
| I-n | Interlock rule | §6.2 |
| E-nn | Electrical/hardware test | WP1 |
| C-nn | Offline config test | WP2 |
| M-nn | On-machine integration test | §9 |
| S-xxx-n | Software acceptance test | WP4 issues |
| CFG-n, CB1-n, TAP-n | Issues to file | WP2, WP3, WP4 |
| K-HW/CFG/SW/OPS-nn | Risk | §12 |
| H-nn | Hazard | §11 |
| O-n | Open item | §13 |
| DEP-n | Cross-repo dependency (Rev D–G name for CB1 issues) | §7.3 |

---

## 3. Glossary

| Term | Meaning |
|---|---|
| **Raw position** | Where Klipper believes a motor is, in machine coordinates (`printer.gcode_move.position`). Unaffected by G92 / SET_GCODE_OFFSET |
| **G-code position** | Raw position minus offsets (`gcode_move.gcode_position`); what `G1` targets |
| **Bound** | A `manual_stepper` registered as an extra G-code axis (`MANUAL_STEPPER … GCODE_AXIS=<letter>`) |
| **Homed (plate / plunger)** | Macro flag set by a successful homing **and** the stepper still enabled. Klipper has no native homed state for `manual_stepper` |
| **Parked (plate)** | Within `park_tol` of 0 (in) or `position_max` (out) |
| **z_safe** | Highest raw Z (closest to 0) at which the tip clears every plate and drawer; tip is safe when raw Z ≤ z_safe |
| **Stage 1 / Stage 2** | Stage 1: config works with today's tapd. Stage 2: tapd uses `G28 P` + absolute `G1 P`; plunger limits on (D28) |
| **Machine** | One CB1 unit + the rig it drives (nick, marie) |
| **Prime / switch / seed** | cb1-autopipette deploy terms (its `CONTEXT.md`) |

---

## 4. Requirements

| ID | Requirement |
|----|-------------|
| R1 | 6 independent plate-drawer stepper axes, all on **one MCU** (Octopus V1.1). |
| R2 | Plates are bound as extra G-code axes **U V W A B C** (plates 1–6). |
| R3 | Pipette plunger stepper and pipette servo run on an **EBB42 CAN V1.2**. Section names stay `pipette_stepper` / `pipette_servo`, with identical physical behavior (direction, travel per unit, servo angles). |
| R3a | `pipette_stepper` is bound to axis **P**. Target interface: `G28 P` to home, absolute `G1 P…` to move (alone or with gantry axes). Today's tapd plunger commands keep working until stage 2. |
| R4 | Each drawer has a physical home switch at its "in" end; no sensorless homing. |
| R5 | Mechanical hard stops at both ends of each drawer's travel. |
| R6 | All powered equipment is downstream of the existing E-stop, which cuts all machine power. |
| R7 | Whole machine on a **single 24 V PSU** rated ≥ 2× the typical whole-machine load, with brief peaks (e.g. a servo stall) below 70% of its rating (owner, Rev J). |
| R8 | No driver run above its rated voltage (the Octopus V1.1's motor-power input feeds every driver; 24 V is within the TMC2209's rating). |
| R9 | All firmware is built from the **same pinned Klipper source the machines run** (nixpkgs `c59305b` → Klipper `0.13.0-unstable-2026-09-28`, rev `7bc4d094`). |
| R10 | Plate soft limits: `position_min: 0`, `position_max: 350`. |
| R11 | **Collision invariant:** the machine never commands a state where the tip is below `z_safe` while any plate is unhomed or mid-travel. |
| R12 | Plates and plunger can't be moved by G-code while unhomed. Homing state is lost on motor disable, restart or E-stop. |
| R13 | All new wiring strain-relieved, routed away from moving parts, labeled at both ends. |
| R14 | Plunger soft limits in **stage 2** (`-60…0`); none in stage 1 (today's tapd homing would be refused). |
| R15 | tapd exposes plate and plunger homing/motion as daemon RPCs, `tap` commands and protocol-file commands. No kiosk UI in this plan. |
| R16 | **Klipper config is the single source of truth** for plate/plunger axis letters, travel and interlock parameters; tapd reads them from Klipper at connect, never duplicates them. |
| R17 | Interlock refusals reach the operator as clear, specific messages through tapd, and protocol validation reports them before upload where it can. |

---

## 5. Background & Prior Decisions

### 5.1 Existing system (verified from the repos at the commits in §14)

- **Hardware:** Manta M8P V2.0 + CB1 (Armbian); services Nix-managed via system-manager (`cb1-autopipette`). Klipper comes from pinned nixpkgs.
- **Firmware:** `mantaFirmware` and `klipperHostMcu` are built from the same source; `flash-manta` reflashes the M8P (ADR-0004).
- **Config files:** `printer.cfg` includes `mainsail.cfg` and `tricca-autopipette.cfg` (the M8P board file).
  - `[mcu]` is absent from the repo; `bootstrap.sh` writes it from the single `usb-Klipper_*` device it finds.
  - The config set seeds once, then is machine-owned (ADR-0005).
- **Gantry:** corexy on 7 of 8 M8P slots: X, Y (0.8 A), Z×4 (0.65 A), and `pipette_stepper` (0.65 A; `rotation_distance: 2`; endstop `^!PB10`). `pipette_servo` is on PE9.
  - Z0 = tip raised.
  - The current `homing_override` homes Z, X, Y, then `G1 X150 Y150 Z0`.
- **tapd:**
  - Sends `G28`, `G90`/`G91`, `G1 X Y Z F`, `M400`, `M84`, `SET_SERVO`, and `MANUAL_STEPPER STEPPER=pipette_stepper …`.
  - Re-zeroes the plunger (`SET_POSITION=0`) around every syringe operation.
  - Homes the plunger with a `2 × max_travel_mm` overshoot (`home`, then `inverted_home`, then zero).
  - Its homed interlock reads only toolhead `homed_axes`.
  - Its G-code builders hard-code X/Y/Z.
  - Never sends `SYNC=0`, G92 or SET_GCODE_OFFSET.
- **Klipper facts at the pinned rev:**
  - `GCODE_AXIS` rejects X Y Z E F N.
  - `position_min`/`position_max` are enforced on `MANUAL_STEPPER MOVE` and on bound G1 moves; `SET_POSITION` bypasses them.
  - Bound steppers refuse plain `MANUAL_STEPPER` commands.
  - G1 silently ignores unregistered letters.
  - G92 and SET_GCODE_OFFSET only cover X/Y/Z/E.
  - `G28` reads only X/Y/Z, but `homing_override` `axes:` can trigger on other letters.
  - `rename_existing` works for `G1` → `G1.1`; macros get `rawparams`.
  - `[extruder]` needs a heater and sensor, blocks motion below `min_extrude_temp` (170 °C default), caps move length, and has no endstop.
- **E-stop:** installed; cuts all power. Electronics are on top of the machine.

### 5.2 Decisions

| ID | Decision | Rationale |
|----|---|---|
| D1 | No steppers on the CB1's 40-pin GPIO | Host-MCU step timing is poor |
| D2 | Plates on **BTT Octopus V1.1 (non-Pro, STM32F446)** over **USB** | 8 slots, drivers already fitted, and the owner already has one (Rev L; it replaced the Octopus Pro H723 of Rev H–K). Pins from Klipper's non-Pro config; firmware 32 KiB bootloader, 12 MHz. Its USB name (`stm32f446xx`) can't be confused with the M8P's H723 |
| D3 | Pipette stepper **and servo** on **EBB42 CAN V1.2** | NEMA17 pipette motor; one CAN cable to the head; mainline sample config |
| D4 | Plate letters **U V W A B C** | In standard G-code only X Y Z U V W A B C name axes (LinuxCNC word table, §14); with X Y Z on the gantry, these are the six left |
| D5 | NC home switches, and plate homing requires the switch to **release** after the first touch | A broken wire reads as triggered; the release check turns that into a homing failure instead of a false "home" |
| D6 | M8P as **USB-to-CAN bridge** | Onboard CAN port; `[mcu]` becomes `canbus_uuid:` |
| D7 | No new safety-chain hardware | Existing E-stop cuts all power; belts + hard stops |
| D8 | No spill shields | Electronics on top |
| D9 | Plate motors **LDO-42STH40-1684AC** | NEMA17, shared spares |
| D10 | **GT2 6 mm belt, 20T pulley**, `rotation_distance: 40` | Standard |
| D11 | Single PSU. **Keep the existing 24 V, ≥ 200 W supply** (owner, Rev I); Mean Well LRS-350-24 only if it's ever replaced | ≈100 W load (WP1 §4) |
| D12 | Firmware built on a **workstation** from pinned source | ADR-0004; never build heavy on a CB1 |
| D13 | Interlock = wrapped `G1`/`G0`, plus wrappers on **every other Klipper command that can move Z or a plate**: `SET_GCODE_OFFSET … MOVE=1`, `SAVE`/`RESTORE_GCODE_STATE` (also covers `RESUME`), `STEPPER_BUZZ`, `MANUAL_STEPPER`, `SET_STEPPER_ENABLE`, `M84`/`M18`; `MANUAL_PROBE` and `Z_ENDSTOP_CALIBRATE` refused outright. Completeness is enforced by a test: Klipper's full command list must match a reviewed, classified inventory (C-45) | Catches tapd's raw moves and console/Mainsail commands without Python changes. The renamed originals (`G1.1`, `…_BASE`, `M84.1`) bypass by design and are never sent (WP2 §4) |
| D14 | Interlock uses **raw** coordinates | Reading position is immune to G92 / SET_GCODE_OFFSET. Commands that *move* because of an offset (`MOVE=1`) are wrapped separately (D13) |
| D15 | Homed = macro flag AND stepper enabled; `M84`/`M18` clear every flag | No native homed state; clearing on motors-off means re-enabling a motor any other way can't restore "homed" |
| D16 | Bare `G28`: Z, X, Y, park, all plates, plunger | tapd sends bare `G28` everywhere |
| D17 | New config in new include files | Small diffs; mechanical migration |
| D18 | `z_safe` defaults to **0.0** | Safe until measured. `G28 Z`'s 3 mm homing retract dips the tip to raw Z 3; the owner confirmed Z 3 clears every drawer (Rev K) |
| D19 | Plate travel `position_max` **350 mm** | Owner-specified; confirmed against the mechanical design (Rev I) |
| D20 | Plunger letter **P** (not the extruder E) | Free in G1; E would need a heater and can't home |
| D21 | Stage 1: `MANUAL_STEPPER` wrapper unbinds → runs → rebinds `pipette_stepper` | Keeps today's tapd working |
| D22 | P bound at startup (`[delayed_gcode]`) | `G1 P` available as soon as Klipper is ready |
| D23 | P `LIMIT_VELOCITY` 50 mm/s, `LIMIT_ACCEL` 200 mm/s² | App's own `HIGH_RISK_BOUNDS` |
| D24 | `SYNC=0` on `pipette_stepper` refused (stage 1) | Async move + rebind could overlap queued motion |
| D25 | `G28 P` / `G28 U…C` via `homing_override` | Owner choice |
| D26 | Absolute plunger coordinates; no G92 override for P | Owner choice; keeps soft limits meaningful |
| D27 | Bare `G28` includes the plunger | Owner: leftover liquid isn't a concern |
| D28 | Two config stages, switched by `variable_stage` in `_PIPETTE_CFG` plus the plunger limits | Today's tapd works until stage 2 lands. In stage 2 only `HOME_PIPETTE` may set the plunger's zero |
| D29 | Servo **MG996R** at **6 V** from a separate 24 V → 6 V converter, ≥ 3 A (the existing one if rated ≥ 3 A) | Same voltage as today (R3); MG996R stall up to ≈2.5 A vs the EBB's 1 A 5 V rail |
| D30 | tapd scope = **daemon + `tap` + protocol-file commands only**; kiosk later (TAP-10) | Owner choice. Conflicts with tapd's client-parity rule ("neither client may be the only way to do something"); recorded as an explicit, time-boxed exception in TAP-11's ADR and closed by TAP-10. The repo's mechanical parity guards (ControlRequests ↔ `tap`, kiosk route → RPC) still pass |
| D31 | Plate homing **sequential**, fast pass 50 mm/s, slow 5 mm/s, 3 mm backoff | Klipper runs manual-stepper homing moves one at a time. Worst case all six drawers fully out ≈ 6 × 7 s ≈ 45 s; typical (drawers in) a few seconds |
| D32 | Issues are filed with `needs-triage` (+ `safety` where marked); the owner promotes to `ready-for-agent` | tapd's triage rules forbid self-promotion on the strength of an issue body |
| D33 | Reference configs live as files (`reference/`), committed by CFG-1; the docs point to them | Code in prose drifts from shipped code |
| D34 | MCU serial IDs and CAN UUIDs live **only on the machine** (its `printer.cfg` and the RB1 §2 backup); never in a repo, the machine record or forms | Owner choice (Rev J). Lost IDs are rediscovered in a minute with the CAN query tool |

---

## 6. Design & Architecture

### 6.1 System

```
 Mains ── E-stop (cuts ALL power) ── single 24 V PSU (existing, ≥ 200 W)
                                       ├── F1 7.5 A ── M8P (→ CB1 5 V, gantry, CAN 24 V → EBB42)
                                       ├── F2 5 A  ── Octopus V1.1 main + motor power
                                       └── F3 3 A  ── 24→6 V converter (≥3 A) ── MG996R servo

 CB1 ─ klippy (pinned Klipper 7bc4d094) ─ Moonraker ─ tapd ─┬─ tap (shell)
  │                                                          └─ kiosk (unchanged in this plan)
  ├── [mcu]          M8P V2.0, USB-to-CAN bridge → can0 (1 Mbit/s, 120 Ω)
  │                    gantry X Y Z Z1 Z2 Z3; 2 spare slots
  ├── [mcu EBBCan]   EBB42 CAN V1.2 (120 Ω): pipette_stepper → P, endstop, servo signal
  ├── [mcu octopus]  Octopus V1.1 F446, USB: plate1–6 → U V W A B C; 2 spare slots
  └── [mcu CB1]      host MCU (unchanged)
```

### 6.2 Interlock (Klipper, WP2)

| Rule | When | Requirement |
|---|---|---|
| I1 | G1/G0 with any plate letter | Z homed; raw Z ≤ z_safe now and at target; moving plates homed |
| I2 | G1/G0 lowering the tip below z_safe | Every plate homed and parked |
| I3 | `MANUAL_STEPPER STEPPER=plateN` | Only from plate macros |
| I4 | `HOME_PLATE(S)` / `G28 U…C` | Z homed and raw Z ≤ z_safe |
| I5 | Stepper disabled (`M84`/`M18`, `SET_STEPPER_ENABLE`, or Klipper's own motors-off after a failed `G28`), restart, E-stop | Becomes unhomed |
| I6 | G1/G0 with `P` | Plunger homed and P bound |
| Soft | Any plate move (and plunger in stage 2) | Klipper `position_min`/`position_max` |

**Where each rule is enforced.** These are all the Klipper paths that can move Z or a plate:

| Path | Rules |
|---|---|
| `G1`, `G0` | I1, I2, I6 |
| `SET_GCODE_OFFSET … MOVE=1` | I2 on the resulting Z move |
| `RESTORE_GCODE_STATE … MOVE=1`, and `RESUME` (which uses it) | I2 on the restored Z |
| `STEPPER_BUZZ` | Plates: Z homed and tip raised. Z steppers: I2 for a 1 mm descent |
| `MANUAL_STEPPER` | I3; plunger rules per stage |
| `G28`, `HOME_PLATE(S)` | I4, plus the switch-release check (D5). Unknown letters refused. `G28 Z`'s 3 mm retract is unchecked but owner-confirmed clear (D18) |
| `M84`, `M18`, `SET_STEPPER_ENABLE` | I5. `ENABLE=0` on a gantry stepper is refused (use `M84`) |
| Klipper's own motors-off (e.g. a failed `G28`) | I5: the next plunger command sees the stepper disabled and clears its flag; plates need their live enable state anyway |
| `MANUAL_PROBE`, `Z_ENDSTOP_CALIBRATE` (then `TESTZ`) | Refused outright (not used on this machine) |
| `FORCE_MOVE`, `SET_KINEMATIC_POSITION`, arcs | Not available: `enable_force_move: False`, no `[gcode_arcs]` |
| Anything else | Classified in `reference/tests/command-inventory.txt`; test C-45 fails on any unclassified command |

Effect: while the tip is low, plates can't move (I1); while a plate is mid-travel or unhomed, the tip can't descend (I2), whichever command asks. Known limits are listed in WP2 §4.

### 6.3 Cross-repo G-code contract

The interface between WP2 (Klipper) and WP4 (tapd). Both sides must match it exactly.

| Command | Meaning | Stage |
|---|---|---|
| `G28` | Z, X, Y, park, plates 1–6, plunger | 1 |
| `G28 <X|Y|Z…>` | Named gantry axes (Z, X, Y order), then park the axes that are homed | 1 |
| `G28 <U|V|W|A|B|C…>` | Named plates (requires Z homed and raised) | 1 |
| `G28 P` | Plunger | 1 |
| `HOME_PLATE PLATE=plateN`, `HOME_PLATES`, `HOME_PIPETTE` | Same as the `G28` forms | 1 |
| `PLATE_MOVE PLATE=plateN POS=<mm> [SPEED=<mm/s>]`, `PLATE_IN`, `PLATE_OUT`, `PLATES_IN` | Plate motion through the interlock | 1 |
| `QUERY_PLATES` | Text report (humans). tapd reads state via Moonraker objects instead | 1 |
| `G1 … U…C…` / `G1 … P…` | Allowed; same interlock | 1 |
| `MANUAL_STEPPER STEPPER=pipette_stepper …` (no `SYNC=0`) | Today's tapd plunger commands | **1 only** |
| `G90` + `G1 P<abs>` | Plunger moves in stage 2 | 2 |
| `G90`, `G91`, `M84`, `SET_SERVO`, `SET_VELOCITY_LIMIT ACCEL=` | Existing tapd commands; `M84` now also clears every homed flag. `SET_VELOCITY_LIMIT` brackets stage-2 plunger moves (TAP-6) | 1 / 2 |
| `G4`, `M117`, `M220`, `M400`, `QUERY_ADC`, `SET_FAN_SPEED`, `SET_LED`, `SET_LED_TEMPLATE`, `SET_PIN`, `SET_TEMPERATURE_FAN_TARGET`, `LOAD_CELL_*` | Other commands tapd sends today (`gcode_commands.py` at `a98439b`); no motion. The fan/LED/pin/load-cell ones exist only where those sections are configured | 1 |
| `STEPPER_BUZZ STEPPER=…` | tapd's wiring check. Now guarded: a plate needs Z homed and the tip raised; a Z stepper needs the plates parked | 1 |
| Pause / resume of a run (Moonraker → Klipper `PAUSE` / `RESUME`) | Unchanged, except that `RESUME` is **refused** (run stays paused) if returning the tip would hit a drawer | 1 |
| Error text `Move refused by interlock: <reason>` / `… refused: …` | Interlock refusals | 1 |
| **Never sent:** `G1.1`, `G0.1`, `*_BASE`, `M84.1`, `M18.1`, `_PLATE_INTERNAL`, and `SET_GCODE_VARIABLE` on `_PLATE_CFG` / `_PLATE_STATE` / `_PIPETTE_CFG` / `_PIPETTE_STATE` / `_GSTATE` | Bypass the interlock (WP2 §4) | — |
| Moonraker objects: `gcode_macro _PLATE_CFG`, `_PLATE_STATE`, `_PIPETTE_CFG`, `_PIPETTE_STATE`, `stepper_enable`, `gcode_move`, `configfile` | State tapd reads (R16) | 1 |

### 6.4 Staging (D28)

| | Stage 1 | Stage 2 |
|---|---|---|
| Config | CFG-1 | CFG-3 |
| Config switch | `variable_stage: 1` | `variable_stage: 2` + plunger limits |
| tapd | TAP-1…TAP-5, TAP-8, TAP-9, TAP-11 | TAP-6; TAP-7 optional |
| Plunger commands from tapd | `MANUAL_STEPPER` (via D21 rebind), or `G28 P` once TAP-5 lands | `G28 P` + absolute `G1 P` only |
| Plunger soft limits | None | `-60…0` |
| Deploy | CB1-5 pins `printer-cfgs` (CFG-1) and optionally a pre-TAP-6 `tricca-src` | CB1-7 bumps **both pins in one switch** (CFG-3 + TAP-6) |

---

## 7. Work Breakdown & Phase Plan

### 7.1 Phases

| Phase | Work | WP | Entry | Exit (accept) | Rollback |
|---|---|---|---|---|---|
| 0 | Survey, measurements, open items | All | Plan approved | `phase0-survey.md` complete for the machine; ⛔ if hardware differs, or typical load > half the PSU's label rating, or peak > 70% (R7) | n/a (read-only) |
| 1 | Firmware environment | WP1 §7 | Phase 0 | All binaries + `.dict` built from pinned source, recorded | Delete artifacts |
| 2 | Bench prep (Octopus, EBB) | WP1 §8 | Phase 1 | Octopus enumerates; EBB in Katapult; E-01 | Reflash the previous firmware by SD (Octopus); DFU (EBB) |
| 3 | Klipper config development | WP2 (CFG-1, CFG-2) | Phase 1 (`.dict` files) | Offline harness green (WP2 §5); owner signs `PROPOSED` values; ⛔ before merge | Close PR |
| 4 | Deployment dependencies | WP3 (CB1-1…CB1-5; CB1-5 is the stage-1 pin bump). CB1-6 (docs) gates Phase 8 sign-off instead | Phase 3 merged | Merged, primed, switched on the target machine | `switch` to previous generation |
| 5 | CAN bring-up (on machine). **The machine is down from here until Phase 7 ends** | WP1 §9 + RB1 | Phase 4; **⛔ STOP** until VR-17 is closed on a spare M8P (`flash-manta` over CAN and `--firmware` rollback rehearsed), the previous M8P firmware path is recorded, and the RB1 §2 backup exists | E-02; E-03 (idle); E-04 (CAN boards) | RB1 §5 |
| 6 | Mechanical & electrical install | WP1 §9 | Phase 5; **⛔ STOP** for owner go-ahead before rewiring (rollback after this point means re-wiring, RB1 §5) | Photo checklist; E-04 (Octopus); E-07; E-09; E-11 | Re-wire pipette to M8P; disconnect Octopus; RB1 §5 |
| 7 | Config migration and powered checks | RB1 §3 | Phase 6 | Klipper starts clean; then E-03 (motion), E-05, E-06, E-08, E-10, E-12 (these need the new config) | RB1 §5 |
| 8 | Stage-1 validation | §9 | Phase 7 | M-01…M-19 and M-23 pass; CB1-6 docs merged; machine record filled in (RB1 §6); owner sign-off | RB1 §5 |
| 9 | tapd stage-1 integration | WP4 (TAP-1…5, 8, 9, 11) | Phase 3 merged (offline dev); Phase 8 (on-machine) | Issue acceptance tests; M-08 rerun via new commands | `switch` to previous `tricca-src` pin |
| 10 | Stage 2 | WP4 TAP-6 (+ optional TAP-7) + WP2 CFG-3 + WP3 CB1-7 | Phase 9 | M-20, M-21 (and M-22 if TAP-7 is implemented); owner sign-off | CB1-7 switches both pins back together; machine config back to stage 1 (WP2 CFG-3) |

### 7.2 Dependency graph

```
Phase 0 ─► 1 ─► 2 ─────────────────────► 5 ─► 6 ─► 7 ─► 8 ─┐
            └─► 3 (CFG-1, CFG-2) ─► 4 (CB1-1..6) ─┘          │
                 │                                            ▼
                 └─► 9 (TAP-1..5,8,9,11; offline dev may start after 3) ─► 10 (TAP-6 ─► CFG-3 ─► CB1-7; TAP-7 optional)
TAP-10 (kiosk) is deferred and depends on TAP-4/TAP-5.
```

### 7.3 Rev D–G name mapping

DEP-1…DEP-7 in earlier revisions = CB1-1…CB1-6 (DEP-6 and DEP-7 merged into CB1-5 and CB1-6). At Rev J, CB1-5's stage-2 half became CB1-7.

---

## 8. Proposed Values & Sources

| Parameter | Value | Source / reasoning | Status |
|---|---|---|---|
| Plate travel `position_max` | **350 mm** | Owner-specified | Confirmed (Rev I) |
| Plate `velocity` / `accel` | 50 mm/s / 500 mm/s² (≈0.05 g) | Conservative for open plates with liquid | `PROPOSED`; tune with M-19 |
| Plate homing | 50 / 5 mm/s, 3 mm backoff | D31 | `PROPOSED`; M-17 |
| Plate `run_current` | 1.0 A | ≈60% of 1.68 A rating | E-10 |
| `z_safe` | 0.0 | Safe default; tip fully raised for any drawer move | Owner: keep 0.0 for now (Rev I) |
| P limits | 50 mm/s, 200 mm/s² | tapd `HIGH_RISK_BOUNDS` | Fixed |
| `max_travel` | 60 mm | `p100_vertical.json` | Fixed for this pipette |
| `home_speed` / `home_accel` | 50 mm/s / 200 mm/s² | `p100_vertical.json` `speed_dispense` / `accel_home` | Fixed |
| `home_dir` | **+1** | tapd's homing move = 2 × 60 × dispense (−1) × motor_orientation (−1) = +120 mm | `PROPOSED`; M-01 |
| Stage-2 plunger limits | −60 … 0 | From `home_dir` and travel | Stage 2 |
| Servo supply | 24→6 V converter ≥ 3 A | Same as today; MG996R stall up to ≈2.5 A | Fixed (D29) |
| ANSI/SLAS plate footprint (reference) | 127.76 × 85.48 mm ±0.25 mm | ANSI/SLAS 1-2004 | — |

---

## 9. Integration Test Plan (on-machine)

E-tests (electrical) are in WP1, C-tests (offline config) in WP2, S-tests (software acceptance) in WP4's issues.

| ID | Test | Pass criteria | Stage |
|---|---|---|---|
| M-01 | Pipette regression vs Phase 0 reference (`phase0-survey.md` §5) | Same plunger direction and distance per `MOVE`; same homing; servo reaches the same physical positions | 1 |
| M-02 | Plate direction | `PLATE_OUT` moves out; `HOME_PLATE` moves in to the switch | 1 |
| M-03 | Stage-1 cases C-02…C-13 and C-26…C-35 repeated with real homing (includes `RESUME`, `SET_GCODE_OFFSET … MOVE=1` and `STEPPER_BUZZ` refusals) | Same results; refused moves produce **no motion** | 1 |
| M-04 | Bare `G28` | Z, X, Y, park, plates 1–6, plunger, in order | 1 |
| M-05 | `M84` then `G1 U10` | Refused until re-homed | 1 |
| M-06 | `SET_STEPPER_ENABLE STEPPER="manual_stepper plate1" ENABLE=1` then `G1 U10` | Refused | 1 |
| M-07 | `FIRMWARE_RESTART` | Plates and plunger unhomed; P rebound | 1 |
| M-08 | tapd end-to-end: existing protocol after `G28` | Completes; no interlock errors with plates parked in | 1 |
| M-09 | Plate soft limits | `PLATE_OUT` stops at 350, short of the hard stop | 1 |
| M-10 | Stage-1 cases C-14…C-25 repeated on hardware (C-17… are stage 2; see M-21) | Same results | 1 |
| M-11 | Coordinated move: `G90` + `G1 Z<up 5> P<+1>` | Z and plunger start and stop together; travel matches a 1 mm `MANUAL_STEPPER MOVE` | 1 |
| M-12 | tapd plunger regression (aspirate/dispense/clear/home) with gravimetric spot-check at one volume | Same delivered volume within the pipette's current tolerance; no new klippy.log errors | 1 |
| M-13 | Restart rebinding | P rebound at startup after `FIRMWARE_RESTART` and a cold boot | 1 |
| M-14 | Same zero: tapd's homing vs `G28 P` | Same physical point within 0.05 mm | 1 |
| M-15 | G1 wrapper latency: 200 short `G1 X` moves, wrapper on vs off | Owner accepts overhead; no "Timer too close" | 1 |
| M-16 | `G28 P`, `G1 P-30`, `G1 P0` | Out and back without triggering the switch | 1 |
| M-17 | Homing time, all drawers fully out, bare `G28` | ≤ 60 s total; each drawer homes cleanly | 1 |
| M-18 | E-stop recovery drill (RB1 §4.2) | Operator can recover to a homed, safe state using only the documented steps | 1 |
| M-19 | Spill test: full plate, water + dye, `PLATE_OUT`/`PLATE_IN` × 20 | No liquid leaves its well; adjust §8 values | 1 |
| M-20 | Stage-2 tapd plunger regression (gravimetric) | As M-12, using `G28 P` + absolute `G1 P` | 2 |
| M-21 | Stage-2 plunger limits | `G1 P` beyond travel refused; nothing moves | 2 |
| M-22 | Stage-2 coordinated move through a tapd command (**only if TAP-7 is implemented**) | As M-11, issued from `tap` and from a protocol file | 2 |
| M-23 | Broken switch wire: disconnect one drawer's switch (drawer mid-travel), then `G28 <letter>` | Homing fails with an error; that plate is not flagged homed; reconnect and home normally | 1 |

---

## 10. Traceability

| Req | Decisions | Verified by |
|---|---|---|
| R1 | D2 | E-04, E-06, M-02 |
| R2 | D4 | C-03, M-02 |
| R3 | D3, D29 | E-12, M-01, M-12 |
| R3a | D20–D22, D25–D28 | C-13…C-16, C-24, C-36s, M-11, M-14, M-16, M-20 (M-22 if TAP-7) |
| R4 | D5 | E-05, M-02, M-23 |
| R5 | — | E-11 |
| R6 | D7 | E-07, M-18 |
| R7 | D11 | E-08, E-09 |
| R8 | — | E-01 |
| R9 | D12 | WP1 §7 record, CB1-1 acceptance |
| R10 | D19 | C-12, M-09 |
| R11 | D13, D14, D18 | C-02…C-10, C-26…C-30b, C-34, C-35, C-38, C-38b, C-41, C-42, C-45, M-03 |
| R12 | D15 | C-15, C-19…C-19c, C-31, C-32, C-32b, C-37s, C-39, C-39b, C-40, M-05, M-06, M-07 |
| R13 | — | WP1 §9 photo checklist |
| R14 | D28 | C-17…C-17c, C-36s, M-21 |
| R15 | D30 | TAP-4, TAP-5 acceptance (S-tests) |
| R16 | — | TAP-2 acceptance |
| R17 | — | TAP-8, TAP-9 acceptance |

---

## 11. Hazard Analysis (mechanical)

Structured after the mechanical-hazard topics IEC 61010-1 (lab equipment) addresses: moving parts, moving masses, jamming/crushing, expelled parts, sharp edges. **This is a design aid, not a compliance assessment.** The owner confirmed internal use only, with no certification planned (Rev I). Selling the machine would need a full risk assessment against the standard's actual text.

| ID | Hazard | Cause | Severity | Mitigation | Residual |
|---|---|---|---|---|---|
| H-01 | Finger pinch between drawer and frame | Drawer moving in (350 mm stroke out of the machine). At 1.0 A a drawer can push roughly 40 N before the motor stalls | Moderate | **Owner's mechanical solution (outside this plan; register §2.2).** Also: E-stop; operator notes (RB1 §4); drawers only move on command or during `G28` | Per the owner's design |
| H-02 | Tip/plate collision | Plate moves while the tip is low, or tip descends onto a moving plate | Damage, contamination | Interlock I1/I2; hard stops | Low |
| H-03 | Gantry crush | Existing gantry; unchanged | Moderate | Existing E-stop | Unchanged |
| H-04 | Spill / splash | Drawer acceleration on open plates | Contamination | 0.05 g accel; M-19 | Low |
| H-05 | Unexpected motion at `G28` | Drawers and plunger now home on bare `G28` | Pinch, surprise | Operator notes; M-04 | Low |
| H-06 | Electrical: mains at the PSU | New/relocated PSU wiring | Severe | Qualified wiring; covered terminals; E-07 | Low |
| H-07 | Servo overload / brownout | MG996R stall | Equipment | Separate 6 V converter (D29); E-12 | Low |

---

## 12. Risks

Likelihood (L) and severity (S) on 1–5; initial estimates, to review at each phase gate.

| ID | Risk | L | S | Owner | Mitigation | Residual |
|---|---|---|---|---|---|---|
| K-HW-01 | Wrong supply wiring (polarity, or motor power above the drivers' rating) destroys drivers/board | 1 | 4 | WP1 agent | E-01 at the terminals before first power-up; photos | Low |
| K-HW-07 | A Pro config used on the non-Pro board (or the reverse): Driver3's enable pin drives a heater output | 1 | 4 | WP2 agent | `octopus-plates.cfg` header names the board; pins from Klipper's non-Pro config; chip-marking check (WP1 §3.1, Phase 0) | Low |
| K-HW-02 | EBB pins (PB7 endstop, PB9 servo) differ from community/sample sources | 2 | 3 | WP1 agent | Verify on BTT pinout; E-05, M-01 | Low |
| K-HW-03 | CAN faults (termination, cable fatigue) | 2 | 3 | WP1 agent | E-02, E-03; high-flex cable | Low |
| K-HW-04 | Load higher than assumed | 1 | 3 | WP1 agent | Phase 0 recompute against the PSU's label rating (R7); E-08 | Low |
| K-HW-05 | Motor cable noise over long runs | 2 | 2 | WP1 agent | Shielded, controller-end shield ground | Low |
| K-HW-06 | Drawer travel/belt length doesn't match 350 mm | 2 | 3 | Owner | Confirm vs mechanical design; M-09 | Low |
| K-CFG-01 | Pipette direction or servo mapping changes after the move to the EBB | 3 | 4 | WP2 agent | M-01 vs Phase 0 reference before any protocol | Low |
| K-CFG-02 | G1 wrapper overhead on the 1 GB CB1 | 2 | 3 | WP2 agent | M-15; ⛔ revisit D13 if unacceptable | Medium |
| K-CFG-03 | Interlock bypass. Reviews found `RESUME`, `RESTORE_GCODE_STATE`/`SET_GCODE_OFFSET … MOVE=1`, `STEPPER_BUZZ` (Rev J), then `MANUAL_PROBE`/`TESTZ` and a failed-`G28` motors-off (Rev K); all closed. Remaining: commanded state only, renamed originals, `SET_GCODE_VARIABLE` on interlock macros, arcs, force_move | 2 | 4 | WP2 agent | §6.2 path table; C-26…C-45; WP2 §4; keep `gcode_arcs`/`force_move` off | Low |
| K-CFG-08 | A future change (config section, Mainsail update, new Klipper version) adds a motion command that skips the interlock | 2 | 4 | WP2 agent | C-45 fails on any command not in the reviewed inventory; WP2 §4 rule: classify it, and add a check and a C-test if it moves anything | Low |
| K-CFG-04 | `configfile.settings` / `stepper_enable` key shapes differ from assumptions | 2 | 2 | WP2 agent | C-tests | Low |
| K-CFG-05 | Rebind (D21) changes tapd plunger timing | 2 | 3 | WP2 agent | M-12 gravimetric | Low |
| K-CFG-06 | `HOME_PIPETTE` zero differs from tapd's, invalidating calibration | 2 | 4 | WP2 agent | Same sequence; M-14 | Low |
| K-CFG-07 | A template silently drops a minus sign (`{-x}` is Jinja whitespace control in Klipper's single-brace templates). Occurred once (Rev H `HOME_PIPETTE`: plunger would have homed the wrong way) | 3 | 4 | WP2 agent | Fixed; harness lint fails on `{-`; stage-2 limits tests; M-01/M-14 | Low |
| K-SW-01 | Stage-1 tapd re-zeroing shifts P frame under a coordinated move | 3 | 4 | WP4 agent | Don't mix old plunger commands with `G1 P`; TAP-7 lands with stage 2 | Low |
| K-SW-02 | tapd's batch-compiled G-code assumes a plunger position that differs from Klipper's at run time | 2 | 4 | WP4 agent | TAP-6: seed from Klipper at protocol start; refuse if unhomed | Low |
| K-SW-03 | Stage-2 deploy with only one of the two pins bumped | 2 | 4 | WP3 agent | CB1-7: bump both pins in one switch; M-20 | Low |
| K-SW-04 | Kiosk lacks plate controls (parity exception) | 3 | 2 | Owner | D30; TAP-10 tracked | Accepted |
| K-OPS-01 | Bridge reflash takes the old config offline | 3 | 3 | RB1 operator | Phases sequenced; RB1 §5 rollback | Low |
| K-OPS-02 | `bootstrap.sh` writes the Octopus as `[mcu]` (it takes the single `usb-Klipper_*` device) before CB1-4 lands | 2 | 4 | WP3 agent | Phase 4 gate. Today's `flash-manta` glob (`stm32h723xx`) can't match the F446 Octopus | Low |
| K-OPS-03 | `G28 X Y` now homes both axes (old override homed only the first) | 2 | 1 | WP2 agent | Noted in PR; C-23 | Low |
| K-OPS-04 | Plain `G28` now moves drawers and plunger | 3 | 2 | Owner | Operator notes; H-05 | Low |
| K-OPS-05 | Someone types a renamed original command (`G1.1`, `…_BASE`) at the console and bypasses the interlock | 1 | 4 | Owner | Operator notes (RB1 §4.1); tapd never sends them (S-TAP1-4) | Low |
| K-OPS-06 | A bridged M8P can't be put back on USB firmware during rollback | 2 | 4 | WP3 agent | Phase 5 ⛔ (VR-17 rehearsed on a spare); `flash-manta --firmware`; BOOT+RESET DFU fallback (RB1 §5) | Low |

---

## 13. Open Items

| ID | Item | Phase |
|---|---|---|
| O-5 | Confirm `home_dir` (+1) | 0 |

(Closed: O-4 servo model, MG996R. O-1 travel, 350 mm confirmed by the owner. O-3 `z_safe`, owner keeps 0.0 for now.)

All open items, `VERIFY` markers and unproven assumptions are tracked together in `verification-register.md` (VR-01…VR-30). O-5 there is VR-21. O-2 (cable lengths) and O-6 (coordinated-move use case) are handled by the owner outside the plan (register §2.2).

---

## 14. References

| Item | Location | Pin |
|---|---|---|
| Klipper | https://github.com/Klipper3d/klipper | `7bc4d09465d31cd30fc0822e8d0abe02cc8c547f` (via nixpkgs `c59305bab2065cfecc4944690d9eedbb56f3a9fa`) |
| `Tricca_Autopipette_Configs` | https://github.com/Tricca-Technologies-Inc/Tricca_Autopipette_Configs | `d7c45ce0a05c6eb19555090e7fc450b049db4cd7` (2026-10-01) |
| `cb1-autopipette` | https://github.com/Tricca-Technologies-Inc/cb1-autopipette | `130d38b47524a75f0d07ab73cbffdc69c52379f2` (2026-10-02) |
| `Tricca_AutoPipette` | https://github.com/Tricca-Technologies-Inc/Tricca_AutoPipette | `a98439b7f051249ca14644690b43de5f8c9d9d03` (2026-10-05) |
| Katapult | https://github.com/Arksine/katapult | Checked at `3b973a485388b4ef0f9efef46f78152e302aea8e` (2026-10-01); record the rev actually used (WP1 §7) |
| Klipper files used | `klippy/extras/manual_stepper.py`, `gcode_move.py`, `homing.py`, `homing_override.py`, `stepper_enable.py`, `gcode_macro.py`, `kinematics/extruder.py`, `heaters.py`, `toolhead.py`; `docs/Config_Reference.md`, `G-Codes.md`, `Debugging.md`, `CANBUS.md`; `src/stm32/Kconfig`, `src/Kconfig`; `config/generic-bigtreetech-octopus-v1.1.cfg`, `config/sample-bigtreetech-ebb-canbus-v1.2.cfg` | At the Klipper pin |
| BTT Octopus V1.1 (non-Pro) | Pins: Klipper `config/generic-bigtreetech-octopus-v1.1.cfg` (at the Klipper pin). Manual: https://github.com/bigtreetech/BIGTREETECH-OCTOPUS-V1.0 (`BIGTREETECH_Octopus_EN_updated_0719.pdf`; the repo covers the V1.x family) | — |
| BTT EBB | https://github.com/bigtreetech/EBB ; https://global.bttwiki.com/EBB%2042%20CAN.html | — |
| BTT Manta M8P H723 firmware | https://neo.bttwiki.com/en/docs/board-docs/manta-series/manta-m8p-firmware-h723 | — |
| M8P V2.0 + EBB menuconfig table | https://forum.vorondesign.com/threads/manta-m8p-btt-ebb-sb22xx-setup.1697/ | — |
| ANSI/SLAS 1-2004 | https://slas.org/SLAS/assets/File/public/standards/ANSI_SLAS_1-2004_FootprintDimensions.pdf | — |
| LinuxCNC G-code word table | https://linuxcnc.org/docs/html/gcode/overview.html | — |
| MG996R / MG90S current | https://tinkered.ai/components/servo-mg996r-straight ; https://www.kpower.com/insight_bldc/7870.html | — |
| IEC 61010 overview | https://blog.johner-institute.com/systems-engineering/iec-61010-ivd/ | — |
| Vendor sheets | LDO-42STH40-1684AC; Mean Well LRS-350-24 | — |

---

## 15. Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| A | 2026-10-20 | James / Claude | Initial hardware plan |
| B | 2026-10-20 | James / Claude | M8P bridge; EBB42 V1.2; pins verified; safety chain and spill shields dropped; motors, belts, PSU |
| C | 2026-10-20 | James / Claude | Single PSU (LRS-350-24); branch fuses |
| D | 2026-10-20 | James / Claude | Klipper config, binding, homing, soft limits, interlock in scope; Nix firmware environment; migration runbook |
| E | 2026-10-20 | James / Claude | Pipette on axis P; transitional rebind; `SYNC=0` refused |
| F | 2026-10-20 | James / Claude | `G28 P` / `G28 U…C` via `homing_override`; absolute plunger coordinates; two stages |
| G | 2026-10-20 | James / Claude | Sourced values (§8); separate servo supply; spill test |
| H | 2026-10-20 | James / Claude | **Restructured into an umbrella + four work packages + runbook + reference files.** tapd and cb1-autopipette work written as issues (TAP-1…11, CB1-1…6, CFG-1…3). Plate travel 350 mm (D19); MG996R (D29); sequential homing at 50 mm/s (D31); tapd scope daemon + commands, parity exception (D30). Added: units, glossary, approval/change control, traceability, hazard analysis, risk ratings, per-phase entry/exit/rollback, pinned SHAs and URLs. Tests renumbered (Appendix A) |
| I | 2026-10-20 | James / Claude | **Verification pass.** Reference config run in the pinned Klipper (batch mode): 27/27 cases in each stage. Fixed the `HOME_PIPETTE` sign bug (K-CFG-07) and the interlock message order. Firmware and Katapult configs validated and built at the pins; EBB pins PB7/PB9 verified. Added `reference/tests/`, verification register, one-page summary (no costs; qualitative downtime), diagrams, commissioning sheet, reviewer checklist. Phase 3 exit now = harness green. Owner answers: keep the existing PSU, 350 mm confirmed, internal use only, `z_safe` stays 0.0, gantry motors are the stock Voron 2.4 set, servo stays at 6 V as today (D29). Added `phase0-survey.md`; cable lengths, coordinated-move use case and tip-ejection force moved out of plan (owner); fixed WP1 section references in §7.1 |
| J | 2026-10-21 | James / Claude | **Independent review fixes** (1 blocker, 17 should, 13 nit). Interlock now covers every Klipper motion path (§6.2 table; D13, D14 corrected); `M84`/`M18` clear homed flags (D15); plate homing checks switch release (D5, M-23); stage switch is `variable_stage` (D28) and the stage-2 plunger can't be re-zeroed without homing. Phases 5–7 re-gated (powered E-tests after config migration; ⛔ before the first reflash and before rewiring). CB1-5 split (CB1-7 = stage-2 bump); TAP-6 → CFG-3 one-way; TAP-7 optional stage-2 work, M-22 conditional. Owner decisions: R7 = 2× typical with peaks < 70%; pinch protection is the owner's mechanical solution (H-01); board IDs only on the machine (D34). Offline harness 43/43 in each stage. Contract adds pause/resume, `M84`, `SET_VELOCITY_LIMIT` and the never-send list |
| K | 2026-10-22 | James / Claude | **Second-review fixes** (Rev J: 0 blockers, 4 should, 13 nit; 27 of 31 earlier findings fully closed). `MANUAL_PROBE`/`Z_ENDSTOP_CALIBRATE` refused (owner: not used); Klipper's own motors-off unhomes the plunger (I5); `G28 Z` 3 mm retract recorded as owner-confirmed clear (D18); `G28` unknown letters refused; CB1-6 moved from the Phase 4 exit to Phase 8 sign-off. Contract lists every command tapd sends today. Offline tests: strict log check and a command inventory that makes "every motion path is checked" testable (C-45); 55/55 stage 1, 52/52 stage 2 |
| L | 2026-10-22 | James / Claude | **Plate controller changed to the owner's Octopus V1.1 (non-Pro, STM32F446)**, identified from a photo. Driver3 enable PA0 (PA2 is a heater output on this board); F446 firmware (32 KiB bootloader, 12 MHz); power via main + motor inputs; E-01 rewritten; K-HW-07 added; BOM: board and drivers already owned. Offline tests rerun with the F446 firmware dictionary |

### Appendix A — Test ID map (Rev G → Rev H)

| Rev G | Rev H | | Rev G | Rev H | | Rev G | Rev H |
|---|---|---|---|---|---|---|---|
| T1 | E-01 | | T15 | C-02 | | T24i | C-21 |
| T2 | E-02 | | T16 | C-03 | | T24j | C-22 |
| T3 | E-03 | | T17 | C-04 | | T24k | C-23 |
| T4 | E-04 | | T18 | C-05 | | T24l | C-24 |
| T5 | E-05 | | T19 | C-06 | | T24m | C-25 |
| T6 | E-06 | | T20 | C-07 | | T25 | M-15 |
| T7 | E-07 | | T21 | C-08 | | T26 | M-04 |
| T8 | E-08 | | T22 | C-09 | | T27 | M-05 |
| T8a | E-09 | | T23 | C-10 | | T28 | M-06 |
| T9 | E-10 | | T24 | C-11 | | T29 | M-07 |
| T10 | E-11 | | T24a | C-12 | | T30 | M-08 |
| T11 | E-12 | | T24b | C-13 | | T31 | M-09 |
| T12 | M-01 | | T24c | C-14 | | T32 | M-10 |
| T13 | M-02 | | T24d | C-15 | | T33 | M-11 |
| T14 | C-01 | | T24e | C-16 | | T34 | M-12 |
| | | | T24f | C-18 | | T35 | M-13 |
| | | | T24g | C-19 | | T36 | M-14 |
| | | | T24h | C-20 | | T37 | M-16 |
| | | | | | | T38 | C-17 / M-21 |
| | | | | | | T39 | M-19 |

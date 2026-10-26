# AutoPipette Axis Expansion — One-Page Summary (Rev L)

**For:** anyone who needs the gist without reading the full plan. **Owner:** James. **Status:** draft for review.

## What changes

1. **Six motorized plate drawers.** Each slides 350 mm in and out on a belt and has a home switch and hard stops. They are driven by a second controller board you already have (BTT Octopus V1.1) and appear to the software as extra axes **U V W A B C**.
2. **The pipette moves to a small board on its own motor.** That board (BTT EBB42) carries both the plunger motor and the tip-eject servo. It connects to the main board with one 4-wire CAN cable instead of a bundle of wires. The plunger becomes axis **P**, so a protocol can move it together with the gantry when that helps.
3. **One power supply** (the existing 24 V unit, ≥ 200 W) feeds everything through three fuses. The existing E-stop still cuts all power.
4. **Collision protection in the firmware.**
   - A drawer can't move while the tip is lowered.
   - The tip can't lower while a drawer is part-way out.
   - Nothing moves until it has been homed.
   - These rules apply to every command that can move the tip or a drawer, including Resume after a pause and Mainsail's Z-offset buttons.
5. **Software support.** The pipette daemon (tapd), the `tap` shell and protocol files gain plate and plunger commands. The touchscreen kiosk gets them later.

## What it means for operators

- **Home now does more.** It pulls all six drawers in and homes the plunger after the gantry. Keep hands clear of the drawer openings.
- **Refused moves explain themselves**, e.g. `Move refused by interlock: plate3 mid-travel`.
- **After an E-stop or motors-off, home again** before doing anything. The recovery steps are in RB1 §4.2.
- **If a drawer is moved during a pause** and the tip would come down onto it, Resume is refused until the drawer is parked.

## How it's rolled out

- **Stage 1:** new hardware and firmware config. The existing software keeps working unchanged.
- **Stage 2:** the software switches to the new plunger commands. Klipper then also enforces plunger travel limits.

Every phase has a rollback (umbrella §7.1): RB1 §5 for the hardware and stage 1, and a two-pin switch back (CB1-7) for stage 2. The two steps that take the machine down (the first main-board reflash and the rewiring) each start with a stop point.

| Phase | What | Machine downtime |
|---|---|---|
| 0–4 | Survey, firmware builds, bench prep, config and deployment code (offline) | None |
| 5–7 | Reflash the main board, install hardware, migrate config | **Down.** Likely 1–2 working days per machine, mostly mechanical install and wiring |
| 8 | Stage-1 validation tests | **Down.** About half a day to a day per machine (gravimetric and spill tests take longest) |
| 9 | Software stage 1 | Brief restarts only |
| 10 | Stage 2 switch and re-test | A few hours per machine |

Downtime figures are planning estimates, not measurements; refine them after the first machine.

## Confidence so far

- **Proven on a desk, without hardware:**
  - The firmware for all three boards builds from the exact Klipper version the machines run.
  - The full Klipper config loads.
  - All collision and homing test cases pass in real Klipper: 55 in stage 1, 52 in stage 2. Testing caught a bug that would have homed the plunger the wrong way.
  - Two independent reviews found ways around the collision protection: Resume, Z-offset moves, the motor-buzz test, manual Z-probing, and motors switching off and back on. All are now closed, and each has a test that failed on the earlier version.
  - The tests also check Klipper's complete command list against a reviewed inventory, so a new command can't slip past unchecked.
- **Not yet proven:** anything needing the real machine. That covers wiring, switch polarity and the broken-wire check, directions, speeds, timing and spill behavior. These are tracked in `verification-register.md` and closed by the tests in WP1 and the umbrella §9.

## Where to read more

- `00-umbrella-plan.md`: the full plan.
- `diagrams.md`: pictures of the boards, power, wiring, the collision check and the phases.
- `phase0-survey.md` and `commissioning-sheet.md`: printable forms, one per machine.

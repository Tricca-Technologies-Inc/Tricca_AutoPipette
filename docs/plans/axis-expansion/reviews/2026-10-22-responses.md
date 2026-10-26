# Responses to the Focused Re-review of Rev J (applied in Rev K)

| Field    | Value |
|----------|-------|
| Status   | Closed: every finding answered in Rev K |
| Revision | K |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Review   | `2026-10-21-review-of-rev-J.md` |
| Date     | 2026-10-22 |

---

**Owner answers (2026-10-22):**
- Manual Z-probing and Z-endstop calibration aren't used on these machines (R2-S-1).
- Z 3 is high enough to clear everything (R2-S-3).

**Result:**
- **Rev K tests:** 55/55 in stage 1 and 52/52 in stage 2 (`reference/tests/results-2026-10-22.txt`).
- **Against the Rev J config:** every new refusal case fails. The positive control C-39c passes.

**Found while fixing.** The new strict log check exposed a bug in the first version of the unknown-letter guard. Klipper passes the command's own letter (`G`) as a parameter, so every `G28` was refused. It was fixed before release, which is exactly what the strict check is for.

## Earlier findings marked partly closed

| # | Response | Where |
|---|---|---|
| S-1 | The "every path" claim is now true and tested: the gaps below are closed, and C-45 compares Klipper's full command list with a reviewed inventory | Umbrella §6.2; `command-inventory.txt` |
| S-4 | Closed by R2-S-2 below | — |
| N-6 | Commissioning M-10 row says stage-1 cases only | Commissioning sheet |
| N-9 | §6.3 now lists every command tapd sends today (from `gcode_commands.py` at `a98439b`), including `STEPPER_BUZZ`, now guarded | Umbrella §6.3; WP4 §4 |

## New findings

| # | Response | Where |
|---|---|---|
| R2-S-1 | **Owner:** not used. `MANUAL_PROBE` and `Z_ENDSTOP_CALIBRATE` are refused outright (C-38, C-38b) | `plate-macros.cfg`; D13; §6.2; VR-31 |
| R2-S-2 | Stage-1 plunger branch clears the flag when the stepper is found disabled (the reviewer's tested fix). C-39 and C-39b refuse; C-39c (normal tapd use) keeps homed | `plate-macros.cfg`; I5; RB1 §4.1 |
| R2-S-3 | **Owner:** Z 3 clears every drawer. Recorded in D18 and §6.2, with a re-check trigger if `homing_retract_dist` or the mechanics change | D18; §6.2; VR-30 |
| R2-S-4 | CB1-6 moved from the Phase 4 exit to Phase 8 sign-off; machine records filled per machine during commissioning | Umbrella §7.1; WP3 CB1-6 |
| R2-N-1 | `_PLATE_PRECHECK` checks I1 and the range before `PLATE_MOVE` changes any state (C-41, C-41b) | `plate-macros.cfg` |
| R2-N-2 | `SET_GCODE_VARIABLE` on the interlock's macros added to every never-send list | §6.3; WP2 §4; WP4 §4; RB1 §4.1 |
| R2-N-3 | `SET_STEPPER_ENABLE … ENABLE=0` on a gantry stepper refused: use `M84` (C-40) | `plate-macros.cfg`; §6.2 |
| R2-N-4 | `stage2.patch.md` lists C-36s and C-37s | — |
| R2-N-5 | Wording now "every new **refusal** case"; positive controls named | WP2 §1; VR-06 |
| R2-N-6 | E-06 scope aligned: plates and plunger; Z steppers need plates parked | WP1 §10; commissioning sheet |
| R2-N-7 | Harness fails any log line that isn't on a short benign list or the expected refusal; verified on the reviewer's "Unknown g-code state" example | `run_offline_tests.py`; tests README |
| R2-N-8 | CB1-2 installs `dfu-util` system-wide; RB1 gives `nix run nixpkgs#dfu-util` for older generations | WP3 CB1-2; RB1 §5 |
| R2-N-9 | "Measured" changed to "label" rating | Umbrella Phase 0, K-HW-04 |
| R2-N-10 | Doc table CB1-1…CB1-7; header date | Umbrella |
| R2-N-11 | Stage-1 plunger frame behaviour documented as a known limit | WP2 §4 |
| R2-N-12 | Unknown `G28` letters refused (C-42 `G28 E`, C-42b `G28 XY`) | `homing_override.cfg.txt`; RB1 §4.1 |
| R2-N-13 | `SAVE_GCODE_STATE` refuses names with quotes or backslashes (C-43) | `plate-macros.cfg`; WP2 §4 |

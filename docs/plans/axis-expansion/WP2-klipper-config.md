# WP2 — Klipper Configuration (`Tricca_Autopipette_Configs`)

| Field    | Value |
|----------|-------|
| Status   | Draft for review (approval in the umbrella header) |
| Revision | L |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Parent   | `00-umbrella-plan.md` |
| Repo     | https://github.com/Tricca-Technologies-Inc/Tricca_Autopipette_Configs (base `d7c45ce`) |
| Date     | 2026-10-22 |

---

## 1. Purpose & Scope

The Klipper side of the upgrade: pipette and servo on the EBB, six plate steppers, axis binding (U V W A B C, P), homing, soft limits, collision interlock, and an offline test harness. Delivered as three issues: **CFG-1** (stage-1 config), **CFG-2** (offline tests), **CFG-3** (stage-2 config).

The reference implementation is in `reference/klipper/`; CFG-1 commits it (D33). The G-code contract other repos rely on is umbrella §6.3.

**Verification status (Rev K; rerun at Rev L with the Octopus V1.1 F446 firmware dictionary).** The reference config and test harness (`reference/tests/`) run in the pinned Klipper (7bc4d09) in batch mode: **55/55 cases pass in stage 1 and 52/52 in stage 2** (`reference/tests/results-2026-10-22.txt`).
- **Rev I** found and fixed a sign bug in `HOME_PIPETTE` that would have homed the plunger the wrong way (K-CFG-07), and fixed the interlock reporting the wrong reason when several checks failed.
- **Rev J** closed the bypasses found in the independent review: `RESUME`, `RESTORE_GCODE_STATE … MOVE=1`, `SET_GCODE_OFFSET … MOVE=1`, `STEPPER_BUZZ`, homed state surviving `M84`, re-zeroing the stage-2 plunger, and a template crash on an unbound plate. It also added a switch-release check to plate homing. Every new refusal case fails on the Rev I macros (positive controls such as C-26b pass on both).
- **Rev K** closed the second review's findings:
  - `MANUAL_PROBE` / `Z_ENDSTOP_CALIBRATE` are refused.
  - A Klipper-initiated motors-off (e.g. after a failed `G28`) can no longer leave the stage-1 plunger "homed".
  - `G28` with unknown letters is refused.
  - A refused `PLATE_MOVE` no longer changes the coordinate mode.
  - Gantry `ENABLE=0` is refused.
  - Saved-state names with quotes are refused.
  - The harness now fails on any unexpected log line and checks Klipper's **full command list** against a reviewed inventory (`reference/tests/command-inventory.txt`).
  
  Every new refusal case fails on the Rev J config.

Hardware behavior (real endstops, homing direction, timing) is still verified only by the M-tests.

## 2. Requirements (from umbrella §4)

R2, R3, R3a, R10–R12, R14, R16.

## 3. Design

### 3.1 File layout

| File | Change |
|---|---|
| `printer.cfg` | Add includes; no MCU sections (see `reference/klipper/printer.cfg.md`) |
| `tricca-autopipette.cfg` | Remove the pipette stepper/TMC/servo sections; replace `[homing_override]` with the section in `reference/klipper/homing_override.cfg.txt` (paste it; never commit that file); update the header comment |
| `ebb-pipette.cfg` (new) | `reference/klipper/ebb-pipette.cfg` |
| `octopus-plates.cfg` (new) | `reference/klipper/octopus-plates.cfg` |
| `plate-macros.cfg` (new) | `reference/klipper/plate-macros.cfg` |
| `tests/` (new, CFG-2) | Offline test harness. **Must not contain any root-level `*.cfg`**: cb1-autopipette seeds every root `*.cfg` onto machines |

### 3.2 Behavior summary

- **Interlock:** I1–I6 (umbrella §6.2), enforced in a `G1` wrapper (`G0` forwards to it) using raw coordinates. Every other Klipper command that can move Z or a plate is wrapped too:
  - `SET_GCODE_OFFSET … MOVE=1` and `RESTORE_GCODE_STATE … MOVE=1` are checked against I2 for the Z move they cause. `RESUME` returns through `RESTORE_GCODE_STATE`, so Resume after a Pause is checked too.
  - `STEPPER_BUZZ` on a plate needs the tip raised; on a Z stepper it is checked as a 1 mm descent.
  - `MANUAL_PROBE` and `Z_ENDSTOP_CALIBRATE` (always loaded by Klipper) are refused outright: their `TESTZ` moves Z directly, and the machine doesn't use them (owner, Rev K).
  - `G28 Z`'s own 3 mm homing retract dips the tip to raw Z 3, below `z_safe` 0. The owner confirmed Z 3 clears every drawer (Rev K). Re-check this if `homing_retract_dist` or the mechanics change.
  - `G28` with letters it doesn't know (`G28 E`, or `G28 XY` without a space) is refused instead of running a full home.
- **Plates:** homed and bound by `HOME_PLATE`; moved by `PLATE_*` macros or `G1` letters; `MANUAL_STEPPER` on a plate is refused unless called from the plate macros.
- **Plunger:**
  - Bound to P at startup.
  - Homed by `HOME_PIPETTE` (same zero point as tapd today).
  - Stage 1: tapd's `MANUAL_STEPPER STEPPER=pipette_stepper …` still works through a transparent unbind/rebind, and `SYNC=0` is refused.
- **Homing override:** bare `G28` = Z, X, Y, park, plates, plunger; `G28 <letters>` homes only what is named.
- **Plate homing:** fast pass to the switch, then the switch **must release** within `home_backoff` (otherwise homing fails), then a slow pass. A broken NC wire therefore fails homing instead of "homing" in place (D5).
- **Homed state:** macro flag AND stepper enabled. Cleared by `M84`/`M18`, `SET_STEPPER_ENABLE`, `ENABLE=0` and restart. When Klipper switches motors off itself (a failed `G28` calls `motor_off` directly, bypassing `M84`), the next plunger command sees the stepper disabled and clears the flag. `SET_STEPPER_ENABLE … ENABLE=0` on a gantry stepper is refused (use `M84`): Klipper would keep that axis "homed". In stage 2 (`variable_stage: 2`), any direct `MANUAL_STEPPER` on the plunger also clears it, so only `HOME_PIPETTE` sets the plunger's zero.
- **Park after a lettered `G28`:** only axes that are homed afterwards move, so `G28 X` on a cold machine works.

## 4. Known Limits (documented in `plate-macros.cfg`)

- **Commanded state only.** Skipped belt steps aren't detected. Hard stops and re-homing at each `G28` mitigate this.
- **Every path that moves Z or a plate is listed and checked** (header of `plate-macros.cfg`; umbrella §6.2). This is enforced: test C-45 compares Klipper's full registered-command list with `reference/tests/command-inventory.txt`, where every command is classified. A new command, from a config section, a Mainsail update or Klipper itself, fails the tests until someone classifies it and adds a check if it can move anything. Raw coordinates make the checks immune to G92 and offsets when *reading* position; commands that *move* because of an offset (`MOVE=1`) are wrapped separately. Keep `[force_move] enable_force_move: False` (FORCE_MOVE, SET_KINEMATIC_POSITION), and never enable `[gcode_arcs]`. Any new config section that adds motion commands (probe, Z tilt, bed mesh, arcs) needs its own check before it is added.
- **The renamed originals bypass the checks by design:** `G1.1`, `G0.1`, every `*_BASE` command (`MANUAL_STEPPER_BASE`, `SET_STEPPER_ENABLE_BASE`, `STEPPER_BUZZ_BASE`, `SET_GCODE_OFFSET_BASE`, `SAVE_GCODE_STATE_BASE`, `RESTORE_GCODE_STATE_BASE`, `MANUAL_PROBE_BASE`, `Z_ENDSTOP_CALIBRATE_BASE`), `M84.1`, `M18.1`, anything with `_PLATE_INTERNAL=1`, and `SET_GCODE_VARIABLE` on `_PLATE_CFG`, `_PLATE_STATE`, `_PIPETTE_CFG`, `_PIPETTE_STATE` or `_GSTATE`. Klipper can't hide them. tapd never sends them (TAP-1 golden test), and operators must not type them. Because `M84` clears every homed flag, re-enabling a motor through a base command still leaves it unhomed.
- **Stage-2 plunger:** a direct `MANUAL_STEPPER` on the plunger clears its homed flag even when Klipper then refuses the command (fails safe).
- **Stage-1 plunger frame is tapd's:** any `home`/`inverted_home` move sets the flag, and tapd re-zeroes with `SET_POSITION` around every syringe operation. That's acceptable because stage 1 has no plunger limits and tapd doesn't send `G1 P` until stage 2.
- **Saved-state names must not contain quotes or backslashes** (`SAVE_GCODE_STATE` refuses them). The wrapper stores each state's raw Z in a macro variable that can't round-trip those characters.
- **Every G1 runs a Jinja template.** Latency is measured in M-15.
- **Rebinding flushes the motion lookahead.** Each tapd plunger command unbinds/rebinds P and both steps flush lookahead (stage 1 only).
- **A failed pipette command leaves P unbound.** The G1 guard refuses `G1 P` until the next pipette command rebinds it.
- **In stage 1, tapd's own `SET_POSITION=0` moves the P frame.** Don't mix tapd plunger commands with `G1 P` until stage 2.
- **`G92 P` does nothing.** Klipper's G92 only covers X/Y/Z/E; deliberately not overridden (D26).
- **Axis indices shift when steppers bind/unbind.** Always look positions up via `gcode_move.axis_map`.
- **Never write `{-x}` in a template.** Klipper templates use single braces, so `{-` is Jinja whitespace control and the minus sign is silently dropped. Write `{0 - x}`. The harness lints for this (K-CFG-07).
- **Jinja comments `{# … #}` don't work.** Klipper's config parser strips everything after `#` first. Use ordinary `#` config comments.
- **First failing check wins.** The interlock reports the most basic cause (e.g. "Z not homed" before "plate1 not homed").

## 5. Offline Tests (run by CFG-2's harness)

Batch mode feeds G-code to klippy with each MCU's `klipper.dict` (from WP1 §7) instead of real boards. A test either homes with `G28` (batch-mode homing moves run to their target) or sets homed state directly through the test-only `_T_HOME_PLATE` macro. The reference harness and its limits are in `reference/tests/README.md`. For every refusal case the harness also checks that **nothing moved**, and any template crash fails the case.

**Result** = outcome of the Rev J run against the reference config. "Stage 1" and "Stage 2" mark cases that run only in that stage; all others run in both.

| ID | Script | Expect | Result |
|---|---|---|---|
| C-01 | Config loads with all includes | No config errors | Pass |
| C-02 | `G1 U10` with Z unhomed | Refused: "Z not homed" | Pass |
| C-03 | Z homed, Z=0, plates homed: `G1 U10` | Accepted; U = 10 | Pass |
| C-04 | Z=20 (> z_safe): `G1 U10` | Refused: tip below safe height | Pass |
| C-05 | plate1 at 10 (mid-travel): `G1 Z20` | Refused: plate1 mid-travel | Pass |
| C-06 | All plates at 0 or 350: `G1 Z20` | Accepted | Pass |
| C-07 | `G1 Z20 U0` | Refused | Pass |
| C-08 | `MANUAL_STEPPER STEPPER=plate1 MOVE=5` | Refused; with `_PLATE_INTERNAL=1` accepted (C-08b) | Pass |
| C-09 | `G91` relative Z descent with a plate mid-travel | Refused | Pass |
| C-10 | `SET_GCODE_OFFSET Z=30` then `G1 Z0` (commands raw Z 30), a plate mid-travel | Refused (raw coordinates, D14) | Pass |
| C-11 | `G0 U10` with Z lowered | Same as `G1` | Pass |
| C-12 | `G1 U351` | Klipper out-of-range error | Pass |
| C-13 | Stage 1: tapd-style `MANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0` / `MOVE=-5` | Executes; P bound again afterwards | Pass |
| C-13s | Stage 2: the same plain `MANUAL_STEPPER` on the bound plunger | Refused by Klipper ("Must unregister…") | Pass |
| C-14 | After startup | `P` in `gcode_move.axis_map` | Not testable offline (timer doesn't fire); body tested as C-14b, timer on hardware M-13 |
| C-14b | `_PIPETTE_BIND` (the startup body) | P bound | Pass |
| C-15 | `G1 P-5` before plunger homing | Refused: plunger not homed | Pass |
| C-16 | Stage 1: tapd's homing sequence, then `G1 P-2` | All accepted; homed; P bound; P = −2 | Pass |
| C-17 | Stage 2: `G28 P`, `G1 P-61` | Out-of-range error | Pass |
| C-17b | Stage 2: `G28 P`, `G1 P-2` | Accepted; P = −2 | Pass |
| C-17c | Stage 2: `G28 P`, `G1 P1` (past the switch) | Out-of-range error | Pass |
| C-18 | Stage 1: `MANUAL_STEPPER STEPPER=pipette_stepper MOVE=1 SYNC=0` | Refused | Pass |
| C-19 | `M84`, then re-home Z, then `G1 U5` | Refused: plate1 not homed | Pass |
| C-19b | Stage 1: `M84`, then `G1 P-1` (C-19s is the stage-2 equivalent) | Refused: plunger not homed | Pass |
| C-19c | `SET_STEPPER_ENABLE … ENABLE=0` then `ENABLE=1`, then `G1 U5` | Refused: plate1 not homed | Pass |
| C-20 | Stage 1: P unbound (as after a failed pipette command), then `G1 P-1` | Refused: P not bound | Pass |
| C-21 | `G28 U` with Z unhomed | Refused | Pass |
| C-22 | Bare `G28` | Gantry homed; six plates homed and bound; plunger homed and bound | Pass |
| C-23 | `G28 X Y` | X and Y homed; parks at X150 Y150; plates and plunger untouched. The park moves only homed axes (Z0 only if Z was already homed) | Pass |
| C-24 | `G28 P` | Only the plunger homed and bound | Pass |
| C-25 | `G28 P`, `G92 P5` | No effect on P | Pass |
| C-26 | Tip low, `PAUSE`, raise tip, plate1 out to 100, `RESUME` | Refused: plate1 mid-travel; nothing moves | Pass |
| C-26b | Same with the plates parked | `RESUME` returns the tip to Z20 | Pass |
| C-27 | `RESTORE_GCODE_STATE … MOVE=1` back down onto a mid-travel plate | Refused | Pass |
| C-27b | `RESTORE_GCODE_STATE NAME=<never saved> MOVE=1` | Refused | Pass |
| C-27c | `PLATE_OUT` (uses SAVE/RESTORE without MOVE) | Still works | Pass |
| C-28 / C-28b | `SET_GCODE_OFFSET Z_ADJUST=20 MOVE=1` / `Z=20 MOVE=1`, plate mid-travel | Refused | Pass |
| C-28c | `SET_GCODE_OFFSET Z_ADJUST=5 MOVE=1`, plates parked | Accepted; Z = 5 | Pass |
| C-30 | `STEPPER_BUZZ` on a plate with the tip low | Refused | Pass |
| C-30b | `STEPPER_BUZZ STEPPER=stepper_z`, plate mid-travel | Refused | Pass |
| C-31 | `M84`, re-enable plate1 with `SET_STEPPER_ENABLE_BASE`, `G1 U5` | Refused: plate1 not homed | Pass |
| C-32 / C-32b | Stage 1: `M84`, then a tapd-style `try_home` move / `ENABLE=1`, then `G1 P` | Refused: plunger not homed | Pass |
| C-33 | `G28 X` on a cold machine | X homed, parks X only, no error | Pass |
| C-34 | A plate flagged homed but unbound, then `G1 Z20` | Refused cleanly: plate1 not homed (no template crash) | Pass |
| C-35 | `g1 u10` (lower case) with the tip low | Refused | Pass |
| C-36s | Stage 2: unbind the plunger, `SET_POSITION=0`, rebind, `G1 P-5` | Refused: plunger not homed (frame can't be moved without re-homing) | Pass |
| C-37s | Stage 2: `M84`, base re-enable, `G1 P-5` | Refused: plunger not homed | Pass |
| C-38 / C-38b | `MANUAL_PROBE` / `Z_ENDSTOP_CALIBRATE` | Refused (disabled on this machine) | Pass |
| C-39 / C-39b | Stage 1: motors off by Klipper itself (`motor_off`, as after a failed `G28`; batch mode emulates it with `M84.1`), then `ENABLE=1` / a tapd `try_home` move, then `G1 P` | Refused: plunger not homed | Pass |
| C-39c | Stage 1: normal tapd re-zero and move, then `G1 P-2` | Accepted; still homed (positive control) | Pass |
| C-40 | `SET_STEPPER_ENABLE STEPPER=stepper_z ENABLE=0` | Refused: use `M84` | Pass |
| C-41 / C-41b | `G91`, then a refused `PLATE_MOVE` (tip low / beyond travel) | Refused before any change; still relative mode | Pass |
| C-42 / C-42b | `G28 E` / `G28 XY` | Refused: unknown axis (no full home) | Pass |
| C-43 | `SAVE_GCODE_STATE NAME="it's"` | Refused | Pass |
| C-45 | Klipper's registered commands vs `command-inventory.txt` | Identical (every command classified) | Pass |

## 6. Issues

File in `Tricca_Autopipette_Configs` if its issue tracker is enabled; otherwise in `cb1-autopipette` with a `configs:` title prefix. Labels per D32.

---

### CFG-1 — Stage-1 Klipper config: EBB pipette, Octopus plates, axis binding, homing, interlock

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** — (develop now; merge needs CFG-2 green)
- **Blocks:** CB1-5, all on-machine phases, TAP-2…TAP-5

**Context.** The machine gains six plate drawers on an Octopus V1.1 (non-Pro, F446) and moves the pipette plunger and servo to an EBB42 CAN board (umbrella §1). The M8P becomes a USB-to-CAN bridge. Klipper must expose the new axes safely and keep today's tapd working.

**Goal.** Commit the stage-1 config from `reference/klipper/` with the §3.1 edits, matching umbrella §6.2 (interlock) and §6.3 (G-code contract) exactly.

**In scope.** §3.1 files; header comments naming the matching firmware Kconfig; a README section describing the new files, the interlock, and that MCU IDs are machine-written.

**Out of scope.** Plunger soft limits and `variable_stage: 2` (CFG-3). Any `[mcu …]` section with an ID.

**Acceptance criteria.**
- The harness's stage-1 case set passes in CFG-2's harness (§5), including the lint.
- Every value marked `PROPOSED` (umbrella §8) is listed in the PR description with the owner's sign-off.
- The PR notes the `G28` behaviour changes (K-OPS-03: all named axes home; the park moves only homed axes), that `[gcode_arcs]` must never be enabled, and the list of renamed base commands nobody may send (§4).
- `pipette_stepper`'s `rotation_distance` / issue #29 comment is carried over verbatim.

**Rollback.** Revert the PR; machines are unaffected until CB1-5 bumps the pin and RB1 migrates them.

**Notes.**
- The reference code is a starting point: fix bugs, but don't weaken I1–I6 or D21–D24.
- `printer.configfile.settings` keys are lower-case section names; confirm value types in C-tests (K-CFG-04).

---

### CFG-2 — Offline Klipper test harness (batch mode) for the config set

- **Labels:** `needs-triage`
- **Blocked by:** WP1 Phase 1 (`klipper.dict` files)
- **Blocks:** merge of CFG-1, CFG-3

**Context.** The interlock is safety-relevant and must be tested before it reaches hardware. Klipper can run without boards in batch mode, given each MCU's protocol dictionary.

**Goal.** A repeatable harness under `tests/` that runs klippy (the pinned Klipper) in batch mode against the repo's config, feeds the C-test G-code scripts, and asserts on klippy's output and errors.

**In scope.**
- Commit `reference/tests/` (runner, `test-harness.cfg`, `make_fixture.py`, README) under `tests/`. It already runs the §5 cases against stage 1 and stage 2 and passes on the reference config.
- A wrapper usable from a workstation via `nix shell --inputs-from <cb1-autopipette>` (pinned Klipper and its Python).
- A documented way to produce the four `.dict` files (WP1 §7), or commit them under `tests/dicts/` together with the firmware Kconfig they came from.

**Out of scope.** CI wiring (follow-up once the harness is stable).

**Acceptance criteria.**
- One command runs all C-tests and exits non-zero on any failure.
- The lint (`{-`; stage variable vs plunger limits) runs and fails the build.
- Refusal cases check that nothing moved; template crashes and any unexpected log line fail the case.
- The command-inventory case (C-45) is part of the run.
- No `*.cfg` at the repo root is added by this issue.
- The batch-mode facts in `reference/tests/README.md` are re-checked if the Klipper pin changes.

**Rollback.** Delete `tests/`.

---

### CFG-3 — Stage-2 config: plunger soft limits, stage switch

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** TAP-6 (merged, not yet deployed), CFG-1
- **Blocks:** CB1-7 (stage-2 pin bump)

**Context.** Once tapd homes with `G28 P` and moves the plunger with absolute `G1 P` (TAP-6), the stage-1 compatibility path is no longer needed. Switching it off lets Klipper enforce plunger travel limits.

**Goal.** Apply `reference/klipper/stage2.patch.md`: `variable_stage: 2` plus the plunger soft limits, in one PR.

**Acceptance criteria.**
- The harness's stage-2 case set passes (stage read from `variable_stage`; the lint checks it agrees with the limits). That includes C-17…C-17c, C-13s, C-36s (the plunger can't be re-zeroed without homing) and C-37s. All of these were verified against a reference stage-2 fixture at Rev J.
- Deployed **only together with** TAP-6 in one switch (CB1-7).
- M-20 and M-21 pass on hardware; M-22 too if TAP-7 is implemented.

**Rollback.** Revert the PR before deployment. After deployment, CB1-7 switches both pins (configs + tapd) back together. Machine-owned configs that were migrated to stage 2 are reverted by setting `variable_stage: 1` and removing the two limit lines (RB1 §5).

## 7. Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| H | 2026-10-20 | James / Claude | Split out of the single plan (Rev G §8, §10.2). Reference code moved to `reference/klipper/`. Plate travel 350 mm, homing 50 mm/s. Issues CFG-1…CFG-3; C-tests renumbered |
| I | 2026-10-20 | James / Claude | Reference config verified in pinned Klipper (batch mode), both stages, 27/27 each. Fixed: `HOME_PIPETTE` sign bug (`{-` dropped the minus), first-error-wins interlock message. Added `reference/tests/`, Result column, C-13s/C-14b/C-17b/C-17c/C-19s. C-23 expectation corrected (park commands Z0). Known limits: `{-`, Jinja comments |
| J | 2026-10-21 | James / Claude | Independent-review fixes: wrapped `SET_GCODE_OFFSET`, `SAVE`/`RESTORE_GCODE_STATE` (covers `RESUME`), `STEPPER_BUZZ`, `M84`/`M18`; stage variable replaces deleting the stage-1 branch; stage-2 plunger can't be re-zeroed without homing; plate homing checks switch release; park only homed axes; unbound plate guard. Harness: nothing-moved check on refusals, template-crash detection, stage lint, `make_fixture.py`; 43/43 each stage. Known limits rewritten (§4). CFG-3 now blocks CB1-7 |
| K | 2026-10-22 | James / Claude | Second-review fixes: `MANUAL_PROBE`/`Z_ENDSTOP_CALIBRATE` refused (owner doesn't use them); plunger flag cleared when Klipper disabled the stepper itself; `G28` unknown letters refused (and the `G` letter bug that check found); `PLATE_MOVE` pre-check; gantry `ENABLE=0` refused; quoted state names refused; `G28 Z` 3 mm retract owner-confirmed. Harness: strict log check, command inventory (C-45); 55/55 stage 1, 52/52 stage 2 |
| L | 2026-10-22 | James / Claude | Plate controller is the Octopus V1.1 (non-Pro, F446): `octopus-plates.cfg` uses Klipper's non-Pro pin map (Driver3 enable PA0). Harness rerun with the F446 dictionary: 55/55 stage 1, 52/52 stage 2 |

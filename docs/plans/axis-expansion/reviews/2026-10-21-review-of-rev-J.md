> Reviewer's report, kept verbatim. Paths under `scratchpad/` refer to the reviewer's workspace and aren't part of the package. Its probe and motors-off cases are now regression tests C-38…C-39c. Responses: `2026-10-22-responses.md`.

# Focused Re-review of Rev J — AutoPipette Axis Expansion Plan

Reviewer: independent agent. I did not write the plan or its fixes. Date: 2026-10-21.

- **Package.** `/home/claude/autopipette-plan/`, which is byte-identical to `autopipette-plan-revJ.zip` (checked with `diff -r`).
- **Klipper.** Pinned rev `7bc4d09465d31cd30fc0822e8d0abe02cc8c547f` (`scratchpad/kpin`).
- **Repos.** Pinned SHAs as in umbrella §14.
- **Workspace.** All work was done on copies under `scratchpad/review2/`. I edited nothing in the package, and no `__pycache__` is left in it.

## 1. Verdict

**Approve with fixes.**

The blocker is closed. `RESUME`, `RESTORE_GCODE_STATE … MOVE=1` and `SET_GCODE_OFFSET … MOVE=1` are now refused whenever they would lower the tip onto an unparked or unhomed drawer. That holds with:
- Mainsail's real `RESUME`/`CANCEL_PRINT`;
- the machine's own `PAUSE` override;
- `PLATE_MOVE`;
- odd state names;
- 300 saved states;
- lower-case commands.

Each of these has a batch case.

The harness reproduces:
- **Rev J:** 43/43 in each stage, on fixtures I built fresh.
- **Rev I macros:** exactly the 11 cases claimed fail in stage 1, plus C-36s and C-37s in stage 2.

Of the 31 findings, 27 are fully closed and 4 are partly closed. None are open.

The package's central claim is still not true. D13, §6.2, WP2 §4 and the header of `plate-macros.cfg` say that *every* Klipper path that can move Z or a plate is checked. Three paths are not:
1. **`MANUAL_PROBE` / `Z_ENDSTOP_CALIBRATE` + `TESTZ`.** `manual_probe` is always loaded, and `TESTZ` lowers the tip onto a drawer that is mid-travel.
2. **A failed `G28`.** Klipper calls `motor_off()` directly, not through the `M84` wrapper. In stage 1 the plunger then keeps its "homed" flag after it is re-enabled.
3. **`G28 Z` homing retract.** It dips the tip 3 mm with no check, including in the E-stop recovery drill.

None of these is reached by tapd in normal operation, so none is a blocker. Fix (1) before CFG-1 merges. That gates Phase 3, so Phases 0–2 can start now. There is also one phase-gating cycle left over from before Rev J (CB1-6 against the Phase 4 exit), and 13 nits.

**Counts:**
- Response verification: 27 closed, 4 partially closed (S-1, S-4, N-6, N-9), 0 not closed.
- New findings: 0 blockers, 4 shoulds, 13 nits.

## 2. Response verification

| Finding | Status | Evidence |
|---|---|---|
| B-1 | **Closed** | `plate-macros.cfg:130-171` wraps `SET_GCODE_OFFSET`, `SAVE`/`RESTORE_GCODE_STATE` and `_CHECK_Z_DESCENT`. Klipper at the pin agrees: `gcode_move.py:207-226` (OFFSET: `Z` takes precedence over `Z_ADJUST`, delta taken from `homing_position`) and `:239-260` (RESTORE moves only XYZ to the saved `last_position`). `pause_resume.py:76-86`: RESUME runs RESTORE before `is_paused=False`, so a refusal leaves the run paused. Harness C-26…C-28c pass. My cases R07, R12, R13, R14, R16, R22, R24, R42 and T01 are refused. The legitimate cases R08, R11, R15, R18, R19, R20, R21, R23 and R45 work |
| S-1 | **Partially closed** | The "can't fool" wording is corrected (D14 `00-umbrella-plan.md:187`; `diagrams.md` §5). The new claim that the path list is complete is false (`00-umbrella-plan.md:186,242`; `WP2:46,62`; `plate-macros.cfg:21`): see R2-S-1, R2-S-2 and R2-S-3 |
| S-2 | **Closed** | `plate-macros.cfg:173-187`. C-30 and C-30b pass. R32 (`stepper_z1`) is refused and R33 (plate, tip raised) is allowed. The WP1 E-06 wording is now inconsistent: R2-N-6 |
| S-3 | **Closed** | `M84`/`M18` wrappers at `plate-macros.cfg:90-100`. C-31, R25 (`M84 X`) and R26 (`M18`) are refused after a base re-enable. The never-send list is in the §6.3 contract, WP2 §4, WP4 §4 (S-TAP1-4), RB1 §4.1 and K-OPS-05 |
| S-4 | **Partially closed** | The M84 route is closed (C-32, C-32b). The same end state is reachable when a G28 fails: `homing.py:337-354` calls `stepper_enable.motor_off()` directly, so no macro runs. Emulated with `M84.1`, which uses the same code path (`stepper_enable.py:116-129`): R03 and R04 accept `G1 P`. See R2-S-2 |
| S-5 | **Closed** | `plate-macros.cfg:237-241` (stage-2 branch). C-36s and C-37s pass. T03 (ENABLE=1) and T07 (manual rebind) are refused; Klipper itself refuses a plain MOVE (C-13s). The stage-1 re-zero is still possible, by design (R37); see R2-N-11 |
| S-6 | **Closed in config; hardware proof pending (M-23 / VR-29)** | `plate-macros.cfg:354` backs off with `STOP_ON_ENDSTOP=inverted_home`. At the pin, `manual_stepper.py:107-128` maps `inverted_home` to triggered=False with check_trigger=True, so "No trigger … after full movement" is raised if the switch never releases. A failed HOME_PLATE leaves the plate unbound with the flag at 0, and C-34's guard then refuses it |
| S-7 | **Closed** | Powered E-tests moved to the Phase 7 exit (`00-umbrella-plan.md:305`; WP1 §10 phase column; `commissioning-sheet.md:20-39`, in phase order). The Phase 5 and 6 exits only list unpowered or non-Klipper tests |
| S-8 | **Closed** | CB1-5 is stage 1 only and CB1-7 is the stage-2 bump (`WP3:153-188`; umbrella `:288,302,308`). The same kind of cycle remains for CB1-6: R2-S-4 |
| S-9 | **Closed** | TAP-6 blocks CFG-3 and CB1-7 (`WP4:203-205`). CFG-3 is blocked by TAP-6 and blocks CB1-7 (`WP2:196-197`). CB1-7 is blocked by both (`WP3:176`). The graphs in umbrella §7.2 and WP4 §6 match. No cycle |
| S-10 | **Closed** | §6.4, Phase 9 and Phase 10 (`00-umbrella-plan.md:285,307-308`), M-22 conditional (`:372`), TAP-7 "Stage 2 … optional" (`WP4:247`), `diagrams.md:148` |
| S-11 | **Closed** | D34. No ID fields in CB1-6 (`WP3:200`), the RB1 §6 template (`RB1:119`), the commissioning sheet or phase0. A grep for UUID or serial patterns across the package finds nothing |
| S-12 | **Closed** | Rollbacks are on CB1-1…CB1-4, CB1-6 and CB1-7. WP4 §4 has a blanket TAP rule (`WP4:61`), and TAP-6 and TAP-10 have their own |
| S-13 | **Closed** | RB1 §5 order: unplug the Octopus, then `flash-manta --firmware` on the new generation, then switch (`RB1:98-108`). The DFU address `0x08020000` matches today's `flash-manta` (`cb1 modules/aliases.nix:205`) and the Kconfigs (`*_FLASH_START_20000`). One nit about `dfu-util` not being on PATH: R2-N-8 |
| S-14 | **Closed** | R7 is rewritten. WP1 §4, phase0 and E-08 use 50%/70% of the label rating. Wording nit: R2-N-9 |
| S-15 | **Closed** | ⛔ before the first M8P reflash (Phase 5 entry; `WP1:206-212`) and before rewiring (Phase 6; `WP1:217`) |
| S-16 | **Closed** | H-01 no longer claims belts skip; it is now the owner's solution (VR-28) |
| S-17 | **Closed (as scoped)** | (a) `CRASH_RE` fails any non-CommandError "Error evaluating": the Rev I macros show a TEMPLATE CRASH on C-34. (b) `with_state_probe` compares positions before and after on every refusal. (c) README has a batch-mode limits table. A remaining gap in error detection is R2-N-7 |
| N-1 | Closed | `plate-macros.cfg:11` "section 6.2", `:367` "section 6.3"; the octopus header is updated |
| N-2 | Closed | `diagrams.md` §3 (same switch and polarity as today); E-05 |
| N-3 | Closed | `homing_override.cfg.txt:35-42`; C-33. R28 (`G28 Z U` cold) and R29 work |
| N-4 | Closed | `plate-macros.cfg:307,312` guard on `ax in gm.axis_map`; C-34 |
| N-5 | Closed | `WP3:30` |
| N-6 | **Partially closed** | Umbrella M-10 is fixed, but `commissioning-sheet.md:61` still says "C-14…C-25", which includes the stage-2 C-17… |
| N-7 | Closed | `commissioning-sheet.md:46` |
| N-8 | Closed | `RB1:67,88` |
| N-9 | **Partially closed** | §6.3 now lists G90/G91, M84, SET_SERVO, SET_VELOCITY_LIMIT, pause/resume and the never-send list. It still lacks commands tapd emits today: `M400`, `M117`, `SET_PIN`, and others such as `SET_LED`/`SET_FAN_SPEED` (`tricca_autopipette` `core/gcode_commands.py:173,308,377`). WP4 §4 says tapd consumes "exactly" the §6.3 commands |
| N-10 | Closed | `homing_override.cfg.txt`; no stale `.cfg` references |
| N-11 | Closed | `WP3:161,165` |
| N-12 | Closed | `SUMMARY.md:29` |
| N-13 | Closed | `WP1:61`; VR-04 |

## 3. New findings (most severe first)

| # | Doc / section | Finding | Severity | Evidence |
|---|---|---|---|---|
| R2-S-1 | `plate-macros.cfg` header `:21-28`; umbrella D13 `:186`, §6.2 `:242-253`, K-CFG-03 `:432`; WP2 `:46,62`; `review-checklist.md:15` | **Interlock bypass via manual probe.** `manual_probe` is one of Klipper's always-loaded modules, not a config section. It registers `MANUAL_PROBE`, plus `Z_ENDSTOP_CALIBRATE` because `stepper_z` has a `position_endstop`. Inside a probe session, `TESTZ Z=<n>` calls `toolhead.manual_move([None,None,z])` with no G1, so the tip goes to raw Z 20 with plate1 at U=100. The checklist's rule ("grep `^\[` for sections that add motion") cannot catch this.<br><br>**Fix.** `TESTZ` can't be wrapped, because it is registered only when a session starts. Wrap `MANUAL_PROBE` and `Z_ENDSTOP_CALIBRATE` with `rename_existing` and **refuse them outright**. An entry check alone is not enough: F07 moves a plate after the probe starts and then runs `TESTZ`. Alternatively, make G1/PLATE_* refuse plate moves while `printer.manual_probe.is_active`. Add a C-test, a §6.2 row and a checklist line for default-loaded modules (`toolhead.py:611-612`). | **should** (fix before CFG-1 merges) | `kpin/klippy/toolhead.py:611-612`; `extras/manual_probe.py:41,67-70,246-252,301-328`. Cases R01, R02, T02 (Z=20 or 15, U=100, no error). The entry-guard prototype refuses F01/F02 but **not** F07 |
| R2-S-2 | `plate-macros.cfg:242-257` (stage-1 pipette branch); I5 / D15 / R12; RB1 §4.1 | **Failed G28 leaves the stage-1 plunger "homed".** When gantry homing fails, `PrinterHoming.cmd_G28` calls `stepper_enable.motor_off()` directly, so the M84 macro never runs and `_PIPETTE_STATE.homed` stays 1. In stage 1, re-enabling the plunger keeps the flag; the S-4 path is open again. Both tapd's next `MANUAL_STEPPER … try_home` move (auto-enables) and `MANUAL_STEPPER … ENABLE=1` do this. `G1 P` is then accepted without re-homing. Plates are still safe because G1 also checks the live enable state and nothing re-enables a plate without clearing its flag (R05).<br><br>**Fix (tested).** At the top of the stage-1 branch, clear `homed` if `printer.stepper_enable.steppers['manual_stepper pipette_stepper']` is false. R03 and R04 become refusals (F04, F05), the normal tapd sequence keeps homed (F06), and the full harness still gives 43/43. Add a C-test, and add "a failed G28" to I5 and RB1 §4.1. | **should** | `kpin/klippy/extras/homing.py:337-354`; `stepper_enable.py:116-120`. R03 (P=−1 accepted, pip_homed=1) and R04 (P=−3). M84.1 is used to drive the identical `motor_off()` because batch homing can't fail |
| R2-S-3 | umbrella §6.2 path table (`G28` row covers only I4), R11; RB1 §4.2 step 5 | **`G28 Z` dips the tip with no check.** `stepper_z` has `homing_retract_dist: 3`, with Z+ lowering the tip. Every Z homing retracts to raw Z = 3 before the slow pass. That is below `z_safe` = 0, whatever the drawers are doing. It happens in the documented E-stop recovery (bare `G28` after a stop that may leave a drawer mid-travel), and on tapd `home z`. This was already true before Rev J, but Rev J's "every path" table omits it. **Fix:** record the real tip-to-drawer clearance at Z = 3 (new VR item), or set `z_safe` ≥ 3, or home Z with `homing_retract_dist: 0`. List the path in §6.2 either way. | **should** | `tricca-autopipette.cfg:79-85` (configs repo, d7c45ce); `kpin/klippy/extras/homing.py:199-202`. R30 accepts `G28 Z` with U=100 (batch mode can't show the retract) |
| R2-S-4 | umbrella §7.1 Phase 4 (`:302`), §7.2; WP3 CB1-6 (`:192-211`); RB1 §6 | **Phase-gate cycle (same class as S-8; present before Rev J).** The Phase 4 exit requires CB1-1…CB1-6 "merged, primed, switched". CB1-6's machine record must contain firmware SHA-256s and the "Phase 0 survey and commissioning results" (RB1 §6: "Tests M-01…M-19, M-23"), which only exist after Phase 8, and CB1-6 itself says "merged before Phase 8 sign-off". Read literally, Phase 4 can't exit until Phase 8, which needs Phase 4. **Fix:** move CB1-6 out of the Phase 4 exit (it gates Phase 8 sign-off), or split it into ADR/README (Phase 4) and machine record (Phase 8). | **should** | `00-umbrella-plan.md:302,314`; `WP3-cb1-deployment.md:194-209` |
| R2-N-1 | plate-macros `PLATE_MOVE` (`:368-378`) | A refused `PLATE_MOVE` (for example, tip low) aborts after its own `G90`, so the `RESTORE` never runs. Klipper is left in **absolute** mode. A following relative move from the console or tapd is then read as absolute: in R46, a relative `G1 Z-5` went to raw Z = −5. The interlock still checks the real target, so there's no collision bypass, but the mode change is unexpected. This was true before Rev J, and refusals are now a normal event. Run the interlock check before `SAVE`/`G90`, or don't change the mode. | nit | R46 (mode true after refusal); R47 (mode false after success) |
| R2-N-2 | §6.3 never-send list; RB1 §4.1; K-OPS-05 | `SET_GCODE_VARIABLE` on `_PLATE_CFG` (for example `z_safe=100`), `_PLATE_STATE`, `_PIPETTE_STATE` or `_GSTATE` defeats every check (R35 accepts `G1 Z20` then `G1 U50`). It belongs to the same class as `_PLATE_INTERNAL`, but it isn't listed as never-send. | nit | R35 |
| R2-N-3 | umbrella §6.2 I5 row; plate-macros `SET_STEPPER_ENABLE` wrapper `:263-273` | `SET_STEPPER_ENABLE STEPPER=stepper_z ENABLE=0` keeps Z "homed" in Klipper (only `motor_off` clears kinematic homing), so `G1 U` is still accepted (R34). With 4-start T8 lead screws (`rotation_distance: 8`) an unpowered gantry may sag. I5 says a disabled stepper becomes unhomed. Refuse `ENABLE=0` on `stepper_z*` in the wrapper, or document it. | nit | `stepper_enable.py:131-134`; R34 |
| R2-N-4 | `reference/klipper/stage2.patch.md:23` | Lists "C-26s", which doesn't exist, and omits C-36s and C-37s, which CFG-3's AC requires. | nit | ID cross-check script: C-26s is the only doc-referenced ID missing from the harness besides C-14 (documented as not testable) |
| R2-N-5 | Responses `:24`; WP2 §1 (`:23`); VR-06 | "Every new case fails on the Rev I macros" overstates it. C-26b, C-27c and C-28c are positive controls, and C-33 and C-35 also pass on Rev I macros. `results-2026-10-21.txt` lists the 11 failing cases correctly. | nit | `harness-revI-macros-stage1.txt`: 12 failures (lint + 11) |
| R2-N-6 | WP1 E-06 (`:236`) vs `commissioning-sheet.md:36` | WP1 says "STEPPER_BUZZ each stepper, drawer mid-travel", and on a Z stepper that is exactly what C-30b refuses (and at Phase 7 the plates aren't homed). The sheet says "each plate". Align them on plates (plus X/Y/plunger), or say Z steppers need the plates homed and parked. | nit | C-30b; R32 |
| R2-N-7 | `run_offline_tests.py:157-160` | `ERR_RE` lists only six error shapes. Any other CommandError, such as "Unknown g-code state", "Unable to parse" or "Unknown stepper", is invisible, so `noerror`/`state` cases pass despite it. For example, C-27c would still pass if `RESTORE_GCODE_STATE` started failing. Check that no `!!`/error line appears except the expected one. | nit | R43: `check(log,'noerror')` and `check(log,'state:…')` both return True with "Unknown g-code state: zzz" in the log |
| R2-N-8 | RB1 §5 step 3 fallback; CB1-2 rollback | The bare `dfu-util …` command isn't on the machine's PATH. cb1-autopipette only uses `${pkgs.dfu-util}` inside `flash-manta`, and `environment.systemPackages` doesn't include it. Give `nix run nixpkgs#dfu-util -- …` (or a store path), or have CB1-2 install it. | nit | `cb1 modules/aliases.nix:205`; `modules/base.nix:8-15` |
| R2-N-9 | Umbrella Phase 0 ⛔ (`:298`), K-HW-04 (`:427`) | These say "PSU's **measured** rating", while R7, WP1 §4, phase0 and the S-14 response all use the **label** rating. | nit | grep "rating" |
| R2-N-10 | Umbrella §1 doc table (`:42`); header date (`:9`) | WP3 is listed as "CB1-1…CB1-6" (README says …CB1-7). The header date is 2026-10-20 for Rev J, while §15 says 2026-10-21. | nit | — |
| R2-N-11 | plate-macros stage-1 branch `:246-256` | In stage 1, any `STOP_ON_ENDSTOP=home` or `inverted_home` move sets `homed=1` from an arbitrary `SET_POSITION`. This includes `inverted_home` from an already-released switch, which "triggers" at once (R38). The P frame can also be moved by unbind → `SET_POSITION` → rebind with the flag kept (R37). This is acceptable for stage 1 (no P limits, tapd doesn't send `G1 P`), but say so in WP2 §4. The deprecated numeric `STOP_ON_ENDSTOP=1` is not treated as homing, which fails safe (R44). | nit | R37, R38, R44 |
| R2-N-12 | `homing_override.cfg.txt:24` | Any `G28` whose letters are all unrecognised runs the **full** home, including the plunger, which expels liquid. Examples are `G28 E` (R27) and `G28 XY` with no space, which Klipper parses as the single key `XY` (R31). The old override behaved the same; mention it in the PR, or refuse unknown letters. | nit | R27, R31; `kpin/klippy/gcode.py:210-218` |
| R2-N-13 | SAVE wrapper `:148-156` | A state name containing `'` makes the `_GSTATE` update malformed (R06), and one containing `\` doesn't round-trip (R10). The base state is saved, but `RESTORE … MOVE=1` of that name is then always refused. Saves of other names are unaffected (R09). This fails closed; mention it in the known limits. | nit | R06 log: `Malformed command 'SET_GCODE_VARIABLE … VALUE="{"it's": 0.0}"'`; R10 |

## 4. Batch-mode cases run

**Harness reruns.** I used fresh fixtures built with `make_fixture.py` from configs `d7c45ce` and the unmodified package runner.

| Run | Result | Output file |
|---|---|---|
| Rev J, stage 1 (`fx1`) | **43/43**, `FAILURES: 0` | `review2/harness-stage1.txt` |
| Rev J, stage 2 (`fx2`) | **43/43**, `FAILURES: 0` | `review2/harness-stage2.txt` |
| Rev I `plate-macros.cfg` in `fx1` | Fails: lint, C-26, C-27, C-27b, C-28, C-28b, C-30, C-30b, C-31, C-34 (TEMPLATE CRASH), C-32, C-32b. Matches the results file | `review2/harness-revI-macros-stage1.txt` |
| Rev I stage-2 macros (pipette branch deleted, as in Rev I `stage2.patch.md`) in `fx2` | Fails: the same set, with C-36s and C-37s in place of C-32/C-32b | `review2/harness-revI-macros-stage2.txt` |

**Runner.** `review2/tools/attack.py` imports the harness's `build()`/`run_case()` and runs one klippy process per case. The case files are `tools/cases1.py`, `cases1b.py`, `cases2.py`, `cases_fix.py`, `cases_fix2.py` and `cases_mode.py`.

**Prefixes.** H = `SET_KINEMATIC_POSITION X=150 Y=150 Z=0` + `_T_HOME_ALL_PLATES`. P = `_PIPETTE_BIND` + the harness PIPHOMED.

**Stage 1 (`fx1`)**

| ID | G-code (after prefix) | Result |
|---|---|---|
| R01 | H; `G1 U100 F3000`, `MANUAL_PROBE`, `TESTZ Z=20` | **Accepted: Z=20, U=100. Bypass (R2-S-1)** |
| R02 | H; `G1 U100`, `Z_ENDSTOP_CALIBRATE`, `TESTZ Z=15` | **Accepted: Z=15, U=100. Bypass** |
| R41 | (cold) `MANUAL_PROBE`, `TESTZ Z=20` | `Must home axis first` (needs Z homed) |
| R03 | P; `M84.1` (= failed-G28 `motor_off`), `MANUAL_STEPPER STEPPER=pipette_stepper ENABLE=1`, `G1 P-1` | **Accepted, pip_homed=1 (R2-S-2)** |
| R04 | P; `M84.1`, tapd `SET_POSITION=0 MOVE=-1 STOP_ON_ENDSTOP=try_home`, `G1 P-3` | **Accepted (R2-S-2)** |
| R05 | H; `M84.1`, `G28 Z/X/Y`, `G1 U5` | Refused: plate1 not homed (plates safe) |
| R06 | H; `SAVE_GCODE_STATE NAME="it's"`, `RESTORE …` | `Malformed command` from the _GSTATE update; fails closed |
| R07 / R08 | `SAVE NAME="a b"` at Z20, then RESTORE MOVE=1 with plate mid-travel / plates parked | Refused / Z=20 restored |
| R09 | `SAVE good` at Z20, `SAVE "it's"`, `G1 Z0`, `RESTORE good MOVE=1` | Z=20 (dict not poisoned) |
| R10 | `SAVE NAME=a\\b` … `RESTORE … MOVE=1` | Refused "was not saved" (backslash doesn't round-trip) |
| R11 | 300 distinct SAVE names, then RESTORE MOVE=1 of the last | Works, Z=20 |
| R12 | `SAVE s` at Z0, `SAVE s` at Z20, Z0, U100, `RESTORE s MOVE=1` | Refused (newest Z used) |
| R13 / R42 | default name / `NAME=` (empty) | Refused onto mid-travel plate |
| R14 | Z20, `PAUSE`, `M84`, `G28 Z/X/Y`, `RESUME` | Refused: plate1 not homed |
| R15 | Z20, `PAUSE`, `M84`, bare `G28`, `RESUME` | Resumed to Z20 |
| R16 | Z20, `PAUSE`, Z0, U100, `RESUME` (refused), `PLATE_IN`, `RESUME` | First refused, second resumed (stays paused in between) |
| R17 | … `PAUSE`, Z0, U100, `CANCEL_PRINT`, `RESUME` | `action:cancel`; "Print is not paused"; no motion |
| R18 | Z20, `PAUSE`, Z0, `PLATE_MOVE plate2 120`, `PLATE_IN plate2`, `RESUME` | Resumed |
| R45 | Z20, `PAUSE` (printer.cfg override → PAUSE_ORIG), `RESUME` | Resumed to Z20 |
| R39 | `G28`, Z20, `PAUSE`, Z0, `G28 U` (rebind), `RESUME` | Resumed (RESTORE across a rebind is fine) |
| R40 | H; U100, Mainsail `_CLIENT_LINEAR_MOVE Z=20 F=600` | Refused by G1 |
| R19 | U100, `SET_GCODE_OFFSET X=5 MOVE=1` | Accepted (XY only) |
| R20 | U100, `SET_GCODE_OFFSET Z_ADJUST=-0.5 MOVE=1` | Accepted (raise) |
| R21 | U100, `SET_GCODE_OFFSET Z_ADJUST=20 MOVE=0` | Accepted, no move |
| R22 | U100, `SET_GCODE_OFFSET Z=20 MOVE=1.0` | Refused |
| R23 | `SET_GCODE_OFFSET Z_ADJUST=0.05 MOVE=1`, plates parked | Z=0.05 |
| R24 | U100, `set_gcode_offset z_adjust=20 move=1` | Refused |
| R25 / R26 | `M84 X` / `M18`, base re-enable plate1, `G1 U5` | Refused: plate1 not homed |
| R27 | (cold) `G28 E` | Full home incl. plates and plunger (R2-N-12) |
| R28 | (cold) `G28 Z U` | z homed, plate1 homed |
| R29 | H; Z20, `G28 X` | Parks X150 Y150 **Z0** (raises tip) |
| R30 | H; U100, `G28 Z` | Accepted; on hardware retracts to Z3 (R2-S-3) |
| R31 | (cold) `G28 XY` | Klipper's parser (`args_r` `[A-Z_]+`) reads `XY` as **one key**, so the override sees no known letter and runs the **full** home incl. plates and plunger (R2-N-12) |
| R32 | U100, `STEPPER_BUZZ STEPPER=stepper_z1` | Refused: plate1 mid-travel |
| R33 | `STEPPER_BUZZ STEPPER="manual_stepper plate1"`, tip at 0 | Accepted |
| R34 | `SET_STEPPER_ENABLE STEPPER=stepper_z ENABLE=0`, `G1 U5` | **Accepted** (Z still homed; R2-N-3) |
| R35 | `SET_GCODE_VARIABLE MACRO=_PLATE_CFG VARIABLE=z_safe VALUE=100`, Z20, U50 | **Accepted** (R2-N-2) |
| R36 | U100, `G01 Z20` | `Unknown command:"G01"`; no move (not a bypass) |
| R37 | P; unbind, `SET_POSITION=-30` (stage-1 branch), `G1 P-40` | Accepted, homed kept (stage-1 by design) |
| R38 | `M84`, `SET_POSITION=0 MOVE=-1 STOP_ON_ENDSTOP=inverted_home`, `G1 P-3` | Accepted, homed=1 |
| R43 | H; `RESTORE_GCODE_STATE NAME=zzz` | "Unknown g-code state", but `check()` passes `noerror`/`state` (R2-N-7) |
| R44 | `… SET_POSITION=-120 MOVE=0 STOP_ON_ENDSTOP=1` | Not treated as homing (fails safe) |
| R46 / R47 | `G91`, Z20, refused `PLATE_MOVE` / successful `PLATE_MOVE`, then report the mode | abs=True after refusal (`G1 Z-5` went to raw −5) / abs=False (R2-N-1) |

**Stage 2 (`fx2`)**

| ID | G-code | Result |
|---|---|---|
| T01 | H; Z20, `PAUSE`, Z0, U100, `RESUME` | Refused |
| T02 | H; U100, `MANUAL_PROBE`, `TESTZ Z=20` | **Accepted: bypass in stage 2 too** |
| T03 | `G28 P`, `MANUAL_STEPPER STEPPER=pipette_stepper ENABLE=1`, `G1 P-5` | Klipper "Must unregister"; flag cleared; G1 P refused |
| T04 / T05 | `G28 P`, `M84.1` [, `STEPPER_BUZZ` pipette], `G1 P-5` | Refused (stepper disabled; buzz restores disabled) |
| T06 | bare `G28`, `G1 P-30` | P=−30 |
| T07 | `G28 P`, unbind, rebind `GCODE_AXIS=P`, `G1 P-5` | Refused: plunger not homed |

**Prototype fixes (`fx1p`: copy of `fx1` with two review-only edits; full harness still 43/43)**

| ID | Case | Result |
|---|---|---|
| F01 / F02 | Entry-guarded `MANUAL_PROBE` / `Z_ENDSTOP_CALIBRATE` with U100 | Refused; `TESTZ` then unknown |
| F03 | Entry-guarded probe, plates parked, `TESTZ Z=5` | Works |
| F07 | Entry-guarded probe started parked, then `G1 U100`, then `TESTZ Z=20` | **Accepted.** An entry guard is not enough; refuse outright, or block plate moves while `manual_probe.is_active` |
| F04 / F05 | R03 / R04 with "clear homed if the plunger stepper is disabled" in the stage-1 branch | Refused: plunger not homed |
| F06 | Normal tapd re-zero + MOVE, then `G1 P-2` | Accepted, homed kept |

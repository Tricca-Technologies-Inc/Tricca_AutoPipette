# Responses to the Independent Review of Rev I (applied in Rev J)

| Field    | Value |
|----------|-------|
| Status   | Closed: every finding answered in Rev J |
| Revision | J |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Review   | `2026-10-21-review-of-rev-I.md` |
| Date     | 2026-10-21 |

---

**Owner decisions** (the three findings that needed judgement):

| Finding | Owner's decision |
|---|---|
| S-11 | Board IDs live only on the machine (D34) |
| S-14 | R7 = 2× typical load, brief peaks under 70% of rating |
| S-16 | Pinch protection is the owner's mechanical solution, outside the plan |

**Fixes:** the author made all the others.

**Verification:** the offline harness passes 43/43 in each stage. Every new case fails on the Rev I macros (`reference/tests/results-2026-10-21.txt`).

| # | Response | Where |
|---|---|---|
| B-1 | Wrapped `SET_GCODE_OFFSET` (checks `MOVE=1`), `SAVE_GCODE_STATE` (records each state's raw Z) and `RESTORE_GCODE_STATE` (checks `MOVE=1`; an unknown state is refused). `RESUME` goes through `RESTORE_GCODE_STATE`, so a refused Resume leaves the run paused. Tests C-26…C-28c | `plate-macros.cfg`; umbrella D13, §6.2, §6.3; WP4 TAP-9 |
| S-1 | Claims corrected: raw coordinates protect *reading*; `MOVE=1` moves are wrapped separately. Umbrella §6.2 now lists every motion path | D14; diagrams §5; WP2 §4 |
| S-2 | `STEPPER_BUZZ` wrapped. Plates: Z homed and tip raised. Z steppers: checked as a 1 mm descent. Tests C-30, C-30b; E-06 runs after `G28 Z` | `plate-macros.cfg`; WP1 §10 |
| S-3 | `M84`/`M18` wrapped to clear every homed flag, so re-enabling a motor by any route can't restore "homed" (C-31). The renamed originals are listed as never-send (tapd golden test S-TAP1-4; operator notes; risk K-OPS-05) | D15; WP2 §4; WP4 §4; RB1 §4.1 |
| S-4 | Closed by the `M84` wrapper. Tests C-32, C-32b | — |
| S-5 | Stage switch is now `variable_stage`. At stage 2, any direct `MANUAL_STEPPER` on the plunger clears its homed flag, so only `HOME_PIPETTE` sets the zero. Tests C-36s, C-37s; the lint checks the stage variable against the limits | `plate-macros.cfg`; `stage2.patch.md`; D28 |
| S-6 | `HOME_PLATE` backs off with `STOP_ON_ENDSTOP=inverted_home`: the switch must release within `home_backoff`, or homing errors. Batch mode can't show this, so it is checked on hardware by M-23 | D5; umbrella §9; VR-29 |
| S-7 | Powered E-tests moved to the Phase 7 exit (after config migration). E-tests now carry a phase column | Umbrella §7.1; WP1 §10; commissioning sheet |
| S-8 | CB1-5 split into CB1-5 (stage-1 bump, Phase 4) and CB1-7 (stage-2 bump, Phase 10) | WP3; umbrella §6.4, §7 |
| S-9 | One direction: TAP-6 → CFG-3 → CB1-7. TAP-6 develops against CFG-3's PR branch | WP4 TAP-6; WP2 CFG-3 |
| S-10 | TAP-7 is optional stage-2 work; M-22 runs only if it is implemented; Phase 10 exit = M-20, M-21 | Umbrella §6.4, §7.1, §9; WP4 TAP-7 |
| S-11 | **Owner:** IDs only on the machine. ID fields removed from CB1-6, the RB1 §6 template, the commissioning sheet and the Phase 0 form | D34; WP3 CB1-4, CB1-6 |
| S-12 | Rollback added to CB1-1…CB1-4 and CB1-6, plus a rule covering every TAP issue (TAP-6 and TAP-10 have their own) | WP3; WP4 §4 |
| S-13 | RB1 §5 reordered: unplug the Octopus, reflash the M8P on the new generation with `flash-manta --firmware` (new in CB1-2), then switch generation. DFU fallback at `0x08020000` | RB1 §5; WP3 CB1-2; K-OPS-06 |
| S-14 | **Owner:** R7 rewritten; Phase 0 ⛔, WP1 §4, E-08 and the Phase 0 form use the PSU's label rating | R7; VR-26 |
| S-15 | ⛔ before the first M8P reflash (VR-17 rehearsed, previous firmware path recorded, backup taken) and before rewiring | Umbrella §7.1 Phases 5–6; WP1 §9 |
| S-16 | **Owner:** the hazard entry no longer claims belts skip; pinch protection is the owner's mechanical design | H-01; VR-28 |
| S-17 | (a) Any template crash fails the case. (b) Every refusal checks that nothing moved (positions before and after). (c) Batch-mode homing limits stated in the README | `run_offline_tests.py`; tests README |
| N-1 | Stale references fixed | `plate-macros.cfg`, `octopus-plates.cfg` |
| N-2 | Plunger switch no longer labelled NC (same switch and polarity as today) | diagrams §3; WP1 E-05 |
| N-3 | Park after a lettered `G28` moves only homed axes. Test C-33 | `homing_override.cfg.txt`; umbrella §6.3 |
| N-4 | `G1` treats an unbound plate as unhomed. Test C-34 | `plate-macros.cfg` |
| N-5 | WP3 §2 no longer calls the no-IDs rule R16 | WP3 |
| N-6 | M-10 limited to stage-1 cases | Umbrella §9 |
| N-7 | Commissioning row reads "z_safe in config" | Commissioning sheet |
| N-8 | Liquid is expelled at the park position; keep it clear or use a waste tray | RB1 §4.1, §4.2 |
| N-9 | Contract adds `G90`/`G91`, `M84`, `SET_SERVO`, `SET_VELOCITY_LIMIT`, pause/resume, and the never-send list | Umbrella §6.3 |
| N-10 | Renamed to `homing_override.cfg.txt` | `reference/klipper/` |
| N-11 | The stage-1 `tricca-src` pin must be named and older than TAP-6 | WP3 CB1-5 |
| N-12 | Summary reworded | `SUMMARY.md` |
| N-13 | PB7 marked image-verified only | WP1 §3.2; VR-04 |

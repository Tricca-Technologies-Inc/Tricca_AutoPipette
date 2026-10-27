# Commissioning Sheet — AutoPipette Axis Expansion (plan Rev L)

Print one per machine. Tick each box, write the value, initial and date. Test details: WP1 §10 (E-tests) and umbrella §9 (M-tests). **Stop at any failure** and record it under Notes. Don't continue past a failed safety item (marked ⚠).

**Never write MCU serial IDs or CAN UUIDs on this sheet.** It gets filed with the machine record in git; the IDs live only in the machine's `printer.cfg` (D34).

| Machine (hostname) | | Operator | | Start date | |
|---|---|---|---|---|---|

## A. Before starting

| ✓ | Item | Value / note | Init. | Date |
|---|---|---|---|---|
| ☐ | `phase0-survey.md` complete and signed | | | |
| ☐ | Config backup tarball made and copied off the machine (RB1 §2) | name: | | |
| ☐ | Previous M8P firmware path recorded (for rollback) | | | |
| ☐ ⚠ | VR-17 closed: `flash-manta` over CAN and `--firmware` rollback rehearsed on a spare M8P (Phase 5 ⛔) | | | |
| ☐ | Firmware SHA-256s match the Phase 1 record | m8p: / octopus: / ebb: / katapult: | | |

## B. Electrical (in phase order; WP1 §10)

| ✓ | Phase | ID | Test | Pass criteria | Measured | Init. |
|---|---|---|---|---|---|---|
| ☐ ⚠ | 2 | E-01 | Octopus main and motor power terminals, before first power-up | Both ≈ +24 V, polarity correct; bed input unconnected | V / V | |
| ☐ | 5 | E-02 | CAN H–L resistance, unpowered | 55–65 Ω | Ω | |
| ☐ | 5 | E-03a | CAN errors, 10 min idle | No error growth | | |
| ☐ | 5 | E-04a | CAN boards detected | 2 UUIDs on can0 (don't write them here) | | |
| ☐ ⚠ | 6 | — | Owner go-ahead before rewiring (⛔) | | | |
| ☐ | 6 | E-04b | Octopus detected | by-id path present (don't write it here) | | |
| ☐ ⚠ | 6 | E-07 | E-stop pressed while powered | All boards and the servo converter lose power | | |
| ☐ | 6 | E-09 | Exactly one 24 V PSU in the machine | Yes | | |
| ☐ | 6 | E-11 | Hard stops by hand, motors off | ≥ 2 mm beyond 0 and 350 on all 6 drawers | | |
| ☐ | 7 | — | New config migrated (RB1 §3); Klipper starts clean | | | |
| ☐ | 7 | E-03b | CAN errors, 10 min with motion | No error growth | | |
| ☐ ⚠ | 7 | E-05 | Each home switch toggles only its own entry (`QUERY_ENDSTOPS`) | 6 plates (NC) + plunger (as today) | | |
| ☐ | 7 | E-06 | `STEPPER_BUZZ` each plate and the plunger (after `G28 Z`, tip raised) | Right motor per slot | | |
| ☐ | 7 | E-08 | PSU current: holding, then all motors moving | Holding < 50% of rating; peaks < 70% | A / A | |
| ☐ | 7 | E-10 | 30 min plate motors enabled | No TMC over-temperature | | |
| ☐ | 7 | E-12 | Servo stall while commanded | Converter ≥ 5.7 V; no EBB reset | V | |

## C. Machine values (record in `docs/machines/<host>.md` too)

| ✓ | Value | Recorded | Init. |
|---|---|---|---|
| ☐ | `[mcu]`, `[mcu EBBCan]`, `[mcu octopus]` written into the machine's `printer.cfg` (tick only; **don't copy the IDs**) | | |
| ☐ | `z_safe` in config (0.0 unless the owner changed it) | mm | |
| ☐ | Plate travel if not 350 mm | mm | |
| ☐ | `home_dir` (confirmed +1, D48; record only if a machine differs) | | |
| ☐ ⚠ | Measured safe plunger travel (D46): the furthest the plunger can go from the switch-release zero without leaving the syringe, measured carefully in small steps. Set `_PIPETTE_CFG.variable_max_travel` and the stage-2 `position_min` to it; keep 60 until measured | mm | |

## D. Stage-1 on-machine tests

| ✓ | ID | Test | Result | Init. |
|---|---|---|---|---|
| ☐ ⚠ | M-01 | Pipette direction, distance, homing and servo positions same as before | | |
| ☐ ⚠ | M-02 | Each drawer: `PLATE_OUT` goes out, `HOME_PLATE` goes in to the switch | | |
| ☐ ⚠ | M-03 | Interlock cases with real homing, including Resume, Z-offset and `STEPPER_BUZZ` refusals; refused moves produce no motion | | |
| ☐ | M-04 | Bare `G28` order: Z, X, Y, park, plates 1–6, plunger | | |
| ☐ | M-05 / M-06 / M-07 | Unhomed after `M84`, manual re-enable, `FIRMWARE_RESTART` | | |
| ☐ | M-08 | Existing protocol runs end to end | | |
| ☐ | M-09 | `PLATE_OUT` stops at 350, short of the hard stop | | |
| ☐ | M-10 | Stage-1 offline cases C-14…C-25 repeated on hardware (not C-17…, which are stage 2) | | |
| ☐ | M-11 | Coordinated `G1 Z… P…` starts and stops together | | |
| ☐ | M-12 | Gravimetric spot-check within current tolerance | mg | |
| ☐ | M-13 | P bound after restart and cold boot | | |
| ☐ | M-14 | `G28 P` zero = tapd's zero within 0.05 mm | mm | |
| ☐ | M-15 | `G1` wrapper latency acceptable; no "Timer too close" | | |
| ☐ | M-16 | `G1 P-30` then `G1 P0` without hitting the switch | | |
| ☐ | M-17 | Bare `G28` with all drawers out ≤ 60 s | s | |
| ☐ ⚠ | M-18 | E-stop recovery drill (RB1 §4.2) | | |
| ☐ | M-19 | Spill test, 20 cycles, no liquid leaves a well | | |
| ☐ ⚠ | M-23 | One drawer switch disconnected: `G28 <letter>` fails; plate not homed | | |

**Stage-1 sign-off (owner):** ______________________  Date: __________

## E. Stage 2 (later)

| ✓ | ID | Test | Result | Init. |
|---|---|---|---|---|
| ☐ | M-20 | Stage-2 gravimetric regression | mg | |
| ☐ ⚠ | M-21 | `G1 P` beyond travel refused; nothing moves | | |
| ☐ | M-22 | Coordinated move from `tap` and from a protocol file (only if TAP-7 is implemented) | | |

**Stage-2 sign-off (owner):** ______________________  Date: __________

## Notes / deviations

&nbsp;

&nbsp;

&nbsp;

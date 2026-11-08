# Verification Register

| Field    | Value |
|----------|-------|
| Status   | Living document; update at every phase gate |
| Revision | L |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Parent   | `00-umbrella-plan.md` |
| Date     | 2026-10-22 |

---

One list of everything the plan **assumes** but hasn't fully proven, and everything already proven. Each item says who can close it and where the evidence goes. When an item closes, record the date and evidence here and add a row to the umbrella revision history if a value changed.

**Who closes it:**
- **Desk:** checked from sources, code or a software run. No hardware needed.
- **Owner:** only the owner knows (existing hardware, mechanical design, intent).
- **Bench:** needs the parts on a bench, not the machine.
- **Machine:** needs the installed machine.

## 1. Verified

| ID | Item | How | Evidence |
|---|---|---|---|
| VR-01 | Klipper behaviors the design relies on (umbrella §5.1): `GCODE_AXIS` rules, soft limits on `MOVE` and bound `G1`, G92/SET_GCODE_OFFSET scope, `homing_override` letters, `rename_existing` | Desk: read the pinned source, then exercised in batch mode (VR-06) | Klipper `7bc4d09`; `reference/tests/results-2026-10-22.txt` |
| VR-02 | The three Klipper firmware configs are valid and build | Desk: `olddefconfig` + build at the pin | `reference/firmware/README.md` |
| VR-03 | Katapult config for the EBB is valid and builds; it launches Klipper at `0x08002000`, matching the EBB's Klipper config | Desk: `olddefconfig` + build at Katapult `3b973a4` | `reference/firmware/README.md` |
| VR-04 | EBB42 V1.2 pins: PB9 servo, PA15 TMC UART, PD0/PD1/PD2 step/dir/enable, CAN PB0/PB1 (Klipper + BTT sample configs). PB7 endstop is **image-verified only** (BTT pinout image; review N-13); E-05 catches a wrong pin | Desk | WP1 §3.2 |
| VR-05 | Octopus V1.1 (non-Pro) driver and endstop pins; the board is the owner's F446 (photo of label and chip, Rev L) | Desk: Klipper `generic-bigtreetech-octopus-v1.1.cfg`; F446 firmware built at the pin; full config loads and the offline tests pass with its dictionary | WP1 §3.1 |
| VR-06 | Interlock, homing override, axis binding, stage-2 plunger limits, every non-G1 motion path | Desk: real Klipper in batch mode, 55/55 stage 1 and 52/52 stage 2 (Rev K). Two independent reviews found bypasses (Rev I: `RESUME`/offsets/buzz/`M84`; Rev J: `MANUAL_PROBE`, failed-`G28` motors-off); all closed, each with a case that fails on the earlier config. Completeness of the path list is itself tested (C-45 command inventory) | WP2 §5; `reference/tests/results-2026-10-22.txt` |
| VR-07 | Plunger values: travel 60 mm, homing 50 mm/s and 200 mm/s², app limits 50 mm/s and 200 mm/s² | Desk: tapd `p100_vertical.json`, `HIGH_RISK_BOUNDS` | Umbrella §8 |
| VR-08 | How a USB-to-CAN bridge board is reflashed: `flashtool -r`, then DFU | Desk: Katapult README | WP1 §7, CB1-2 |

## 2. Needs the owner

None. The owner is handling the remaining owner items outside the plan (§2.2).

### 2.1 Closed by the owner (2026-10-20)

| ID | Item | Answer | Effect on the plan |
|---|---|---|---|
| VR-09 | Existing PSU | 24 V, ≥ 200 W | Keep it (D11). LRS-350-24 not bought (BOM qty 0). E-08 still checks headroom |
| VR-10 | Existing motors | Stock Voron 2.4 set: A/B LDO-42STH40-2004MAH (1.1 Ω), Z×4 LDO-42STH48-2004AC (1.6 Ω) ([klipper_tmc_autotune database](https://github.com/andrewmcgr/klipper_tmc_autotune/blob/main/motor_database.cfg)). Assumes the stock motors were fitted; the pipette motor model is unrecorded | At the configured currents these draw no more than WP1 §4 assumed. Budget stands (≈100 W) |
| VR-11 | Drawer travel | 350 mm confirmed against the mechanical design | O-1 closed; D19 confirmed |
| VR-13 | Certification | Internal use only; no certification planned | Umbrella §11 stays a design aid. Revisit if the machine is ever sold |
| VR-20 | `z_safe` | Keep 0.0 for now | Tip must be fully raised whenever a drawer moves. Safe, possibly slower. Measure later if it costs time |
| VR-15 | Independent reviewer | A fresh review agent, run against `review-checklist.md` (Rev I) | Done: 1 blocker, 17 should, 13 nit, all answered in Rev J |
| VR-26 | PSU headroom rule (review S-14) | 2× typical load; brief peaks under 70% of rating | R7 rewritten; Phase 0 ⛔ and E-08 use it |
| VR-30 | Tip clearance during `G28 Z`'s 3 mm homing retract (second review R2-S-3) | Z 3 clears every drawer (owner, Rev K) | D18; §6.2. Re-check if `homing_retract_dist` or the mechanics change |
| VR-31 | Manual Z-probing / Z-endstop calibration (second review R2-S-1) | Not used on these machines (owner, Rev K) | `MANUAL_PROBE`/`Z_ENDSTOP_CALIBRATE` refused |
| VR-27 | Where board IDs live (review S-11) | Only on the machine (`printer.cfg` + backup) | D34; ID fields removed from the machine record, forms and CB1-6 |

### 2.2 Out of plan — handled by the owner

The plan doesn't track these. They're listed so nobody assumes they were forgotten.

| ID | Item | Plan's assumption until the owner says otherwise |
|---|---|---|
| VR-12 | Cable lengths (O-2) | Space for them in `phase0-survey.md` §7 |
| VR-14 | First use case for coordinated plunger moves (O-6) | TAP-7 stays parked (`needs-info`) |
| VR-19 | Tip ejection sometimes struggles today (MG996R already at 6 V) | Unchanged by this plan: servo and 6 V supply stay as today (D29). Baseline in `phase0-survey.md` §5.5 |
| VR-28 | Drawer finger-pinch protection (review S-16: a drawer can push ≈ 40 N before stalling) | The owner's mechanical solution. The plan makes no current-limit claim (H-01) |

## 3. Open — bench

| ID | Item | How to close | Phase |
|---|---|---|---|
| VR-16 | Katapult flash by DFU on the EBB (`dfu-util … -s 0x08000000:mass-erase:force:leave`) | Run on the bench; EBB then shows up in `flashtool -q` on a CAN adapter | 2 |
| VR-17 | `flash-manta` over CAN (`flashtool -r`, then DFU), and `flash-manta --firmware` back to USB firmware | CB1-2 acceptance on a spare M8P. **Phase 5 ⛔ until closed** | 4 |
| VR-18 | Plunger switch polarity on the EBB (`^!PB7`) | E-05 | 2 / 6 |

## 4. Open — machine

| ID | Item | How to close | Phase |
|---|---|---|---|
| VR-21 | Plunger homing direction, `home_dir` = +1 (O-5) | M-01 and M-14: `G28 P` moves toward the switch and reaches the same zero as tapd's homing | 8 |
| VR-22 | Plate direction per slot (+ = out) | M-02 | 8 |
| VR-23 | P bound at startup by the timer (offline only the body is tested, C-14b) | M-13 | 8 |
| VR-29 | Plate homing fails safe on a broken switch wire (release check; batch mode can't show switch behaviour) | M-23 | 8 |
| VR-24 | `G1` wrapper latency on the CB1 | M-15 | 8 |
| VR-25 | Plate speed, acceleration and homing values (`PROPOSED`, umbrella §8) | M-17, M-19 | 8 |

## 5. Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| I | 2026-10-20 | James / Claude | New. Consolidates the open items, `VERIFY` markers and `PROPOSED` values from Rev H, plus what Rev I verified. Owner answers close VR-09, VR-10, VR-11, VR-13, VR-15, VR-20; VR-12, VR-14, VR-19 moved out of plan |
| J | 2026-10-21 | James / Claude | Review outcome: VR-06 updated (43/43, bypasses closed); VR-04 PB7 image-verified only; VR-15 done; owner decisions VR-26 (R7), VR-27 (IDs), VR-28 (pinch, out of plan); VR-17 now gates Phase 5; VR-29 (switch-release test) added |
| K | 2026-10-22 | James / Claude | Second review: VR-06 updated (55/52 cases, inventory test); owner answers VR-30 (Z 3 clearance) and VR-31 (no manual probing) |
| L | 2026-10-22 | James / Claude | VR-05: plate controller is the owner's Octopus V1.1 F446 |

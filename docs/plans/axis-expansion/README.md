# AutoPipette Axis Expansion — Plan Package (Rev L)

Six plate drawers (axes U V W A B C), the pipette plunger and servo moved to an EBB42 CAN board (plunger on axis P), a Klipper collision interlock, and tapd support.

## Reading order

**New here, or not implementing anything?** Read `SUMMARY.md` (one page), then `diagrams.md`.

**Implementing or reviewing:**

1. `00-umbrella-plan.md`: requirements, decisions, architecture, G-code contract (§6.3), phase plan, integration tests, traceability, hazards, risks. **Start here.**
2. `verification-register.md`: what is already proven and what is still to verify, and who closes each item.
3. The work package for your area:

| Doc | Implemented in | Issues |
|---|---|---|
| `WP1-hardware-firmware.md` | Bench / machine | — |
| `WP2-klipper-config.md` | `Tricca_Autopipette_Configs` | CFG-1…CFG-3 |
| `WP3-cb1-deployment.md` | `cb1-autopipette` | CB1-1…CB1-7 |
| `WP4-tapd.md` | `Tricca_AutoPipette` | TAP-1…TAP-11 |
| `RB1-migration-and-operations.md` | On each machine | — |

4. `reference/`: files the work packages point to.
   - `reference/klipper/`: config files for CFG-1, `homing_override.cfg.txt` (a section to paste, never a file to commit), `printer.cfg.md`, `stage2.patch.md`.
   - `reference/firmware/`: Klipper and Katapult Kconfig files for CB1-1 / WP1, with their build check.
   - `reference/tests/`: offline Klipper test harness for CFG-2, a fixture builder, the command inventory, and the Rev K results (55/55 stage 1, 52/52 stage 2).

**Reviews:** `reviews/` holds both independent reviews (of Rev I and of Rev J) and the author's responses (answered in Rev J and Rev K).

**Forms:**
- `phase0-survey.md`: fill one per machine before any change.
- `commissioning-sheet.md`: print one per machine.
- `review-checklist.md`: for the independent reviewer.

## For the implementing agent

- **File the issues** from WP2–WP4 in their repos with the labels shown. Add the dependencies, and add tapd issues to backlog map #34.
- Leave promotion to `ready-for-agent` to the owner (umbrella D32).
- Respect every **⛔ STOP**.
- Follow each repo's own `CLAUDE.md`.
- Never put MCU IDs in a repo.
- Run `reference/tests/run_offline_tests.py` after any change to the reference config.

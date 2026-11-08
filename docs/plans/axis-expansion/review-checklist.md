# Reviewer Checklist (plan Rev K)

For an independent reviewer: a person, or an agent that did **not** write the plan. Record findings as a list under "Findings", each with the doc and section. The author answers each one in the next revision.

## Consistency
- [ ] Every requirement R1–R17 traces to at least one test (umbrella §10), and each named test exists.
- [ ] The G-code contract (umbrella §6.3) matches `reference/klipper/*.cfg` and what WP4's issues send.
- [ ] Interlock rules I1–I6 (umbrella §6.2) match `plate-macros.cfg` and `diagrams.md` §5.
- [ ] Pins in WP1 §3 match `octopus-plates.cfg` and `ebb-pipette.cfg`.
- [ ] Every `PROPOSED` value in umbrella §8 appears in the config with the same number.
- [ ] Phase entry/exit criteria (umbrella §7.1) and the dependency graph agree.

## Safety
- [ ] No sequence of documented commands lets a drawer move with the tip low, or the tip lower onto a moving drawer. Try to break it, e.g. with `G91`, offsets, `G0`, `M84` then re-enable, or a failed command halfway through.
- [ ] Every command in `reference/tests/command-inventory.txt` is classified correctly (C-45 keeps the list complete; a reviewer checks the classes). Every CHECKED or REFUSED command appears in umbrella §6.2's path table and has a C-test. Remember Klipper's always-loaded modules (`toolhead.py`: gcode_move, homing, manual_probe, …), not just config sections.
- [ ] Every ⛔ STOP sits before an irreversible step.
- [ ] Rollback exists for every phase that touches a machine.
- [ ] The E-stop recovery (RB1 §4.2) works for someone who didn't write it.

## Reproducibility
- [ ] Build both fixtures with `reference/tests/make_fixture.py`, run `reference/tests/run_offline_tests.py` on each (README in that folder). Both stages pass.
- [ ] Rebuild one firmware config at the pin; its SHA-256 matches the Phase 1 record once that exists.

## Repo rules
- [ ] No MCU serial ID or CAN UUID appears anywhere in the package or the issues.
- [ ] Each issue in WP2–WP4 has labels, blockers, acceptance criteria and a rollback.
- [ ] Nothing would put a `*.cfg` at the configs repo root except the intended config files.

## Findings

| # | Doc / section | Finding | Severity (blocker / should / nit) | Author response |
|---|---|---|---|---|
| | | | | |

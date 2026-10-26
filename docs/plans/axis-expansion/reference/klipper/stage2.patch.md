# Stage 2 config changes (issue CFG-3; deploy together with tapd TAP-6)

1. `plate-macros.cfg`, `[gcode_macro _PIPETTE_CFG]`: set `variable_stage: 2`.

   From then on, any direct `MANUAL_STEPPER STEPPER=pipette_stepper …` (unbind,
   `SET_POSITION`, `ENABLE`, …) marks the plunger unhomed. A plain `MOVE` on the
   bound stepper is refused by Klipper as well. Only `HOME_PIPETTE` / `G28 P`
   (which use `MANUAL_STEPPER_BASE`) set the plunger frame, so the soft limits
   below always refer to the homed zero (D26). Stage-2 tapd sends `G28 P` and
   `G1 P…` only.

2. `ebb-pipette.cfg`, `[manual_stepper pipette_stepper]`: add

   ```ini
   position_min: -60    # home_dir = +1, 60 mm syringe travel
   position_max: 0
   ```
   If Phase 0 measured `home_dir = -1`, use `position_min: 0` / `position_max: 60`.

3. Both changes go in the same PR. The offline harness checks they agree: limits
   present with `stage: 1` (or the reverse) fails its lint.

4. Tests: the harness's stage-2 case set (C-13s, C-17…C-17c, C-19s, C-36s, C-37s), and
   on hardware M-20, M-21 (and M-22 if TAP-7 is implemented).

The stage-1 branch in `MANUAL_STEPPER` stays in the file but is unreachable at
`stage: 2`; deleting it is optional cleanup.

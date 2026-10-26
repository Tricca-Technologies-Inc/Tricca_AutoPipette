# printer.cfg changes (seed file in Tricca_Autopipette_Configs)

Includes, in this order (the first two exist today):

```ini
[include mainsail.cfg]
[include tricca-autopipette.cfg]
[include ebb-pipette.cfg]
[include octopus-plates.cfg]
[include plate-macros.cfg]
```

Keep `[mcu CB1]` (host MCU) as it is. Do **not** add `[mcu]`, `[mcu EBBCan]` or
`[mcu octopus]`: `bootstrap.sh` writes them per machine (WP3 issue CB1-4):

```ini
[mcu]
canbus_uuid: <M8P uuid>        # M8P in USB-to-CAN bridge mode

[mcu EBBCan]
canbus_uuid: <EBB42 uuid>

[mcu octopus]
serial: /dev/serial/by-id/usb-Klipper_stm32f446xx_<id>-if00   # Octopus V1.1 (F446)
```

`tricca-autopipette.cfg` edits:
- Remove `[manual_stepper pipette_stepper]`, `[tmc2209 manual_stepper pipette_stepper]`
  and `[servo pipette_servo]` (they move to `ebb-pipette.cfg`; carry the
  rotation_distance / issue #29 comment across verbatim).
- Replace `[homing_override]` with the section in `homing_override.cfg.txt` (paste it; never add that file to the repo root).
- Update the header comment: the M8P is built as a USB-to-CAN bridge
  (`reference/firmware/m8p-bridge.config`).
- Keep `[force_move] enable_force_move: False`. Never add `[gcode_arcs]`.

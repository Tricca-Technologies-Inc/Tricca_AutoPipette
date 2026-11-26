# nick

## Syringe plunger

| | Value | Measured |
|---|---|---|
| Screw | 4-start T8x8 | 2026-11-04 |
| Lead (`lead_mm`, Klipper `rotation_distance`) | 8 mm | 2026-11-04: a commanded 4 mm moved 4 mm with `rotation_distance: 8` (16 mm with 2) |
| Usable stroke (`max_travel_mm`, `_PIPETTE_CFG max_travel`) | 68 mm | 2026-11-04, in small steps |

nick's local pipette files carry `lead_mm: 8` and syringe speeds, accels and
`calibration_mm` at 4x the shared 2 mm values. It homes the plunger at its
`speed_dispense` (200 mm/s) unless `speed_home` is set.

Commission the plunger as in [README.md](README.md) after any screw or
syringe change.

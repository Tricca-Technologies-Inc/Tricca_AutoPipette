# marie

## Syringe plunger

| | Value | Measured |
|---|---|---|
| Screw | unknown | not yet |
| Lead (`lead_mm`, Klipper `rotation_distance`) | unknown | not yet |
| Usable stroke (`max_travel_mm`, `_PIPETTE_CFG max_travel`) | unknown | not yet |

The lead is unmeasured: the screws got mixed between rigs (issue #178), so
don't assume the shared 2 mm. Commission the plunger as in
[README.md](README.md) before any long plunger move, then set `lead_mm` and
Klipper's `rotation_distance` together.

# Machines

One file per rig: hardware facts measured on that rig, which the shared
configs can't know. The syringe screws differ between rigs (issue #178): a
single-start T8 has a 2 mm lead, a 4-start T8x8 an 8 mm one.

## Commissioning the syringe plunger

Do this before any long plunger move on a new rig, or after a screw or
syringe change. A wrong lead moves the plunger 4x as far as commanded and
can crash it into the end of the syringe.

1. Command a 4 mm plunger move and measure how far the plunger actually
   moves. 4 mm means Klipper's `[manual_stepper pipette_stepper]
   rotation_distance` matches the screw's lead; 16 mm means the screw is an
   8 mm lead on a 2 mm setting, 1 mm the reverse.
2. Set `rotation_distance` and every local pipette file's `syringe.lead_mm`
   to the lead, together. The syringe speeds, accels and `calibration_mm` in
   the local pipette and liquid files scale with it (the shared files are
   for 2 mm: multiply by `lead_mm / 2`).
3. Re-measure the 4 mm move, then find the usable stroke in small steps
   toward the unknown end, and set `max_travel_mm` (and `_PIPETTE_CFG
   max_travel`) to it.
4. Record the lead and stroke in this rig's file.

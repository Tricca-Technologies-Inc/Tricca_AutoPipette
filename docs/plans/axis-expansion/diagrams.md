# Diagrams

| Field    | Value |
|----------|-------|
| Status   | Draft for review |
| Revision | L |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Parent   | `00-umbrella-plan.md` |
| Date     | 2026-10-20 |

---

Mermaid diagrams. They render on GitHub and in most Markdown viewers. Where a diagram and a table disagree, **the table in the work package wins**; fix the diagram.

## 1. Controllers and data links

How the CB1 talks to each board. Only one CAN bus: M8P bridge ↔ EBB42.

```mermaid
flowchart LR
  subgraph CB1["CB1 (host)"]
    K["klippy<br/>Klipper 7bc4d09"]
    M["Moonraker"]
    T["tapd"]
    TAP["tap / protocol files"]
    KI["kiosk (unchanged)"]
    T --> M --> K
    TAP --> T
    KI --> T
  end
  K -- "USB" --> M8P["Manta M8P V2.0<br/>[mcu]<br/>USB-to-CAN bridge<br/>gantry X Y Z Z1 Z2 Z3"]
  K -- "USB" --> OCT["Octopus V1.1 (F446)<br/>[mcu octopus]<br/>plate1–6 → U V W A B C"]
  K -. "host MCU" .-> HOST["[mcu CB1]<br/>(unchanged)"]
  M8P == "CAN 1 Mbit/s<br/>120 Ω each end" ==> EBB["EBB42 CAN V1.2<br/>[mcu EBBCan]<br/>pipette_stepper → P<br/>endstop PB7, servo PB9"]
```

## 2. Power and fuses

Everything sits downstream of the existing E-stop.

```mermaid
flowchart TD
  AC["Mains"] --> ES["Existing E-stop<br/>(cuts all power)"]
  ES --> PSU["Existing 24 V PSU<br/>≥ 200 W"]
  PSU --> F1["F1 7.5 A"] --> M8P["M8P V2.0<br/>CB1 5 V, gantry motors"]
  M8P -- "24 V + CAN<br/>in one 4-core cable" --> EBB["EBB42<br/>pipette motor"]
  PSU --> F2["F2 5 A"] --> OCT["Octopus V1.1<br/>main + motor power inputs<br/>6 plate motors (bed input unused)"]
  PSU --> F3["F3 3 A"] --> BUCK["24 → 6 V converter, ≥ 3 A<br/>(as today)"] --> SERVO["MG996R servo<br/>+ 470 µF at servo"]
  EBB -- "signal PB9 + GND" --> SERVO
```

Typical load ≈ 100 W (≈ 115 W with a servo stall); PSU headroom ≥ 2×. Fuse wire gauges and expected currents: WP1 §4.

## 3. Pipette head wiring (EBB42)

```mermaid
flowchart LR
  CAN["CAN cable from M8P<br/>24 V · GND · CAN-H · CAN-L"] --> EBB["EBB42 CAN V1.2<br/>120 Ω jumper fitted"]
  EBB -- "motor port<br/>step PD0 · dir PD1 · en PD2<br/>TMC2209 UART PA15" --> MOT["Pipette plunger motor<br/>(NEMA17; EBB mounted on it)"]
  EBB -- "endstop header PB7<br/>^! (same switch and polarity as today)" --> SW["Plunger home switch"]
  EBB -- "probe header PB9 (signal)<br/>+ GND" --> SV["MG996R servo"]
  BUCK["6 V converter (F3)"] -- "6 V + GND<br/>short lead, ≥ 22 AWG" --> SV
```

The servo's power **never** comes from the EBB (its 5 V rail is 1 A total). The converter ground and the EBB ground are common.

## 4. Plate drawer wiring (Octopus V1.1, one per slot)

```mermaid
flowchart LR
  subgraph OCT["Octopus V1.1 (non-Pro, F446)"]
    D0["Driver0 → plate1 / U"]
    D1["Driver1 → plate2 / V"]
    D2["Driver2 → plate3 / W"]
    D3["Driver3 → plate4 / A"]
    D4["Driver4 → plate5 / B"]
    D5["Driver5 → plate6 / C"]
    S0["STOP_0 PG6"]
    S1["STOP_1 PG9"]
    S2["STOP_2 PG10"]
    S3["STOP_3 PG11"]
    S4["E0DET PG12"]
    S5["E1DET PG13"]
  end
  D0 -- "shielded 4-core" --> M1["Drawer 1 motor"]
  S0 -- "shielded 2-core, NC" --> H1["Drawer 1 home switch (in end)"]
  D5 -- "shielded 4-core" --> M6["Drawer 6 motor"]
  S5 -- "shielded 2-core, NC" --> H6["Drawer 6 home switch (in end)"]
```

Drawers 2–5 follow the same pattern on the slots shown. Full pin table (step/dir/enable/UART): WP1 §3.1; driver 3's enable pin is PA0 on this board. Shields are grounded at the controller end only. Every DIAG jumper is removed; this board has no per-driver voltage jumpers.

## 5. Interlock decision for a `G1` / `G0` move

```mermaid
flowchart TD
  A["G1 / G0 command"] --> B{"Any plate letter<br/>U V W A B C?"}
  B -- yes --> C{"Z homed?"}
  C -- no --> R1["Refuse: Z not homed"]
  C -- yes --> D{"Raw Z ≤ z_safe<br/>now and at target?"}
  D -- no --> R2["Refuse: tip below safe height"]
  D -- yes --> E{"Each moving plate<br/>homed?"}
  E -- no --> R3["Refuse: plateN not homed"]
  E -- yes --> P
  B -- no --> F{"Lowers the tip<br/>below z_safe?"}
  F -- yes --> G{"Every plate homed<br/>and parked (in or fully out)?"}
  G -- no --> R4["Refuse: plateN not homed / mid-travel"]
  G -- yes --> P
  F -- no --> P{"P in the move?"}
  P -- no --> OK["Run the move<br/>(Klipper soft limits still apply)"]
  P -- yes --> H{"P bound and<br/>plunger homed?"}
  H -- no --> R5["Refuse: P not bound / plunger not homed"]
  H -- yes --> OK
```

The first failing check is the one reported. The check reads **raw** positions, so G92 and offsets can't hide where the tip really is.

Commands that move Z **without** `G1` get the "lowers the tip" branch of this check before they run:
- `SET_GCODE_OFFSET … MOVE=1`, for example Mainsail's Z-offset buttons.
- `RESTORE_GCODE_STATE … MOVE=1`, and `RESUME` after a pause.
- `STEPPER_BUZZ` on a Z stepper.

`STEPPER_BUZZ` on a plate needs Z homed and the tip raised. `MANUAL_PROBE` and `Z_ENDSTOP_CALIBRATE` are refused outright. The full list is in umbrella §6.2, and the offline tests check it against every command Klipper registers.

## 6. What a bare `G28` does

```mermaid
flowchart LR
  Z["G28 Z"] --> X["G28 X"] --> Y["G28 Y"] --> PK["Park<br/>G1 X150 Y150 Z0"] --> HP["HOME_PLATES<br/>plate1 … plate6, one at a time"] --> PI["HOME_PIPETTE"]
```

`G28` with letters homes only what is named, in Z, X, Y order. If any gantry axis was named, it then parks the axes that are now homed (so `G28 X` on a cold machine moves only X). Next come the named plates, then `P`. Each plate's homing fails if its switch doesn't release after the first touch, so a broken wire can't fake a "home".

## 7. Phases

```mermaid
flowchart LR
  P0["0 Survey"] --> P1["1 Firmware env"]
  P1 --> P2["2 Bench prep"]
  P1 --> P3["3 Config<br/>CFG-1, CFG-2"]
  P3 --> P4["4 Deployment<br/>CB1-1…6"]
  P2 --> P5["5 CAN bring-up<br/>⛔ VR-17 rehearsed first<br/>machine down until 7"]
  P4 --> P5
  P5 --> P6["6 Install<br/>⛔ owner go-ahead"] --> P7["7 Migrate config<br/>+ powered E-tests"] --> P8["8 Stage-1 validation"]
  P3 -. "offline dev" .-> P9["9 tapd stage 1<br/>TAP-1…5, 8, 9, 11"]
  P8 --> P9
  P9 --> P10["10 Stage 2<br/>TAP-6 → CFG-3 → CB1-7<br/>(TAP-7 optional)"]
```

## 8. Rollout stages

```mermaid
flowchart LR
  subgraph S1["Stage 1"]
    A1["Config CFG-1<br/>variable_stage: 1"]
    A2["Today's tapd plunger commands work<br/>(transparent rebind)"]
    A3["No plunger soft limits"]
  end
  subgraph S2["Stage 2"]
    B1["Config CFG-3<br/>variable_stage: 2"]
    B2["tapd: G28 P + absolute G1 P (TAP-6)"]
    B3["Plunger limits −60 … 0<br/>only HOME_PIPETTE sets the zero"]
  end
  S1 -- "CB1-7: both pins in one switch" --> S2
```

## Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| I | 2026-10-20 | James / Claude | New: topology, power, head and drawer wiring, interlock, `G28`, phases, stages |
| J | 2026-10-21 | James / Claude | Review fixes: non-G1 Z paths under the interlock diagram (offset claim corrected); plunger switch label (not NC); `G28` park and switch-release notes; phases and stages use CB1-7, `variable_stage`, TAP-7 optional |
| K | 2026-10-22 | James / Claude | Interlock notes: manual probe commands refused; command list is tested |
| L | 2026-10-22 | James / Claude | Octopus V1.1 (non-Pro, F446): topology, power and drawer wiring |

# WP1 — Hardware & Firmware

| Field    | Value |
|----------|-------|
| Status   | Draft for review (approval in the umbrella header) |
| Revision | L |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Parent   | `00-umbrella-plan.md` |
| Date     | 2026-10-22 |

---

## 1. Purpose & Scope

Everything physical, plus the firmware build environment:
- Component specifications, power budget, wiring, BOM.
- Workstation firmware builds from the pinned Klipper source.
- Bench preparation, CAN bring-up, installation.
- Electrical tests **E-01…E-12**.

Klipper config is WP2. Deployment code (derivations, flash helpers, `can0` unit, bootstrap) is WP3. On-machine integration tests (M-xx) are in umbrella §9.

## 2. Requirements (from umbrella §4)

R1, R4–R9, R13. Units per umbrella §2.

## 3. Component Specifications

### 3.1 Octopus V1.1 (non-Pro, STM32F446) — plate axes

The owner already has this board; it was identified from a photo of its label ("Octopus V1.1") and chip ("STM32F446ZET6") at Rev L. The non-Pro and Pro pin maps differ, so **don't mix their config files**.

- Firmware: `reference/firmware/octopus-v1.1-f446.config` (32 KiB bootloader, 12 MHz crystal, USB).
- Pins: `reference/klipper/octopus-plates.cfg`, from Klipper `config/generic-bigtreetech-octopus-v1.1.cfg` (non-Pro only).
- Check the chip marking before flashing. Some Octopus V1.1 boards have an STM32F429, which needs an 8 MHz crystal setting instead (Klipper's config notes).

| Slot | Plate / axis | step | dir | enable | UART | Home input |
|------|---|---|---|---|---|---|
| Driver0 | plate1 / U | PF13 | PF12 | !PF14 | PC4 | PG6 (STOP_0) |
| Driver1 | plate2 / V | PG0 | PG1 | !PF15 | PD11 | PG9 (STOP_1) |
| Driver2 | plate3 / W | PF11 | PG3 | !PG5 | PC6 | PG10 (STOP_2) |
| Driver3 | plate4 / A | PG4 | PC1 | !PA0 | PC7 | PG11 (STOP_3) |
| Driver4 | plate5 / B | PF9 | PF10 | !PG2 | PF2 | PG12 (E0DET) |
| Driver5 | plate6 / C | PC13 | PF0 | !PF1 | PE4 | PG13 (E1DET) |
| Driver6 | spare | PE2 | PE3 | !PD4 | PE1 | PG14 (E2DET) |
| Driver7 | spare | PE6 | PA14 | !PE0 | PD3 | PG15 (E3DET) |

- **Driver3's enable pin is PA0 on this board.** On the Pro it's PA2, and on this board PA2 is the HE0 heater output.
- **Power.** The board has separate inputs for main (board) power, motor power and bed power (BTT manual).
  - Feed fuse branch F2 to **both the main power and motor power inputs** at 24 V.
  - Leave bed power unconnected.
  - There are no per-driver voltage jumpers on this board; every driver runs at the motor-power voltage. 24 V is within the TMC2209's rating.
- **Remove all DIAG jumpers.** A fitted DIAG jumper shares the endstop pin with the driver, and the switch may not read.
- Set the UART-mode jumpers for TMC2209 (BTT manual).
- Physically confirm the STOP/DET silkscreen.
- The board arrived with eight TMC2209 V1.3 drivers fitted. Six drive the plates; two are spares.

### 3.2 EBB42 CAN V1.2 — pipette stepper and servo signal

- Firmware: `reference/firmware/ebb42-v1.2.config` (STM32G0B1, 8 MHz, CAN PB0/PB1, 1 Mbit/s, 8 KiB Katapult offset). Bootloader: `reference/firmware/katapult-ebb42-v1.2.config`.
- Pins: `reference/klipper/ebb-pipette.cfg`.

| Function | Pin | Notes |
|---|---|---|
| step / dir / enable | PD0 / PD1 / !PD2 | Direction re-established in M-01 |
| TMC2209 UART | PA15 | |
| Plunger home switch | PB7 (endstop header) | **Image-verified** only: BTT's pinout image `EBB42 CAN V1.1&V1.2-PIN.png` shows it; BTT's text wiki and sample config don't list it. E-05 catches a wrong pin. Polarity as today (`^!`), confirm with E-05 |
| Servo signal | PB9 (BLTouch/probe header, control pin) | **Verified** on the same image (Rev I). Signal only (§3.3) |
| Hotend PB13, fans PA0/PA1 | Unused | Leave unconnected |

- Mount the board on the back of the NEMA17 pipette motor.
- Fit the 120 Ω termination jumper.
- Fit the VUSB jumper only while DFU-flashing.
- The onboard 5 V DC-DC is rated 1 A total (BTT wiki).

### 3.3 Pipette servo (MG996R)

- Power from a **dedicated 24 V → 6 V converter, ≥ 3 A continuous** on fuse branch F3. The MG996R stalls at up to ≈2.5 A; running current is ≈0.5–0.9 A at 6 V.
  - **6 V matches today's machine** (owner, Rev I: MG996R on a 24→6 V converter). Don't drop to 5 V: torque falls, and ejection already struggles sometimes (VR-19).
  - Reuse the existing converter if its rating is ≥ 3 A continuous; otherwise buy one (BOM 7).
- Signal from EBB PB9; **common ground** between the buck output and the EBB.
- Keep the servo's 6 V lead short and use ≥ 22 AWG; add a 470 µF+ electrolytic capacitor across the servo supply at the servo end to absorb stall transients.

### 3.4 Manta M8P V2.0 — USB-to-CAN bridge

- Firmware: `reference/firmware/m8p-bridge.config` (replaces `klipper-manta-mcu.config`).
- Fit the 120 Ω jumper.
- Freed pins: PC7/PC8/PD2 (old pipette slot), PE9 (old servo) are spare.

### 3.5 Plate drawer drive (×6)

| Item | Spec |
|---|---|
| Travel | **350 mm** (umbrella D19; confirmed against the mechanical design) |
| Motor | LDO-42STH40-1684AC: NEMA17 40 mm, 1.8°, 1.68 A, 1.65 Ω, 450 mN·m |
| Belt / pulley / idler | GT2 6 mm; 20T 5 mm bore; matching idler; `rotation_distance: 40`. Belt length ≈ 2 × (pulley-to-idler span) + one pulley circumference, with the span ≥ 350 mm + carriage length |
| Home switch | NC microswitch at the "in" end |
| Hard stops | Both ends, set ≥ 2 mm beyond the soft limits (0 and 350) |
| Motor cable | Shielded 4-core from the top bay; lengths measured in Phase 0 |

## 4. Power Budget (single PSU)

Per motor: 2 × I² × R + ≈2 W driver/motion losses. Gantry motors are the stock Voron 2.4 set (owner, Rev I): A/B LDO-42STH40-2004MAH 1.1 Ω, Z LDO-42STH48-2004AC 1.6 Ω. The rows below use 1.65 Ω, so they slightly overestimate.

| Load | Basis | Estimate |
|---|---|---|
| X, Y | 0.8 A → 4.1 W each | 8 W |
| Z, Z1, Z2, Z3 | 0.65 A → 3.4 W each | 14 W |
| Pipette (EBB) | 0.65 A | 3 W |
| 6 plates | 1.0 A → 5.5 W each | 33 W |
| Logic: CB1, M8P, Octopus, EBB | — | 17 W |
| Fans | — | 10 W |
| MG996R via 6 V converter (≈0.9 A running, ~90% efficient) | — | 6 W typical, ≈17 W at stall |
| Display / accessories | allowance | 10 W |
| **Total** | | **≈ 100 W** typical, ≈ 115 W with a servo stall |
| Existing PSU | 24 V, ≥ 200 W | Typical ≈ 100 W ≤ 50% of rating; stall peak ≈ 115 W < 70% (R7); confirm with E-08 |

- **Keep the existing PSU.** The owner confirmed it is 24 V and ≥ 200 W (Rev I). The LRS-350-24 is only needed if it is ever replaced.
- **⛔ STOP** if Phase 0's recompute, against the rating on the PSU's label, gives a typical load above 50% of the rating or a peak above 70% (R7).

| Fuse | Branch | Expected | Rating |
|---|---|---|---|
| F1 | M8P (CB1, gantry, EBB via CAN cable) | ≈2 A | 7.5 A |
| F2 | Octopus V1.1 (main + motor power inputs) | ≈2 A | 5 A |
| F3 | Servo converter input | ≈0.7 A at stall | 3 A |

18 AWG for F1/F2, 20 AWG for F3. The PSU's AC input is downstream of the E-stop.

## 5. Wiring

- **CAN:** 4-core high-flex, twisted H/L, drag-chain rated, through the gantry cable chain; strain relief at both ends.
- **Servo:** signal + ground from the EBB, 6 V from the converter (§3.3). The run on the head is short.
- **Plate motors:** shielded 4-core; **switches:** shielded 2-core. Shields grounded at the controller end only; routed away from the CAN pair.
- **Labels** at both ends: `PLATE1-MTR`…`PLATE6-MTR`, `PLATE1-HOME`…`PLATE6-HOME`, `CAN-EBB`, `PIPETTE-MTR`, `PIPETTE-HOME`, `PIPETTE-SERVO`, `SERVO-6V`, `PSU-AC`, `PSU-F1-M8P`, `PSU-F2-OCTO`, `PSU-F3-SERVO`.

## 6. Bill of Materials

| # | Item | Part | Qty | Notes |
|---|------|------|-----|-------|
| 1 | Plate controller | BTT Octopus V1.1 (non-Pro, **STM32F446**) | 0 | Owner already has one, with drivers fitted |
| 2 | Drivers | BTT TMC2209 | 0 | Already fitted to the owner's Octopus (8 × V1.3) |
| 3 | Plate motors | LDO-42STH40-1684AC | 6 (+1) | |
| 4 | Pipette toolboard | BTT **EBB42 CAN V1.2** | 1 | Confirm "V1.2" on the packaging |
| 5 | PSU | Mean Well LRS-350-24 | 0 | Existing 24 V ≥ 200 W PSU kept (D11) |
| 6 | Fuses + holder/block | 7.5 A, 5 A, 3 A | 1 set | |
| 7 | Servo converter | 24 V in, 6 V ≥ 3 A out | 0–1 | D29. Reuse the existing 24→6 V unit if ≥ 3 A |
| 8 | Servo bulk capacitor | 470 µF+, ≥ 10 V | 1 | §3.3 |
| 9 | Pipette servo | MG996R | 1 (+1) | |
| 10 | GT2 6 mm belt | — | per drawer | Length per §3.5 |
| 11 | GT2 20T pulley (5 mm bore) / idler | — | 6 / 6 | |
| 12 | Home microswitches (NC) | — | 6 | Plus pipette if absent |
| 13 | CAN cable, high-flex | — | gantry run + 20% | |
| 14 | Shielded motor / switch cable | — | 6 + 6 runs | |
| 15 | USB cable CB1 → Octopus | — | 1 | Short, shielded |
| 16 | USB-C cable (bench DFU) | — | 1 | |
| 17 | microSD card (Octopus SD flashing) | — | 1 | |
| 18 | Octopus mounting + driver fan | — | 1 set | |
| 19 | Connectors, ferrules, labels, AC wiring | — | as needed | |

## 7. Firmware Build Environment (workstation)

Builds run on a **workstation**, never a CB1 (cb1-autopipette rule 8), using cb1-autopipette's pinned nixpkgs so firmware matches the machines (R9).

1. Clone `cb1-autopipette`. Re-read `flake.lock` at execution time; if the pin has moved from nixpkgs `c59305b` / Klipper `7bc4d094`, use the new one and note it.
2. **Validate the Kconfig files** in `reference/firmware/`:
   - Check out Klipper at the pinned rev.
   - Open a shell: `nix shell --inputs-from ./cb1-autopipette nixpkgs#gnumake nixpkgs#gcc nixpkgs#ncurses nixpkgs#python3 nixpkgs#gcc-arm-embedded`.
   - For each file, run `make olddefconfig KCONFIG_CONFIG=<file>` and confirm no symbol was dropped.
   - **Done once at Rev I** (Klipper 7bc4d09, ARM GCC 14.2.1): all three Klipper configs survive `olddefconfig` and build, and their `klipper.dict` files ran the WP2 offline tests. Repeat this with Nix's toolchain, because the Rev I check used a standalone toolchain.
3. **Build** each with the pinned `klipper-firmware`:
   ```
   nix build --impure --print-out-paths --expr '
     let f = builtins.getFlake "path:/abs/path/cb1-autopipette";
         pkgs = f.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
     in pkgs.klipper-firmware.override {
          mcu = "<name>"; firmwareConfig = /abs/path/reference/firmware/<file>; }'
   ```
   Keep each `klipper.bin` **and** `klipper.dict`; WP2's offline tests need the dicts.
4. **Katapult** for the EBB:
   - Clone `github.com/Arksine/katapult` and record the rev. Rev I checked `3b973a4` (2026-10-01).
   - Build with `reference/firmware/katapult-ebb42-v1.2.config`:
     - STM32G0B1, 8 MHz, CAN PB0/PB1, 1 Mbit/s, 8 KiB application offset, double-reset entry.
     - At Rev I, `olddefconfig` kept every symbol and the build succeeded (`katapult.bin`, 3.7 KB).
     - Katapult itself sits at `0x08000000` and launches Klipper at `0x08002000`, which matches the EBB's `STM32_FLASH_START_2000`.
   - Use the pinned Klipper's vendored `lib/katapult/flashtool.py` for CAN flashing (`-i can0 -u <uuid> -f <bin>`; `-q` to query).
   - For the **M8P bridge**, Katapult's README says USB-to-CAN bridge boards are flashed by putting them into the bootloader with `flashtool.py -r` and then using DFU or Katapult-USB. CB1-2's `flash-manta` follows that.
5. Record store paths, the Klipper rev, the Katapult rev and SHA-256 of each binary in the Phase 1 report. These artifacts are the inputs to CB1-1.

## 8. Bench Preparation (Phase 2)

1. **Octopus V1.1:**
   - Check the chip marking is STM32F446 (§3.1).
   - Set the jumpers per §3.1, run E-01, and photograph the board.
   - Flash by SD card: copy `klipper.bin` as `firmware.bin`, then power-cycle. The file becomes `FIRMWARE.CUR` when it has been taken (BTT manual).
   - Confirm `/dev/serial/by-id/usb-Klipper_stm32f446xx_*` appears. Don't write the ID down (D34).
2. **EBB42:**
   - Fit VUSB and enter DFU (hold BOOT, tap RESET). Confirm with `dfu-util -l` (ID `0483:df11`).
   - Flash Katapult, erasing the chip first (Katapult's README recommends a full chip erase):
     ```
     dfu-util -d 0483:df11 -a 0 -R -s 0x08000000:mass-erase:force:leave -D katapult.bin
     ```
     Address and `-a 0 -R … :leave` match Klipper's own `scripts/flash_usb.py`. `mass-erase:force` is a standard dfu-util DfuSe modifier, still to be run once on the bench (VR-16).
   - Remove VUSB; fit 120 Ω. Klipper is flashed over CAN in §9.

**Rollback:**
- Octopus: reflash the previous firmware by SD card (it's the owner's existing board, so keep its current `firmware.bin` or `FIRMWARE.CUR` from the SD card first).
- EBB: reflash in DFU.

## 9. CAN Bring-up & Install (Phases 5–6, on machine)

Requires WP3 merged and switched (umbrella Phase 4). Procedure steps that touch the machine's config are in RB1.

1. Back up `/var/lib/moonraker/config/` (RB1 §2).
2. **⛔ STOP** until all of these are true (umbrella Phase 5 entry):
   - VR-17 is closed: `flash-manta` over CAN, and `flash-manta --firmware` back to USB firmware, both rehearsed on a spare M8P.
   - The previous `mantaFirmware` path is recorded (`phase0-survey.md` §2).
   - The RB1 §2 backup exists off the machine.

   Then flash the M8P bridge firmware with CB1-2's `flash-manta`. **The machine is down from here until umbrella Phase 7 ends.**
3. Confirm `can0` is up (CB1-3).
4. With power off, wire the bus and run E-02.
5. Power on; query UUIDs with Klipper stopped. Identify the M8P with the EBB unplugged.
6. Flash Klipper to the EBB with `flash-ebb`. Write the UUIDs straight into the machine's `printer.cfg` (CB1-4 bootstrap, or by hand). **Don't record them anywhere else** (D34).
7. **⛔ STOP** for the owner's go-ahead before rewiring: from here, rollback means re-wiring (RB1 §5). Then install:
   - PSU and fuses (§4).
   - Octopus mount + USB.
   - EBB on the pipette motor; move the stepper, endstop and servo signal to it.
   - Servo buck.
   - Drawer drives with hard stops and switches.
   - Labels.
8. Photo checklist of every termination.

**Rollback:** RB1 §5. Re-wire the pipette and servo to the M8P (original pins in umbrella §5.1).

## 10. Electrical Tests

**Phase** = the umbrella phase whose exit needs the test. Tests marked 7 need Klipper running with the new config, so they run after config migration (RB1 §3).

| ID | Phase | Test | Pass criteria |
|---|---|---|---|
| E-01 | 2 | Octopus power inputs before first power-up: multimeter at the main power and motor power terminals, polarity included | Both ≈ +24 V; bed input unconnected |
| E-02 | 5 | CAN H–L resistance, unpowered | 55–65 Ω |
| E-03 | 5 (idle), 7 (motion) | `ip -details -statistics link show can0`, 10 min idle, then 10 min with motion | No error growth |
| E-04 | 5 (CAN), 6 (Octopus) | Board detection | 2 UUIDs on can0; Octopus by-id present |
| E-05 | 7 | Home switches with `QUERY_ENDSTOPS` | Each switch toggles only its own entry. Plates: NC (open = triggered). Plunger: same polarity as today |
| E-06 | 7 | `STEPPER_BUZZ` each plate stepper (drawer mid-travel) and the plunger, after `G28 Z` with the tip raised (a plate is refused otherwise). X/Y/Z wiring is unchanged by this plan; buzzing a Z stepper needs every plate homed and parked | Correct motor per slot |
| E-07 | 6 | E-stop with the machine powered | PSU output drops; all boards and the servo converter lose power |
| E-08 | 7 | PSU current: all motors holding, then simultaneous motion | Holding < 50% of rating; motion peaks < 70% (R7); branches under F1/F2/F3 |
| E-09 | 6 | Inspection | Exactly one 24 V PSU in the machine |
| E-10 | 7 | 30 min with all plate motors enabled at run current | No TMC over-temperature warnings |
| E-11 | 6 | Hard stops, by hand, motors disabled | Engage ≥ 2 mm beyond 0 and 350; before any collision |
| E-12 | 7 | Servo stall (horn held) during commanded motion | Converter output ≥ 5.7 V; no EBB brownout; no CAN errors |

## 11. Risks

See umbrella §12: K-HW-01…K-HW-06, K-OPS-01. Hazards H-01, H-06, H-07.

## 12. Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| H | 2026-10-20 | James / Claude | Split out of the single plan (Rev G §5–§7, §9 Phases 1–2/5–6, §10.1). 350 mm travel; MG996R with separate buck on fuse F3; E-tests renumbered |
| I | 2026-10-20 | James / Claude | EBB pins PB7/PB9 verified on BTT's pinout. Firmware configs validated and built at the pin. Katapult config added and built (rev 3b973a4); `dfu-util` command added. Wiring diagrams in `diagrams.md`. Owner: keep existing PSU; Voron 2.4 motors; 350 mm confirmed |
| J | 2026-10-21 | James / Claude | Review fixes: power rule per R7 (50% typical / 70% peak); ⛔ before the first M8P reflash and before rewiring; E-tests tagged with the phase that needs them (powered tests after config migration); board IDs only in the machine's printer.cfg; PB7 marked image-verified |
| K | 2026-10-22 | James / Claude | E-06 scope aligned with the interlock (plates and plunger; Z steppers need plates parked) |
| L | 2026-10-22 | James / Claude | Plate controller is the owner's **Octopus V1.1 (non-Pro, STM32F446)**: pin map from Klipper's non-Pro config (Driver3 enable PA0), F446 firmware (32 KiB bootloader, 12 MHz), power via main + motor inputs (no voltage jumpers), E-01 rewritten, BOM qty 0 for board and drivers |

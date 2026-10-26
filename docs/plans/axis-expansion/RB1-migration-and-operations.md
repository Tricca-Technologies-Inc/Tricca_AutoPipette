# RB1 — Machine Migration, Rollback & Operations

| Field    | Value |
|----------|-------|
| Status   | Draft for review (approval in the umbrella header) |
| Revision | L |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Parent   | `00-umbrella-plan.md` |
| Applies to | Existing machines (nick, marie) and any machine seeded before CFG-1 |
| Date     | 2026-10-22 |

---

## 1. Purpose & Scope

Step-by-step procedures for a person or agent working **on a machine**:
- Backing up config.
- Migrating its machine-owned Klipper config (ADR-0005: config seeds once, so pin bumps don't reach existing machines).
- Rolling back.
- What changes for operators, including E-stop recovery.

**Prerequisites:**
- Umbrella Phases 4–6 complete: WP3 merged, primed and switched; CAN up; hardware installed.
- The machine's completed `phase0-survey.md`.

Operate as root on the machine (cb1-autopipette hard-won rule 6).

## 2. Backup (before any change)

1. `sudo systemctl stop klipper`
2. `sudo tar czf /root/moonraker-config-$(date +%Y%m%d-%H%M%S).tgz -C /var/lib/moonraker config`
3. Copy the tarball off the machine (workstation) and record its name in `docs/machines/<host>.md`.
4. Record the current M8P firmware binary path (the current `mantaFirmware` store path) for rollback.

## 3. Config Migration

1. **Check local edits.** Diff each file in `/var/lib/moonraker/config/*.cfg` against the `printer-cfgs` rev the machine was seeded from (Phase 0 survey).
2. **Path A — re-seed (no local edits beyond the bootstrap `[mcu]` block, and no `SAVE_CONFIG` block in printer.cfg):**
   1. Move printer.cfg aside: `mv printer.cfg printer.cfg.pre-upgrade`.
   2. Start klipper. Its preStart copies **all** `*.cfg` from the new pin, **overwriting the other cfg files**.
   3. Stop klipper.
3. **Path B — hand merge (anything else):**
   1. Copy `ebb-pipette.cfg`, `octopus-plates.cfg` and `plate-macros.cfg` from the pinned `printer-cfgs` store path.
   2. Apply `reference/klipper/printer.cfg.md` to the machine's `printer.cfg` and `tricca-autopipette.cfg`, preserving local edits.
   3. Show the owner the full diff. **⛔ STOP** for approval.
4. **MCU sections.** Replace the old `[mcu] serial:` with the three sections:
   - `[mcu]` canbus_uuid (M8P)
   - `[mcu EBBCan]` canbus_uuid
   - `[mcu octopus]` serial
   Find them with the query tool as in WP1 §9, or let CB1-4's bootstrap write them. They live **only** in this `printer.cfg` and its backup (D34); never copy them into `docs/machines/` or onto a form.
5. **Per-machine values.** Set from the Phase 0 survey, and record each in `docs/machines/<host>.md`:
   - `_PLATE_CFG.z_safe`
   - each plate's `position_max`, only if it differs from 350
   - `_PIPETTE_CFG.home_dir`, only if Phase 0 measured −1
6. Start klipper. Check `klippy.log` for config errors and for "MCU has deprecated code" (it would mean a firmware/host mismatch).
7. **Powered checks (umbrella Phase 7 exit):** E-03 (motion), E-05, E-06, E-08, E-10, E-12 (WP1 §10).
8. **Stage-1 validation (Phase 8):** umbrella §9 tests M-01…M-19 and M-23. Record results on `commissioning-sheet.md`.

## 4. Operations

### 4.1 What changes for operators

- **Home (bare `G28`, the kiosk Home button, `tap init` / `home all`):**
  - It now pulls **all six drawers in** and **homes the plunger**, after the gantry.
  - Keep hands clear of the drawer openings while homing.
  - The plunger homes **after** the gantry parks, so liquid left in the tip is pushed out at the park position (X150 Y150, tip fully raised). Keep that spot clear of open labware, or put a waste tray there.
- **Drawers only move** on a plate command or during homing.
- A plate command is **refused** if:
  - the gantry isn't homed,
  - the tip is lowered below the safe height, or
  - the plate isn't homed.
- **The tip won't lower** while any drawer is part-way out or unhomed. Retract or finish the drawer move first.
- **After motors are switched off** (`M84`, idle timeout, or a stepper disabled by hand), the plates and plunger count as unhomed, even if a motor is switched back on. Home again.
- **Pause and resume:** if you move a drawer while a run is paused and the tip would come down onto it, **Resume is refused** and the run stays paused. Park the drawer (fully in or fully out) and resume again.
- **Mainsail's Z-offset buttons** move the tip too, and the same rules apply: they're refused while a drawer is part-way out.
- Error messages start with `Move refused by interlock:` and state the reason.
- **`G28` takes only the letters X Y Z U V W A B C P, separated by spaces.** Anything else (`G28 E`, `G28 XY`) is refused instead of homing everything.
- **`MANUAL_PROBE` and `Z_ENDSTOP_CALIBRATE` are disabled** on these machines.
- **If homing fails**, Klipper switches the motors off: everything counts as unhomed. Fix the cause and home again.
- **Never type** `G1.1`, `G0.1`, any command ending in `_BASE`, `M84.1`/`M18.1`, anything with `_PLATE_INTERNAL`, or `SET_GCODE_VARIABLE` on `_PLATE_CFG`, `_PLATE_STATE`, `_PIPETTE_CFG`, `_PIPETTE_STATE` or `_GSTATE`. They are Klipper's unchecked originals and bypass the collision protection.

### 4.2 E-stop recovery

The E-stop cuts all power: CB1, both controllers, the EBB and the servo.

1. **Before resetting the E-stop**, clear the hazard. Check that nothing (hands, labware) is in a drawer's path or under the gantry.
2. **Reset the E-stop.** Wait for the kiosk to return; the CB1 boots and Klipper starts. Everything is now **unhomed**, and any running protocol has ended. If Klipper reports an MCU or CAN error (a board came up after Klipper did), send `FIRMWARE_RESTART` from the Mainsail console.
3. **Note where the protocol stopped** (run status or `tap` history) before doing anything else.
4. **Tip check.**
   - If a tip is on and holds liquid you care about, remove the tip by hand now. Homing expels it at the park position (§4.1).
   - Reconcile tip inventory afterwards with `tips` / `set_tips` (tapd's persisted state is from before the stop).
5. **Home** (§4.1). Drawers retract, the plunger homes.
6. **Check state:** `QUERY_PLATES` (Mainsail console) or the plate-status command in `tap` (TAP-4) shows all plates homed and in.
7. **Resume:** restart the protocol from a safe step, or start it again.

Drill this once per machine during commissioning (M-18).

## 5. Rollback

Use when stage-1 validation fails and the cause can't be fixed quickly. **The order matters**: the M8P must be reflashed while the new generation (with CAN tools) is still active, and the Octopus must be unplugged first so no tool mistakes it for the main board.

1. Stop klipper.
2. **Unplug the Octopus's USB** (so no tool can pick it up as the main board).
3. **Reflash the M8P back to its previous USB firmware** (path recorded in `phase0-survey.md` §2), still on the new generation:
   `flash-manta --firmware <previous mantaFirmware>/klipper.bin` (CB1-2).
   - **Fallback** if that fails: hold BOOT, tap RESET, then
     `dfu-util -d 0483:df11 -a 0 -s 0x08020000:leave -D <previous mantaFirmware>/klipper.bin`.
     `dfu-util` is installed system-wide by CB1-2; on an older generation use `nix run nixpkgs#dfu-util -- <same arguments>`.
     `0x08020000` keeps BTT's 128 KiB bootloader, the same address today's `flash-manta` uses.
   - Check: `/dev/serial/by-id/usb-Klipper_stm32h723xx_*` appears, and exactly one does.
4. `switch` to the previous cb1-autopipette generation (removes the CAN unit and the new flash helpers).
5. Restore the §2 tarball over `/var/lib/moonraker/config`. This brings back the old `printer.cfg`, including its `[mcu] serial:`.
6. Re-wire the pipette stepper, endstop and servo to the M8P (original pins in umbrella §5.1).
7. Start klipper and run tapd's existing protocol (M-08) to confirm the old behavior.

**Stage-2 rollback:** CB1-7 switches both pins back together. Then set `variable_stage: 1` and remove the plunger `position_min`/`position_max` lines in the machine's config (WP2 CFG-3), and restart Klipper. No re-wiring.

## 6. Per-machine Record (template for `docs/machines/<host>.md`)

```
## Axis expansion (umbrella plan rev J)
(No MCU serial IDs or CAN UUIDs in this file: they live only in the machine's printer.cfg, D34.)
- Migration path: A (re-seed) | B (hand merge)  — date, operator
- Backup tarball: <name> (stored off the machine; contains the IDs)
- Firmware SHA-256: m8p-bridge …, octopus …, ebb42 …, katapult …
- z_safe: …    plate travel: …    home_dir: …
- Tests M-01…M-19, M-23: pass/fail, date (attach the signed commissioning sheet)
- Stage 2 deployed: date (CB1-7 PR #)
```

## 7. Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| H | 2026-10-20 | James / Claude | Split out of the single plan (Rev G §9.7). Added backup detail, rollback, operator notes and E-stop recovery |
| I | 2026-10-20 | James / Claude | Points to the commissioning sheet |
| J | 2026-10-21 | James / Claude | Review fixes: rollback reordered (unplug Octopus, reflash M8P on the new generation with `flash-manta --firmware`, DFU fallback address, then switch generation); stage-2 rollback via CB1-7 and `variable_stage`; IDs only in printer.cfg; Phase 7 powered checks; operator notes for paused-run resume, Z-offset buttons, never-type commands, park-position liquid, `FIRMWARE_RESTART` after E-stop |
| K | 2026-10-22 | James / Claude | `dfu-util` availability for the rollback fallback; never-type list adds `SET_GCODE_VARIABLE` on the interlock's macros; operator notes on disabled probe commands and `G28` letters |
| L | 2026-10-22 | James / Claude | Octopus V1.1 naming |

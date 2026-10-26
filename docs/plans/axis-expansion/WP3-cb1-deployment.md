# WP3 — Deployment (`cb1-autopipette`)

| Field    | Value |
|----------|-------|
| Status   | Draft for review (approval in the umbrella header) |
| Revision | L |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Parent   | `00-umbrella-plan.md` |
| Repo     | https://github.com/Tricca-Technologies-Inc/cb1-autopipette (base `130d38b`) |
| Date     | 2026-10-22 |

---

## 1. Purpose & Scope

Teach the deployment about the new topology: three firmware images, CAN-aware flashing, the `can0` interface, three-MCU detection in `bootstrap.sh`, a pin bump for each stage, and the docs that go with them. Delivered as issues **CB1-1…CB1-7** (CB1-1…CB1-6 were DEP-1…DEP-7 in Rev D–G; CB1-7 was split out of CB1-5 at Rev J).

**Binding rules from the repo** (read `CLAUDE.md`, `CONTEXT.md`, `docs/adr/` first):
- Firmware is built from the pinned source (ADR-0004).
- printer.cfg seeds once (ADR-0005).
- Prime before switch (ADR-0009).
- Nix units call apt binaries by absolute path (rule 1).
- Never build heavyweight packages on a CB1 (rule 8).
- Format and lint with `nixfmt` / `statix` / `deadnix` (CI `lint` job).
- Issues use the repo's canonical triage labels (`docs/agents/triage-labels.md`). Labels per umbrella D32.

## 2. Requirements (from umbrella §4)

R6, R9. Also the agent rule "never write MCU serial IDs or CAN UUIDs into a repo" (umbrella §1).

## 3. Interfaces Consumed

- Kconfig files: `reference/firmware/*.config` (WP1 §7 validates them).
- Config set: `Tricca_Autopipette_Configs` at CFG-1 (stage 1) / CFG-3 (stage 2).
- tapd: `Tricca_AutoPipette` at the TAP issues' merge commits.

## 4. Issues

---

### CB1-1 — Build M8P bridge, Octopus V1.1 and EBB42 firmware from the pinned Klipper source

- **Labels:** `needs-triage`
- **Blocked by:** WP1 Phase 1 (validated Kconfig files)
- **Blocks:** CB1-2, umbrella Phase 4

**Context.**
- `mantaFirmware` builds the M8P's `klipper.bin` from the pinned Klipper (ADR-0004).
- The upgrade adds two boards (Octopus V1.1 F446 over USB, EBB42 over CAN) and turns the M8P into a USB-to-CAN bridge.

**Goal.**
- `mantaFirmware` builds from `m8p-bridge.config` (replacing `klipper-manta-mcu.config`).
- New derivations build the Octopus V1.1 (`octopus-v1.1-f446.config`) and EBB42 Klipper images the same way.
- Optionally, a derivation builds the EBB's Katapult bootloader from a pinned `Arksine/katapult` input, using `reference/firmware/katapult-ebb42-v1.2.config` (built and checked at Katapult `3b973a4`, WP1 §7).

**In scope.**
- The three Klipper `config/*.config` files, copied from `reference/firmware/` (and the Katapult config if the optional derivation is done). All were validated and built at the pin in plan Rev I.
- Derivations following `mantaFirmware`'s pattern (ship only `klipper.bin`; `disallowedReferences` on the ARM toolchain, issue #30).
- Exposure as `packages.aarch64-linux.*`.
- ADR-0004 updated to cover all three boards.

**Acceptance criteria.**
- CI's `flake-check` builds all images.
- Each binary's SHA-256 matches a workstation build of the same Kconfig at the same pin (WP1 §7 record).
- The runtime closure doesn't grow by the ARM toolchain.

**Rollback.** Revert the PR. Nothing reaches a machine until a generation containing it is switched to; if one was, `switch` to the previous generation (its `mantaFirmware` is the old USB build).

---

### CB1-2 — Flash helpers that can't target the wrong board: `flash-manta` (CAN), `flash-octopus`, `flash-ebb`

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** CB1-1
- **Blocks:** umbrella Phase 5

**Context.**
- Today's `flash-manta` finds the board via `/dev/serial/by-id/usb-Klipper_stm32h723xx_*`.
- After the upgrade, the M8P is a CAN bridge with no serial device, and the Octopus is a USB device too (`usb-Klipper_stm32f446xx_*`). The existing H723 glob can't match it, but any looser glob (`usb-Klipper_*`) would.

**Goal.**
- **`flash-manta`:** request the bootloader over CAN via `flashtool -i can0 -u <M8P uuid> -r`, then flash via DFU as today. The UUID comes from the machine's printer.cfg `[mcu]` section, or an explicit argument.
- **`flash-octopus`:** use the exact recorded `[mcu octopus]` by-id path, never a glob.
- **`flash-ebb`:** run `flashtool -i can0 -u <EBB uuid> -f <ebb42 klipper.bin>`.
- All three stop `klipper.service` first and restart it afterwards, as `flash-manta` does now.
- **`flash-manta --firmware <klipper.bin>`** flashes a given binary instead of the generation's `mantaFirmware`. RB1 §5 needs this to put the old USB firmware back on a bridged M8P: the previous generation's `flash-manta` can't find the M8P once it is in bridge mode, because it enumerates as a CAN adapter, not a serial device.

**Acceptance criteria.**
- With all three boards attached, each helper refuses to proceed unless it has identified exactly its own board.
- `flash-manta` over CAN is **bench-verified** on a spare M8P before use on a machine. Document the BOOT+RESET fallback in README Troubleshooting.
- `flash-ebb` updates the EBB without touching it physically.
- `flash-manta --firmware` with the previous USB build, run on a bridged spare M8P, brings it back as a USB serial device (rehearses RB1 §5).
- `dfu-util` is installed system-wide (`environment.systemPackages`, from the Nix cache; no build on the CB1), so RB1 §5's manual DFU fallback works without `flash-manta`.

**Rollback.** Revert the PR, or `switch` to the previous generation. A board left in DFU by a failed flash is recovered with BOOT+RESET and `dfu-util -d 0483:df11 -a 0 -s 0x08020000:leave -D <klipper.bin>` (from a generation with `dfu-util` installed, or `nix run nixpkgs#dfu-util -- …`) (M8P: 128 KiB BTT bootloader kept; for the Octopus F446 the address is `0x08008000`, keeping its 32 KiB bootloader, or reflash by SD card), or with Katapult over CAN for the EBB.

---

### CB1-3 — Nix-managed `can0` interface and Klipper ordering

- **Labels:** `needs-triage`
- **Blocked by:** —
- **Blocks:** umbrella Phase 5

**Context.**
- NetworkManager is the netplan renderer on these machines (`modules/networking.nix`); there is no systemd-networkd.
- Klipper needs `can0` up at 1 Mbit/s before it connects to the M8P bridge and EBB.

**Goal.**
- A systemd unit (system-manager) brings `can0` up with bitrate 1000000 and `txqueuelen 128`, bound to `sys-subsystem-net-devices-can0.device`.
- It calls `/usr/sbin/ip` by absolute path (rule 1).
- `klipper.service` gets `After=`/`Wants=` on it.

**Acceptance criteria.**
- `can0` comes up at boot and after unplugging/replugging the bridge.
- `nmcli device status` shows `can0` as unmanaged.
- Klipper connects on a cold boot without a manual restart.

**Rollback.** Revert the PR, or `switch` to the previous generation (the unit disappears; nothing else depends on it before Phase 5).

---

### CB1-4 — `bootstrap.sh`: detect and write three MCU sections

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** CB1-3
- **Blocks:** new-machine bring-up; RB1 for new machines

**Context.**
- `bootstrap.sh` appends `[mcu] serial:` for the single `usb-Klipper_*` device it finds.
- After the upgrade, that single device would be the Octopus, so the logic would write the wrong board as `[mcu]`.

**Goal.** Write three sections into the machine's printer.cfg:
- `[mcu]` with the M8P `canbus_uuid`.
- `[mcu EBBCan]` with the EBB `canbus_uuid`.
- `[mcu octopus]` with the Octopus `serial` by-id path.

**Identification.**
- Query `can0` with Klipper stopped.
- Tell the M8P from the EBB by asking the operator to unplug the EBB CAN cable and querying again.
- If anything is ambiguous, print instructions and **don't guess** (the script's existing style).

**Acceptance criteria.**
- On a machine with all three boards, bootstrap writes all three sections correctly.
- With a board missing, it writes nothing for that board and prints clear instructions.
- Re-running doesn't duplicate sections.
- The IDs go only into the machine's `printer.cfg` (machine-owned, outside git). Bootstrap never writes them anywhere else.

**Rollback.** Revert the PR, or `switch` to the previous generation. On a machine where the new bootstrap wrote sections, restore `printer.cfg` from the RB1 §2 backup.

---

### CB1-5 — Stage-1 pin bump

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** CFG-1, CB1-1…CB1-4
- **Blocks:** umbrella Phase 4 exit, Phases 5–8

**Context.** `printer-cfgs` and `tricca-src` are flake inputs.

**Goal.** Bump `printer-cfgs` to CFG-1's merge commit. Optionally bump `tricca-src` to a commit that contains stage-1 TAP work **and is older than TAP-6's merge**; name the commit explicitly in the PR, never "latest".

**Acceptance criteria.**
- Normal PR + CI + prime + switch path.
- The PR lists the umbrella phases it unlocks and confirms `tricca-src` doesn't contain TAP-6.

**Rollback.** `switch` to the previous generation.

**Note.** Existing machines don't re-seed config from a pin bump (ADR-0005). RB1 migrates them.

---

### CB1-7 — Stage-2 pin bump (both pins, one switch)

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** CFG-3 and TAP-6 merged
- **Blocks:** umbrella Phase 10

**Context.** Stage 2 changes the Klipper config and tapd's plunger handling together. Deploying one without the other breaks plunger homing or movement (K-SW-03).

**Goal.** Bump **both** `printer-cfgs` (CFG-3) and `tricca-src` (TAP-6) in **one commit / one PR**, so one switch deploys both.

**Acceptance criteria.**
- Normal PR + CI + prime + switch path.
- The PR explicitly confirms both pins changed.
- Machine-owned configs are migrated to stage 2 by hand in the same maintenance window (`stage2.patch.md`), since pin bumps don't re-seed (ADR-0005).

**Rollback.** `switch` to the previous generation (both pins revert together) and revert the machine's config to stage 1 (WP2 CFG-3 rollback).

---

### CB1-6 — Docs: topology ADR, machine records, operator notes

- **Labels:** `needs-triage`
- **Blocked by:** —
- **Blocks:** umbrella Phase 8 sign-off (not Phase 4: the machine record is filled in during commissioning, after Phase 8's tests)

**Goal.**
- **New ADR:** "M8P as USB-to-CAN bridge + EBB42 + Octopus V1.1". Record the decision, alternatives considered (U2C adapter, a second USB board without CAN), and consequences (three MCUs, CAN-aware flashing).
- **`docs/machines/<host>.md`** (tracked in git, so **no MCU or CAN IDs**; they live only in the machine's `printer.cfg` and its backup tarball):
  - `z_safe`, drawer travel, `home_dir`.
  - Firmware SHA-256s.
  - Phase 0 survey and commissioning results, with any IDs left out.
  - CB1-6 provides the template; each machine's record is filled in by a small follow-up PR during commissioning (RB1 §6).
- **README:**
  - **Operator section:** bare `G28` now moves all drawers in and homes the plunger; E-stop recovery from RB1 §4.2.
  - **Troubleshooting:** CAN bring-up and the flash-manta fallback.
- **`CLAUDE.md`:** update the architecture bullets for ADR-0004 and the new topology.

**Acceptance criteria.** Docs merged before umbrella Phase 8 sign-off. `grep` of the PR finds no `canbus_uuid` value or `usb-Klipper_…` serial.

**Rollback.** Revert the PR (docs only).

## 5. Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| H | 2026-10-20 | James / Claude | New work package (was "interface only" DEP-1…DEP-7 in Rev D–G); owner brought it into scope as issues CB1-1…CB1-6 |
| I | 2026-10-20 | James / Claude | CB1-1 points to the Katapult config and the Rev I build check |
| J | 2026-10-21 | James / Claude | Review fixes: CB1-5 split into CB1-5 (stage 1) and CB1-7 (stage 2); rollback on every issue; `flash-manta --firmware` for RB1 rollback; IDs only on the machine; stage-1 `tricca-src` pinned before TAP-6 |
| K | 2026-10-22 | James / Claude | Second-review fixes: CB1-6 gates Phase 8 sign-off, not the Phase 4 exit (removes a phase loop); CB1-2 installs `dfu-util` system-wide for the RB1 fallback |
| L | 2026-10-22 | James / Claude | Octopus V1.1 (non-Pro, F446) instead of the Octopus Pro H723: CB1-1 firmware file, flash-helper context, DFU address `0x08008000` |

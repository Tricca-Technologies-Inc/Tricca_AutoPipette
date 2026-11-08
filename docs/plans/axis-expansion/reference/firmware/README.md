# Firmware Kconfig files

Minimal, symbol-only files in the same style as `cb1-autopipette/config/klipper-manta-mcu.config`. Klipper's `CANBUS_FREQUENCY` defaults to 1000000 and is deliberately not set.

| File | Board | Built from | Notes |
|---|---|---|---|
| `m8p-bridge.config` | Manta M8P V2.0 | Klipper | USB-to-CAN bridge, CAN on PD0/PD1. Replaces `klipper-manta-mcu.config` |
| `octopus-v1.1-f446.config` | Octopus V1.1 (non-Pro), STM32F446 | Klipper | 32 KiB bootloader (application at `0x08008000`), 12 MHz crystal, USB on PA11/PA12, per Klipper's `generic-bigtreetech-octopus-v1.1.cfg`. This is the owner's board, identified from a photo of the chip marking (Rev L) |
| `ebb42-v1.2.config` | EBB42 CAN V1.2 | Klipper | 8 KiB Katapult offset, CAN on PB0/PB1 |
| `katapult-ebb42-v1.2.config` | EBB42 CAN V1.2 | Katapult | Bootloader at `0x08000000`, launches Klipper at `0x08002000`; CAN PB0/PB1, 1 Mbit/s; double-reset entry |

## Verification (plan Rev I, 2026-10-20; Octopus file Rev L, 2026-10-22)

| Check | Klipper `7bc4d09` | Katapult `3b973a4` |
|---|---|---|
| `make olddefconfig KCONFIG_CONFIG=<file>` keeps every symbol | All three pass | Pass |
| Builds (ARM GCC 14.2.1) | All three pass; each `klipper.dict` is used by WP2's offline tests (Octopus F446 `klipper.bin` 45.9 KB) | Pass (`katapult.bin` 3.7 KB) |

Repeat both checks with the pinned Nix toolchain (WP1 §7) before CB1-1 commits these files. Record the SHA-256 of each binary in the Phase 1 report.

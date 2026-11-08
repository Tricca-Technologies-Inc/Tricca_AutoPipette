# Offline Klipper Tests (reference for issue CFG-2)

These tests run the pinned Klipper in **batch mode** (no boards attached) against a checkout of `Tricca_Autopipette_Configs`. Each test case runs in its own klippy process, and the script checks that case's errors or reported state.

| File | Role |
|---|---|
| `run_offline_tests.py` | Builds a temporary, stubbed copy of the config, lints it, runs every case, and exits non-zero on any failure |
| `test-harness.cfg` | Test-only macros (`_T_HOME_PLATE`, `_T_HOME_ALL_PLATES`, `_T_STATE`, `_T_CMDS`). Included into the temporary copy only |
| `make_fixture.py` | Builds a "configs repo after CFG-1" (or after CFG-3 with `--stage 2`) from the configs repo plus `reference/klipper/`, so the tests can run before CFG-1 exists |
| `command-inventory.txt` | Every G-code command Klipper registers with this config, classified (checked, refused, bypass, no motion …). Case C-45 fails on any difference |
| `results-2026-10-22.txt` | The Rev L run (Octopus V1.1 F446): 55/55 stage 1, 52/52 stage 2, plus the Rev K check that the new cases fail on the Rev J config |

In the configs repo these files go under `tests/`. **Nothing goes at the repo root**, because cb1-autopipette seeds every root `*.cfg` onto machines.

## Running

```sh
# Before CFG-1 exists, build a config to test:
python3 tests/make_fixture.py --configs <Tricca_Autopipette_Configs> --out /tmp/fx1
python3 tests/make_fixture.py --configs <Tricca_Autopipette_Configs> --out /tmp/fx2 --stage 2

python3 tests/run_offline_tests.py \
  --klipper <klipper checkout at the pinned rev> \
  --config  <configs repo checkout, or a fixture dir> \
  --dicts   <dir with m8p-bridge.dict ebb42.dict octopus.dict host.dict> \
  --python  <python with klippy's dependencies>
```

- **Klipper:** the rev cb1-autopipette pins (7bc4d09 at plan Rev K). With Nix, `nix shell --inputs-from <cb1-autopipette>` provides it.
- **Dictionaries:** each firmware build writes `out/klipper.dict` (WP1 §7). The host one comes from a `CONFIG_MACH_LINUX=y` build.
- **Stage:** read from `variable_stage` in `_PIPETTE_CFG`. `--stage 1|2` overrides it.

## What the harness does

1. **Copies** the repo's root `*.cfg` into a temporary directory.
2. **Stubs the MCUs.**
   - Removes any `[mcu …]` sections and adds `[mcu]`, `[mcu EBBCan]` and `[mcu octopus]` with `serial: /dev/null`.
   - Keeps `[mcu CB1]`.
   - CAN MCUs crash batch mode (`canbus_bus_state` enumeration). The dictionaries still provide each board's commands and pins.
3. **Includes** `test-harness.cfg`.
4. **Lints** the configs. A lint failure fails the run.
   - `{-` or `-}` in a template: Jinja whitespace control silently drops the minus sign. Write `{0 - x}`.
   - `variable_stage` and the plunger soft limits must agree (both stage 1 or both stage 2).
5. **Runs one process per case** and checks the result:
   - **Refusal cases:** the expected error must appear **and nothing may move**. The harness records the state just before and just after the refused command, and the axis map and positions must be identical.
   - **Any template crash** (an `Error evaluating …` that isn't a deliberate refusal) fails the case, even one expecting "no error".
   - **Any unexpected log line** fails the case. Only a short list of harmless lines (state reports, "Pausing toolhead…", stepper enable notices, pause/resume actions, reactor timing dumps) and the expected refusal are allowed, so an unrecognised Klipper error can't pass silently.
   - **Command inventory (C-45):** Klipper's full registered-command list must equal `command-inventory.txt`. When a config change, a Mainsail update or a Klipper bump adds a command, classify it there, and add an interlock check and a C-test if it can move Z, a plate or the plunger.

## Batch-mode limits (verified at 7bc4d09)

| Limit | Consequence | Covered on hardware by |
|---|---|---|
| Homing moves never trigger early: each runs to its `MOVE` target, and the position is set to that target. Homing can't fail | G28 sequencing is tested. Switch behaviour is not: release checks, homing direction, trigger point. A failed `G28`'s motors-off is emulated with `M84.1`, which runs the same Klipper code (C-39) | M-02, M-03, M-04, M-14, M-23 |
| `delayed_gcode` doesn't fire before the input ends | Startup binding is tested by calling its body (`_PIPETTE_BIND`, case C-14b) | M-13 |
| No real time or latency | Template cost per `G1` isn't measured | M-15 |
| No skipped steps or stalls | Commanded-state limits (WP2 §4) can't be exercised | Known limit |

## Cases

C-ids match WP2 §5.
- **Both stages:** C-01…C-12, C-14b, C-15, C-19, C-19c, C-21…C-28c, C-30, C-30b, C-31, C-33…C-35, C-38, C-38b, C-40…C-43, C-45.
- **Stage 1 only:** C-13, C-16, C-18, C-19b, C-20, C-32, C-32b, C-39…C-39c.
- **Stage 2 only:** C-13s, C-17…C-17c, C-19s, C-36s, C-37s.

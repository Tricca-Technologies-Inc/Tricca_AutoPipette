# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tricca AutoPipette controls an automated liquid handling system (ALHS) built on the Voron 3D-printer/Klipper platform. A `cmd2`-based interactive shell (`tap`) sends JSON-RPC/G-code commands over WebSocket to a Moonraker instance running on the machine's controller board (Manta), which drives the gantry, syringe pump, and tip-ejection servo. A separate FastAPI "kiosk" app provides a touchscreen web UI for non-interactive protocol runs.

The root `README.md` is stale (marked `(OUTDATED!!!)`, describes a flat pre-`src/` layout) — do not trust it for current structure; this file supersedes it.

## Commands

```bash
# Install (editable, with dev tools)
pip install -e ".[dev]"

# Run the interactive shell
tap                          # connects to hostname/IP from config/system/system.json
tap --no-connect             # start without a WebSocket connection
tap --local-connect          # connect to ws://localhost/websocket (e.g. local Moonraker/mock)
tap --config <file.json>     # override system config (resolved under config/system/)
tap --log-level DEBUG

# Run the kiosk web backend
uvicorn autopipette_kiosk.main:app --host 0.0.0.0 --port 8000

# Lint / format / type-check
ruff check .
ruff format .
pyright

# Tests
pytest   # no tests currently exist in the repo; pytest is configured (pythonpath=src) but testpaths is commented out in pyproject.toml
```

Inside the `tap` shell, protocol files (`.pipette`, plain text — one shell command per line, blank lines allowed) are run with `run <path>`; see `protocols/*.pipette` for examples. `run` executes each line in batch mode, buffering G-code, then uploads and executes it as a single file on the pipette.

## Architecture

### Two independent apps, one core library
- `src/tricca_autopipette/` — the shell/CLI and hardware-control core. Entry point `tap` → `cli.main:main`.
- `src/autopipette_kiosk/` — a thin FastAPI app (`main.py` + a static `index.html`) that lists `.pipette` files and triggers runs by shelling out to `python -m tricca_autopipette.cli.main --local-connect` and piping `run <file>\nquit\n` into its stdin. It does not import the core library directly.

### Shell composition (`cli/tap_shell.py`)
`TriccaAutoPipetteShell` (a `cmd2.Cmd` subclass) owns:
- an `AutoPipette` instance (`core/autopipette.py`) — the domain/state layer,
- a `WebSocketClient` (`moonraker/websocket_client.py`) — async I/O in a background thread, exposing a sync `send_jsonrpc()`/futures-based `upload_gcode_file()`,
- a `MoonrakerRequests` builder (`moonraker/moonraker_requests.py`) — pure functions that build Moonraker JSON-RPC payloads,
- a `GCodeManager` (`core/gcode_manager.py`) — has an *immediate mode* (write file, upload, execute, delete) and a *batch mode* (accumulate G-code across multiple shell commands, used by `run` to execute a whole protocol as one uploaded file via `GCodeBuffer`).

Commands are split into `CommandSet` subclasses (`commands/*.py`, all extending `TAPCommandSet` in `base_command_set.py`, which exposes `self.shell` back to the parent `TriccaAutoPipetteShell`) and registered in `_register_command_sets()`:
- `MovementCommands` — `init`, `home`, `move`, `move_loc`, `move_rel`
- `PipetteCommands` — `pipette`, `aspirate`, `dispense`, `next_tip`, `eject_tip`, `dispose_tip`, `change_tip`
- `ConfigurationCommands` — `set`, `coor`, `plate`, `ls`, `switch_liquid`/`list_liquids`/`load_liquid`, `save_locations`/`load_locations`, `reset_plate(s)`, `del_loc`, `clear_locs`
- `ProtocolCommands` — `run`, `stop`, `pause`, `resume`, `cancel`, `break`
- `WebSocketCommands` — `send`, `notify`, `subscribe`/`unsubscribe`, `upload`, `read`/`read_all`, `reconnect`, `ping`, `ws_status`
- `UtilityCommands` — `wait`, `trigger`, `gcode_print`, `webcam`, `vol_to_steps`/`steps_to_vol`

Argparse parsers/arg dataclasses for commands live centrally in `commands/tap_cmd_parsers.py` (`TAPCmdParsers`), not next to each `do_*` method.

A `precmd` hook in `tap_shell.py` blocks movement/pipetting/`run` commands unless `AutoPipette.state.homed` is true (safety interlock — run `init` or `home all` first). Shell startup runs `core/.init_pipette` as a startup script and persists history to `core/.tap_history`.

### Config system (layered JSON, see `config/README.md`)
`JsonConfigManager` (`core/json_config_manager.py`) loads and merges:
- `config/system/*.json` — top-level, references network settings, gantry, pipette model, liquids
- `config/gantry/*.json` — kinematics (speeds/accel)
- `config/pipettes/*.json` — syringe kinematics, servo angles, volume capacity
- `config/liquids/*.json` — per-liquid overrides (viscosity, prewet/air-gap/blowout technique, optional custom calibration curve) merged on top of the pipette's base syringe kinematics
- `config/locations/*.json` (loaded separately by `LocationManager`, `core/location_manager.py`) — named coordinates and plate placements, including special `tipbox`/`waste_container` plate types
- `config/plates/*.json` — reusable plate templates (dimensions, well layout, dipping strategy), instantiated via `PlateFactory` in `core/plates.py` (registry-based: `Plate` → `PlateArray`/`PlateSingleton` → `TipBox`/`WasteContainer`)

Filenames not paths are passed around at the shell/CLI layer — `DefaultPaths`/`DefaultFilenames` (`core/pipette_constants.py`) resolve them against `DefaultPaths.DIR_REPO_ROOT` (repo root, four levels up from `pipette_constants.py`). `ConfigKey` centralizes JSON key name constants; use those instead of hardcoding strings when touching config parsing.

The kiosk (`autopipette_kiosk/main.py`) computes its own `REPO_ROOT` independently (two levels up from `main.py`) rather than importing `DefaultPaths` — keep both in sync if the package layout ever moves. It also honors an `AUTOPIPETTE_PROTOCOLS_DIR` env var override for `PROTOCOLS_DIR`.

### Domain model (`core/`)
- `autopipette.py` — `AutoPipette`: central controller tying config, location manager, G-code buffer, and volume converter together; owns `pipette()`/`aspirate()`/`dispense()`/tip-handling and multi-liquid switching (`switch_liquid`).
- `pipette_models.py` — pydantic-style dataclasses for `SystemConfig`, `GantryKinematics`, `PipetteModel`, `PipetteSyringeKinematics`, `PipetteState`, `TipState`, `FluidDisplacement`.
- `volume_converter.py` / `print_volume_equation.py` — volume↔motor-step conversion, including calibration-curve-based conversion.
- `coordinate.py` — `Coordinate`, used throughout for absolute/relative XYZ positions.
- `well.py` — `Well`, `StrategyType` (dipping/aspirate strategies per well).
- `plates.py` — plate class hierarchy + `PlateFactory` registry (`@PlateFactory.register(...)`-style pattern — check the file before adding a new plate type).
- `pipette_exceptions.py` — domain exceptions (`NoTipboxError`, `TipAlreadyOnError`, `NotALocationError`, etc.) — prefer raising/catching these over generic exceptions in this layer.
- `gcode_buffer.py` — low-level G-code line accumulation used by `GCodeManager`'s batch mode.

### Moonraker/WebSocket layer (`moonraker/`)
- `websocket_client.py` — `WebSocketClient` runs an asyncio event loop on a background thread; public API is synchronous (`send_jsonrpc`, `wait_for_connection`, context-manager support) with a `Queue`-based `MessageType` (`fatal_error`/`error`/`handler_error`/`notification`/`parse_error`) for async notifications/errors surfaced back to the shell.
- `moonraker_requests.py` — `MoonrakerRequests`: pure builders for Moonraker JSON-RPC payloads (printer control, file upload/print-start, etc.) — no I/O itself.

## Code style
- Target Python 3.12+, `from __future__ import annotations` at the top of modules.
- Ruff (`preview = true`) enforces pycodestyle/pyflakes/isort/pyupgrade/bugbear/simplify/comprehensions/return/annotations/**Google-style docstrings** (`D` rules, convention `google`, `D203`/`D213` ignored). Match the existing heavy-docstring style (Args/Returns/Raises/Example) in `core/` and `commands/` when adding public functions/classes there.
- Pyright runs in `strict` mode with `extraPaths = ["src"]` — keep new code fully typed.
- First-party import groups for isort: `tricca_autopipette`, `autopipette_kiosk`.

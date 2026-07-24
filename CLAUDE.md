# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tricca AutoPipette controls an automated liquid handling system (ALHS) built on the Voron 3D-printer/Klipper platform. A long-running control daemon (`tapd`) owns the single connection to a Moonraker instance running on the machine's controller board (Manta) — sending JSON-RPC/G-code over WebSocket to drive the gantry, syringe pump, and tip-ejection servo — and exposes a local control-plane WebSocket that two thin clients talk to: a `cmd2`-based interactive shell (`tap`) and a FastAPI "kiosk" touchscreen web UI for non-interactive protocol runs. Neither client connects to Moonraker directly.

The root `README.md` is stale (marked `(OUTDATED!!!)`, describes a flat pre-`src/` layout) — do not trust it for current structure; this file supersedes it.

## Commands

```bash
# Install (editable, with dev tools)
pip install -e ".[dev]"

# Run the control daemon first -- tap and the kiosk are both clients of it
# and do nothing useful until it's running.
tapd                          # connects to hostname/IP from config/system/system.json
tapd --no-connect             # start without a Moonraker connection (local testing)
tapd --local-connect          # connect to ws://localhost/websocket (e.g. local Moonraker/mock)
tapd --config <file.json>     # override system config (resolved under config/system/)
tapd --host / --port          # control-plane bind address (default 127.0.0.1:8765)
tapd --log-level DEBUG

# Run the interactive shell (a thin tapd client -- start tapd first)
tap                           # connects to ws://127.0.0.1:8765/control by default
tap --control-uri <uri>       # point at a different tapd instance
tap --log-level DEBUG

# Run the kiosk web backend (also a tapd client)
uvicorn autopipette_kiosk.main:app --host 0.0.0.0 --port 8000

# Lint / format / type-check
ruff check .
ruff format .
pyright

# Tests
pytest   # no tests currently exist in the repo; pytest is configured (pythonpath=src) but testpaths is commented out in pyproject.toml
```

Inside the `tap` shell, protocol files (`.pipette`, plain text — one shell command per line, blank lines allowed) are run with `run <path>`; see `protocols/*.pipette` for examples. `run` executes each line in batch mode, buffering G-code, then uploads and executes it as a single file on the pipette — all of this happens inside `tapd`, which `tap`'s `run`/`cancel`/`pause`/`resume` (and any other command, via a generic forwarding path) dispatch to over the control-plane connection.

## Architecture

### Three components, one core library
- `src/tricca_autopipette/` — the hardware-control core, the `tapd` daemon, and the interactive shell.
  - `daemon/` — `tapd` (entry point `daemon.main:main`), a long-running process that owns the single persistent Moonraker connection and exposes a local control-plane WebSocket (`ws://127.0.0.1:8765/control` by default) that both `tap` and the kiosk talk to instead of connecting to Moonraker themselves. See "The `tapd` daemon" below.
  - `cli/` — `tap` (entry point `cli.main:main`): `cli/remote_shell.py`'s `RemoteTapShell` is a thin client that owns no `AutoPipette`/`WebSocketClient` itself; `cli/tap_shell.py`'s `TriccaAutoPipetteShell` (the class that actually owns the domain/Moonraker layer, see "Shell composition") is hosted inside the daemon instead, via `daemon/headless_shell.py`'s `HeadlessTapShell` subclass.
  - `core/`, `commands/`, `moonraker/` — the domain model, command implementations, and Moonraker transport, shared by both `TriccaAutoPipetteShell` (still usable directly for local one-off scripting/testing with its own Moonraker connection) and `HeadlessTapShell`.
- `src/autopipette_kiosk/` — a thin FastAPI app (`main.py` + a static `index.html`) exposing `GET /protocols` (lists `.pipette` files via a local directory glob — the one thing it still does without the daemon), `POST /run` (calls the daemon's `run.start`), `POST /home` (calls `shell.exec "init"`), `POST /breakpoint/respond`, `GET /status`, and `WS /ws/status` (re-broadcasts the daemon's `notify_run_status`/`notify_breakpoint` pushes to connected browsers, event-driven rather than polled). It holds one persistent `WebSocketClient` connected to `tapd`'s control plane for the app's lifetime (FastAPI `lifespan`), and reports real completion — driven by Moonraker `print_stats` transitions — rather than inferring it from a subprocess's exit code.
- `systemd/` — unit files for both processes (`tapd.service`, `autopipette-kiosk.service`, the latter `Requires=`/`After=` the former) plus an install README.

### The `tapd` daemon (`daemon/`)
- `service.py` — `AutoPipetteService`: owns the one long-lived `HeadlessTapShell` (and, through it, the single `WebSocketClient` to Moonraker), the "current run" state, and the breakpoint-confirmation handshake. Exposes the async API (`execute_line`, `start_run`/`cancel_run`/`pause_run`/`resume_run`, `list_protocols`, `request_breakpoint`/`confirm_breakpoint`, `ping`) that `control_server.py` dispatches control-plane requests to.
  - `start_run` returns as soon as the run is *started*, not when it finishes: the actual protocol replay runs as a background task rather than being awaited inline, since `do_break` can pause for an arbitrarily long time waiting on a remote client and the `run.start` RPC itself must not block on that.
  - `cancel_run`/`pause_run`/`resume_run` deliberately bypass the service's dispatch lock — `do_cancel`/`do_pause`/`do_resume` only send a Moonraker control RPC, never touching the G-code buffer or `AutoPipette` domain state, and must be able to interrupt a run that's stuck (e.g. paused at a breakpoint, which holds the lock for the run's whole duration).
  - `execute_line` captures a command's output through two mechanisms at once: `contextlib.redirect_stdout` for rich's `rprint` calls (rich resolves `sys.stdout` dynamically on every call), and cmd2's own `PyBridge` (`cmd2.py_bridge`, the mechanism `do_py`/scripting uses) for everything routed through `self.shell.stdout` instead — argparse usage/error text and `self.poutput`/`self.perror` calls, none of which respond to `redirect_stdout` because cmd2 captures that reference once at shell construction. Using only one of the two silently drops half of a command's output.
- `headless_shell.py` — `HeadlessTapShell(TriccaAutoPipetteShell)`: runs with no TTY/`cmdloop()`. Replaces the interactive shell's precmd-based interlock (see below) with a `postparsing_hook`-based one backed by live Moonraker state, and a postcmd hook that persists tip/liquid state (see below) without any changes to `commands/*.py`.
- `moonraker_state.py` — `MoonrakerStateTracker`: subscribes to Klipper's `toolhead`/`print_stats` objects (`printer.objects.subscribe`) and tracks live `homed_axes` (for the interlock) and job completion (mapped onto run status) from real Moonraker pushes, rather than a locally-set flag or a subprocess exit code. Also persists tip/liquid state (`tip_state`, `has_liquid`, `current_liquid`) through Moonraker's `server.database` API so it survives daemon restarts — Klipper has no native notion of "is a pipette tip attached," so unlike homed-axes tracking this is a durability layer only, not a live-hardware-truth source.
- `control_server.py` / `control_requests.py` — the control-plane WebSocket server and its pure-function JSON-RPC request builders (`ControlRequests`, mirroring `MoonrakerRequests`'s shape and envelope). Methods: `shell.exec`, `run.start`/`status`/`cancel`/`pause`/`resume`/`confirm_breakpoint`, `protocols.list`, `daemon.ping`. Pushes: `notify_run_status`, `notify_breakpoint`.
- `main.py` — the `tapd` entry point; parses the `--config*`/`--no-connect`/`--local-connect` flags the old `tap` used to (they now configure the daemon's Moonraker connection, not a CLI client). Validates config file paths via `core/config_validation.py`'s `validate_config_files` — moved there from `cli/main.py`, which no longer loads config files at all.

Control-plane clients (kiosk, `tap`) reuse `moonraker/websocket_client.py`'s `WebSocketClient` unmodified as their transport — the control-plane envelope is deliberately isomorphic to Moonraker's own, so the same client class works for both hops.

### Homed-safety interlock
Backed by live Moonraker state, not a locally-mutated flag: `HeadlessTapShell` subscribes to Klipper's `toolhead` object and blocks movement/pipetting commands (`move`, `move_loc`, `move_rel`, `pipette`, `aspirate`, `dispense`, `next_tip`, `eject_tip`, `dispose_tip`, `change_tip`) unless `{"x","y","z"}` is a subset of the live `homed_axes` Klipper reports. `home`/`init` are exempt (they're what performs homing), and so is `run` itself — `runcmds_plus_hooks` already re-applies the interlock to every line inside a protocol, so a protocol that needs homing must include its own leading `home all`/`init` line. (Most files under `protocols/*.pipette` predate this and don't — home the machine once via the kiosk's Home button, or `tap`'s `init`/`home all`, before running them; `homed_axes` then stays true for the rest of the daemon's uptime, no need to re-home between runs.) There is no `--skip-homed-check` flag anymore — it was a blanket per-process bypass that never actually verified physical homing state, superseded by checking the real thing.

The check itself lives in a `register_postparsing_hook` callback (`PostparsingData` genuinely has a `stop` field) rather than the interactive shell's `precmd` hook — that one's "block the command" mechanism (`dataclasses.replace(data, stop=True)` on a `PrecommandData`) is broken against the installed cmd2 4.0 API (that dataclass has no `stop` field), so it silently fails to block anything; `TriccaAutoPipetteShell` still has this bug if instantiated directly, but nothing does anymore except one-off scripting. If `runcmds_plus_hooks` blocks a line mid-protocol, it aborts the *whole* remaining batch rather than skipping just that line — `AutoPipetteService.start_run` detects this via `HeadlessTapShell.last_blocked_command` and reports a clear error instead of leaving the run silently stuck at `"running"` forever.

### Shell composition (`cli/tap_shell.py`)
`TriccaAutoPipetteShell` (a `cmd2.Cmd` subclass) owns:
- an `AutoPipette` instance (`core/autopipette.py`) — the domain/state layer,
- a `WebSocketClient` (`moonraker/websocket_client.py`) — async I/O in a background thread, exposing a sync `send_jsonrpc()`/futures-based `upload_gcode_file()`,
- a `MoonrakerRequests` builder (`moonraker/moonraker_requests.py`) — pure functions that build Moonraker JSON-RPC payloads,
- a `GCodeManager` (`core/gcode_manager.py`) — has an *immediate mode* (write file, upload, execute, delete) and a *batch mode* (accumulate G-code across multiple shell commands, used by `run` to execute a whole protocol as one uploaded file via `GCodeBuffer`).

This class is hosted inside the daemon via `HeadlessTapShell` (see above) — the interactive `tap` CLI no longer instantiates it directly, `RemoteTapShell` does instead (`cli/remote_shell.py`): it registers no `CommandSet`s and forwards unrecognized commands verbatim to the daemon's `shell.exec` via cmd2's `default()`, with explicit thin wrappers for `run`/`cancel`/`pause`/`resume`/`continue`/`abort` so live progress renders from `notify_run_status`/`notify_breakpoint` pushes (delivered as async alerts via `add_alert`, same mechanism `send_rpc`'s background thread already used) instead of a single blocking round-trip.

Commands are split into `CommandSet` subclasses (`commands/*.py`, all extending `TAPCommandSet` in `base_command_set.py`, which exposes `self.shell` back to the parent shell — a `TriccaAutoPipetteShell`- or `HeadlessTapShell`-typed object, transparently) and registered in `_register_command_sets()`:
- `MovementCommands` — `init`, `home`, `move`, `move_loc`, `move_rel`
- `PipetteCommands` — `pipette`, `aspirate`, `dispense`, `next_tip`, `eject_tip`, `dispose_tip`, `change_tip`
- `ConfigurationCommands` — `set`, `coor`, `plate`, `ls`, `switch_liquid`/`list_liquids`/`load_liquid`, `save_locations`/`load_locations`, `reset_plate(s)`, `del_loc`, `clear_locs`
- `ProtocolCommands` — `run`, `stop`, `pause`, `resume`, `cancel`, `break` (`break` publishes a `notify_breakpoint` event and blocks on `AutoPipetteService.request_breakpoint`/`confirm_breakpoint` when hosted in the daemon — there's no TTY to prompt directly there — falling back to the old `self.shell.select(...)` prompt only if `breakpoint_handler` isn't wired up, i.e. `TriccaAutoPipetteShell` used standalone)
- `WebSocketCommands` — `send`, `notify`, `subscribe`/`unsubscribe`, `upload`, `read`/`read_all`, `reconnect`, `ping`, `ws_status`
- `UtilityCommands` — `wait`, `trigger`, `gcode_print`, `webcam`, `vol_to_steps`/`steps_to_vol`

Argparse parsers/arg dataclasses for commands live centrally in `commands/tap_cmd_parsers.py` (`TAPCmdParsers`), not next to each `do_*` method.

Shell startup runs `core/.init_pipette` as a startup script (replayed manually by `AutoPipetteService._run_startup_script` when hosted in the daemon, since the daemon never calls `cmdloop()`) and persists history to `core/.tap_history`.

### Config system (layered JSON, see `config/README.md`)
`JsonConfigManager` (`core/json_config_manager.py`) loads and merges:
- `config/system/*.json` — top-level, references network settings, gantry, pipette model, liquids
- `config/gantry/*.json` — kinematics (speeds/accel)
- `config/pipettes/*.json` — syringe kinematics, servo angles, volume capacity
- `config/liquids/*.json` — per-liquid overrides (viscosity, prewet/air-gap/blowout technique, optional custom calibration curve) merged on top of the pipette's base syringe kinematics
- `config/locations/*.json` (loaded separately by `LocationManager`, `core/location_manager.py`) — named coordinates and plate placements, including special `tipbox`/`waste_container` plate types
- `config/plates/*.json` — reusable plate templates (dimensions, well layout, dipping strategy), instantiated via `PlateFactory` in `core/plates.py` (registry-based: `Plate` → `PlateArray`/`PlateSingleton` → `TipBox`/`WasteContainer`)

Filenames not paths are passed around at the shell/CLI layer — `DefaultPaths`/`DefaultFilenames` (`core/pipette_constants.py`) resolve them against `DefaultPaths.DIR_REPO_ROOT` (repo root, four levels up from `pipette_constants.py`). `ConfigKey` centralizes JSON key name constants; use those instead of hardcoding strings when touching config parsing.

The kiosk (`autopipette_kiosk/main.py`) computes its own `REPO_ROOT` independently (`Path(__file__).parents[2]`: `autopipette_kiosk` → `src` → repo root) rather than importing `DefaultPaths` — keep both in sync if the package layout ever moves. `PROTOCOLS_DIR` (default `REPO_ROOT / "protocols"`, overridable via `AUTOPIPETTE_PROTOCOLS_DIR`) is resolved once at module import time, so changing the env var requires a process restart to take effect.

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

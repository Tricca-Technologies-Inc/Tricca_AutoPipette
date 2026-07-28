# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tricca AutoPipette controls an automated liquid handling system (ALHS) built on the Voron 3D-printer/Klipper platform. A long-running control daemon (`tapd`) owns the single connection to a Moonraker instance running on the machine's controller board (Manta) — sending JSON-RPC/G-code over WebSocket to drive the gantry, syringe pump, and tip-ejection servo — and exposes a local control-plane WebSocket that two thin clients talk to: a `cmd2`-based interactive shell (`tap`) and a FastAPI "kiosk" touchscreen web UI for non-interactive protocol runs. Neither client connects to Moonraker directly. `tapd` itself has no cmd2/CLI framework in it at all — it's a plain `AutoPipetteService` object plus an `aiohttp`-based control-plane server; cmd2 only exists in the two client processes.

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
pytest   # unit/integration tests under tests/ (pythonpath=src, testpaths=tests in pyproject.toml)
```

Inside the `tap` shell, protocol files (`.pipette`, plain text — one shell command per line, blank lines allowed) are run with `run <path>`; the command grammar is exactly the shell's own, so `commands/tap_cmd_parsers.py` is the authoritative reference for what a line may contain. The `protocols/` directory was cleared out and its remaining contents are not a reliable syntax reference — check a file against the parsers before assuming it runs. `run` executes each line in batch mode, buffering G-code, then uploads and executes it as a single file on the pipette — all of this happens inside `tapd`, which every `tap` command (not just `run`/`cancel`/`pause`/`resume`) dispatches to over the control-plane connection via a structured RPC.

## Architecture

### Three components, one core library
- `src/tricca_autopipette/` — the hardware-control core, the `tapd` daemon, and the interactive shell.
  - `daemon/` — `tapd` (entry point `daemon.main:main`), a long-running process that owns the single persistent Moonraker connection and exposes a local control-plane WebSocket (`ws://127.0.0.1:8765/control` by default) that both `tap` and the kiosk talk to instead of connecting to Moonraker themselves. See "The `tapd` daemon" below. There is no cmd2 anywhere in this process.
  - `cli/` — `tap` (entry point `cli.main:main`) instantiates `cli/remote_shell.py`'s `RemoteTapShell`, a `cmd2.Cmd` whose `do_*` methods are all thin wrappers around control-plane RPC calls; it owns no `AutoPipette`/Moonraker connection itself. `cli/tap_shell.py`'s `TriccaAutoPipetteShell` (see "Shell composition") is a *separate*, standalone `cmd2.Cmd` for local one-off scripting/testing — it is not used by `tap`/the daemon at all, it constructs its own `AutoPipetteService` (with its own direct Moonraker connection) internally.
  - `core/`, `commands/`, `moonraker/` — the domain model, command implementations (thin cmd2 adapters used only by `TriccaAutoPipetteShell`), and Moonraker transport.
- `src/autopipette_kiosk/` — a thin FastAPI app (`main.py` + a static `index.html`) exposing `GET /protocols` (lists `.pipette` files via a local directory glob — the one thing it still does without the daemon), `POST /run` (calls the daemon's `run.start`), `POST /home` (calls `movement.init`), `POST /breakpoint/respond`, `GET /status`, and `WS /ws/status` (re-broadcasts the daemon's `notify_run_status`/`notify_breakpoint` pushes to connected browsers, event-driven rather than polled). It holds one persistent `WebSocketClient` connected to `tapd`'s control plane for the app's lifetime (FastAPI `lifespan`), and reports real completion — driven by Moonraker `print_stats` transitions — rather than inferring it from a subprocess's exit code.
- `systemd/` — unit files for both processes (`tapd.service`, `autopipette-kiosk.service`, the latter `Requires=`/`After=` the former) plus an install README.

### The `tapd` daemon (`daemon/`)
- `service.py` — `AutoPipetteService`: the single business-logic/application-service object. Builds its own `AutoPipette` (domain layer), `WebSocketClient`/`MoonrakerRequests` (the one Moonraker connection), and `GCodeManager` directly in `__init__` — there is no intermediate shell object of any kind. Every command (`move`, `aspirate`, `switch_liquid`, `ls`-equivalents, WebSocket diagnostics, run lifecycle, ...) is a plain typed method here, taking one of `commands/tap_cmd_parsers.py`'s `*Args` dataclasses (or a bare value) and returning a `CommandResult` (`ok`/`message`/`data`). `control_server.py` dispatches control-plane RPCs straight to these methods (via `dataclasses.asdict`), and `commands/*.py`'s cmd2 adapters call them too (via `self.service`, see "Shell composition") — one implementation, two driving adapters.
  - Async, non-blocking API for the daemon (used by `control_server.py`): `start`/`stop` (connect/disconnect without blocking the event loop, via `asyncio.to_thread`), `start_run`/`cancel_run`/`pause_run`/`resume_run`/`stop_run`, `dispatch` (runs a sync method under the service's lock, in a worker thread), `request_breakpoint`/`confirm_breakpoint`, `ping`.
  - Plain sync counterparts for `TriccaAutoPipetteShell`'s standalone use, which has no event loop: `connect`/`disconnect`, `run_protocol_blocking` (blocks until the protocol finishes, reusing the exact same per-line dispatch loop `start_run` uses), and the underlying `send_cancel`/`send_pause`/`send_resume`/`emergency_stop` Moonraker calls the async wrappers just run via `asyncio.to_thread`.
  - `start_run` returns as soon as the run is *started*, not when it finishes: the actual protocol replay runs as a background task rather than being awaited inline, since a `break` line can pause for an arbitrarily long time waiting on a remote client and the `run.start` RPC itself must not block on that.
  - `cancel_run`/`pause_run`/`resume_run`/`stop_run` deliberately bypass the service's dispatch lock — they only send a Moonraker control RPC, never touching the G-code buffer or `AutoPipette` domain state, and must be able to interrupt a run that's stuck (e.g. paused at a breakpoint, which holds the lock for the run's whole duration).
  - `_run_protocol_sync`/`_dispatch_protocol_line` replay a `.pipette` file by tokenizing each line (`shlex.split`) and looking it up in one of two module-level dispatch tables (`_LINE_DISPATCH` for parser-backed commands, `_STR_ARG_DISPATCH` for the handful taking one bare string like `switch_liquid`) built from the exact same data `control_server.py`/`commands/tap_cmd_parsers.py` already define — one source of truth for "command name → parser → service method," not three. `break` is special-cased to call `request_breakpoint` directly. An unrecognized command name reports `CommandResult(ok=False, ...)` rather than raising (preserves old tolerant behavior for typos in committed protocol files), but any exception a *recognized* command's method raises aborts the rest of the batch.
- `moonraker_state.py` — `MoonrakerStateTracker`: subscribes to Klipper's `toolhead`/`print_stats` objects (`printer.objects.subscribe`) and tracks live `homed_axes` (for the interlock) and job completion (mapped onto run status) from real Moonraker pushes, rather than a locally-set flag or a subprocess exit code. Also persists tip/liquid state (`tip_state`, `has_liquid`, `current_liquid`) through Moonraker's `server.database` API so it survives daemon restarts — Klipper has no native notion of "is a pipette tip attached," so unlike homed-axes tracking this is a durability layer only, not a live-hardware-truth source.
- `control_server.py` / `control_requests.py` — the control-plane WebSocket server and its pure-function JSON-RPC request builders (`ControlRequests`, mirroring `MoonrakerRequests`'s shape and envelope). Method namespaces: `movement.*`, `pipette.*` (`transfer` for the `pipette` command, avoiding a `pipette.pipette` stutter), `config.*` (mutating commands plus `list_locations`/`list_plates`/`list_liquids`/`system_summary` reporting), `util.*`, `run.*` (`start`/`status`/`cancel`/`pause`/`resume`/`stop`/`confirm_breakpoint`), `ws.*` (WebSocket/Moonraker diagnostics: `status`/`ping`/`send`/`notify`/`subscribe`/`unsubscribe`/`upload`/`read`/`read_all`/`clear_queue`/`reconnect`), `protocols.list`, `daemon.ping`. Pushes: `notify_run_status`, `notify_breakpoint`, `notify_raw_event` (relays a `ws.subscribe`d raw Moonraker notification to every connected control-plane client, since an arbitrary client-side callback can't itself cross the wire). There's a dispatch-completeness test (`tests/daemon/test_control_server_dispatch_completeness.py`) asserting every `ControlRequests` builder has a matching `_call` branch.
- `main.py` — the `tapd` entry point; parses the `--config*`/`--no-connect`/`--local-connect` flags the old `tap` used to (they now configure the daemon's Moonraker connection, not a CLI client). Validates config file paths via `core/config_validation.py`'s `validate_config_files` — moved there from `cli/main.py`, which no longer loads config files at all.

Control-plane clients (kiosk, `tap`) reuse `moonraker/websocket_client.py`'s `WebSocketClient` unmodified as their transport — the control-plane envelope is deliberately isomorphic to Moonraker's own, so the same client class works for both hops.

### Homed-safety interlock
Backed by live Moonraker state, not a locally-mutated flag: `daemon/service.py`'s `require_homed(command_name)` decorator (applied directly to the gated `AutoPipetteService` methods — `move`, `move_loc`, `move_rel`, `transfer`, `aspirate`, `dispense`, `next_tip`, `eject_tip`, `dispose_tip`, `change_tip`) checks `self.moonraker_state.is_homed()` and raises `core/pipette_exceptions.py`'s `NotHomedError` if unset/false. `home`/`init` are exempt (they're what performs homing). Since the decorator wraps the whole method, the homed check always runs *before* any "soft precondition" short-circuit the method body itself might otherwise check first (e.g. `move_rel`'s all-zero-offset no-op) — deliberately, for consistent behavior across every gated method.

This one check now covers every call path uniformly — the interactive `TriccaAutoPipetteShell`, the daemon's protocol-file dispatch loop, and direct `ControlServer` RPCs all go through the same decorated method, so there's no separate hook to keep in sync (a prior interactive-shell-only `precmd` hook was broken against the installed cmd2 4.0 API and never actually blocked anything; standalone `TriccaAutoPipetteShell` use now gets the real check too, closing that gap). `_run_protocol_sync` aborts the whole remaining batch if a gated line raises `NotHomedError` (or anything else) rather than skipping just that line — protocol files aren't expected to include their own leading `home all`/`init` line, so home the machine once via the kiosk's Home button, or `tap`'s `init`/`home all`, before running them; `homed_axes` then stays true for the rest of the daemon's uptime. There is no `--skip-homed-check` flag — it was a blanket per-process bypass that never actually verified physical homing state, superseded by checking the real thing.

A matching `persist_tip_liquid_state` decorator (same file) persists tip/liquid state to Moonraker's database via `MoonrakerStateTracker.save_tip_liquid_state` whenever it actually changed, applied to the same gated methods plus `init`/`home`/`switch_liquid`/`load_liquid` — this also closes a gap a hook-based approach would have: every call path (RPC, protocol-file line, interactive) persists identically, since it's the method itself that's wrapped.

### Shell composition (`cli/tap_shell.py`)
`TriccaAutoPipetteShell` (a `cmd2.Cmd` subclass, for standalone/local-scripting use only — **not** used by `tap`/the daemon) constructs its own `AutoPipetteService` (`self.service`, `daemon/service.py`) in `__init__` — the exact same class the daemon builds directly, so this shell and `tapd` share one business-logic implementation, differing only in lifecycle: this shell calls `self.service.connect()`/`disconnect()` (plain sync) from its `preloop`/`postloop` hooks, while the daemon awaits `service.start()`/`stop()` (non-blocking wrappers around the same steps) from its own event loop.

Commands are split into `CommandSet` subclasses (`commands/*.py`, all extending `TAPCommandSet` in `base_command_set.py`, which exposes `self.shell` — the parent `TriccaAutoPipetteShell` — and `self.service`, a passthrough to `self.shell.service`) and registered in `_register_command_sets()`. Every `do_*` method is a thin adapter: parse args (via `@with_argparser`/a bare `Statement`), call `self.service.<method>(args)`, render the returned `CommandResult`/exception with `rprint`. `ls`/`list_liquids` call the service's data-only reporting methods (`list_locations`/`list_plates`/`list_liquids`/`system_summary`) and render the result as a `rich.table.Table` via `cli/report_tables.py` — shared with `RemoteTapShell` so both shells display these identically despite one running locally and one over the control plane.
- `MovementCommands` — `init`, `home`, `move`, `move_loc`, `move_rel`
- `PipetteCommands` — `pipette`, `aspirate`, `dispense`, `next_tip`, `eject_tip`, `dispose_tip`, `change_tip`
- `ConfigurationCommands` — `set`, `coor`, `plate`, `ls`, `switch_liquid`/`list_liquids`/`load_liquid`, `save_locations`/`load_locations`, `reset_plate(s)`, `del_loc`, `clear_locs`
- `ProtocolCommands` — `run` (calls `AutoPipetteService.run_protocol_blocking`, blocking until the protocol finishes or aborts), `stop`, `pause`, `resume`, `cancel` (all call the service's sync Moonraker-control methods directly), `break` (only reachable by typing it directly at the prompt outside a running protocol — inside one, the per-line dispatch loop calls `request_breakpoint` itself and never reaches this method; blocks on `AutoPipetteService.request_breakpoint`/`confirm_breakpoint` if `breakpoint_handler` is wired up — only true for the daemon — else falls back to `self.shell.select(...)`)
- `WebSocketCommands` — `send`, `notify`, `subscribe`/`unsubscribe`, `upload`, `read`/`read_all`, `reconnect`, `ping`, `ws_status`
- `UtilityCommands` — `wait`, `trigger`, `gcode_print`, `webcam`, `vol_to_steps`/`steps_to_vol`

Argparse parsers/arg dataclasses for commands live centrally in `commands/tap_cmd_parsers.py` (`TAPCmdParsers`), not next to each `do_*` method; `args_from_namespace` (same file) converts a parsed `Namespace` into the matching `*Args` dataclass, shared by `RemoteTapShell` and `AutoPipetteService`'s protocol-file dispatch.

Shell startup runs `core/.init_pipette` as a startup script (replayed manually via `AutoPipetteService._run_startup_script`'s per-line dispatch — the same one protocol files use — when hosted in the daemon, since the daemon never calls `cmdloop()`) and persists history to `core/.tap_history`.

### `RemoteTapShell` (`cli/remote_shell.py`)
The actual `tap` CLI. A `cmd2.Cmd` with no `CommandSet`s and no domain/Moonraker objects of its own — every `do_*` builds a `ControlRequests` request and sends it over the control-plane WebSocket, rendering the JSON response. Hand-written wrappers exist for `run`/`cancel`/`pause`/`resume`/`stop`/`continue`/`abort` (so live progress renders from `notify_run_status`/`notify_breakpoint` pushes, delivered as async alerts via `add_alert`) and for the WebSocket-diagnostics/reporting group (`send`/`notify`/`subscribe`/`unsubscribe`/`upload`/`read`/`read_all`/`clear_queue`/`reconnect`/`ws_status`/`ping`/`ls`/`list_liquids`); everything else (movement/pipette/most configuration/utility commands) is generated from a declarative `_STRUCTURED_COMMANDS` table (name, parser, request-builder) rather than ~25 near-duplicate hand-written methods. There is no `shell.exec`/generic-forwarding fallback — every command maps to a real control-plane RPC, and an unrecognized command falls through to cmd2's own built-in "unknown command" handling.

### Config system (layered JSON, see `config/README.md`)
`JsonConfigManager` (`core/json_config_manager.py`) loads and merges:
- `config/system/*.json` — top-level, references network settings, gantry, pipette model, liquids
- `config/gantry/*.json` — kinematics (speeds/accel)
- `config/pipettes/*.json` — syringe kinematics, servo angles, volume capacity
- `config/liquids/*.json` — per-liquid overrides (viscosity, prewet/air-gap/blowout technique, optional custom calibration curve) merged on top of the pipette's base syringe kinematics
- `config/locations/*.json` (loaded separately by `LocationManager`, `core/location_manager.py`) — named coordinates and plate placements, including special `tipbox`/`waste_container` plate types
- `config/plates/*.json` — reusable plate templates (dimensions, well layout, dipping strategy), instantiated via `PlateFactory` in `core/plates.py` (registry-based: `Plate` → `PlateArray`/`PlateSingleton` → `TipBox`/`WasteContainer`)

Filenames not paths are passed around at the shell/CLI layer — `DefaultPaths`/`DefaultFilenames` (`core/pipette_constants.py`) resolve them against `DefaultPaths.DIR_REPO_ROOT` — four levels up from `pipette_constants.py`, which is only correct for a src-layout checkout, so installed packages (Nix, pip, wheel) must set `AUTOPIPETTE_REPO_ROOT` to an absolute path (a relative one raises at import; both systemd units set it, see `systemd/README.md`). `ConfigKey` centralizes JSON key name constants; use those instead of hardcoding strings when touching config parsing.

The kiosk (`autopipette_kiosk/main.py`) takes its `REPO_ROOT` from `DefaultPaths.DIR_REPO_ROOT` rather than recomputing it from `__file__` — it used to do the latter, and the copy silently diverged (it missed the `AUTOPIPETTE_REPO_ROOT` override); don't reintroduce a second resolution path. `PROTOCOLS_DIR` (default `REPO_ROOT / "protocols"`, overridable via `AUTOPIPETTE_PROTOCOLS_DIR`) is resolved once at module import time, so changing the env var requires a process restart to take effect.

### Domain model (`core/`)
- `autopipette.py` — `AutoPipette`: central controller tying config, location manager, G-code buffer, and volume converter together; owns `pipette()`/`aspirate()`/`dispense()`/tip-handling and multi-liquid switching (`switch_liquid`).
- `pipette_models.py` — pydantic-style dataclasses for `SystemConfig`, `GantryKinematics`, `PipetteModel`, `PipetteSyringeKinematics`, `PipetteState`, `TipState`, `FluidDisplacement`.
- `volume_converter.py` / `print_volume_equation.py` — volume↔motor-step conversion, including calibration-curve-based conversion.
- `coordinate.py` — `Coordinate`, used throughout for absolute/relative XYZ positions.
- `well.py` — `Well`, `StrategyType` (dipping/aspirate strategies per well).
- `plates.py` — plate class hierarchy + `PlateFactory` registry (`@PlateFactory.register(...)`-style pattern — check the file before adding a new plate type).
- `pipette_exceptions.py` — domain exceptions (`NoTipboxError`, `TipAlreadyOnError`, `NotALocationError`, etc.), plus two daemon/service-lifecycle signals kept here to avoid an import cycle with `commands/*.py` (see that module's docstrings for why): `NotHomedError` (the homed-interlock's exception) and `ProtocolAbortedError` (raised when a `break` line's breakpoint is answered "abort"). Prefer raising/catching these over generic exceptions in this layer.
- `gcode_buffer.py` — low-level G-code line accumulation used by `GCodeManager`'s batch mode.

### Moonraker/WebSocket layer (`moonraker/`)
- `websocket_client.py` — `WebSocketClient` runs an asyncio event loop on a background thread; public API is synchronous (`send_jsonrpc`, `wait_for_connection`, context-manager support) with a `Queue`-based `MessageType` (`fatal_error`/`error`/`handler_error`/`notification`/`parse_error`) for async notifications/errors surfaced back to the shell.
- `moonraker_requests.py` — `MoonrakerRequests`: pure builders for Moonraker JSON-RPC payloads (printer control, file upload/print-start, etc.) — no I/O itself.

## Code style
- Target Python 3.12+, `from __future__ import annotations` at the top of modules.
- Ruff (`preview = true`) enforces pycodestyle/pyflakes/isort/pyupgrade/bugbear/simplify/comprehensions/return/annotations/**Google-style docstrings** (`D` rules, convention `google`, `D203`/`D213` ignored). Match the existing heavy-docstring style (Args/Returns/Raises/Example) in `core/` and `commands/` when adding public functions/classes there.
- Pyright runs in `strict` mode with `extraPaths = ["src"]` — keep new code fully typed.
- First-party import groups for isort: `tricca_autopipette`, `autopipette_kiosk`.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tricca AutoPipette controls an automated liquid handling system (ALHS) built on the Voron 3D-printer/Klipper platform. A long-running control daemon (`tapd`) owns the single connection to a Moonraker instance running on the machine's controller board (Manta) — sending JSON-RPC/G-code over WebSocket to drive the gantry, syringe pump, and tip-ejection servo — and exposes a local control-plane WebSocket that two thin clients talk to: a `cmd2`-based interactive shell (`tap`) and a FastAPI "kiosk" touchscreen web UI for non-interactive protocol runs. Neither client connects to Moonraker directly. `tapd` itself has no cmd2/CLI framework in it at all — it's a plain `AutoPipetteService` object plus an `aiohttp`-based control-plane server; cmd2 only exists in the two client processes.

The root `README.md` is stale (marked `(OUTDATED!!!)`, describes a flat pre-`src/` layout) — do not trust it for current structure; this file supersedes it.

This file describes the system as it **is**. Planned-but-unimplemented work lives in `docs/TODO.md` — check it before starting anything non-trivial, since several entries record decisions already taken and open questions that must be settled first. It also flags problems that are true of the code *today*: the "steps" vocabulary in `VolumeConverter`/`vol_to_steps` actually denotes **millimetres** (Klipper's `MANUAL_STEPPER` takes `MOVE` in mm, `SPEED` in mm/s, `ACCEL` in mm/s²) — a naming bug rather than a correctness one, but the names lie; and the non-atomic/lossy config writer. Note that neither `tapd`'s control plane nor the kiosk has **any** authentication — both are protected solely by binding loopback, so treat any change to a bind address as a security decision (see `systemd/README.md`).

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

# Run the kiosk web backend (also a tapd client).
# Loopback only -- the kiosk has no authentication; see systemd/README.md.
uvicorn autopipette_kiosk.main:app --host 127.0.0.1 --port 8000

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

**Client parity rule.** Every capability reachable from the kiosk must also be reachable from `tap`, and vice versa — neither client may be the only way to do something. This is nearly free if capability lands as an `AutoPipetteService` method plus a `ControlRequests` builder: both clients are thin adapters over the same control-plane RPCs, and `tap` picks it up by appending one row to `_STRUCTURED_COMMANDS` (`cli/remote_shell.py`). The way to break it is adding logic directly in `autopipette_kiosk/main.py`, which produces a kiosk-only capability with no RPC behind it, invisible to `tap` and to protocol files. `main.py` holds exactly one such thing today — the `/protocols` directory glob — and that is the shape to avoid repeating. Current gaps are tracked as `docs/TODO.md` item 14.

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

A sibling `persist_tip_presence` decorator (same file) does the same for the *other* piece of state Klipper has no notion of — which tip positions are still occupied — applied to `transfer`/`next_tip`/`change_tip` plus the location-loading and tip-inventory commands. It writes `TipBoxManager.snapshot()` under the `tip_presence` DB key, and only when the snapshot actually changed.

### Location loading and tip inventory
`LocationManager.load_from_json` is **additive** — loading a second file adds to the deck rather than replacing it, so a deck composes from reusable groups. `--replace`/`replace=True` opts into the old wipe-then-load. Everything is parsed and validated *before* anything is applied, so a missing file or a malformed entry leaves the existing deck untouched (it used to `clear()` first and validate second, wiping the deck on a mistyped filename). A duplicate name is last-load-wins with a WARNING naming both source files, tracked via `LocationManager._sources`/`source_of`.

Names are the sole identifier: `set_plate` no longer also files a waste container under the literal alias `"waste_container"`, which stored one plate under two names.

Tipboxes are registered with `core/tipbox_manager.py`'s `TipBoxManager` (see below) rather than merged, so `unload`/`del_loc` removes exactly one box and leaves every other box's consumed-tip state intact. `AutoPipette.next_tip` asks the manager for `(name, box, coord)` and takes the dip distance from *that* box — boxes may sit at different heights.

Because Klipper has no notion of tip occupancy, the operator reconciles the daemon's record with the physical boxes via `tips` (ASCII map; `--db` diffs it against the persisted state and flags divergent cells), `reset_tips <box>`/`reset_tips_all` (a fresh box was loaded), and `set_tips <box> <ranges> [--available]` (declare exact state — absolute, not additive, so it can restore positions too). A locations entry may also declare a partially-used box up front with `"tips": {"consumed": ["A1:C12"]}`.

**⚠️ Tip disposal is currently unsafe on a deck with no waste container.** `AutoPipette.pipette()` ends with a bare `if not keep_tip: self.dispose_tip()`, and `dispose_tip` raises `NoWasteContainerError` when none is configured — so the run **aborts mid-transfer with a tip still attached**. The planned fix (verify the waste container up front; otherwise return the tip to the exact tipbox position it came from; replace the `keep_tip` boolean with an explicit `tip_disposition` flag) is `docs/TODO.md` item 1. Do not add a "just eject it here" fallback — dropping a used tip over a sample plate is the failure mode that work removes.

### Shell composition (`cli/tap_shell.py`)
`TriccaAutoPipetteShell` (a `cmd2.Cmd` subclass, for standalone/local-scripting use only — **not** used by `tap`/the daemon) constructs its own `AutoPipetteService` (`self.service`, `daemon/service.py`) in `__init__` — the exact same class the daemon builds directly, so this shell and `tapd` share one business-logic implementation, differing only in lifecycle: this shell calls `self.service.connect()`/`disconnect()` (plain sync) from its `preloop`/`postloop` hooks, while the daemon awaits `service.start()`/`stop()` (non-blocking wrappers around the same steps) from its own event loop.

Commands are split into `CommandSet` subclasses (`commands/*.py`, all extending `TAPCommandSet` in `base_command_set.py`, which exposes `self.shell` — the parent `TriccaAutoPipetteShell` — and `self.service`, a passthrough to `self.shell.service`) and registered in `_register_command_sets()`. Every `do_*` method is a thin adapter: parse args (via `@with_argparser`/a bare `Statement`), call `self.service.<method>(args)`, render the returned `CommandResult`/exception with `rprint`. `ls`/`list_liquids` call the service's data-only reporting methods (`list_locations`/`list_plates`/`list_liquids`/`system_summary`) and render the result as a `rich.table.Table` via `cli/report_tables.py` — shared with `RemoteTapShell` so both shells display these identically despite one running locally and one over the control plane.
- `MovementCommands` — `init`, `home`, `move`, `move_loc`, `move_rel`
- `PipetteCommands` — `pipette`, `aspirate`, `dispense`, `next_tip`, `eject_tip`, `dispose_tip`, `change_tip`
- `ConfigurationCommands` — `set`, `coor`, `plate`, `ls`, `switch_liquid`/`list_liquids`/`load_liquid`, `save_locations`/`load_locations`/`unload_locations`, `reset_plate(s)`, `del_loc`, `clear_locs`, plus the tip-inventory group `tips`/`reset_tips`/`reset_tips_all`/`set_tips`
- `ProtocolCommands` — `run` (calls `AutoPipetteService.run_protocol_blocking`, blocking until the protocol finishes or aborts), `stop`, `pause`, `resume`, `cancel` (all call the service's sync Moonraker-control methods directly), `break` (only reachable by typing it directly at the prompt outside a running protocol — inside one, the per-line dispatch loop calls `request_breakpoint` itself and never reaches this method; blocks on `AutoPipetteService.request_breakpoint`/`confirm_breakpoint` if `breakpoint_handler` is wired up — only true for the daemon — else falls back to `self.shell.select(...)`)
- `WebSocketCommands` — `send`, `notify`, `subscribe`/`unsubscribe`, `upload`, `read`/`read_all`, `reconnect`, `ping`, `ws_status`
- `UtilityCommands` — `wait`, `trigger`, `gcode_print`, `webcam`, `vol_to_steps`/`steps_to_vol`

Argparse parsers/arg dataclasses for commands live centrally in `commands/tap_cmd_parsers.py` (`TAPCmdParsers`), not next to each `do_*` method; `args_from_namespace` (same file) converts a parsed `Namespace` into the matching `*Args` dataclass, shared by `RemoteTapShell` and `AutoPipetteService`'s protocol-file dispatch.

Shell startup runs `core/.init_pipette` as a startup script (replayed manually via `AutoPipetteService._run_startup_script`'s per-line dispatch — the same one protocol files use — when hosted in the daemon, since the daemon never calls `cmdloop()`) and persists history to `core/.tap_history`.

### `RemoteTapShell` (`cli/remote_shell.py`)
The actual `tap` CLI. A `cmd2.Cmd` with no `CommandSet`s and no domain/Moonraker objects of its own — every `do_*` builds a `ControlRequests` request and sends it over the control-plane WebSocket, rendering the JSON response. Hand-written wrappers exist for `run`/`cancel`/`pause`/`resume`/`stop`/`continue`/`abort` (so live progress renders from `notify_run_status`/`notify_breakpoint` pushes, delivered as async alerts via `add_alert`) and for the WebSocket-diagnostics/reporting group (`send`/`notify`/`subscribe`/`unsubscribe`/`upload`/`read`/`read_all`/`clear_queue`/`reconnect`/`ws_status`/`ping`/`ls`/`list_liquids`); everything else (movement/pipette/most configuration/utility commands) is generated from a declarative `_STRUCTURED_COMMANDS` table (name, parser, request-builder) rather than ~25 near-duplicate hand-written methods. There is no `shell.exec`/generic-forwarding fallback — every command maps to a real control-plane RPC, and an unrecognized command falls through to cmd2's own built-in "unknown command" handling.

### Config system (layered JSON, see `config/README.md`)
`JsonConfigManager` (`core/json_config_manager.py`) loads and merges:
- `config/system/*.json` — top-level, references network settings, gantry, pipette model, liquids, and the deck layout (`locations`). A config may `extends` another system file, shallow-merged per top-level key (cycle- and depth-guarded), so a per-protocol config carries only what differs — usually just `locations` — instead of duplicating machine settings that would then drift.
- `config/gantry/*.json` — kinematics (speeds/accel)
- `config/pipettes/*.json` — syringe kinematics, servo angles, volume capacity
- `config/liquids/*.json` — per-liquid overrides (viscosity, speeds/waits, prewet and air-gap technique, optional custom calibration curve) merged on top of the pipette's base syringe kinematics — see "Pipetting technique" below
- `config/locations/*.json` (parsed by `LocationManager`, `core/location_manager.py`) — named coordinates and plate placements, including special `tipbox`/`waste_container` plate types, plus per-plate `order`/`mask`/`on_exhaust`/`tips`
- `config/plates/*.json` — reusable plate templates (dimensions, well layout, dipping strategy), instantiated via `PlateFactory` in `core/plates.py` (registry-based: `Plate` → `PlateArray`/`PlateSingleton` → `TipBox`/`WasteContainer`)

Filenames not paths are passed around at the shell/CLI layer — `DefaultPaths`/`DefaultFilenames` (`core/pipette_constants.py`) resolve them against `DefaultPaths.DIR_REPO_ROOT` — four levels up from `pipette_constants.py`, which is only correct for a src-layout checkout, so installed packages (Nix, pip, wheel) must set `AUTOPIPETTE_REPO_ROOT` to an absolute path (a relative one raises at import; both systemd units set it, see `systemd/README.md`). `ConfigKey` centralizes JSON key name constants; use those instead of hardcoding strings when touching config parsing.

The kiosk (`autopipette_kiosk/main.py`) takes its `REPO_ROOT` from `DefaultPaths.DIR_REPO_ROOT` rather than recomputing it from `__file__` — it used to do the latter, and the copy silently diverged (it missed the `AUTOPIPETTE_REPO_ROOT` override); don't reintroduce a second resolution path. `PROTOCOLS_DIR` (default `REPO_ROOT / "protocols"`, overridable via `AUTOPIPETTE_PROTOCOLS_DIR`) is resolved once at module import time, so changing the env var requires a process restart to take effect.

### Pipetting technique (air gaps, prewet, capacity)
Technique parameters resolve **explicit CLI flag > active liquid profile > pipette default > 0**, in `AutoPipette.resolve_technique`. The per-command flags (`--pre_air_gap`, `--post_air_gap`, `--prewet`, `--prewet_vol`) and their `*Args` fields are `| None`-typed and default to `None`, so "flag omitted" is distinguishable from an explicit `0` — with plain zero-defaulted floats, `--pre_air_gap 0` could not override a non-zero profile value. For the same reason `get_merged_syringe_params` tests these with `is not None` rather than the `or` used for the older speed/wait keys.

**Naming:** the concept is an *air gap* everywhere — `pre_air_gap`/`post_air_gap`, never `aspirate_air`. It names the thing (a gap of air that persists in the tip through the dispense) rather than the action that created it, and it's the term protocol authors already know. An earlier `pre_aspirate_air`/`post_aspirate_air` spelling from the merged `aspirate-air` branch was renamed out; don't reintroduce it. Microlitre quantities carry a `_ul` suffix on model/dataclass/parameter names but **not** on user-facing flags, which is why `--pre_air_gap`, `--post_air_gap` and `--prewet_vol` set explicit `dest=`s (`pre_air_gap_ul`, …) — the same pattern as the pre-existing `--dispense_vol` → `disp_vol_ul`.

`LiquidProfile` carries `pre_air_gap_ul`/`post_air_gap_ul`/`prewet_cycles`/`prewet_vol_ul` (all `| None` = "defer to the pipette"), and `PipetteSyringeKinematics` carries the non-optional fallbacks. `_update_syringe_params` must copy every one of these onto `self.syringe` — it silently dropping fields is what previously made `air_gap_ul` and `prewet_recommended` inert config that `ls` displayed but nothing applied.

`AutoPipette.fit_air_volumes` reconciles `pre + volume + post` against `usable_capacity_ul()` (`max_volume_ul - capacity_margin_ul`, the latter a config field replacing an earlier hard-coded `+2` µL fudge). It fits the **post**-gap first — that is the anti-drip cushion at the tip orifice — and shrinks the pre-gap for whatever is left, logging a WARNING naming requested vs applied. It raises `VolumeCapacityError` only when the *liquid alone* doesn't fit, since shrinking air can't rescue that and quietly aspirating less would deliver the wrong amount. `pipette()`'s chunking subtracts the air overhead from the per-chunk budget, or every full chunk would overflow by exactly that much.

Because the post-aspirate cushion sits between the liquid and the orifice, a metered dispense has to drive it out ahead of the liquid — `dispense_volume(purge_air_gap_ul=...)`. The dispense-everything path (`clear_syringe()`) doesn't need this.

There is deliberately **no** blowout support and **no** touch-off: both existed as config/flags (`speed_blowout`, `blowout_recommended`, `--touch` wired to a `pass  # TODO`) that nothing implemented, and were removed rather than left looking live. Neither legacy branch has a real implementation to port.

#### Multi-dispense (`--splits`)
`pipette --splits 'plate_a:12@A1;plate_b:8@C3'` does one aspirate then N metered dispenses (`AutoPipette.pipette_splits`), saving a tip pickup and a source trip per destination. Ported from `origin/sticky-test-scott`'s `pipette_splits`, but addressing wells by ID through `traversal.well_id_to_rc` rather than that branch's `@ROW,COL` integers; `@WELL` is optional and omitting it defers to the plate's own `TraversalOrder`. Parsing is in `core/splits.py` (syntax only); `AutoPipette.resolve_splits` validates against the deck and runs **before any G-code is emitted**, matching `LocationManager.load_from_json`'s parse-then-apply rule — a bad spec must not strand a half-dispensed tip mid-plate.

Unlike `pipette`, this never chunks: the whole volume must fit in the syringe at once, since a single aspirate is the point.

Leftover liquid requires an explicit `--leftover keep|waste`; omitting it is an error rather than the silent `keep` the original defaulted to. `waste` verifies the waste container up front. A tip still holding liquid (`keep`) is always retained regardless of `keep_tip` — never send a tip with liquid in it to the bin.

**`trigger` is a stub — don't mistake it for a working command.** `AutoPipetteService.trigger` (`daemon/service.py`) validates its channel and state against `TriggerChannels` (`core/pipette_constants.py`) and then returns an `ok=False` "not yet implemented" result; `AutoPipette` has no trigger method at all. Both the control-plane RPC and the `trigger` shell command route to that stub, so auxiliary hardware (air, shake, lid) cannot be driven from a protocol. The planned implementation — including the working `set_trigger` on `origin/sticky-test-scott` to port from — is `docs/TODO.md` item 2.

### Domain model (`core/`)
- `autopipette.py` — `AutoPipette`: central controller tying config, location manager, G-code buffer, and volume converter together; owns `pipette()`/`aspirate()`/`dispense()`/tip-handling and multi-liquid switching (`switch_liquid`).
- `pipette_models.py` — pydantic-style dataclasses for `SystemConfig`, `GantryKinematics`, `PipetteModel`, `PipetteSyringeKinematics`, `PipetteState`, `TipState`, `FluidDisplacement`.
- `volume_converter.py` — volume↔motor-step conversion, including calibration-curve-based conversion.
- `coordinate.py` — `Coordinate`, used throughout for absolute/relative XYZ positions.
- `well.py` — `Well`, `StrategyType` (dipping/aspirate strategies per well).
- `plates.py` — plate class hierarchy + `PlateFactory` registry (`@PlateFactory.register(...)`-style pattern, generic in the decorated subclass so `TipBox`-specific methods stay visible to type checkers — check the file before adding a new plate type). Wells are always stored row-major in `Plate.wells`; the *visiting* order is a separate `Plate.sequence` of flat indices, and `Plate.curr` is a cursor into that sequence, not into `wells`. With the defaults (`row_major`, no mask) the sequence is the identity, which is what keeps existing behavior unchanged.
- `traversal.py` — well addressing (`A1`/`H12`/`A1:D6` ↔ flat indices), `TraversalOrder` (four orthogonal fields: `major`/`row_dir`/`col_dir`/`serpentine`, covering every raster and serpentine walk as *data* rather than code), `TraversalRegistry` of readable preset names for config files, and `WellMask` for restricting a plate to a sub-region. Ordering decides sequence, masking decides membership — masking never reorders the survivors.
- `splits.py` — `Split`, `LeftoverAction`, and `parse_splits_spec` for the `pipette --splits` mini-language. Syntax only; deck validation lives in `AutoPipette.resolve_splits` (see "Multi-dispense" above). Kept out of `commands/tap_cmd_parsers.py` because the domain layer is what validates against the deck, and `commands/` imports from `core/`, not the reverse.
- `tipbox_manager.py` — `TipBoxManager`: owns several independent `TipBox`es and decides which supplies the next tip, drawing in registration order (which `LocationManager` takes from config-file order). Boxes are never merged: an earlier `TipBox.append_box` spliced their well lists together, which destroyed per-box provenance and made unloading, per-box counts, and persistence impossible. Each box tracks per-position tip presence and raises `OutOfTipsError` rather than reissuing a used tip; `snapshot`/`restore` move that state through Moonraker's DB, and `restore` refuses a record whose plate dimensions no longer match rather than misaligning consumed positions onto different physical wells.
- `pipette_exceptions.py` — domain exceptions (`NoTipboxError`, `OutOfTipsError`, `TipAlreadyOnError`, `NotALocationError`, etc.), plus two daemon/service-lifecycle signals kept here to avoid an import cycle with `commands/*.py` (see that module's docstrings for why): `NotHomedError` (the homed-interlock's exception) and `ProtocolAbortedError` (raised when a `break` line's breakpoint is answered "abort"). Prefer raising/catching these over generic exceptions in this layer.
- `gcode_buffer.py` — low-level G-code line accumulation used by `GCodeManager`'s batch mode.

### Moonraker/WebSocket layer (`moonraker/`)
- `websocket_client.py` — `WebSocketClient` runs an asyncio event loop on a background thread; public API is synchronous (`send_jsonrpc`, `wait_for_connection`, context-manager support) with a `Queue`-based `MessageType` (`fatal_error`/`error`/`handler_error`/`notification`/`parse_error`) for async notifications/errors surfaced back to the shell.
- `moonraker_requests.py` — `MoonrakerRequests`: pure builders for Moonraker JSON-RPC payloads (printer control, file upload/print-start, etc.) — no I/O itself.

## Code style
- Target Python 3.12+, `from __future__ import annotations` at the top of modules.
- Ruff (`preview = true`) enforces pycodestyle/pyflakes/isort/pyupgrade/bugbear/simplify/comprehensions/return/annotations/**Google-style docstrings** (`D` rules, convention `google`, `D203`/`D213` ignored). Match the existing heavy-docstring style (Args/Returns/Raises/Example) in `core/` and `commands/` when adding public functions/classes there.
- Pyright runs in `strict` mode with `extraPaths = ["src"]` — keep new code fully typed.
- First-party import groups for isort: `tricca_autopipette`, `autopipette_kiosk`.

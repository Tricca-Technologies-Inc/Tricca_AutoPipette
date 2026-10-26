# WP4 — tapd: Daemon, `tap` and Protocol-File Commands (`Tricca_AutoPipette`)

| Field    | Value |
|----------|-------|
| Status   | Draft for review (approval in the umbrella header) |
| Revision | K |
| Owner    | James |
| Project  | Tricca AutoPipette |
| Parent   | `00-umbrella-plan.md` |
| Repo     | https://github.com/Tricca-Technologies-Inc/Tricca_AutoPipette (base `a98439b`) |
| Date     | 2026-10-22 |

---

## 1. Purpose & Scope

Make tapd aware of the six plate axes and the plunger axis P:
- Read their configuration from Klipper.
- Track their homed state.
- Home and move them.
- Surface interlock refusals.
- In stage 2, drive the plunger with absolute `G1 P` moves.

**Scope (D30): daemon (`AutoPipetteService`, control-plane RPCs), `tap` (`RemoteTapShell`) and protocol-file commands only.** The kiosk is deferred to TAP-10.

These issues describe **what** and **why**, the contract to meet and the acceptance criteria. The **how** follows the repo's own `CLAUDE.md`. This work package doesn't prescribe class names, file layout or test structure beyond what those rules already require.

## 2. Binding Repo Rules

Read `CLAUDE.md`, `CONTEXT.md`, `docs/adr/`, `docs/agents/*` first.

- **TDD is mandatory** (`docs/agents/tdd.md`). Name and confirm seams before any test file exists; red before green.
- **Capabilities land as an `AutoPipetteService` method + `ControlRequests` builder + `control_server.py` dispatch + a hand-written `RemoteTapShell.do_*`.**
  - The completeness tests (`tests/cli/test_remote_shell_dispatch_completeness.py`, `tests/daemon/test_control_server_dispatch_completeness.py`) must pass.
  - Protocol-file commands go through the shared `_LINE_DISPATCH` / `_STR_ARG_DISPATCH` tables, never a second table.
- **Client parity.** Kiosk support is deferred by an owner decision (D30). TAP-11 records the exception in an ADR, and TAP-10 tracks closing it. Don't add kiosk-only or `tap`-only *logic*; everything goes through RPCs.
- **G-code only via `GCodeCommands` builders** (`core/gcode_commands.py`), typed `GCode`. The golden emission test (`tests/core/test_autopipette_gcode_emission.py`) pins every emission site, so update it deliberately.
- **Issues:** `gh`, label `needs-triage` (+ `safety` as marked); the owner promotes to `ready-for-agent` (D32). Add each issue to the backlog map #34 with its dependencies. Encode hard dependencies as native GitHub issue dependencies (`docs/agents/issue-tracker.md`).
- **Style:** ruff (Google docstrings, `DOC` rules), pyright strict, Python 3.12+.

## 3. Facts About the Current Code (verified at `a98439b`)

| Area | Today |
|---|---|
| `GCodeCommands.home(*axes: Literal["X","Y","Z"])` | Gantry letters only |
| `GCodeCommands.linear_move(x, y, z, feedrate)` | X/Y/Z/F only |
| `GCodeCommands.manual_stepper(...)`, `manual_stepper_gcode_axis(...)` | Exist; the latter is unused |
| `MoonrakerStateTracker` | Subscribes to `toolhead` + `print_stats`; `is_homed()` = `homed_axes ⊇ {x,y,z}` |
| `require_homed` | Gates `move`, `move_loc`, `move_rel`, `transfer`, `aspirate`, `dispense`, tip commands |
| `home` RPC / `HomeArgs.motors` | `x`, `y`, `z`, `pipette`, `axis`, `all`, `servo`; `all` → `init_pipette()` (abs mode, speeds, `G28`, then plunger and servo homing) |
| Plunger homing / moves | `MANUAL_STEPPER … SET_POSITION=0 MOVE=<±2·max_travel> STOP_ON_ENDSTOP=home`, then `inverted_home`, then `SET_POSITION=0`. Moves re-zero before/after and use `try_home` |
| Syringe parameters | `config/pipettes/*.json` (`max_travel_mm`, speeds, `accel_home`, `accel_move`, `motor_orientation`); bounds in `HIGH_RISK_BOUNDS` |
| Protocol runs | Lines dispatched → G-code buffered → uploaded as one file → printed; completion from `print_stats` |

## 4. Contract With Klipper (umbrella §6.3)

tapd consumes exactly the commands, error texts and Moonraker objects listed in umbrella §6.3. If something tapd needs isn't there, change the umbrella contract and WP2 first; don't work around it in Python.

tapd must **never** send Klipper's renamed original commands (`G1.1`, `G0.1`, any `*_BASE`, `M84.1`, `M18.1`), `_PLATE_INTERNAL`, or `SET_GCODE_VARIABLE` on the interlock's macros (`_PLATE_CFG`, `_PLATE_STATE`, `_PIPETTE_CFG`, `_PIPETTE_STATE`, `_GSTATE`). They bypass the interlock (WP2 §4). tapd's existing `STEPPER_BUZZ` (wiring check) is now guarded: on a plate it needs Z homed and the tip raised.

**Rollback for every TAP issue** (unless the issue says otherwise): revert the PR. tapd reaches machines only through a `tricca-src` pin bump (CB1-5 stage 1, CB1-7 stage 2), so a deployed change is rolled back by `switch`ing to the previous generation.

## 5. Issues

---

### TAP-1 — G-code builders for extra axes (plates U V W A B C, plunger P)

- **Labels:** `needs-triage`
- **Blocked by:** —
- **Blocks:** TAP-4, TAP-5, TAP-6, TAP-7

**Context.** Klipper now has extra G-code axes (umbrella §6.3). `GCodeCommands` can only emit X/Y/Z moves and homing.

**Goal.**
- Builders can emit moves and homing commands that include any configured extra axis letter.
- They can also emit the plate macros (`PLATE_MOVE`, `PLATE_IN`, `PLATE_OUT`, `PLATES_IN`, `HOME_PLATE`, `HOME_PLATES`, `HOME_PIPETTE`) and `SET_VELOCITY_LIMIT` with `ACCEL`.

**Constraints.**
- Builders validate only what Python alone knows: one line, a well-formed letter.
- Axis letters are not hard-coded. They come from TAP-2's discovered configuration, or are passed in by the caller.
- Reserved letters (X Y Z E F N) can't be used as extra axes.

**Acceptance criteria.**
- **S-TAP1-1:** doctest-style examples for each new builder.
- **S-TAP1-2:** golden-file entries for every new emission.
- **S-TAP1-3:** a reserved or multi-character letter is rejected.
- **S-TAP1-4:** the golden emission file contains none of the never-send commands in §4.

---

### TAP-2 — Discover plate and plunger axis configuration from Klipper at connect

- **Labels:** `needs-triage`
- **Blocked by:** CFG-1 merged (contract fixed)
- **Blocks:** TAP-3, TAP-4, TAP-8

**Context.** R16: Klipper's config is the single source of truth for plate letters, travel and interlock parameters, and for P's letter and limits. Duplicating them in tapd's JSON config would drift.

**Goal.**
- On connect (and after a Klipper restart), query Moonraker for the objects in umbrella §6.3 (`gcode_macro _PLATE_CFG`, `_PIPETTE_CFG`, and `configfile` settings for `manual_stepper plate*` / `pipette_stepper`).
- Build a typed, read-only description: plate names, letters, `position_min`/`position_max`, `z_safe`, `park_tol`, P letter, P limits.
- Expose it through `system_summary` (and `tap`'s existing reporting).

**Constraints.** Missing objects (a machine not yet upgraded) mean "no plates, no P axis". Every plate/P command then refuses with a clear message; existing behavior is unchanged.

**Acceptance criteria.**
- **S-TAP2-1:** a fake Moonraker status produces the expected description.
- **S-TAP2-2:** absence produces the "not configured" state, and existing commands keep working.
- **S-TAP2-3:** a Klipper restart refreshes the description.

---

### TAP-3 — Track plate and plunger homed state; gate commands on it

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** TAP-2
- **Blocks:** TAP-4, TAP-6, TAP-8

**Context.**
- tapd's interlock is driven by live Moonraker state (`homed_axes`), which covers X/Y/Z only.
- Klipper now tracks plate and plunger homing in macro variables plus `stepper_enable` (umbrella §3, "Homed").

**Goal.**
- Extend the live-state tracking (subscription) to `gcode_macro _PLATE_STATE`, `gcode_macro _PIPETTE_STATE` and `stepper_enable`.
- Answer: is plate N homed, is the plunger homed, is the gantry homed.
- Provide gates in the same style as `require_homed`:
  - Plate commands need gantry Z homed plus that plate homed.
  - Stage-2 plunger moves need the plunger homed.

**Constraints.**
- Live state only, never a locally set flag (same reasoning as the existing interlock).
- The existing X/Y/Z gate is unchanged.
- tapd's checks are an early, friendly refusal. **Klipper's interlock remains the authority.**

**Acceptance criteria.**
- **S-TAP3-1:** homed flags follow a scripted sequence of fake status pushes (home → M84 → re-enable → re-home).
- **S-TAP3-2:** a gated command raises the not-homed error naming the plate or plunger.
- **S-TAP3-3:** no change to existing gated commands' behavior with plates unconfigured.

---

### TAP-4 — Plate commands: home, move in/out/to, status (daemon, `tap`, protocol files)

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** TAP-1, TAP-2, TAP-3
- **Blocks:** TAP-8, TAP-10

**Context.** Operators and protocols need to move plates in and out of the machine. Klipper provides macros for this behind the interlock (umbrella §6.3).

**Goal.** New capabilities, each as service method + RPC + `ControlRequests` builder + `tap` command + protocol-file command:
- Home one plate / all plates.
- Move a plate in, out, or to a position (optional speed).
- Retract all plates.
- Report plate status (homed, position, parked).

Plates are addressed by **name** (`plate1`…`plate6`, as discovered in TAP-2). Accept the axis letter as an alias only if it's unambiguous.

**Constraints.**
- Emit only the macros from umbrella §6.3. Never `MANUAL_STEPPER` on a plate (Klipper refuses it).
- Positions are validated against TAP-2's limits before emitting.
- Gated per TAP-3.
- Plate motion is protocol-file-safe: a refused line aborts the batch like any other raised error. It is not run-locked.

**Acceptance criteria.**
- **S-TAP4-1:** each command emits the exact contract G-code (golden file).
- **S-TAP4-2:** out-of-range positions and unknown plates are refused before any G-code.
- **S-TAP4-3:** both completeness tests pass.
- **S-TAP4-4:** a protocol file using every plate command dispatches through the shared tables.
- **S-TAP4-5:** M-02 / M-09 behaviors reproduced through `tap` on hardware.

---

### TAP-5 — Homing integration: `G28` forms for plates and plunger

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** TAP-1, TAP-3; CFG-1 deployed (umbrella Phase 8) for on-machine checks
- **Blocks:** TAP-6

**Context.**
- Bare `G28` now homes gantry, plates and plunger (D16, D27).
- `G28 P` homes the plunger at the same zero as tapd's current sequence.
- `G28 U…C` home single plates.

**Goal.**
- `home all` / `init` rely on bare `G28` for gantry, plates and plunger, and stop emitting the separate `MANUAL_STEPPER` plunger homing. Keep coordinate-system/speed setup and servo homing.
- `home pipette` emits `G28 P`.
- New `home` targets for plates (all plates; a named plate) emit `G28 <letter>`.
- `_homing_invalidated` semantics are unchanged: only a full home clears it.

**Constraints.** Works with stage-1 config. tapd's stage-1 syringe operations still re-zero, so the plunger frame they assume is unaffected.

**Acceptance criteria.**
- **S-TAP5-1:** golden-file changes for `init`/`home` reviewed.
- **S-TAP5-2:** `home` rejects unknown targets with the valid list, including plate names.
- **S-TAP5-3:** on hardware, M-04 and M-14 pass when triggered from `tap`.

---

### TAP-6 — Stage 2: absolute plunger coordinates with `G1 P`

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** TAP-5
- **Blocks:** CFG-3, CB1-7
- **Note:** develop and test against CFG-3's PR branch (stage-2 fixture from `make_fixture.py --stage 2`); CFG-3 merges after this issue.

**Context.** D26: after `G28 P`, P is absolute (mm from the switch-release point; aspiration is negative per `home_dir = +1`, umbrella §8). Stage-2 Klipper refuses plain `MANUAL_STEPPER` moves on the bound plunger and enforces `-60…0`.

**Goal.**
- Every syringe operation (aspirate, dispense, clear, prewet, air gaps, calibration dispense) emits **absolute `G1 P` moves** instead of `SET_POSITION` + relative `MANUAL_STEPPER` moves.
- Volume → travel conversion is unchanged (`VolumeConverter`). The target is current position ± travel.

**Key design points for the implementer.**
- **Plunger position model.**
  - Protocols compile to G-code before running, so tapd tracks the plunger's absolute position while compiling.
  - The model is seeded from Klipper's reported P position (or 0 after a `G28 P` in the same batch) at protocol start.
  - Refuse to compile if the plunger isn't homed.
  - `domain_state_snapshot` must snapshot and restore the model (issue #35 pattern).
- **Per-liquid acceleration.**
  - `MANUAL_STEPPER ACCEL=` is gone.
  - Bracket plunger moves with `SET_VELOCITY_LIMIT ACCEL=<liquid accel>` and restore the previous gantry value afterwards.
  - Speeds become `F` (mm/min).
- **Endstop safety stop.** `try_home` on ordinary moves is replaced by the stage-2 soft limits (`-60…0`); clamp in Python before emitting.
- **Calibration.** `last_syringe_travel_mm` keeps meaning *commanded travel*, so curves stay valid (M-14 guarantees the same zero).

**Acceptance criteria.**
- **S-TAP6-1:** golden file shows no `SET_POSITION` / `MANUAL_STEPPER` for the plunger.
- **S-TAP6-2:** a compiled multi-step transfer reaches the expected absolute positions, and rollback restores the model.
- **S-TAP6-3:** commands are refused before emission if a target would leave `-60…0`.
- **S-TAP6-4:** acceleration bracketing restores the gantry value.
- **S-TAP6-5:** on hardware, M-20…M-21 pass, with gravimetric results within the pipette's current tolerance.

**Rollback.** Before deployment: revert the PR. After deployment: only through CB1-7, which switches both pins back together; never revert tapd alone on a stage-2 machine (K-SW-03).

---

### TAP-7 — Coordinated plunger + gantry moves

- **Labels:** `needs-triage`, `needs-info`
- **Blocked by:** TAP-6; the owner choosing a first use case (handled outside the plan; register VR-14)
- **Blocks:** M-22

**Context.**
- With P bound and absolute (stage 2), one `G1` can move the plunger together with X/Y/Z.
- The owner wants this **only where it makes sense**, not as the default.

**Stage.** Stage 2 work (needs TAP-6). It is optional: Phase 10 completes without it, and M-22 runs only if it is implemented.

**Goal.** One opt-in capability exposing a combined move, e.g. aspirate or dispense while Z moves. Its exact shape follows the first use case, agreed with the owner before implementation. It is a service method + RPC + `tap` + protocol command like the others.

**Constraints.**
- The whole move is capped by P's `LIMIT_VELOCITY` / `LIMIT_ACCEL`, so gantry axes run slower during it (umbrella §6.3).
- Coordinated moves must use the TAP-6 position model.

**Acceptance criteria.** Defined with the owner when `needs-info` clears. They must include M-22.

---

### TAP-8 — Protocol validation knows about plates and the interlock

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** TAP-4
- **Blocks:** —

**Context.**
- A protocol is uploaded and printed as one file.
- If Klipper's interlock refuses a line mid-print, the run aborts part-way.
- `validate_protocol` already dry-runs protocols catch-and-continue (issue #36).

**Goal.**
- During validation, model plate homed/position state and Z relative to `z_safe` (from TAP-2).
- Report as findings any line Klipper would refuse under I1/I2/I4/I6 or the soft limits.

**Constraints.** Advisory only, like other findings. No change to how real runs are started.

**Acceptance criteria.**
- **S-TAP8-1:** protocol fixtures that violate each rule produce one finding per violation, with the line number.
- **S-TAP8-2:** a compliant fixture produces none.

---

### TAP-9 — Surface interlock refusals clearly

- **Labels:** `needs-triage`, `safety`
- **Blocked by:** TAP-3
- **Blocks:** —

**Context.**
- Klipper reports refusals as G-code errors (`Move refused by interlock: …`, `… refused: …`, umbrella §6.3). During a print these end the job, and tapd currently reports only a generic failure.
- `resume_run` → Moonraker resume → Klipper `RESUME` is now checked too: if a drawer was moved while paused and would be hit, `RESUME` is refused and the run **stays paused**.

**Goal.**
- Recognize the contract error texts in Moonraker's responses and print-status messages.
- Report them as a specific run failure: which rule, which axis, and the reason text.
- Surface it in `run.status`, `notify_run_status` and `tap`.

**Acceptance criteria.**
- **S-TAP9-1:** fake Moonraker error payloads for each refusal map to the specific reason.
- **S-TAP9-2:** unrelated errors keep today's handling.
- **S-TAP9-3:** a refused `RESUME` leaves the run reported as paused, with the reason, and a later resume (after the drawer is parked) works.

---

### TAP-10 — Kiosk support for plates and plunger (deferred; closes the parity exception)

- **Labels:** `needs-triage`
- **Blocked by:** TAP-4, TAP-5 (and TAP-6/TAP-7 for plunger features)
- **Blocks:** removal of the D30 exception

**Goal.** Kiosk routes and UI for plate status, plate in/out, homing targets, and interlock messages. Built as routing-only wrappers over the existing RPCs, so no new logic lives in the kiosk.

**Note.** **Not part of this plan's implementation.** File it so the exception is tracked.

**Rollback.** n/a (deferred).

---

### TAP-11 — Docs: ADR for Klipper-owned extra axes + parity exception; CONTEXT and CLAUDE updates

- **Labels:** `needs-triage`
- **Blocked by:** —
- **Blocks:** umbrella Phase 9 sign-off

**Goal.**
- **New ADR** recording:
  1. Plate and plunger axes are owned by the Klipper config, and tapd discovers them (R16).
  2. tapd's checks are early refusals; Klipper's interlock is the authority.
  3. The time-boxed client-parity exception (D30), closed by TAP-10.
- **`CONTEXT.md`:** add glossary terms (plate/drawer, parked, `z_safe`, P axis, stage 1/2).
- **`CLAUDE.md`:**
  - Architecture sections: homed-safety interlock, `GCodeCommands`, Moonraker state.
  - Stage-2 plunger model once TAP-6 lands.

**Acceptance criteria.** Merged before umbrella Phase 9 sign-off; updated again with TAP-6.

**Rollback.** Revert the PR (docs only).

## 6. Issue Order

```
TAP-11 (any time)
TAP-1 ─┐
TAP-2 ─┼─► TAP-3 ─┬─► TAP-4 ─┬─► TAP-8
       │          │          └─► TAP-10 (deferred)
       │          ├─► TAP-5 ─► TAP-6 ─► CFG-3 ─► CB1-7   (stage 2)
       │          │                 └─► TAP-7 (optional, stage 2, needs-info)
       │          └─► TAP-9
```

## 7. Revision History

| Rev | Date | Author | Change |
|-----|------|--------|--------|
| H | 2026-10-20 | James / Claude | New work package: tapd brought into scope (daemon + `tap` + protocol files, D30). Issues TAP-1…TAP-11 written from the code at `a98439b` |
| I | 2026-10-20 | James / Claude | Revision aligned with the package. No content change. The interlock now reports the first failing check (WP2 §4), so error text for TAP-9 is deterministic |
| J | 2026-10-21 | James / Claude | Review fixes: rollback rule for every issue; never send renamed base commands (S-TAP1-4); TAP-6 → CFG-3 one-way dependency; TAP-7 is optional stage-2 work; refused `RESUME` handling (S-TAP9-3) |
| K | 2026-10-22 | James / Claude | Never-send list adds `SET_GCODE_VARIABLE` on interlock macros; note that `STEPPER_BUZZ` is guarded; contract (umbrella §6.3) now lists every command tapd sends today |

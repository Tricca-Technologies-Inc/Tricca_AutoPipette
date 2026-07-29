# TODO

The project backlog: planned work that is **not implemented yet**.

Each entry is written so a planning session can start from it cold — the problem,
the intended behavior, what already exists to build on, and the open questions
that must be settled *before* implementation. Several entries record decisions
already taken; those are marked **decided** and should not be relitigated without
a reason.

**Every item here needs its own planning session.** None are shovel-ready, and
some are load-bearing enough that starting without settling the open questions
would entrench the wrong shape.

`CLAUDE.md` describes the system as it *is* and links here for what it should
become. Keep that split: architecture facts there, backlog here.

> Line references (`file.py:123`) were accurate on 2026-07-29 against branch
> `feat/location-groups-and-tipbox-manager`. Symbol names are more durable than
> line numbers — verify before relying on either.

## Findings worth acting on independently

Three things below are true of the code *now*, not proposals. They surfaced while
researching other items and are worth triaging on their own:

1. **The kiosk was network-exposed with no authentication** (item 18) — the
   shipped unit binds `127.0.0.1` as of 2026-07-29, **but the fix is not
   retroactive**: machines provisioned from an earlier revision keep serving on
   `0.0.0.0` until the unit is re-copied and reloaded. Audit deployed hosts.
   `tapd`'s control plane still has no authentication either, protected only by
   its own loopback default.
2. **The "steps" vocabulary already means millimetres** (item 15) — confirmed
   2026-07-29 against Klipper's docs: `MANUAL_STEPPER`'s `MOVE`/`SET_POSITION`
   are mm, `SPEED` is mm/s, `ACCEL` is mm/s². `VolumeConverter.vol_to_steps`
   returns mm despite its name and docstring. **A naming bug, not a correctness
   bug** — the emitted G-code is fine. The rename touches public RPC and `tap`
   surface. A related unverified point: the code passes `STOP_ON_ENDSTOP`
   numeric values that current Klipper documents only as strings.
3. **The only config writer is non-atomic and lossy** (item 19).
   `LocationManager.save_to_json` is a bare `open("w")` + `json.dump` that
   reconstructs plates from `wells[0]` via `hasattr` probing, and `extends`
   chains are flattened at load — so save-after-load can truncate the deck
   definition on a crash, drop fields, and collapse config inheritance.

## Dependency order

Most items are independent. These interlock:

```
4  (green tree) ──> 5 (CI + branch protection) ──> 8 (versioning/release)
                                                        ^
                                          10 (dep pinning) ─┘

15 (travel-not-volume) ──> 16 (G-code library) ──> 15's rename executes through it
   └─ mm/steps question RESOLVED: units are mm; it's a naming bug, not a
      correctness bug, so 15 is a refactor and is not urgent

19 (config write-back) ──> 13 (pipette max volume; subsumed by 19)
                       └─> 12 (a fitted calibration curve is a config write)

11 (kiosk nav shell) ──> 3, 12, 13 land as pages within it
14 (CLI/kiosk parity) ──> constrains 3, 11, 12, 13, 17
18 (kiosk exposure)   ──> 17 (fleet tool) — same auth question, answer once
```

## Index

| # | Item | Risk / note |
|---|---|---|
| 1 | [Tip disposal falls back to the tip's origin](#1-tip-disposal-falls-back-to-the-tips-origin) | ⚠️ current behavior is unsafe |
| 2 | [Make `trigger` do something](#2-make-trigger-do-something) | stub; port exists |
| 3 | [Kiosk tip-inventory UI](#3-kiosk-tip-inventory-ui) | UI only; RPCs exist |
| 4 | [Green the tree](#4-green-the-tree-prerequisite-for-ci-gating) | blocks 5 |
| 5 | [CI workflow + branch protection](#5-ci-workflow--branch-protection-on-main) | needs 4 |
| 6 | [Issue tracking](#6-issue-tracking) | |
| 7 | [Auto-building documentation](#7-auto-building-documentation) | docs are broken, not just unbuilt |
| 8 | [Versioning and release process](#8-versioning-and-release-process) | needs 4, 5 |
| 9 | [Strip cookiecutter boilerplate](#9-strip-cookiecutter-boilerplate-from-pyprojecttoml) | small |
| 10 | [Dependency pinning](#10-dependency-pinning--reproducible-environments) | ⚠️ already broke a safety interlock once |
| 11 | [Kiosk multi-page navigation](#11-kiosk-multi-page-navigation--frontend-restructure) | shell for 3, 12, 13 |
| 12 | [Calibration procedure + wizard](#12-calibration-procedure--kiosk-wizard) | no backend yet |
| 13 | [Writable pipette configuration](#13-writable-pipette-configuration-max-volume--safety-sensitive) | ⚠️ safety-sensitive; subsumed by 19 |
| 14 | [Kiosk/CLI capability parity](#14-capability-parity-between-the-kiosk-and-the-cli) | standing rule |
| 15 | [Syringe limit as travel, not volume](#15-model-the-syringe-limit-as-travel-distance-not-volume) | units confirmed mm; naming bug |
| 16 | [Typed G-code command library](#16-a-typed-g-code-command-library) | |
| 17 | [Fleet browser tool](#17-fleet-browser-tool-mainsail-like-network-connected) | large; needs 18 |
| 18 | [Kiosk is network-exposed](#18-the-kiosk-is-network-exposed-with-no-authentication) | default fixed; ⚠️ audit deployed hosts |
| 19 | [Editable/saveable configuration](#19-editable-and-saveable-configuration-from-every-client) | supersedes 13 |

---

## 1. Tip disposal falls back to the tip's origin

**Status:** needs planning session
**Touches:** `core/autopipette.py`, `core/tipbox_manager.py`, `core/pipette_models.py`, `commands/tap_cmd_parsers.py`

**Problem.** `AutoPipette.pipette()` ends with a bare
`if not keep_tip: self.dispose_tip()`, and `dispose_tip` raises
`NoWasteContainerError` when none is configured — so a deck without a waste
container aborts mid-transfer with a tip still attached. The only alternative,
`eject_tip`, drops the tip wherever the head currently is, which after a transfer
is over the destination well. The fallback isn't merely missing, it's unsafe.

**Intended behavior.**
1. Verify a waste container exists up front for any run that will discard tips,
   rather than discovering it mid-protocol.
2. With none configured, return the used tip to the exact tipbox position it came
   from.
3. Replace the `keep_tip` boolean with an explicit disposition flag on every
   function deciding where a tip goes after a transfer — `keep_tip: bool` can't
   express the three real outcomes (keep on / send to waste / put back).
   Something like `tip_disposition: "keep" | "waste" | "return"`, threaded
   through `PipetteArgs`, `AutoPipette.pipette`, and `change_tip`.

**Already in place.** `TipBoxManager.next_tip` returns
`(box_name, box, coordinate)` and `TipBox.take_tip` returns
`(flat_index, coordinate)`, so the tip's origin is knowable and
`TipBox.present[index]` can be flipped back. This was impossible under the old
`append_box` design, which erased per-box provenance. Record the origin on
`PipetteState` at pickup, clear it on eject/dispose.

**Open questions.**
- `keep_tip` is public surface (`PipetteArgs`, the `pipette` parser, the
  `pipette.transfer` RPC, committed `.pipette` files) — it likely needs to stay
  as a deprecated alias for `--tip_disposition keep`.
- A *returned* tip is a used tip. Marking its slot plainly `present` again would
  let a later `next_tip` hand out a contaminated tip; this may need a distinct
  returned/dirty state rather than a bool.

**Constraint.** Do not add a "just eject it here" fallback — dropping a used tip
over a sample plate is the exact failure mode this removes.

## 2. Make `trigger` do something

**Status:** needs planning session
**Touches:** `daemon/service.py`, `core/pipette_constants.py`, `core/autopipette.py`, `core/pipette_models.py` (`SystemConfig`)

**Problem.** `AutoPipetteService.trigger` validates its channel and state against
`TriggerChannels` in `core/pipette_constants.py`, then returns an `ok=False`
"not yet implemented" result. `AutoPipette` has no trigger method at all. The
control-plane RPC and the `trigger` shell command both route to that stub, so
auxiliary hardware (air, shake, lid) cannot be driven from a protocol.

**Already in place.** A working implementation exists on
`origin/sticky-test-scott` (`Tricca_AutoPipette/autopipette.py`, `set_trigger`):
it emits a `SET_PIN`-style command followed by `M400`, and maps channel names to
Klipper object names from config rather than hardcoding them. Murphy's
`conf/murphy-100.conf` has:

```ini
[TRIGGERS]
shake = arduino_trigger
lid   = arduino_trigger2
air   = arduino_trigger3
```

**Open questions.**
- The channel→object map belongs in the JSON config (probably on `SystemConfig`,
  since it's machine wiring rather than pipette or liquid), which makes
  `TriggerChannels.VALID_CHANNELS` redundant — validate against the configured
  map instead, so a machine without a lid servo rejects `trigger lid` rather than
  silently accepting it.
- A triggered device is state the daemon doesn't track. Decide whether
  `trigger air on` left set at the end of a protocol is an error, a warning, or
  fine, before protocols start depending on either answer.

## 3. Kiosk tip-inventory UI

**Status:** needs planning session
**Touches:** `src/autopipette_kiosk/` (`index.html`, possibly `main.py` for nothing more than routing)

**Problem.** Klipper has no notion of which tip positions are occupied, so the
daemon's record is the only source of truth — and it drifts whenever someone
swaps a box. The tip commands (`tips`, `reset_tips`, `reset_tips_all`,
`set_tips`) exist solely in `tap` and the standalone shell, so an operator
working only from the touchscreen cannot see or correct that drift. A run then
fails with `OutOfTipsError`, or worse, reaches for a tip that isn't there. The
kiosk is the primary interface for non-interactive runs, which is exactly when
nobody is at a terminal.

**Intended behavior (minimum useful version).** Render the per-box grid, a "box
reloaded" button per box calling `config.reset_tips`, and tap-to-toggle positions
writing back via `config.set_tips`.

**Already in place.** `config.tips`, `config.reset_tips`, `config.reset_tips_all`
and `config.set_tips` are real control-plane RPCs, and the kiosk already holds a
persistent `WebSocketClient` to `tapd` for the app's lifetime. The
`config.tips` `data["boxes"]` records carry `present`, `eligible`,
`num_row`/`num_col`, `remaining`, `capacity`, `next_well`. Only the UI is missing.

**Constraint.** Build it as a kiosk view over the existing RPCs — do not add tip
logic to `autopipette_kiosk/main.py`. `TipBoxManager.describe` is deliberately
data-only for this reason, and `cli/report_tables.py`'s `build_tipbox_map` is the
terminal renderer of that same data, so the web UI is a second renderer of one
payload, not a second implementation.

---

## 4. Green the tree (prerequisite for CI gating)

**Status:** needs planning session — blocks item 5
**Touches:** `daemon/service.py` (8), `core/plates.py` (5), `cli/remote_shell.py` (5), `core/pipette_models.py` (3), `daemon/moonraker_state.py` (3), `autopipette_kiosk/main.py` (3), `pyproject.toml` (3), `tests/core/test_json_config_manager.py` (3), `core/gcode_manager.py`

**Problem.** CI can't gate on checks that don't pass. As of 2026-07-29:
`pytest` is clean (548 passed, 1.3s), but `ruff check .` reports **38 errors**
and `pyright` reports **1**.

Ruff breakdown:

| Rule | Count | Fixable | Notes |
|---|---|---|---|
| `RUF105` noqa-comments | 20 | yes | mechanical |
| `D421` property-docstring-starts-with-verb | 7 | no | mechanical |
| `RUF069` float-equality-comparison | 6 | **no** | **read these individually** |
| `RUF201` rule-codes-in-selectors | 3 | yes | in `pyproject.toml` itself |
| `D420` incorrect-section-order | 1 | no | mechanical |
| `RUF075` fallible-context-manager | 1 | **no** | **read this one** |

Pyright: `core/gcode_manager.py:75` — `@contextmanager` annotated
`-> Iterator[Foo]`, deprecated in favor of `-> Generator[Foo]`.

**Intended behavior.** Land a cleanup commit that takes the tree to zero on both
tools, so item 5 can gate on them.

**Do not blanket-`--fix`.** `RUF069` flags float `==` comparisons — in
volume/coordinate/step-conversion code that's a genuine correctness class, not
style. Each of the 6 needs reading: some may want a tolerance comparison, some
may be legitimately comparing a sentinel. `RUF075` likewise flags a context
manager that can fail before yielding, which is a resource-leak shape. Treat
these 7 as a review, and the other 31 as mechanical.

**Open questions.**
- Every failing rule is a ruff **preview** rule (`preview = true` in
  `pyproject.toml`). These appeared from a ruff *upgrade*, not from new code —
  so this will recur. Decide: pin an exact ruff version in the `dev` extra and in
  CI (stable, but upgrades become deliberate work), or keep floating and accept
  that CI can go red without a code change. Pinning is strongly implied once
  item 5 makes ruff a merge gate.
- Whether to keep `preview = true` at all, given it opts into unstable rules.

## 5. CI workflow + branch protection on `main`

**Status:** needs planning session — depends on item 4
**Touches:** new `.github/workflows/ci.yml`; repo settings (ruleset)

**Problem.** There is no `.github/` directory at all — no CI, so nothing verifies
a branch before it reaches `main`. There are 16 local branches and more on the
remote, and `delete_branch_on_merge` is `false`, so merged work accumulates.

**Intended behavior.**
- `.github/workflows/ci.yml`: on PR and push to `main`, run `ruff check .`,
  `ruff format --check .`, `pyright`, and `pytest` on Python 3.12. Pin tool
  versions (see item 4).
- A repo **ruleset** on `main`: block direct pushes, require a PR, require those
  checks green. **No required approvals** — decided, since a solo maintainer
  would just be overriding it. Revisit when a second regular contributor appears.
- Enable `delete_branch_on_merge`.

**Already in place.** Repo is **public** and org-owned with admin access, so
rulesets/branch protection are available at no cost. `pyproject.toml` already
fully configures all four tools — CI just invokes them, no config duplication.

**Open questions.**
- Test suite is 1.3s, so no need for caching or matrix splitting initially. A
  Python version matrix (3.12/3.13) is optional — `requires-python = ">=3.12"`
  currently claims 3.13 support that nothing verifies.
- Whether the one-time sweep of the 16 local and remote stale branches belongs
  in this item or its own.

## 6. Issue tracking

**Status:** needs planning session
**Touches:** new `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md`, `CONTRIBUTING.md`

**Problem.** Issues are enabled but **zero have ever been filed** — the backlog
lives in `CLAUDE.md` prose and Claude's memory (which is exactly what this
`docs/TODO.md` is fixing). There's no bug-report path for outside users of a
public GPL project, no PR template, no contribution guide.

**Intended behavior.** Issue templates (bug report / feature request), a PR
template, a label taxonomy, and a `CONTRIBUTING.md` covering the dev setup
(`pip install -e ".[dev]"`), the four checks, and the daemon-first run model
(`tapd` before `tap`/kiosk).

**Open questions.**
- Relationship between `docs/TODO.md` and GitHub Issues. These are the same
  backlog in two places, which is the exact problem this file was created to
  solve. Decide one: file items 1–3 as issues and let `docs/TODO.md` become a
  pointer index; keep `docs/TODO.md` authoritative for design-heavy work and use
  Issues only for externally-reported bugs; or migrate wholesale. **Settle this
  before filing anything**, or the split re-forms.
- A bug report for a hardware system needs machine context (config file, Klipper
  version, `tapd` log) that a stock template won't ask for.

## 7. Auto-building documentation

**Status:** needs planning session
**Touches:** `docs/conf.py`, `docs/api.rst`, `docs/modules.rst`, `docs/index.rst`, `pyproject.toml` (`dev` extra), new `.github/workflows/docs.yml`

**Problem.** The Sphinx tree is **broken, not merely unbuilt**:
- `docs/conf.py` does `sys.path.insert(0, os.path.abspath("../Tricca_AutoPipette/"))`
  — the pre-`src/` layout. Nothing importable is there.
- `docs/api.rst` autosummaries `tricca_autopipette` and a bare `autopipette`
  module that no longer exists; `autopipette_kiosk` is absent.
- `docs/modules.rst` is an empty stub still titled `AutoPipette_MANTA`.
- `docs/index.rst` is unedited sphinx-quickstart boilerplate ("Add your content
  using reStructuredText syntax").
- `sphinx`/`sphinx_rtd_theme` are installed in `.venv` but **not declared** in
  the `dev` extra, so a fresh `pip install -e ".[dev]"` can't build docs.
- `copyright = "2024, James Cook"` is stale.

**Intended behavior.** Repair `conf.py` for the `src/` layout, point autodoc at
`tricca_autopipette` and `autopipette_kiosk`, declare the doc deps, write a real
`index.rst`, and publish to **GitHub Pages** via Actions on push to `main`.

**Already in place.** The codebase is already written for this — ruff enforces
Google-style docstrings (`D` rules, `convention = "google"`) across `core/` and
`commands/`, and `sphinx.ext.napoleon` is already in `extensions`. The docstrings
are the content; only the build is broken.

**Open questions.**
- Autodoc must import every module. `daemon/`, `moonraker/`, and the kiosk pull
  in aiohttp/websockets/fastapi and touch `DefaultPaths.DIR_REPO_ROOT` at import
  time — the docs build environment will need `AUTOPIPETTE_REPO_ROOT` set, or
  those imports fail. Verify before wiring the workflow.
- `README.md` is marked `(OUTDATED!!!)` and describes the flat pre-`src/` layout.
  Generated API docs won't fix a wrong front page. Decide whether the README
  rewrite is in scope here or its own item.
- Whether narrative docs (getting started, protocol-authoring guide for the
  `.pipette` grammar) belong in the same Sphinx tree. `commands/tap_cmd_parsers.py`
  is currently the only authoritative reference for what a `.pipette` line may
  contain, and `protocols/` was cleared out — so protocol authors have no
  document at all today.

## 8. Versioning and release process

**Status:** needs planning session — depends on items 4, 5
**Touches:** `pyproject.toml`, new `CHANGELOG.md`, new `.github/workflows/release.yml`

**Problem.** `version = "0.1.0"` in `pyproject.toml`, **zero git tags**, no
changelog, no release artifacts. There is no way for an outside user of a public
repo to obtain a known-good version, and no record of what changed between any
two points.

**Intended behavior.**
- **SemVer, staying in 0.x** — decided. The control-plane RPC namespaces and the
  `.pipette` grammar are both public contracts still being reshaped (item 1's
  `keep_tip` → `tip_disposition` change is exactly such a break). 1.0 is gated on
  those two surfaces stabilizing; write that gate down explicitly so it's a
  decision, not a drift.
- **GitHub Releases, no PyPI** — decided. Tag `vX.Y.Z` → Actions builds sdist +
  wheel and attaches them to a Release with notes. No PyPI namespace to claim, no
  publishing credentials, and it avoids pretending a bare wheel solves the
  `AUTOPIPETTE_REPO_ROOT`/`config/` deployment story (it doesn't).
- `CHANGELOG.md`, Keep-a-Changelog style.

**Open questions.**
- Single source of truth for the version. Today it exists only in
  `pyproject.toml`; there's no `__version__` anywhere, so neither `tap`, `tapd`,
  nor the kiosk can report what they're running — which matters a lot for a bug
  report from a machine in the field. Options: hand-bump `pyproject.toml` and
  expose it via `importlib.metadata.version()`, or derive from the git tag with
  `setuptools-scm`. Recommend the former for simplicity; either way, add a
  `--version` flag to both entry points.
- `config/` and `systemd/` are not currently packaged (only
  `autopipette_kiosk/static/*` is in `package-data`), so a released wheel is not
  installable-and-runnable on its own. Decide whether the 0.x releases are
  honest about being "source + wheel for people who clone the repo," or whether
  the packaging gap gets closed first. **Do not advertise a release as turnkey
  until this is answered.**
- Tagging the first release requires picking a starting point — likely after
  items 4 and 5 land, so `v0.2.0` is the first tag with a green, gated tree
  behind it.

## 9. Strip cookiecutter boilerplate from `pyproject.toml`

**Status:** small — may not need its own planning session
**Touches:** `pyproject.toml`

**Problem.** `pyproject.toml` still carries template `# TODO:` comments
instructing the reader to fill in sections that are *already filled in*:

- above `requires-python` — "Replace with your actual minimum supported version"
  (it says `>=3.12`)
- above `dependencies` — "Add runtime dependencies here" (nine are listed)
- above `[tool.ruff.lint.isort] known-first-party` — "Replace with your package
  name under src/" (both packages are listed)
- above `[tool.coverage.run] source` — "Replace with your package name"
  (`tricca_autopipette` is set)

These are stale instructions, not real work items. They make a reader — human or
Claude — doubt whether the adjacent values are intentional, which is a real cost
in the one file that configures packaging and all four quality tools.

**Intended behavior.** Delete the four `# TODO:` comments. Keep the genuinely
explanatory comments around them (the `venvPath`/pyright rationale, the
`allowed-confusables` note, the per-file-ignores justifications) — those are
good and hard-won.

**Related.** Item 4 fixes 3 `RUF201` errors in this same file, and item 8 touches
`version`/`package-data`. Worth folding into whichever of those lands first
rather than making a standalone commit.

**Note.** `[tool.coverage.run] source` lists only `tricca_autopipette` —
`autopipette_kiosk` is missing, so kiosk code is invisible to coverage. That's a
real gap, not boilerplate. Decide whether to add it here or leave it to a
coverage-focused item (there is currently no coverage gate anywhere).

## 10. Dependency pinning / reproducible environments

**Status:** needs planning session — interacts with items 5 and 8
**Touches:** `pyproject.toml`, possibly a new lockfile, `systemd/README.md`

**Problem.** Every dependency is **completely unconstrained** — nine runtime deps
(`aiohttp`, `cmd2`, `opencv-python`, `pydantic>=2`, `requests`, `websockets`,
`numpy`, `fastapi`, `uvicorn`) and four dev tools, with `pydantic>=2` the only
one carrying any bound at all. There is no `uv.lock`, `poetry.lock`,
`requirements.txt`, or `flake.nix` in the repo.

Consequences, in rough order of severity:
- Two installs a week apart produce different environments. For software driving
  physical hardware against a Klipper/Moonraker API, "it worked on the machine we
  commissioned" is not reproducible today.
- `cmd2` is the clearest hazard: `CLAUDE.md` already records that a `precmd` hook
  "was broken against the installed cmd2 4.0 API and never actually blocked
  anything" — a silent breakage from an unpinned major version bump, in the
  homed-safety interlock. That is the failure mode this item prevents, and it has
  already happened once.
- Item 4 documents the same class of problem for `ruff` (preview rules appearing
  on upgrade), which becomes a CI-reddening event once item 5 gates on it.
- `opencv-python` and `numpy` are heavy and ABI-sensitive; unpinned they're a
  likely source of install failures on the Raspberry-Pi-class hardware the
  daemon actually runs on.

**Intended behavior.** Lower bounds on runtime deps in `pyproject.toml`
(what the code actually requires), plus a committed lockfile for reproducible
deployment and CI.

**Open questions.**
- Tooling. `uv` (fast, `uv.lock`, good CI story, doesn't change the
  setuptools build backend) vs `pip-tools` (`requirements.txt` +
  `requirements-dev.txt`, more conventional) vs Nix (`CLAUDE.md` names Nix as a
  real install target for `AUTOPIPETTE_REPO_ROOT`, so someone may already be
  packaging this that way — **find out before choosing**, since a flake would
  subsume the question).
- Application vs library. Pinning exactly is right for a deployed application and
  wrong for something others `pip install` as a dependency. Item 8 chose
  "GitHub Releases, no PyPI," which leans application — so lock hard and keep
  `pyproject.toml` bounds loose. Confirm that reading.
- Whether to pin the *dev* tools exactly (`ruff`, `pyright`) as item 4's open
  question implies. Strongly yes if CI gates on them.
- Whether to add Dependabot/Renovate once bounds exist, so upgrades become
  reviewed PRs instead of surprises. Interacts with item 5's CI.

## 11. Kiosk multi-page navigation + frontend restructure

**Status:** needs planning session — is the shell items 3, 12, 13 plug into
**Touches:** `src/autopipette_kiosk/static/` (`index.html` → split), `autopipette_kiosk/main.py` (routing only)

**Problem.** The kiosk is a single screen. `static/index.html` is 636 lines /
18 KB with `<style>` inline at lines 9–405 and `<script>` inline at 473–636 —
vanilla JS, no build step, no framework. It serves exactly one view (header,
protocol list, Run button, breakpoint Continue/Abort). Every capability the
daemon exposes beyond "run a protocol" is unreachable from the touchscreen,
which is the *only* interface during non-interactive runs.

**Intended behavior.**
- **Persistent tab bar** — decided, over a hamburger drawer. On a fixed-purpose
  kiosk nothing should be hidden behind a tap: an operator mid-run, possibly
  gloved, shouldn't hunt for a drawer. Larger targets, current page always
  visible, no open/close state to manage.
- **Split into files, stay vanilla** — decided. Break out `style.css` and
  per-page JS modules under `static/`, with client-side view switching. No build
  step and no JS dependencies (which matters given item 10). FastAPI already
  mounts `/static`, so `main.py` needs routing changes at most.
- Client-side switching specifically, **not** server-rendered separate pages: a
  full page load would drop and re-establish the `/ws/status` WebSocket on every
  navigation, which is unacceptable during a live run.

**Page inventory.**

| Page | Backend status | Notes |
|---|---|---|
| Run | ✅ built | the existing view |
| Tip inventory | ✅ RPCs exist | **item 3** — becomes a page rather than a bolt-on |
| Manual control / jog | ✅ RPCs exist | `movement.*`, `pipette.*` |
| Deck / locations | ✅ RPCs exist | `list_locations`/`list_plates`/`list_liquids`/`system_summary` |
| Location verify/correct | ✅ RPCs exist | see below — pure UI |
| Calibration wizard | ❌ **no backend** | **item 12** |
| Pipette max volume | ❌ **no backend** | **item 13** |

**Location verify/correct is pure UI.** Everything it needs already exists:
`move_loc` (drive to the location), `move_rel` (jog to the true position),
`coor`/`set` (overwrite the stored coordinate), `save_locations` (persist via
`LocationManager.save_to_json`). Worth building early — it's the highest
value-per-effort page on the list.

**Already in place.** `cli/report_tables.py` is the existing terminal renderer of
the same data-only payloads (`build_tipbox_map` and friends). Follow item 3's
rule for every page: the web UI is a **second renderer of one payload**, not a
second implementation. Do not put domain logic in `autopipette_kiosk/main.py`.

**Open questions.**
- Seven pages is past what a tab bar carries well (~5). Group them: primary tabs
  for Run / Tips / Move / Deck, with Calibration / Max volume / Verify behind a
  "Setup" or "Service" tab. Decide the grouping when the page set is final.
- Manual jog and the verify page both move hardware from a touchscreen. They must
  respect the homed interlock (`NotHomedError`) and should refuse to operate
  while a run is active — the daemon's `run.status` is the signal. Decide whether
  the UI greys these out or the daemon rejects them (prefer both).
- Whether pages are lazily loaded or all inlined at startup. Kiosk hardware is
  modest; all-at-once is likely fine and simpler.

## 12. Calibration procedure + kiosk wizard

**Status:** needs planning session — significant, backend + UI
**Touches:** `core/volume_converter.py`, `core/pipette_models.py`, `daemon/service.py`, `daemon/control_requests.py`/`control_server.py`, `config/pipettes/*.json`, kiosk page

**Problem.** Calibration is **half-built**: `core/volume_converter.py` can
*consume* a custom calibration curve (and `config/liquids/*.json` can carry one),
but nothing in this branch *generates* one. There is no calibration RPC in
`ControlRequests` at all — the whole surface listed in `control_requests.py` has
no calibration method. So a curve can only be produced by hand, off-machine.

**Intended behavior.** A guided procedure — dispense a known series of target
volumes, have the operator weigh or otherwise measure each, feed the measurements
back, fit a curve, and store it against the pipette (or liquid) profile.

**CLI parity is in scope (item 14).** Build the `AutoPipetteService` method and
control-plane RPC first, expose a `calibrate` command in `tap`, and treat the
kiosk wizard as the second renderer. Do not build the wizard as kiosk-only.

**Already in place.** `origin/calibration` exists as a remote branch — **read it
first**; it likely holds a working or partial procedure worth porting rather than
reinventing, the same way `origin/sticky-test-scott` did for items 2 and the
multi-dispense work. `volume_converter.py`'s curve-consumption side is the target
format, so the fitting output shape is already pinned down.

**Open questions.**
- **Where does the fitted curve get written?** This runs into item 13's problem —
  nothing currently writes `config/pipettes/*.json` or `config/liquids/*.json`
  back to disk. Settle the write-back mechanism once, for both items.
- Is calibration per-pipette-model, per-physical-machine, or per-liquid? The
  config layering allows all three and they mean different things. A curve
  measured on one machine shouldn't silently apply to another.
- What measurement does the operator supply — mass (needs a balance and a
  density), or volume read off a graduation? Mass is the standard method and
  wants a density field per liquid.
- `core/volume_converter.py:78` carries a `# TODO Change to degree 1?` on the fit
  degree — resolve that as part of this, not separately.

## 13. Writable pipette configuration (max volume) — safety-sensitive

**Status:** needs planning session — **do not implement casually**. Largely
**subsumed by item 19** (general config write-back): plan them together, with
this item contributing the safety bounds rather than its own write mechanism.
**Touches:** `core/pipette_models.py`, `core/json_config_manager.py`, `daemon/service.py`, `daemon/control_requests.py`/`control_server.py`, `config/pipettes/*.json`, kiosk page

**Problem.** There is **no path anywhere in the codebase that writes pipette
configuration back to disk.** `LocationManager.save_to_json`
(`core/location_manager.py:756`) is the *only* config-writing code that exists,
and it covers locations only. `config/pipettes/*.json` is strictly read-only at
runtime. So "a page to set a maximum volume for a given pipette model" requires
a new capability, not a new screen.

**Why this needs care.** `max_volume_ul` is not a display value — it feeds
`usable_capacity_ul()` (`max_volume_ul - capacity_margin_ul`), which
`AutoPipette.fit_air_volumes` uses to size air gaps and which raises
`VolumeCapacityError` when liquid alone won't fit. It is the software limit
standing between a protocol and physically overdriving the syringe. Exposing it
as a touchscreen field means an operator can raise it past what the hardware can
actually do, and the failure is mechanical, not an exception.

**Intended behavior (to be designed).** At minimum: a generic, validated
config write-back mechanism in `JsonConfigManager` — not an ad-hoc file write in
a kiosk handler — plus hard bounds that a UI cannot exceed.

**CLI parity is in scope (item 14).** If this item survives its open question
below, the write-back capability ships as a service method + RPC + `tap` command,
with the kiosk page as one renderer. An ad-hoc write in
`autopipette_kiosk/main.py` is exactly the leak item 14 names.

**Open questions.**
- **Should this be editable from the kiosk at all?** A hard physical ceiling
  belongs in the pipette model definition, set by whoever commissions the
  machine. The legitimate operator-facing need may be narrower (choosing among
  *defined* pipette models, or setting a per-protocol *lower* cap). Answer this
  before building the write path — it may dissolve the item.
- If it is editable: enforce an absolute maximum from the model that the writable
  value can only reduce, never raise. A soft limit the operator can raise isn't
  a limit.
- Config `extends` layering (`config/system/*.json` shallow-merges per top-level
  key) means "write it back" is ambiguous — which layer receives the edit, and
  what happens to a value inherited from a parent config?
- Whether an edit requires re-homing or invalidates a calibration curve fitted
  against the old capacity (interacts with item 12).
- Audit trail: a changed safety limit should be traceable. Decide whether writes
  are logged, and whether the daemon reports the effective value on startup.

## 14. Capability parity between the kiosk and the CLI

**Status:** standing principle + concrete gaps — read before items 3, 11, 12, 13
**Touches:** `daemon/service.py`, `daemon/control_requests.py`/`control_server.py`, `cli/remote_shell.py`, `commands/tap_cmd_parsers.py`, `src/autopipette_kiosk/`

**The rule.** Every capability reachable from the kiosk must also be reachable
from `tap`, and vice versa. Neither client is allowed to be the only way to do
something.

**Why the architecture already almost guarantees this — and where it leaks.**
Both clients are thin adapters over the *same* control-plane RPC surface: a
capability added as an `AutoPipetteService` method plus a `ControlRequests`
builder is automatically available to both, and `tap` gets it nearly free by
appending one row to `_STRUCTURED_COMMANDS` (`cli/remote_shell.py:474`). Parity
is cheap **if** capability lands at the service layer.

The leak is adding logic directly in `autopipette_kiosk/main.py`. That produces a
kiosk-only capability with no RPC behind it, invisible to `tap` and to protocol
files. `main.py` currently holds exactly one thing the daemon doesn't — the
`/protocols` directory glob — and that's the shape to avoid repeating.

**Current state (2026-07-29): the gap is one-directional.** `tap` exposes the
full surface (hand-written `do_*` plus `_STRUCTURED_COMMANDS`-generated commands
over every `ControlRequests` builder). The kiosk exposes only run / home /
breakpoint-respond / status. Nothing is kiosk-only today.

**Gaps this TODO list would create, and what each needs on the CLI side:**

| New capability | Item | CLI status | Needs |
|---|---|---|---|
| Tip inventory | 3 | ✅ `tips`/`reset_tips`/`reset_tips_all`/`set_tips` | nothing — kiosk is catching up |
| Manual jog | 11 | ✅ `move`/`move_rel`/`move_loc`/`aspirate`/`dispense` | nothing |
| Deck view | 11 | ✅ `ls`/`list_liquids` | nothing |
| Location verify/correct | 11 | ⚠️ primitives only | a guided `verify_locations` command, or accept that the workflow is UI-only while every *step* has a CLI equivalent — **decide which** |
| Calibration | 12 | ❌ nothing | a `calibrate` command + RPC, designed alongside the wizard |
| Pipette max volume | 13 | ❌ nothing | a config-write command + RPC (if item 13 survives its own open question) |

**How to apply.** For items 12 and 13, the CLI command is not a follow-up — it's
the same work. Build the `AutoPipetteService` method and RPC first, expose it in
`tap`, and treat the kiosk page as the second renderer. A capability that reaches
the touchscreen before it reaches the service layer is built wrong.

**Open questions.**
- Do interactive *wizards* (calibration, location verify) need a CLI equivalent
  of the whole guided flow, or only of each underlying step? A multi-step
  operator-prompting flow is awkward in a shell but not impossible — `break`
  already blocks a run pending a client response, so the machinery exists.
  Recommend: every step gets an RPC; the guided sequencing may be UI-only,
  documented as such.
- Should this parity rule be enforced by a test, the way
  `tests/daemon/test_control_server_dispatch_completeness.py` asserts every
  `ControlRequests` builder has a `_call` branch? An analogous test could assert
  every builder is reachable from `RemoteTapShell`. That would catch CLI drift
  mechanically; kiosk coverage is harder to assert and probably stays a review
  rule.
- Where the rule gets written down so it survives — likely `CLAUDE.md`'s
  architecture section, since it constrains all future work.

## 15. Model the syringe limit as travel distance, not volume

**Status:** needs planning session — **investigate the unit question first**
**Touches:** `core/pipette_models.py`, `core/autopipette.py`, `core/volume_converter.py`, `core/json_config_manager.py`, `daemon/service.py`, `cli/report_tables.py`, `config/pipettes/*.json`, `tests/core/test_autopipette.py`

**Problem.** The pipette pulls a syringe plunger a fixed mechanical distance. The
*volume* that displaces depends on the syringe's bore — swap the syringe and the
volume changes while the travel limit does not. The config stores
`max_volume_ul` as if volume were the primary quantity, making the machine's
actual hard limit a derived value that must be re-measured for every syringe.

The inversion is visible in the code. `core/autopipette.py:436` and `:678` both
read:

```python
distance = self.volume_converter.vol_to_steps(2 * self.syringe.max_volume_ul)
```

Both want a distance for a homing move and route through volume to get one.

**Decisions taken.**
- Store travel in the **same unit Klipper's `MANUAL_STEPPER` uses** — the
  codebase emits `MANUAL_STEPPER STEPPER=… MOVE=…` directly
  (`core/autopipette.py:442`, `:445`, `:448`, `:513`, `:516`, `:683`, `:686`),
  so staying in Klipper's units is more important than picking an ideal one.
  Klipper interprets `MOVE=` in **mm**. Verify against the Klipper docs and the
  machine before committing — see the investigation below.
- `max_volume_ul` becomes **derived, display-only**: a computed property backing
  `ls`/`report_tables.py:127` and `VolumeCapacityError` messages. Protocol
  authors keep thinking in µL, and "needs 250 µL, capacity 98 µL" stays
  actionable in a way a travel figure wouldn't be.
- Scope covers **`max_volume_ul` and `capacity_margin_ul`** — the margin is
  anti-overrun plunger headroom, a distance too. Converting one and not the other
  would leave `usable_capacity_ul()` mixing units. The volume-facing *protocol*
  API (`aspirate --vol`, `dispense`, `pipette`) is deliberately untouched:
  protocols should ask for µL.

**✅ RESOLVED 2026-07-29: the "steps" vocabulary already means millimetres.**
Checked against Klipper's own documentation. This is a **naming bug, not a
correctness bug** — the emitted G-code is fine.

Klipper's [G-Codes reference](https://www.klipper3d.org/G-Codes.html) documents
`MANUAL_STEPPER STEPPER=config_name [ENABLE=[0|1]] [SET_POSITION=<pos>]
[SPEED=<speed>] [ACCEL=<accel>] [MOVE=<pos>] [SYNC=0]`, with **`MOVE` and
`SET_POSITION` in millimetres, `SPEED` in mm/s, and `ACCEL` in mm/s²**. The
[config reference](https://www.klipper3d.org/Config_Reference.html) confirms the
mechanism: `[manual_stepper]`'s `rotation_distance` is "the distance (in
millimeters) that the axis travels with one complete rotation of the stepper
motor," and that is what converts a millimetre `MOVE` into step pulses.

So `VolumeConverter.vol_to_steps` — documented as returning "motor microsteps"
(`core/volume_converter.py:81–99`) — feeds its output **directly** into a
parameter Klipper reads as millimetres. Since the machine dispenses correct
volumes in practice, the polynomial is empirically a µL→**mm** fit that has
simply been labelled "steps" throughout.

The calibration table agrees: `_consts` maps 100 µL → 39.25. As mm, the implied
bore area is 100 µL / 39.25 mm ≈ 2.55 mm² — a diameter of ≈1.8 mm, entirely
plausible for a 100 µL glass syringe. As a microstep count for 100 µL it would
be implausibly coarse.

`core/autopipette.py:425–427` shows the confusion in a *single* docstring:

```
speed: Homing speed in steps/s, or None for default.
accel: Homing acceleration in mm/s², or None for default.
```

Two different units for two parameters of the same call. `speed` is mm/s.

**Consequently this item grows a rename.** The whole "steps" vocabulary denotes
mm and should say so: `vol_to_steps`/`steps_to_vol`, the matching shell commands
and control-plane RPCs, `VolToStepsArgs`, and every "μsteps" docstring. Both RPCs
and both `tap` commands are **public surface**, so this needs the same
deprecation-alias treatment item 1 needs for `keep_tip`.

**Quick win available now:** the `core/autopipette.py:425` docstring is
confirmed wrong and can be corrected independently of the full rename.

**Unrelated finding from the same check — worth verifying against your Klipper
version.** The code emits `STOP_ON_ENDSTOP` with **numeric** values: `=1`
(`core/autopipette.py:444`, `:685`), `=-1` (`:447`), and `=2` (`:515`). Current
Klipper documents that parameter as taking **string** values — `probe`, `home`,
`inverted_probe`, `inverted_home`, and `try_*` variants — with no numeric form
mentioned.

The numeric form is the older API, and the mapping is presumably
`1`→`probe`, `2`→`home`, `-1`→`inverted_probe`, `-2`→`inverted_home` (note `home`
additionally sets the final position so the trigger point matches `MOVE`, which
matters for `:515`). It is most likely still accepted for backwards
compatibility — the machine works — but this was **not** confirmed, and it is
exactly the kind of thing a Klipper upgrade drops. Verify against the Klipper
version actually deployed, and note this would be caught automatically by item
16's typed `MANUAL_STEPPER` builder.

**Open questions.**
- Deriving capacity from travel routes `usable_capacity_ul()` through
  `VolumeConverter.steps_to_vol`, which does polynomial root-finding and returns
  `min(valid_roots)` on a **degree-2** fit — non-monotonic and potentially wrong
  outside the calibrated range. Making a safety limit depend on it raises the
  stakes on `core/volume_converter.py:78`'s `# TODO Change to degree 1?`.
  Interacts directly with item 12.
- Config migration: three files under `config/pipettes/` carry `max_volume_ul`
  (`p100_vertical.json`, `default_p100.json`, `default_pipette.json`). Decide
  whether the loader accepts the old key with a warning, or whether this is a
  hard break — and note item 8 keeps the project in 0.x precisely so breaks like
  this are allowed.
- What converts travel → volume for a *given* syringe: the fitted calibration
  curve (status quo) or explicit bore geometry. Geometry would make swapping
  syringes a config edit rather than a recalibration, which is the practical
  payoff of this whole item. Larger change; interacts with item 12.
- Item 13 (writable max volume) is directly affected — if the stored limit
  becomes travel, the kiosk field it proposed to edit changes meaning. Settle
  item 15 first.

## 16. A typed G-code command library

**Status:** needs planning session
**Touches:** new `core/gcode_commands.py` (or `moonraker/`-adjacent), `core/autopipette.py` (39 call sites), `core/gcode_buffer.py`

**Problem.** Every G-code line in the project is a hand-built f-string. There are
**39 emission sites**, all funnelling into `GCodeBuffer.add(command: str)`
(`core/gcode_buffer.py:34`) — a bare string parameter, so nothing type-checks a
command name, validates a parameter, or enforces a unit. In a strict-pyright,
fully-annotated codebase, the layer that actually drives the hardware is the one
place with no type safety at all.

Item 15's finding is the direct consequence: a `MANUAL_STEPPER` builder with a
typed `move_mm` parameter would have made the steps-vs-millimetres confusion
impossible to write, and a single docstring could not have claimed
`speed` in steps/s alongside `accel` in mm/s² for the same call.

**Intended behavior.** A pure-builder library covering Klipper's **documented
built-in G-Code set** — the closed set in Klipper's `G-Codes.md`. Commands added
by `[gcode_macro]` config sections are explicitly out of scope: that surface is
machine-specific and controlled by whoever writes the config.

**Justification is correctness and discoverability**, not firmware portability.
A Klipper-shaped API doesn't make the G-code dialect swappable — callers still
think in `MANUAL_STEPPER` — and this item does not claim otherwise. The wins are
typed/unit-checked parameters, one tested definition per command, and
autocomplete over commands the authors wouldn't otherwise know exist.

**Follow the existing pattern.** `moonraker/moonraker_requests.py`'s
`MoonrakerRequests` and `daemon/control_requests.py`'s `ControlRequests` are both
already "pure builders, no I/O" — one returns Moonraker JSON-RPC payloads, the
other control-plane ones. A `GCodeCommands` returning G-code strings is the same
shape a third time, which is a strong argument that it belongs.

**Commands actually emitted today** (the migration target, and the ones that need
tests first): `MANUAL_STEPPER`, `LINEAR_MOVE`, `SET_SERVO`,
`SET_VELOCITY_LIMIT`, plus homing and `M400`.

**Open questions.**
- **Hand-write or generate?** Klipper's documented set runs to a few hundred
  commands across modules. Ruff enforces Google-style docstrings and pyright runs
  strict, so each hand-written builder is more than a one-liner. Generating from
  Klipper's `G-Codes.md` is attractive but couples the build to an upstream doc's
  formatting. Recommend hand-writing the ~10 in use plus the obvious neighbours
  first, proving the pattern, then deciding on bulk coverage.
- **Availability is config-dependent.** A Klipper command only exists if its
  module is configured — `SET_HEATER_TEMPERATURE` on a machine with no heater is
  rejected at runtime. A builder that emits it can't know that. Decide whether
  builders are grouped by Klipper module to make the dependency legible, and
  whether anything validates against the machine's actual config.
- **Where does validation live?** Range/unit checks in the builder catch errors
  before they reach hardware, but duplicate what Klipper already enforces.
  Recommend validating only what the domain knows (units, sign conventions,
  `FluidDisplacement`/`motor_orientation` handling) and letting Klipper own the
  rest.
- Whether `GCodeBuffer.add` should stop accepting bare `str` once builders exist,
  or keep it as an escape hatch for user macros. Keeping it is probably right
  given macros are out of scope — but then it should be named to look like an
  escape hatch.
- Sequencing against item 15: doing 15 first means migrating call sites once,
  with correct units baked in. Doing 16 first gives typed builders that make 15's
  rename mechanical. Recommend settling 15's unit question first (it may be a
  bug), then building 16, then executing 15's rename through the builders.

## 17. Fleet browser tool (Mainsail-like, network-connected)

**Status:** needs planning session — large; **depends on item 18**
**Touches:** new frontend + probably a new backend component; `daemon/control_server.py`, `daemon/main.py`, `config/system/*.json`

**Problem/goal.** The kiosk is deliberately confined to one local pipette on a
small touchscreen. There's no way to see or drive a *fleet* from one place, and
no interface designed for a full-size screen. The goal is a browser tool in the
spirit of Mainsail: connect to a single pipette or many over a network, with the
same capability set as `tap` and the kiosk, using the larger viewport to show far
more per page.

**Decisions taken.**
- **Explicit machine ownership/lock** for concurrent control. A client claims a
  machine before sending commands; others are read-only until release, with the
  current owner visible and a force-takeover path. Today `AutoPipetteService._lock`
  (`daemon/service.py:370`) only *serializes* dispatch and `RunAlreadyActiveError`
  only guards runs — nothing prevents a browser jog landing midway through
  someone's manual work at the kiosk, on the same physical gantry.
- **Tailnet as the network boundary, plus application-level authn/authz**, reusing
  **whatever authentication Moonraker provides** rather than inventing a scheme.
- **Topology deferred** to the planning session: central aggregator (one service
  holding a control-plane connection per machine; each `tapd` keeps its loopback
  bind; one place for auth, audit, rate limiting; fleet views trivial; new SPOF)
  versus browser-connects-to-each-`tapd` (the literal Mainsail model; no new
  backend, but every `tapd` must bind a network interface and enforce auth N
  times, with CORS/origin handling per host). Record both.

**Already in place — more than expected.** `moonraker/moonraker_requests.py`
already contains builders for Moonraker's entire authorization API:
`access.login`, `access.refresh_jwt`, `access.oneshot_token`,
`access.get_api_key`, `access.post_api_key` (lines 102–114, 780+), and
`api_key: str | None` at line 351. **None of it is used anywhere.** The
request-building half of Moonraker auth is already written.

Also reusable: `WebSocketClient` is already the transport for both hops (the
control-plane envelope is deliberately isomorphic to Moonraker's), and
`cli/report_tables.py` is the existing renderer of the data-only reporting
payloads.

**⚠️ Open question that must be settled first: *whose* authentication?**
Moonraker's auth protects **Moonraker**, which sits at the far end of the chain
(browser → [aggregator?] → `tapd` → Moonraker). `tapd` owns the Moonraker
connection; the browser never talks to Moonraker directly. So "use Moonraker's
authentication" resolves two very different ways:
- **Adopt the scheme** — implement Moonraker's model (JWT user accounts, API
  keys, `trusted_clients` CIDR allowlists, CORS domains) in the control plane, so
  operators get one mental model and the existing builders inform the design.
- **Delegate to it** — authenticate against each machine's Moonraker and pass
  credentials through. Awkward given `tapd` holds the connection, and Moonraker's
  user database is **per-machine**, meaning N user databases for a fleet unless
  something centralizes them.

Decide this before any code. It determines whether the control plane grows its
own auth or borrows one.

**Other open questions.**
- Tailscale gives *device* identity and ACLs, not *user* identity. Any node added
  to the tailnet, or any compromised laptop already on it, otherwise gets full
  unauthenticated control of syringes and gantries. Roles (view / operate /
  configure) need to be real, not implied by network membership.
- Fleet-wide and per-machine **emergency stop** must be prominent and reachable
  without claiming ownership. `AutoPipetteService.emergency_stop`
  (`daemon/service.py:2373`) exists; note that `cancel`/`pause`/`stop`
  deliberately bypass `_lock` for exactly this reason, and any ownership scheme
  must preserve that bypass.
- Item 14's parity rule now spans **three** clients. Confirm it still means
  "every capability reachable from each" — or explicitly carve out fleet-only
  operations (bulk actions across machines) that have no single-machine meaning.
- Machine discovery/inventory: how the tool learns what pipettes exist. Static
  config, tailnet enumeration, or mDNS. `config/system/*.json`'s `network` block
  currently carries only `hostname`/`port` and no credentials field.
- An audit trail of who commanded what, which the current design cannot produce
  at all.

## 18. The kiosk is network-exposed with no authentication

**Status:** **default fixed 2026-07-29** — the shipped unit now binds loopback.
Remaining work below; still read before item 17.
**Touches:** `systemd/autopipette-kiosk.service`, `systemd/README.md`, `src/autopipette_kiosk/main.py`, `daemon/control_server.py`

**Problem (as shipped before the fix).** `systemd/autopipette-kiosk.service` ran:

```
ExecStart=… uvicorn autopipette_kiosk.main:app --host 0.0.0.0 --port 8000
```

`0.0.0.0` binds every interface, and the kiosk app has **no authentication of any
kind** — no login, no token, no origin check. Anyone who could reach that host on
the network could `POST /home` and `POST /run`, and answer breakpoints. On a lab
or office network, that is every device on it.

**Fixed:** the unit now passes `--host 127.0.0.1`, with the reasoning recorded in
the unit itself and a "Network exposure" section in `systemd/README.md` covering
why, and what to do instead of reverting to `0.0.0.0`.

**⚠️ Still outstanding — the fix is not retroactive:**

1. **Already-deployed machines stay exposed.** The installed copy under
   `/etc/systemd/system/` is unaffected until someone re-copies the unit and runs
   `systemctl daemon-reload && systemctl restart autopipette-kiosk`. Audit every
   machine that was provisioned from an earlier revision.
2. **`tapd`'s control plane still has no authentication.** It is protected only
   by its own `127.0.0.1:8765` default bind — the same single control, one
   `--host` flag away from being removed. Item 17 proposes exactly that.
3. **Nothing prevents reintroducing the exposure.** A `--host 0.0.0.0` is still
   a valid, silently-accepted configuration for both processes.
4. The public repo now documents this exposure (this file), so any machine still
   running an old unit is described in public before it is fixed. That raises the
   priority of point 1 rather than changing what the fix is.

The control plane behind it has no auth either — no token, TLS, or origin
checking anywhere in `daemon/control_server.py` or `daemon/main.py`. Its only
protection is the default `127.0.0.1:8765` bind, which is real but is the *sole*
control. Item 17 proposes to remove exactly that protection.

**Why this is separable from item 17.** It's true now, on every deployed machine,
independent of whether the fleet tool ever gets built. It should be triaged on
its own timeline.

**Intended behavior (to be designed).** At minimum, decide deliberately what the
kiosk's exposure should be and make the systemd unit match. Options, roughly
increasing in effort: bind `127.0.0.1` and require the touchscreen to be local;
bind a tailnet interface only; put it behind a reverse proxy with auth; or build
real authentication into the app.

**Open questions.**
- Does the kiosk need to be reachable from other machines at all? If the
  touchscreen is physically attached, `--host 127.0.0.1` is a one-line fix that
  closes this entirely. **Answer this first** — it may make the rest moot.
- If remote access is wanted, this becomes the first instance of item 17's
  authentication question, and should be solved once for both.
- Whether `tapd`'s control plane should refuse non-loopback binds unless
  authentication is configured — a guard that would make the unsafe
  configuration hard to reach by accident, and would fail closed when item 17
  starts binding network interfaces.
- Physical-safety framing: unlike a 3D printer, an unauthorized `POST /run` here
  moves a gantry and drives a syringe in a lab. Worth stating the threat model
  explicitly rather than inheriting Klipper-world norms, where Mainsail/Moonraker
  are also commonly run unauthenticated on trusted LANs.

## 19. Editable and saveable configuration from every client

**Status:** needs planning session — **supersedes item 13**, which becomes one case of it
**Touches:** `core/json_config_manager.py`, `core/location_manager.py`, `core/pipette_constants.py` (`DefaultPaths`), `daemon/service.py`, `daemon/control_requests.py`/`control_server.py`, `cli/remote_shell.py`, kiosk + fleet UIs

**Problem.** Configuration is effectively read-only at runtime.
`JsonConfigManager` has **no write methods at all** — every one of its ~20
methods is `load_*`, `get_*`, `list_*`, or `switch_liquid`. The single writer in
the entire codebase is `LocationManager.save_to_json`
(`core/location_manager.py:756`), reachable as the `save_locations` RPC and
`tap` command. Everything else — liquids, pipettes, gantry, system — can only be
changed by editing JSON on disk and restarting.

**Three defects in the one writer that exists**, all of which the general
mechanism must not inherit:

1. **Non-atomic.** `location_manager.py:822` is a bare
   `with locations_file.open("w") … json.dump(…)`. A crash, power loss, or full
   disk mid-write truncates the file that defines the deck geometry. Needs
   write-to-temp-then-`os.replace`, and probably a backup of the prior version.
2. **Lossy round-trip.** It reconstructs plate entries from `location.wells[0]`
   and probes optional attributes with `hasattr`, re-emitting only the subset it
   knows about. Load → save silently drops anything not explicitly handled.
   Config the operator never touched can disappear by saving.
3. **Collapses `extends`.** `_read_system_file` resolves the inheritance chain
   and returns merged data "with `extends` removed"
   (`core/json_config_manager.py:238`). Writing in-memory state back turns a
   three-line `{"extends": "default_system.json", "locations": {…}}` into a
   fully-expanded file — destroying exactly the layering `config/README.md`
   exists to provide, and guaranteeing drift from defaults thereafter.

**Decisions taken.**
- **Writes go to a separate user/runtime config directory**, layered over the
  git-tracked repo defaults — not into `config/` itself. On a deployed machine
  `/opt/tricca-autopipette` is a git checkout (`systemd/tapd.service:11`), so
  in-place edits become uncommitted changes that a `git pull` upgrade clobbers or
  conflicts with. A separate dir also makes "what has this machine changed"
  answerable as a diff against defaults. Fits the existing layered model rather
  than fighting it.
- **All four config types become writable**: locations, liquids, pipettes,
  gantry/system — with risk tiering (below), not uniform treatment.

**Risk tiering.** These are not equally safe to expose, and the UI should not
pretend otherwise:

| Type | Risk | Notes |
|---|---|---|
| Locations | low | already writable; fix the three defects above. Drives item 11's verify/correct page |
| Liquids | low | speeds, waits, air gaps, prewet — routine bench tuning |
| Pipettes | **high** | syringe kinematics and capacity. This is **item 13** — contains the safety limit (`max_volume_ul`, or item 15's travel limit). Needs hard bounds a UI cannot exceed |
| Gantry/system | **high** | wrong speeds/accels crash the gantry into hardware; least routine need |

**CLI parity is in scope (item 14).** The capability lands as
`AutoPipetteService` methods + control-plane RPCs, exposed in `tap`, with kiosk
and fleet UIs as renderers. `save_locations` already demonstrates the shape.

**Open questions.**
- **How is `extends` preserved on write?** The likely answer is that the runtime
  dir holds *overlay* files carrying only what differs, with the load path
  merging them — which means writing a diff against the resolved defaults, not
  the resolved state. Settle this first; it determines the whole file format.
- Round-trip fidelity needs a test: load every file under `config/`, save, reload,
  assert equality. That test would fail today for locations.
- Validation must be parse-then-apply, matching the rule
  `LocationManager.load_from_json` already follows (validate everything before
  touching live state) — and must extend to *rejecting a write* that would
  produce an unloadable config.
- Does a config write take effect live, or on next daemon restart? Changing
  gantry speed mid-run is not obviously safe; some fields may need to be
  restart-only, or refused while a run is active.
- Who may write what, once items 17/18 add real authn — config editing is the
  clearest case for a "configure" role distinct from "operate".
- Interaction with item 12: a fitted calibration curve is a config write, and
  should use this mechanism rather than its own.
- Whether the runtime dir is exposed as `AUTOPIPETTE_CONFIG_DIR` alongside the
  existing `AUTOPIPETTE_REPO_ROOT`/`AUTOPIPETTE_PROTOCOLS_DIR` env vars, and how
  `DefaultPaths` resolves the two-layer lookup.

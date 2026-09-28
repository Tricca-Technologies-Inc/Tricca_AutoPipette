# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
while staying in the `0.x` series (see `RELEASING.md`).

Entries are drafted per release from merged PR titles since the previous
tag, then hand-edited into the categories below — there is no hand-maintained
"Unreleased" section kept current between releases (see `RELEASING.md` for
why). Categories in use: `Added`, `Changed`, `Fixed`, `Removed`.

## [0.2.0] - 2026-09-28

First tagged release. No previous tag exists, so this entry summarizes the
project's whole history to date rather than listing all 53 merged PRs
individually — see `git log` for the full record.

### Added
- Core architecture: `tapd` control daemon (owns the single Moonraker
  connection), `tap` remote shell, and the kiosk touchscreen web UI, all
  talking over a shared control-plane WebSocket.
- Location groups, `TipBoxManager` (per-box tip-presence tracking with
  Moonraker-DB persistence), and configurable traversal orders.
- Kiosk multi-page navigation shell with Tip-inventory (#17/#25), Move
  (#86, jog/absolute/named-location movement), and Deck (#87, read-only
  spatial map + tip-occupancy view) pages.
- Protocol pre-flight validation: `run.validate` RPC, `tap validate`
  command, dry-run replay (#36), plus the kiosk Run-tab "Check" button
  (#88).
- Compile-time protocol rollback (`domain_state_snapshot`) — a failed
  `.pipette` run no longer leaves the deck model advanced (#35).
- Multi-machine config split: shared repo vs. per-machine local config
  root (#68), with an automated migration for real per-rig data.
- RPC client-identity tagging and a connected-clients diagnostic surface
  (#53/#59); movement/RPC logging with variable provenance and per-chunk
  G-code comments (#52).
- Protocol-authoring guide, generated command reference, and runnable
  examples (#54).
- Full test-suite ground-up coverage pass across CLI, kiosk, daemon, and
  core layers, including real-socket concurrency tests for
  `WebSocketClient` (#37/#38/#41/#42/#43).
- Kiosk browser regression suite (`pytest-playwright`) and an AI-review
  screenshot tool (#78).
- CI workflow (`ruff`/`pyright`/`pytest`/browser tests, four parallel
  jobs) and this versioning/release process (#19/#22).
- `tests/kiosk/test_route_rpc_parity.py`: a structural guard against a
  capability existing in the kiosk with no matching `tap`-reachable RPC
  behind it (#28).

### Changed
- Standalone `TriccaAutoPipetteShell`/`cli/tap_shell.py` removed now that
  `RemoteTapShell` has full command parity (#39).
- `RemoteTapShell`'s commands hand-written instead of generated, so
  `help`/`help -v` show real per-command text.
- Docstrings audited across `src/`, ruff `DOC` rules enabled repo-wide,
  the Sphinx docs build fixed, and the root `README.md` rewritten as a
  thin front door (#50/#21/#51).
- `daemon/service.py`'s `RunStatus.status` typed as a `Literal` for
  kiosk/tap parity (#84); the kiosk frontend's duplicate
  `isRunning`-style checks consolidated into `App.isRunActive` (#83).
- Test-driven development (`mattpocock-skills:tdd`) mandated going
  forward for new features and bug fixes with a concrete input/output.

### Fixed
- 38 ruff preview-rule errors, greening the tree ahead of CI (#18).
- `websockets`-version pyright-strict typing drift in the real-socket
  test suite, found while standing up the CI workflow (#101).
- Assorted dead code, duplication, and real bugs from two codebase
  quality sweeps.

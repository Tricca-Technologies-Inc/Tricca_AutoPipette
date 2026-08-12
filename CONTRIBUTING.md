# Contributing

Thanks for considering a contribution to Tricca AutoPipette. This is a small,
mostly solo-maintained project driving physical lab hardware — a few notes
below will save you a round-trip.

## Before you start

- **Read `CLAUDE.md`** at the repo root first. It's the authoritative,
  up-to-date architecture description (components, the `tapd` daemon, the
  config system, code style) — more detailed and more current than this file.
- **Check the backlog.** Planned-but-unimplemented work lives as GitHub
  issues, starting from the map, [#34](https://github.com/Tricca-Technologies-Inc/Tricca_AutoPipette/issues/34).
  It carries dependency order and standing findings. Several entries record
  decisions already taken — read an issue fully before proposing a different
  shape for it. See `docs/agents/issue-tracker.md` for the tracker's
  conventions and `docs/agents/triage-labels.md` for what the labels mean.
- **`safety`-labeled issues need extra care.** That label marks work where a
  wrong value fails *mechanically* — overdriving a syringe, crashing a
  gantry — not as a catchable exception. Small diffs in that territory still
  need a human reviewer and explicit reasoning about the bound being changed.

## Dev setup

```bash
pip install -e ".[dev]"
```

Run the daemon first — `tap` and the kiosk are both thin clients of it and do
nothing useful until it's running:

```bash
tapd --no-connect       # or --local-connect against a local/mock Moonraker
```

Then, in another terminal:

```bash
tap                                    # interactive shell
uvicorn autopipette_kiosk.main:app --host 127.0.0.1 --port 8000   # kiosk
```

Both the daemon's control plane and the kiosk are loopback-only with no
authentication by default — see `systemd/README.md` before changing a bind
address; that's a security decision, not a convenience toggle.

## Checks

Run all four before opening a PR — there's no CI yet ([#19](https://github.com/Tricca-Technologies-Inc/Tricca_AutoPipette/issues/19)), so this is
what stands behind a review today:

```bash
ruff check .
ruff format .
pyright
pytest
```

If you touched a docstring's `>>> ` example, also run:

```bash
pytest --doctest-modules
```

If you touched a docstring or anything under `docs/`, also run:

```bash
sphinx-build -W docs docs/_build/html
```

(`-W` treats warnings as errors — this is the check to run before a
docs-affecting PR, not the plain build.)

## Code style

Briefly, since `CLAUDE.md`'s "Code style" section is authoritative: Python
3.12+, `from __future__ import annotations`, Google-style docstrings
enforced repo-wide via ruff's `D`/`DOC` rules (only `tests/**` is exempt from
`D`, none are exempt from `DOC`), pyright strict mode. Match the surrounding
file's docstring density and naming rather than introducing a new style
locally.

## Opening a PR

- Branch off `main`; don't push directly to it.
- If the PR closes an issue, say so in the description (`Closes #NN`) so it
  closes automatically on merge.
- The PR template's verification checklist is the minimum bar — check off
  what you actually ran, not what you intend to.

## License

By contributing, you agree your contribution is licensed under this
project's [GPL-3.0-or-later](LICENSE) license.

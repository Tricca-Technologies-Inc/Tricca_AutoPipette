# Domain Docs

How the engineering skills should consume this repo's domain documentation when
exploring the codebase.

## Before exploring, read these

- **`CLAUDE.md`** at the repo root — the authoritative description of the system
  as it *is*. It is unusually detailed for this repo and supersedes `README.md`,
  which is explicitly marked `(OUTDATED!!!)`.
- **`CONTEXT.md`** at the repo root, if it exists.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their
absence; don't suggest creating them upfront. The `/domain-modeling` skill
(reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates
them lazily when terms or decisions actually get resolved.

Neither `CONTEXT.md` nor `docs/adr/` exists yet. `CLAUDE.md` currently carries
the glossary-shaped content that would otherwise live in `CONTEXT.md` — the
naming rules (air gap vs `aspirate_air`, `_ul` suffixes), the client parity rule,
and the "steps means millimetres" correction. Read it as the glossary until a
real one exists.

## File structure

This is a **single-context** repo:

```
/
├── CLAUDE.md
├── CONTEXT.md          ← not yet created
├── docs/
│   ├── adr/            ← not yet created
│   └── agents/         ← this directory
└── src/
    ├── tricca_autopipette/
    └── autopipette_kiosk/
```

`src/` holds two packages, but they are not separate bounded contexts — the
kiosk is a thin client of the daemon and shares its domain model. Don't split
into `CONTEXT-MAP.md` on the strength of the package count alone.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal,
a hypothesis, a test name), use the term as defined in `CLAUDE.md` / `CONTEXT.md`.
Don't drift to synonyms the project explicitly avoids. Live examples in this
repo:

- **air gap**, never `aspirate_air` or `pre_aspirate_air` — names the thing, not
  the action that created it.
- Microlitre quantities carry a `_ul` suffix on model/dataclass/parameter names
  but **not** on user-facing flags.
- "steps" in `VolumeConverter` denotes **millimetres**. The names lie; the
  numbers are correct. Renaming is tracked as issue #29.

If the concept you need isn't in the glossary yet, that's a signal — either
you're inventing language the project doesn't use (reconsider) or there's a real
gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than
silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_

The same applies to a decision recorded in an issue. Several backlog issues mark
sections **decided**; those should not be relitigated without a reason, and
contradicting one is worth saying out loud.

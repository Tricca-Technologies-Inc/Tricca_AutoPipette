# Test-Driven Development

Policy, not just a reference: for any new feature or bug fix that has a
concrete input and an observable output — business logic, a control-plane RPC,
a transformation, validation, a new domain method — run the
`mattpocock-skills:tdd` skill (`/tdd`) rather than writing the implementation
and tests together afterward. Red before green, one seam at a time, and the
seams under test are named and confirmed before any test file exists. Full
rules live in the skill itself; this file only records how it applies here.

## Scope

Per the skill's own guidance, don't force the loop where it doesn't fit:
config, wiring, glue, type annotations, and straight CRUD delegation (e.g. a
`config.*` RPC that's a thin pass-through to a `JsonConfigManager` getter)
have no independent source of truth to assert against, so a forced test there
is the tautological anti-pattern from the other direction. Use judgment; when
in doubt, ask.

## Backend (Python)

This is where `/tdd` applies cleanly today. Test at the seams the codebase
already tests at — real `ControlServer`/`AutoPipetteService` round trips via
`tests/support/live_control_plane.py`'s `LiveControlPlane`, or `TestClient`
for kiosk HTTP routes — mocking only at the Moonraker boundary
(`tests/fakes/`), never internal collaborators. That boundary-only-mocking
discipline is already established in this repo; keep it.

## Frontend (kiosk JS)

`static/*.js` has no test tooling at all yet (issue #78 — no
`package.json`, no Jest/Vitest/Playwright, nothing exercises `app.js`/
`run.js`/`tips.js`). That's a tooling gap, not a license to skip testing
indefinitely: it needs its own `/grill-me` session to pick an approach
(pure-logic extraction under `node:test`, `pytest-playwright`, or another
option) before a red-green loop can run there. Until that lands, don't
silently ship new non-trivial JS logic untested — call it out explicitly in
the PR description so it's a visible, tracked gap rather than an invisible
one, the way `tips.js`'s toggle math was flagged after the fact in PR #77.

Per the skill's own guidance, once browser/e2e tooling exists, don't write
those tests first — they're slow enough that the red-green loop stops paying
for itself. Write the behavior, then the browser test.

## What this replaces

The 2026-08-05 six-PR "test-suite audit"
([[test-suite-audit-in-progress]] in memory) — module-by-module gap-filling
against a coverage-percentage target, done after the code already existed —
was a one-time cleanup of a pre-existing backlog, not a template to repeat.
That pattern is exactly the **horizontal slicing** anti-pattern the `tdd`
skill warns against: bulk tests written after bulk implementation, verifying
the shape of things rather than driving the implementation. Going forward,
coverage gaps get closed at the moment the code is touched, one vertical
slice via `/tdd`, not batched into a future audit PR.

## Seams

When the right seam isn't obvious, don't guess silently and don't leave it to
the skill's bare seam-name prompt either — ask what each candidate seam
catches and misses (component vs. integration, etc.) before picking, per the
skill's own documented friction point. `mattpocock-skills:codebase-design` is
the shared vocabulary for that discussion when the question is really about
interface shape rather than test placement.

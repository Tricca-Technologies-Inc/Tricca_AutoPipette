# Test-Driven Development

Policy, not just a reference: for any new feature or bug fix that has a
concrete input and an observable output — business logic, a control-plane RPC,
a transformation, validation, a new domain method — follow the loop below
rather than writing the implementation and tests together afterward. It
applies to every contributor and every AI tool. Claude Code users get the
same loop from the `mattpocock-skills:tdd` skill (`/tdd`). Everyone else
follows the steps here.

## The loop

1. **Name the seam.** Say which public interface the test drives (a service
   method, a control-plane RPC, a kiosk route, a G-code golden file; see
   "Seams" below) and what behavior it pins. Agree it with the reviewer
   before writing a test file when it isn't obvious.
2. **Red.** Write one test for one behavior, run it, and see it fail for the
   reason you expect. A test that passes before the change proves nothing.
3. **Green.** Write the least code that makes that test pass. Don't build
   ahead of the tests.
4. **Repeat** one behavior at a time (a vertical slice), not every test
   first and then every implementation.
5. **Refactor** only while green, then run the full check:
   `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`.

Test behavior through public interfaces, not implementation details. Mock
only at the Moonraker boundary (`tests/fakes/`).

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

`static/*.js` is tested in a real browser with `pytest-playwright` (issue
#78), under `tests/kiosk/browser/`, against a real kiosk and control plane
with only the Moonraker client faked (`tests/support/live_control_plane.py`,
`tests/support/live_kiosk_server.py`). Install it with
`uv sync --extra dev --extra browser-test` and
`uv run playwright install chromium`; CI runs the suite in the
`test-browser` job. `tests/kiosk/browser/capture_screenshot.py` saves a
screenshot of a page for checking layout by eye (see its docstring).

New kiosk JS behavior gets a browser test. Per the skill's own guidance,
don't write those tests first — they're slow enough that the red-green loop
stops paying for itself. Write the behavior, then the browser test, and
check that it fails with the behavior removed. Logic with a concrete input
and output (like `tips.js`'s toggle math) can still be pulled into a pure
function and driven red-green from a browser test.

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

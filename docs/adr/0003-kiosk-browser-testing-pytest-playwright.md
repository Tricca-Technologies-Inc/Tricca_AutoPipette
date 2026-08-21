# Kiosk browser/screenshot testing: `pytest-playwright`, not Node's Playwright Test

**Status:** accepted

Issue #78 (kiosk frontend JS has zero coverage) named three rough options and
asked for a `/grill` session before implementation. That session also
surfaced a second need beyond #78's scope: screenshots specifically so a
Claude session can visually review its own UI changes, not automated
pixel-diff regression.

**Decision.** Two separate pieces, both on `pytest-playwright` (Python), not
Node's `@playwright/test`:

1. **An automated regression suite** — real browser driving real clicks
   against the kiosk, reusing `tests/kiosk/`'s existing `LiveControlPlane`
   (real fake-Moonraker-backed `ControlServer`, matching this repo's
   established mock-only-at-the-Moonraker-boundary discipline) behind a new
   live-`uvicorn` fixture, since Playwright needs a real socket and
   `TestClient`'s in-process ASGI transport doesn't provide one. Assertions
   are DOM-based (`expect(locator).to_have_text()`/`to_have_class()`/etc.)
   only — no pixel-diffing. No separate `node:test` pure-logic-extraction
   layer either: the JS (419 lines, all DOM-entangled IIFEs with nothing
   currently exported) is small enough that Playwright driving the real grid
   already exercises `tips.js`'s `wellId()`/toggle math end to end.
2. **A standalone, on-demand screenshot-capture tool** — no assertions, not
   run as part of `pytest`, parameterized by page/state rather than a fixed
   inventory. Its only job is producing a PNG for a Claude session to `Read`
   after touching the kiosk frontend. Runs against the same
   `LiveControlPlane`-backed fixture as (1).

`pytest-playwright` gets its own dedicated install extra, separate from
`dev` — folding it into `dev` would put a ~300MB browser-binary download
(`playwright install chromium`) in the path of every contributor touching
any part of the repo, not just the kiosk.

**Why not Node's Playwright Test.** Its main edge over the Python bindings is
first-party `expect(page).to_have_screenshot()` — baseline management,
`--update-snapshots`, per-OS/browser naming — which only matters for
automated pixel-diff regression. Since the screenshot need here is AI review,
not diffing, that edge doesn't apply, and Python wins on practical grounds:
one process can both start the real kiosk+`LiveControlPlane` backend *and*
drive the browser, with no cross-language orchestration to boot a Python
server from a Node test runner — and it avoids this repo's first
`package.json`.

**Why not a third-party Python snapshot-diff plugin**
(`pytest-playwright-visual-snapshot` and similar) either: same reasoning —
there's no automated diffing need to solve, so installing one would be
unused surface area. If automated visual regression becomes a real need
later (not just AI review), revisit this decision rather than bolting a
plugin onto the current shape.

**Baseline/CI stability deliberately deferred.** No CI exists yet (#19).
Playwright screenshots are OS/font-rendering sensitive across machines, but
since nothing here diffs against a baseline, that sensitivity doesn't bite
yet. Revisit (e.g. a Docker-pinned browser image) if/when #19 lands and
regression-suite runs need to be reproducible across machines.

**Narrow update (2026-08-21).** `tips.js`'s toggle math (`wellId()` +
consumed-range computation) was pulled out as `computeToggle`, a private
pure function inside the same IIFE. This does not reopen the "no separate
pure-logic-extraction layer" call above: assertions still land on the DOM
via Playwright (`tests/kiosk/browser/test_tips_toggle.py`), including a new
test for the previously-untested revert-on-failure branch, driven by
`page.route`-mocking a rejected `/tips/set` rather than a unit test calling
`computeToggle` directly. The extraction is a locality win for maintainers
reading `toggleCell`, not a new test seam or a `node:test` layer — that call
still stands.

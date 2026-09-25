"""Route -> RPC parity guard for the kiosk.

CLAUDE.md's client-parity rule, rescoped one-directionally by issue #28: no
capability may exist in the kiosk without also existing as a real
control-plane RPC (and, by `tests/cli/test_remote_shell_dispatch_completeness.py`,
a `tap` command). The kiosk->RPC direction had no mechanical guard until this
file -- unlike that test and
`tests/daemon/test_control_server_dispatch_completeness.py`, there's no single
dispatch point to probe here, so this instead inspects each route function's
own source.

Deliberately a source-shape/grep-style check, not AST parsing or a
hand-maintained route->RPC registry: every `@app.get`/`@app.post` route in
`autopipette_kiosk/main.py`, except a hardcoded exception list, must contain
exactly one call whose target is `_control_requests.<builder>` -- a new route
is checked automatically without anyone remembering to update a second list.
A count of zero is the leak this guards against (kiosk-only logic with no RPC
behind it, invisible to `tap` and to protocol files); a count above one means
this check itself needs a closer look at that route.
"""

from __future__ import annotations

import inspect

from fastapi.routing import APIRoute

from autopipette_kiosk.main import app

# "/": serves the static shell, no RPC involved.
# "/protocols": the one documented kiosk-only capability (a directory glob),
#   see CLAUDE.md's "Client parity rule" paragraph -- not a gap to close.
# "/status": serves locally-cached state that arrived via a Moonraker
#   notification push; no RPC round-trip needed to re-fetch it.
# The `/ws/status` websocket route is excluded separately below, since it's
# an `APIWebSocketRoute`, not an `APIRoute` -- it never matches this filter.
_EXEMPT_PATHS = frozenset({"/", "/protocols", "/status"})


def _checked_routes() -> list[APIRoute]:
    """Every `@app.get`/`@app.post` route in `main.py` subject to this check.

    Returns:
        `APIRoute`s (the websocket route isn't one) whose path isn't in
        `_EXEMPT_PATHS`.
    """
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path not in _EXEMPT_PATHS
    ]


def test_exempt_paths_are_real_routes_on_the_app() -> None:
    """Guards the exemption list itself against a renamed/removed route.

    Without this, a typo'd or stale path in `_EXEMPT_PATHS` would just
    silently fail to exempt anything, or exempt a path that no longer
    exists -- either way defeating the point of an explicit, checked list.
    """
    actual_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    missing = _EXEMPT_PATHS - actual_paths
    assert not missing, (
        f"_EXEMPT_PATHS names paths that aren't real routes on `app`: "
        f"{sorted(missing)} -- main.py must have renamed/removed one."
    )


def test_every_non_exempt_route_calls_exactly_one_control_requests_builder() -> None:
    """Every non-exempt kiosk route must be a thin `_control_requests.*` passthrough.

    A route with zero such calls has grown kiosk-only logic with no RPC
    behind it -- invisible to `tap` and to protocol files, the exact leak
    issue #28 exists to catch. More than one is unexpected for the routes
    this repo has today and worth a closer look rather than silently
    allowing.
    """
    violations = {
        route.path: inspect.getsource(route.endpoint).count("_control_requests.")
        for route in _checked_routes()
    }
    violations = {path: count for path, count in violations.items() if count != 1}
    assert not violations, (
        f"Routes not making exactly one _control_requests.<builder> call: "
        f"{violations} -- every kiosk route (other than the documented "
        "exceptions in _EXEMPT_PATHS) must be a thin passthrough to a "
        "control-plane RPC (CLAUDE.md's Client parity rule, issue #28)."
    )

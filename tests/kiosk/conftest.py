"""Shared fixtures for kiosk (`autopipette_kiosk`) control-plane tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient
from support.live_control_plane import LiveControlPlane

from autopipette_kiosk import main as kiosk_main
from tricca_autopipette.core.pipette_constants import DefaultPaths


@pytest.fixture
def protocols_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect both the kiosk's and the daemon's protocol directories.

    `autopipette_kiosk.main.PROTOCOLS_DIR` (the kiosk's own existence
    pre-check/listing) and `DefaultPaths.DIR_PROTOCOL` (what
    `AutoPipetteService.start_run`, reached over the real control plane,
    actually reads) normally point at the same physical `protocols/` folder
    in a single-machine deployment. Both are resolved once, not read fresh
    per request (see CLAUDE.md), so patching each module constant directly
    -- not the env vars they were originally read from -- is the only way
    to redirect them per test.

    Returns:
        The empty temp dir now patched in as both protocol directories.
    """
    monkeypatch.setattr(kiosk_main, "PROTOCOLS_DIR", tmp_path)
    monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", tmp_path)
    return tmp_path


@pytest.fixture
def kiosk_client(
    live_control_plane: LiveControlPlane, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A `TestClient` for the kiosk app, connected to a real control plane.

    Used as `with TestClient(app) as client:` internally -- required for
    the app's `lifespan` (and thus its own control-plane `WebSocketClient`)
    to actually run; a `TestClient` used without a `with` block dispatches
    HTTP routes without ever starting it (see `test_main.py`'s "not
    connected" tests, which rely on exactly that to get a clean
    `_control_client is None` state for free).

    Also resets the run/breakpoint/websocket-client module globals
    `autopipette_kiosk/main.py` keeps instead of per-request state (it's a
    long-lived singleton in production) -- tests share that same module
    across the whole session, so leftover state from one test would
    otherwise leak into the next.

    Yields:
        A `TestClient` for the kiosk app, with its `lifespan` running.
    """
    empty_clients: set[WebSocket] = set()
    monkeypatch.setattr(kiosk_main, "TAPD_CONTROL_URI", live_control_plane.url)
    monkeypatch.setattr(kiosk_main, "_current_run", kiosk_main.RunStatus(status="idle"))
    monkeypatch.setattr(kiosk_main, "_current_breakpoint", None)
    monkeypatch.setattr(kiosk_main, "_ws_clients", empty_clients)

    with TestClient(kiosk_main.app) as client:
        yield client

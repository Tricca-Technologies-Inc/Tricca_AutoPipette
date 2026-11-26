"""Shared fixtures for kiosk (`autopipette_kiosk`) control-plane tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fakes.fake_websocket_client import FakeWebSocketClient
from fastapi import WebSocket
from fastapi.testclient import TestClient
from support.live_control_plane import LiveControlPlane

from autopipette_kiosk import main as kiosk_main
from tricca_autopipette.core.pipette_constants import DefaultPaths


@pytest.fixture(autouse=True)
def _allow_testclient_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let `TestClient`'s ``Host: testserver`` past the kiosk's host check."""
    monkeypatch.setattr(
        kiosk_main, "ALLOWED_HOSTS", kiosk_main.ALLOWED_HOSTS | {"testserver"}
    )


@pytest.fixture
def protocols_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the daemon's shared protocol directory to an empty temp dir.

    The kiosk has no protocol directory of its own: it lists and checks
    protocols through `tapd`'s `protocols.list`, and the daemon resolves
    them against `DefaultPaths.DIR_PROTOCOL`. That is read fresh on every
    call, so patching it is enough.

    Returns:
        The empty temp dir now patched in as the shared protocol directory.
    """
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

    Also resets the run/breakpoint/toolhead/websocket-client module globals
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
    monkeypatch.setattr(kiosk_main, "_config_locked", False)
    monkeypatch.setattr(kiosk_main, "_homing_invalidated", False)
    monkeypatch.setattr(
        kiosk_main, "_current_toolhead", {"position": None, "homed_axes": None}
    )
    monkeypatch.setattr(kiosk_main, "_ws_clients", empty_clients)

    with TestClient(kiosk_main.app) as client:
        yield client


@pytest.fixture
def kiosk_client_with_moonraker(
    live_control_plane: LiveControlPlane, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A `kiosk_client` whose daemon has a (fake) Moonraker connection.

    For the live toolhead-relay tests (issue #86): `live_control_plane`'s
    plain `service.client` is None (see `tests/conftest.py`'s `service`
    fixture), so the `ws.subscribe("notify_status_update")` call the
    kiosk's `lifespan` makes on connect would raise before ever
    registering a handler. Wiring a `FakeWebSocketClient` in as the
    daemon's own "Moonraker connection" lets that subscribe succeed, so a
    test can then call `client.trigger_notification(...)` on it to
    simulate a real Moonraker push and assert it reaches the kiosk over
    `/ws/status`.

    Yields:
        A `TestClient` for the kiosk app, with its `lifespan` running and
        `live_control_plane.service.client` set to a `FakeWebSocketClient`
        the test can drive directly.
    """
    live_control_plane.service.client = FakeWebSocketClient(connected=True)  # type: ignore[assignment]
    empty_clients: set[WebSocket] = set()
    monkeypatch.setattr(kiosk_main, "TAPD_CONTROL_URI", live_control_plane.url)
    monkeypatch.setattr(kiosk_main, "_current_run", kiosk_main.RunStatus(status="idle"))
    monkeypatch.setattr(kiosk_main, "_current_breakpoint", None)
    monkeypatch.setattr(kiosk_main, "_config_locked", False)
    monkeypatch.setattr(kiosk_main, "_homing_invalidated", False)
    monkeypatch.setattr(
        kiosk_main, "_current_toolhead", {"position": None, "homed_axes": None}
    )
    monkeypatch.setattr(kiosk_main, "_ws_clients", empty_clients)

    with TestClient(kiosk_main.app) as client:
        yield client


@pytest.fixture
def kiosk_client_with_plates(
    live_control_plane_with_plates: LiveControlPlane,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """A `kiosk_client` whose service has a tipbox/waste/plate wired up.

    For the `/tips*` routes, which need a real registered tipbox
    (`live_control_plane`'s plain `service` has none) to report or mutate.

    Yields:
        A `TestClient` for the kiosk app, with its `lifespan` running and a
        real tipbox (named ``"tipbox"``, 1x2) behind it.
    """
    empty_clients: set[WebSocket] = set()
    monkeypatch.setattr(
        kiosk_main, "TAPD_CONTROL_URI", live_control_plane_with_plates.url
    )
    monkeypatch.setattr(kiosk_main, "_current_run", kiosk_main.RunStatus(status="idle"))
    monkeypatch.setattr(kiosk_main, "_current_breakpoint", None)
    monkeypatch.setattr(kiosk_main, "_config_locked", False)
    monkeypatch.setattr(kiosk_main, "_homing_invalidated", False)
    monkeypatch.setattr(
        kiosk_main, "_current_toolhead", {"position": None, "homed_axes": None}
    )
    monkeypatch.setattr(kiosk_main, "_ws_clients", empty_clients)

    with TestClient(kiosk_main.app) as client:
        yield client

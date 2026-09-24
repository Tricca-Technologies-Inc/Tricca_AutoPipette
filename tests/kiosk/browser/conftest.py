"""Fixtures for real-browser kiosk tests (ADR-0003).

`pytest-playwright` (the `browser-test` install extra) supplies `page`/
`browser`/`context`. This module supplies the other half: a real, running
kiosk HTTP server for `page` to point at, since `fastapi.testclient
.TestClient` -- what `tests/kiosk/conftest.py`'s `kiosk_client` fixture uses
-- is an in-process ASGI transport with no real socket a browser can dial.

Files under this directory don't import `playwright` at module scope unless
guarded by `pytest.importorskip("playwright")` -- that's what lets `pytest`
skip them cleanly (not error) in a `dev`-only checkout that never installed
`browser-test`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fakes.fake_websocket_client import FakeWebSocketClient
from fastapi import WebSocket
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer

from autopipette_kiosk import main as kiosk_main


def _start_live_kiosk(
    live_control_plane: LiveControlPlane, monkeypatch: pytest.MonkeyPatch
) -> Iterator[LiveKioskServer]:
    """Point the kiosk app at `live_control_plane` and serve it for real.

    Same module-global reset `tests/kiosk/conftest.py`'s `kiosk_client`
    fixture does -- `autopipette_kiosk/main.py` keeps run/breakpoint/
    ws-client state as module globals (a long-lived singleton in
    production), so tests sharing that module need it reset per test.

    Yields:
        The started `LiveKioskServer`, stopped after the test.
    """
    empty_clients: set[WebSocket] = set()
    monkeypatch.setattr(kiosk_main, "TAPD_CONTROL_URI", live_control_plane.url)
    monkeypatch.setattr(kiosk_main, "_current_run", kiosk_main.RunStatus(status="idle"))
    monkeypatch.setattr(kiosk_main, "_current_breakpoint", None)
    monkeypatch.setattr(
        kiosk_main, "_current_toolhead", {"position": None, "homed_axes": None}
    )
    monkeypatch.setattr(kiosk_main, "_ws_clients", empty_clients)

    server = LiveKioskServer(kiosk_main.app)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def live_kiosk_server(
    live_control_plane: LiveControlPlane, monkeypatch: pytest.MonkeyPatch
) -> Iterator[LiveKioskServer]:
    """A real, running kiosk HTTP server backed by a plain `live_control_plane`.

    Yields:
        The started `LiveKioskServer`, stopped after the test.
    """
    yield from _start_live_kiosk(live_control_plane, monkeypatch)


@pytest.fixture
def live_kiosk_server_with_plates(
    live_control_plane_with_plates: LiveControlPlane, monkeypatch: pytest.MonkeyPatch
) -> Iterator[LiveKioskServer]:
    """A `live_kiosk_server` whose backend has a tipbox/waste/plate wired up.

    Yields:
        The started `LiveKioskServer`, stopped after the test.
    """
    yield from _start_live_kiosk(live_control_plane_with_plates, monkeypatch)


@pytest.fixture
def live_kiosk_server_with_moonraker(
    live_control_plane: LiveControlPlane, monkeypatch: pytest.MonkeyPatch
) -> Iterator[LiveKioskServer]:
    """A `live_kiosk_server` whose daemon has a (fake) Moonraker connection.

    For the Move page's live toolhead-relay browser tests (issue #86) --
    see `tests/kiosk/conftest.py`'s `kiosk_client_with_moonraker` for why
    this is needed (a real Moonraker connection is what makes the daemon's
    `ws.subscribe("notify_status_update")` succeed).

    Yields:
        The started `LiveKioskServer`, with `live_control_plane.service
        .client` set to a `FakeWebSocketClient` the test can drive
        directly, stopped after the test.
    """
    live_control_plane.service.client = FakeWebSocketClient(connected=True)  # type: ignore[assignment]
    yield from _start_live_kiosk(live_control_plane, monkeypatch)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register options for `capture_screenshot.py`'s opt-in capture tool.

    Not consumed by any collected test -- `capture_screenshot.py` only runs
    when explicitly named on the command line (its filename doesn't match
    pytest's default `test_*.py` collection glob), and reads these itself.
    """
    parser.addoption(
        "--capture-page",
        default=None,
        help="Kiosk page/state to screenshot (see capture_screenshot.py's PAGES).",
    )
    parser.addoption(
        "--capture-out",
        default="kiosk_screenshot.png",
        help="Output PNG path for --capture-page.",
    )

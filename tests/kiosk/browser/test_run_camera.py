"""Real-browser coverage of the Run tab's deck camera panel (issue #242).

The daemon looks the camera up in Moonraker's `server.webcams.list`, so
these tests answer that one request on the fake Moonraker client. The
stream URL points at a closed local port: the browser's load fails fast,
and only the `src` attribute is under test.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

pytest.importorskip("playwright")

from fakes.fake_websocket_client import FakeWebSocketClient
from playwright.sync_api import Page, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer

STREAM = "http://127.0.0.1:9/webcam/?action=stream"
FULLSCREEN = re.compile(r"\bfullscreen\b")


@pytest.fixture
def camera(live_control_plane: LiveControlPlane) -> None:
    """Answer every `server.webcams.list` with one enabled webcam."""
    client = live_control_plane.service.client
    assert isinstance(client, FakeWebSocketClient)
    send = client.send_jsonrpc

    def send_jsonrpc(payload: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
        if payload.get("method") == "server.webcams.list":
            cam = {"name": "deck", "enabled": True, "stream_url": STREAM}
            return {"result": {"webcams": [cam]}}
        return send(payload, timeout)

    client.send_jsonrpc = send_jsonrpc  # type: ignore[method-assign]


def test_panel_is_hidden_without_a_camera(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    page.goto(live_kiosk_server.url)

    expect(page.locator("#cameraPanel")).to_be_hidden()


def test_panel_shows_the_stream_with_a_camera(
    page: Page, live_kiosk_server_with_moonraker: LiveKioskServer, camera: None
) -> None:
    page.goto(live_kiosk_server_with_moonraker.url)

    expect(page.locator("#cameraPanel")).to_be_visible()
    expect(page.locator("#cameraImg")).to_have_attribute("src", STREAM)


def test_stream_stops_on_another_tab_and_resumes_on_return(
    page: Page, live_kiosk_server_with_moonraker: LiveKioskServer, camera: None
) -> None:
    page.goto(live_kiosk_server_with_moonraker.url)
    expect(page.locator("#cameraImg")).to_have_attribute("src", STREAM)

    page.click('.tab-btn[data-page="move"]')
    expect(page.locator("#cameraImg")).not_to_have_attribute("src", STREAM)

    page.click('.tab-btn[data-page="run"]')
    expect(page.locator("#cameraImg")).to_have_attribute("src", STREAM)


def test_tapping_the_panel_toggles_full_screen(
    page: Page, live_kiosk_server_with_moonraker: LiveKioskServer, camera: None
) -> None:
    page.goto(live_kiosk_server_with_moonraker.url)
    panel = page.locator("#cameraPanel")

    panel.click()
    expect(panel).to_have_class(FULLSCREEN)

    panel.click()
    expect(panel).not_to_have_class(FULLSCREEN)

"""Real-browser coverage of the Move page's plate jog column (issue #215).

The `/plate_move`/`/plates_in`/`/plates` routes' status mapping is covered at
the HTTP level in `tests/kiosk/test_move.py`; this file proves the selector,
the arrow signs, the refusal message, the hidden column and the live readout.
"""

from __future__ import annotations

import re
from typing import Any, cast

import pytest

pytest.importorskip("playwright")

from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient
from playwright.sync_api import Page, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer

from tricca_autopipette.daemon.moonraker_state import AxisConfig, PlateAxis

ACTIVE = re.compile(r"\bactive\b")

PLATE_AXES = AxisConfig(
    plates=(
        PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),
        PlateAxis("plate2", "V", 0.0, 350.0, (0.0, 350.0)),
    ),
    z_safe=0.0,
    park_tol=0.1,
)


def _with_plates(plane: LiveControlPlane, *, homed: bool = True) -> FakeMoonrakerState:
    fake = plane.service.moonraker_state
    assert isinstance(fake, FakeMoonrakerState)
    fake.axis_config = PLATE_AXES  # type: ignore[misc]
    fake.set_homed(homed)
    fake.homed_plates = {"plate1", "plate2"} if homed else set()
    fake.positions = {"U": 100.0, "V": 200.0, "Z": 0.0}
    return fake


def _open_move(page: Page, server: LiveKioskServer) -> None:
    page.goto(server.url)
    page.click('.tab-btn[data-page="move"]')


def test_column_hidden_without_plates(
    page: Page, live_kiosk_server: LiveKioskServer
) -> None:
    _open_move(page, live_kiosk_server)

    expect(page.locator(".dpad-z")).to_be_visible()
    expect(page.locator("#movePlateCol")).to_have_count(1)
    expect(page.locator("#movePlateCol")).to_be_hidden()


def test_selector_lists_plates_and_remembers_the_choice(
    page: Page, live_kiosk_server: LiveKioskServer, live_control_plane: LiveControlPlane
) -> None:
    _with_plates(live_control_plane)
    _open_move(page, live_kiosk_server)

    buttons = page.locator("#plateSelector .plate-sel-btn")
    expect(buttons).to_have_text(["plate1", "plate2"])
    expect(buttons.nth(0)).to_have_class(ACTIVE)

    buttons.nth(1).click()
    expect(buttons.nth(1)).to_have_class(ACTIVE)
    expect(buttons.nth(0)).not_to_have_class(ACTIVE)

    _open_move(page, live_kiosk_server)
    expect(page.locator('.plate-sel-btn[data-plate="plate2"]')).to_have_class(ACTIVE)


@pytest.mark.parametrize(("button", "sign"), [(".plate-in", -1), (".plate-out", 1)])
def test_top_arrow_jogs_in_and_bottom_out_by_the_shared_step(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
    button: str,
    sign: int,
) -> None:
    _with_plates(live_control_plane)
    _open_move(page, live_kiosk_server)
    page.click('.plate-sel-btn[data-plate="plate2"]')
    page.click('.step-btn[data-step="10"]')

    with page.expect_request("**/plate_move") as request:
        page.click(button)

    body = cast("dict[str, Any]", request.value.post_data_json)
    assert body == {"plate": "plate2", "target": str(10 * sign), "rel": True}
    expect(page.locator("#moveJogFeedback")).to_contain_text(
        "190" if sign < 0 else "210"
    )


def test_a_refused_jog_shows_the_daemons_reason(
    page: Page, live_kiosk_server: LiveKioskServer, live_control_plane: LiveControlPlane
) -> None:
    _with_plates(live_control_plane, homed=False)
    _open_move(page, live_kiosk_server)

    page.click(".plate-in")

    feedback = page.locator("#moveJogFeedback")
    expect(feedback).to_have_class(re.compile(r"\berror\b"))
    expect(feedback).to_contain_text(re.compile(r"not homed", re.I))


def test_plates_in_button(
    page: Page, live_kiosk_server: LiveKioskServer, live_control_plane: LiveControlPlane
) -> None:
    _with_plates(live_control_plane)
    _open_move(page, live_kiosk_server)

    with page.expect_request("**/plates_in"):
        page.click("#platesInBtn")

    expect(page.locator("#moveJogFeedback")).to_contain_text("every plate in")


def test_readout_shows_the_stop_and_follows_the_status_push(
    page: Page,
    live_kiosk_server_with_moonraker: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    client = live_control_plane.service.client
    assert isinstance(client, FakeWebSocketClient)
    _with_plates(live_control_plane).positions["U"] = 350.0
    _open_move(page, live_kiosk_server_with_moonraker)

    # From /plates, before any push.
    expect(page.locator("#plateStopLive")).to_have_text("out")
    expect(page.locator("#platePosLive")).to_have_text("350.00")

    client.trigger_notification(
        "notify_status_update",
        [
            {
                "gcode_move": {
                    "position": [0.0, 0.0, 0.0, 0.0, 42.5],
                    "axis_map": {"X": 0, "Y": 1, "Z": 2, "E": 3, "U": 4},
                },
                "gcode_macro _PLATE_STATE": {"plate1": False},
            },
            1.0,
        ],
    )

    expect(page.locator("#platePosLive")).to_have_text("42.50")
    expect(page.locator("#plateHomedLive")).to_have_text("Not homed")

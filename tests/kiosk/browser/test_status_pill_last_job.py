"""Real-browser coverage of a failed immediate job on the header pill.

A Home (or any command outside a protocol) that Klipper cancels or errors
rides ``notify_run_status`` as ``last_job`` (issue #187); the pill shows
Klipper's message as an error.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer


def _push_last_job(plane: LiveControlPlane, state: str, message: str) -> None:
    plane.service._last_job = {
        "filename": "home_all.gcode",
        "state": state,
        "message": message,
    }
    plane.service._broadcast_status()


def test_a_failed_home_shows_klippers_message(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    page.goto(live_kiosk_server.url)
    expect(page.locator("#statusPillLabel")).to_have_text("Idle")

    _push_last_job(
        live_control_plane, "cancelled", "Endstop z3 still triggered after retract"
    )

    expect(page.locator("#statusPillLabel")).to_have_text(
        "Endstop z3 still triggered after retract"
    )
    expect(page.locator("#statusPill")).to_have_class(re.compile(r"\berror\b"))


def test_a_completed_job_leaves_the_pill_alone(
    page: Page,
    live_kiosk_server: LiveKioskServer,
    live_control_plane: LiveControlPlane,
) -> None:
    page.goto(live_kiosk_server.url)

    _push_last_job(live_control_plane, "cancelled", "Endstop z3 still triggered")
    expect(page.locator("#statusPill")).to_have_class(re.compile(r"\berror\b"))
    _push_last_job(live_control_plane, "completed", "")

    expect(page.locator("#statusPillLabel")).to_have_text("Idle")
    expect(page.locator("#statusPill")).to_have_class(re.compile(r"\bidle\b"))

"""Real-browser coverage of `run.js`: protocol list/selection, and the
run-status pipeline it shares with `app.js`'s status pill (ADR-0003 /
issue #78).

The run test below is the other named gap from issue #78 beyond `tips.js`'s
toggle math: "the client-side WebSocket message handling." It drives a real
`/run` POST through the real daemon and checks the real `notify_run_status`
push lands on *both* app.js's shared pill and run.js's own status card --
proof the two independently-subscribed listeners (`App.onStatus`) both
actually receive it, not just one. It stops at "running": nothing in this
fake-Moonraker-backed test setup ever fires a print-completion event (see
`tests/fakes/fake_moonraker_state.py`), so a "done" transition isn't
reachable here yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fakes.fake_websocket_client import FakeWebSocketClient

pytest.importorskip("playwright")

from playwright.sync_api import Page, Route, expect
from support.live_control_plane import LiveControlPlane
from support.live_kiosk_server import LiveKioskServer
from support.polling import poll_until


def test_empty_protocol_list_shows_a_placeholder(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    del protocols_dir  # exists (redirected), just empty
    page.goto(live_kiosk_server.url)

    expect(page.locator("#protocolList")).to_contain_text("No .pipette files found")


def test_new_page_does_not_use_a_stale_unversioned_app_script(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text("wait 1\n")

    def stale_script(route: Route) -> None:
        if "?" not in route.request.url:
            route.fulfill(
                content_type="application/javascript",
                body=(
                    "const App = {onStatus: f => f({status:'idle'}), "
                    "describeStatus: () => ({}), isRunActive: () => false};"
                ),
            )
        else:
            route.continue_()

    page.route("**/static/app.js*", stale_script)
    page.goto(live_kiosk_server.url)
    expect(page.locator(".protocol-item")).to_have_count(1)


def test_protocol_loading_error_is_visible(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    del protocols_dir
    page.route("**/protocols", lambda route: route.fulfill(status=500))
    page.goto(live_kiosk_server.url)
    expect(page.locator("#protocolList")).to_contain_text("Failed to load protocols")


def test_selecting_a_protocol_enables_run_and_shows_its_name(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
    page.goto(live_kiosk_server.url)
    expect(page.locator(".protocol-item")).to_have_count(1)

    page.click(".protocol-item")

    expect(page.locator("#selectionName")).to_have_text("a")
    expect(page.locator("#runBtn")).to_be_enabled()
    expect(page.locator("#runBtn")).to_have_text("Run protocol")


def test_folder_navigation_selects_and_checks_nested_protocol(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    nested = protocols_dir / "examples" / "transfers"
    nested.mkdir(parents=True)
    (nested / "a.pipette").write_text("wait 1\n")
    (protocols_dir / "a.pipette").write_text("wait 1\n")
    page.goto(live_kiosk_server.url)

    page.get_by_role("button", name="examples /").click()
    page.get_by_role("button", name="transfers /").click()
    page.locator(".protocol-item").click()
    expect(page.locator("#selectionName")).to_have_text("examples/transfers/a")
    page.click("#checkBtn")
    expect(page.locator("#findingsList")).to_contain_text("No issues found")
    page.get_by_role("button", name="← Back").click()
    page.get_by_role("button", name="← Back").click()
    expect(page.locator(".protocol-item")).to_have_count(1)


def test_protocol_names_are_rendered_as_text(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "quote's <test>.pipette").write_text("wait 1\n")
    page.goto(live_kiosk_server.url)

    page.locator(".protocol-item").click()
    expect(page.locator("#selectionName")).to_have_text("quote's <test>")
    page.click("#checkBtn")
    expect(page.locator("#findingsList")).to_contain_text("No issues found")


def test_legacy_folder_warns_that_protocols_are_unverified(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "legacy").mkdir()
    (protocols_dir / "legacy" / "a.pipette").write_text("wait 1\n")
    page.goto(live_kiosk_server.url)

    page.get_by_role("button", name="legacy /").click()

    expect(page.locator(".protocol-legacy-warning")).to_contain_text(
        "unverified on hardware"
    )


def test_running_a_protocol_updates_the_shared_pill_and_the_run_page_card(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text("break\n")
    page.goto(live_kiosk_server.url)
    page.click(".protocol-item")

    try:
        page.click("#runBtn")
        expect(page.locator("#statusPillLabel")).to_have_text("Running")
        expect(page.locator("#statusState")).to_have_text("Running")
        expect(page.locator("#runBtn")).to_be_disabled()
        expect(page.locator("#runBtn")).to_have_text("Pause")
        expect(page.locator("#bpAbortBtn")).to_be_visible()
    finally:
        page.click("#bpAbortBtn")


def test_cancel_can_abort_a_protocol_at_a_breakpoint(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text("break\n")
    page.goto(live_kiosk_server.url)
    page.click(".protocol-item")
    page.click("#runBtn")
    expect(page.locator("#bpAbortBtn")).to_be_visible()
    expect(page.locator("#cancelBtn")).to_be_enabled()
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#cancelBtn")
    expect(page.locator("#statusMsg")).to_contain_text("canceled")
    expect(page.locator("#bpAbortBtn")).to_be_hidden()


def test_run_controls_and_estimated_progress(
    page: Page,
    live_kiosk_server_with_moonraker: LiveKioskServer,
    live_control_plane: LiveControlPlane,
    protocols_dir: Path,
) -> None:
    class JobClient(FakeWebSocketClient):
        def __init__(self) -> None:
            super().__init__()
            self.job: dict[str, Any] = {}

        def send_jsonrpc(
            self, payload: dict[str, Any], timeout: float = 5.0
        ) -> dict[str, Any]:
            if payload["method"] == "printer.objects.query":
                if not self.is_connected():
                    raise RuntimeError("Disconnected")
                return {"result": {"status": self.job}}
            return super().send_jsonrpc(payload, timeout)

    fake = JobClient()
    live_control_plane.service.client = fake  # type: ignore[assignment]
    (protocols_dir / "a.pipette").write_text('gcode_print "hi"\n')
    page.goto(live_kiosk_server_with_moonraker.url)
    page.click(".protocol-item")
    page.click("#runBtn")
    assert poll_until(lambda: bool(fake.uploaded_files))
    name = fake.uploaded_files[0][0]
    fake.job = {
        "print_stats": {"filename": name, "state": "printing"},
        "virtual_sdcard": {"progress": 0.41},
    }
    expect(page.locator("#progressLabel")).to_have_text(
        "Estimated G-code file progress: 41%"
    )
    expect(page.locator("#runBtn")).to_have_text("Pause")
    expect(page.locator("#runBtn")).to_be_enabled()
    fake.set_connected(False)
    expect(page.locator("#progressLabel")).to_have_text("Progress unavailable")
    expect(page.locator("#runBtn")).to_be_disabled()
    expect(page.locator("#cancelBtn")).to_be_disabled()
    fake.set_connected(True)
    expect(page.locator("#runBtn")).to_be_enabled()
    page.click("#runBtn")
    expect(page.locator("#runControlFeedback")).to_contain_text(
        "waiting for confirmation"
    )
    expect(page.locator("#runBtn")).to_be_disabled()
    expect(page.locator("#runBtn")).to_have_text("Pause")
    fake.job = {
        "print_stats": {"filename": name, "state": "paused"},
        "virtual_sdcard": {"progress": 0.41},
    }
    expect(page.locator("#statusState")).to_have_text("Paused")
    expect(page.locator("#runBtn")).to_have_text("Resume")
    expect(page.locator("#runBtn")).to_be_enabled()
    page.click("#runBtn")
    expect(page.locator("#runControlFeedback")).to_contain_text(
        "waiting for confirmation"
    )
    expect(page.locator("#runBtn")).to_be_disabled()
    expect(page.locator("#runBtn")).to_have_text("Resume")
    fake.job = {
        "print_stats": {"filename": name, "state": "printing"},
        "virtual_sdcard": {"progress": 0.5},
    }
    expect(page.locator("#runBtn")).to_have_text("Pause")
    expect(page.locator("#runBtn")).to_be_enabled()
    page.once("dialog", lambda dialog: dialog.accept())
    page.click("#cancelBtn")
    expect(page.locator("#runControlFeedback")).to_contain_text(
        "waiting for confirmation"
    )
    fake.job = {"print_stats": {"filename": name, "state": "cancelled"}}
    expect(page.locator("#statusState")).to_have_text("Error")
    expect(page.locator("#cancelBtn")).to_be_disabled()
    expect(page.locator("#runBtn")).to_have_text("Run protocol")
    expect(page.locator("#runBtn")).to_be_enabled()


def test_a_failed_run_shows_the_error_label_and_icon_on_both_widgets(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    # `next_tip` is a homed-gated command (see `require_homed` in
    # daemon/service.py); this fixture's fake Moonraker state starts
    # unhomed, so it raises `NotHomedError` synchronously and the daemon
    # reports the run as "error" without needing a real print-completion
    # event -- the one non-"running" status this fake-backed setup can
    # reach (see this file's module docstring).
    (protocols_dir / "a.pipette").write_text("next_tip\n")
    page.goto(live_kiosk_server.url)
    page.click(".protocol-item")

    page.click("#runBtn")

    expect(page.locator("#statusPillLabel")).to_have_text("Error")
    expect(page.locator("#statusState")).to_have_text("Error")
    expect(page.locator("#statusIcon")).to_have_text("✕")


def test_rejected_run_shows_feedback_without_replacing_current_status(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text("wait 1\n")
    page.route("**/run", lambda route: route.fulfill(
        status=409, json={"detail": "Another run is active"}
    ))
    page.goto(live_kiosk_server.url)
    page.click(".protocol-item")
    page.click("#runBtn")

    expect(page.locator("#runControlFeedback")).to_have_text(
        "Run failed: Another run is active"
    )
    expect(page.locator("#statusState")).to_have_text("Idle")


def test_check_button_reports_no_issues_for_a_clean_protocol(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    (protocols_dir / "a.pipette").write_text("wait 1\n")
    page.goto(live_kiosk_server.url)
    page.click(".protocol-item")

    page.click("#checkBtn")

    expect(page.locator("#findingsList")).to_contain_text("No issues found")


def test_check_button_lists_findings_without_disabling_run(
    page: Page, live_kiosk_server: LiveKioskServer, protocols_dir: Path
) -> None:
    # move_loc references an undefined location -- run.validate reports it
    # as an "error"-severity finding (see test_control_server_run_validate.py)
    # but never touches the machine, so it works on this fixture's unhomed
    # fake Moonraker state.
    (protocols_dir / "a.pipette").write_text("move_loc missing\n")
    page.goto(live_kiosk_server.url)
    page.click(".protocol-item")

    page.click("#checkBtn")

    finding = page.locator(".finding-item.error")
    expect(finding).to_be_visible()
    expect(finding).to_contain_text("error")
    # Warn-only (issue #88): Check never disables/blocks Run, regardless of
    # what it finds.
    expect(page.locator("#runBtn")).to_be_enabled()

"""Unit tests for ``MoonrakerRequests``.

Pure builder tests -- no transport, no fakes -- exercising each JSON-RPC
request builder directly and asserting the exact ``method``/``params``
shape it produces, the same thing
``tests/daemon/test_control_server_dispatch_completeness.py`` already does
for ``daemon/control_requests.py``'s ``ControlRequests`` (the control-plane
sibling of this module). See issue #43.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tricca_autopipette.moonraker.moonraker_requests import MoonrakerRequests

# Sentinel: this builder takes no params, so "params" must be entirely
# absent from the generated request (not merely `{}`) -- `gen_request`
# only adds the key when `params is not None`.
NO_PARAMS = object()

# Every public builder on `MoonrakerRequests`, paired with a representative
# call and the exact `method`/`params` it must produce. `test_covers_every_
# public_builder` below asserts this table's names match `dir(MoonrakerRequests)`
# exactly, so a future builder added without a row here is caught immediately.
_BUILDER_CALLS: list[
    tuple[str, Callable[[MoonrakerRequests], dict[str, Any]], str, Any]
] = [
    # ---- Server Administration ----
    ("server_info", lambda r: r.server_info(), "server.info", NO_PARAMS),
    ("server_config", lambda r: r.server_config(), "server.config", NO_PARAMS),
    (
        "server_temperature_store",
        lambda r: r.server_temperature_store(include_monitors=True),
        "server.temperature_store",
        {"include_monitors": True},
    ),
    (
        "server_gcode_store",
        lambda r: r.server_gcode_store(count=25),
        "server.gcode_store",
        {"count": 25},
    ),
    (
        "server_logs_rollover",
        lambda r: r.server_logs_rollover(application="klipper"),
        "server.logs.rollover",
        {"application": "klipper"},
    ),
    ("server_restart", lambda r: r.server_restart(), "server.restart", NO_PARAMS),
    (
        "server_websocket_id",
        lambda r: r.server_websocket_id(),
        "server.websocket.id",
        NO_PARAMS,
    ),
    # ---- Printer Administration ----
    ("printer_info", lambda r: r.printer_info(), "printer.info", NO_PARAMS),
    (
        "printer_emergency_stop",
        lambda r: r.printer_emergency_stop(),
        "printer.emergency_stop",
        NO_PARAMS,
    ),
    (
        "printer_restart",
        lambda r: r.printer_restart(),
        "printer.restart",
        NO_PARAMS,
    ),
    # ---- Printer Status ----
    (
        "printer_objects_list",
        lambda r: r.printer_objects_list(),
        "printer.objects.list",
        NO_PARAMS,
    ),
    (
        "printer_objects_query",
        lambda r: r.printer_objects_query({"toolhead": ["position"]}),
        "printer.objects.query",
        {"objects": {"toolhead": ["position"]}},
    ),
    (
        "printer_query_endstops_status",
        lambda r: r.printer_query_endstops_status(),
        "printer.query_endstops.status",
        NO_PARAMS,
    ),
    # ---- G-code API ----
    (
        "printer_gcode_script",
        lambda r: r.printer_gcode_script("G28"),
        "printer.gcode.script",
        {"script": "G28"},
    ),
    (
        "printer_gcode_help",
        lambda r: r.printer_gcode_help(),
        "printer.gcode.help",
        NO_PARAMS,
    ),
    # ---- Print Management ----
    (
        "printer_print_start",
        lambda r: r.printer_print_start("protocol.gcode"),
        "printer.print.start",
        {"filename": "protocol.gcode"},
    ),
    (
        "printer_print_pause",
        lambda r: r.printer_print_pause(),
        "printer.print.pause",
        NO_PARAMS,
    ),
    (
        "printer_print_resume",
        lambda r: r.printer_print_resume(),
        "printer.print.resume",
        NO_PARAMS,
    ),
    (
        "printer_print_cancel",
        lambda r: r.printer_print_cancel(),
        "printer.print.cancel",
        NO_PARAMS,
    ),
    # ---- Machine Requests ----
    (
        "machine_system_info",
        lambda r: r.machine_system_info(),
        "machine.system_info",
        NO_PARAMS,
    ),
    (
        "machine_shutdown",
        lambda r: r.machine_shutdown(),
        "machine.shutdown",
        NO_PARAMS,
    ),
    ("machine_reboot", lambda r: r.machine_reboot(), "machine.reboot", NO_PARAMS),
    (
        "machine_services_restart",
        lambda r: r.machine_services_restart("klipper"),
        "machine.services.restart",
        {"service": "klipper"},
    ),
    (
        "machine_services_stop",
        lambda r: r.machine_services_stop("klipper"),
        "machine.services.stop",
        {"service": "klipper"},
    ),
    (
        "machine_proc_stats",
        lambda r: r.machine_proc_stats(),
        "machine.proc_stats",
        NO_PARAMS,
    ),
    (
        "machine_sudo_info",
        lambda r: r.machine_sudo_info(check_access=True),
        "machine.sudo.info",
        {"check_access": True},
    ),
    (
        "machine_sudo_password",
        lambda r: r.machine_sudo_password("hunter2"),
        "machine.sudo.password",
        {"password": "hunter2"},
    ),
    (
        "machine_peripherals_usb",
        lambda r: r.machine_peripherals_usb(),
        "machine.peripherals.usb",
        NO_PARAMS,
    ),
    (
        "machine_peripherals_serial",
        lambda r: r.machine_peripherals_serial(),
        "machine.peripherals.serial",
        NO_PARAMS,
    ),
    (
        "machine_peripherals_video",
        lambda r: r.machine_peripherals_video(),
        "machine.peripherals.video",
        NO_PARAMS,
    ),
    (
        "machine_peripherals_canbus",
        lambda r: r.machine_peripherals_canbus(interface="can1"),
        "machine.peripherals.canbus",
        {"interface": "can1"},
    ),
    # ---- File Operations ----
    (
        "server_files_roots",
        lambda r: r.server_files_roots(),
        "server.files.roots",
        NO_PARAMS,
    ),
    (
        "server_files_metadata",
        lambda r: r.server_files_metadata("a.gcode"),
        "server.files.metadata",
        {"filename": "a.gcode"},
    ),
    (
        "server_files_metascan",
        lambda r: r.server_files_metascan("a.gcode"),
        "server.files.metascan",
        {"filename": "a.gcode"},
    ),
    (
        "server_files_thumbnails",
        lambda r: r.server_files_thumbnails("a.gcode"),
        "server.files.thumbnails",
        {"filename": "a.gcode"},
    ),
    (
        "server_files_get_directory",
        lambda r: r.server_files_get_directory("gcodes", extended=False),
        "server.files.get_directory",
        {"path": "gcodes", "extended": False},
    ),
    (
        "server_files_post_directory",
        lambda r: r.server_files_post_directory("gcodes/new"),
        "server.files.post_directory",
        {"path": "gcodes/new"},
    ),
    (
        "server_files_delete_directory",
        lambda r: r.server_files_delete_directory("gcodes/old", force=True),
        "server.files.delete_directory",
        {"path": "gcodes/old", "force": True},
    ),
    (
        "server_files_move",
        lambda r: r.server_files_move("a.gcode", "b.gcode"),
        "server.files.move",
        {"source": "a.gcode", "dest": "b.gcode"},
    ),
    (
        "server_files_copy",
        lambda r: r.server_files_copy("a.gcode", "b.gcode"),
        "server.files.copy",
        {"source": "a.gcode", "dest": "b.gcode"},
    ),
    (
        "server_files_zip",
        lambda r: r.server_files_zip(
            "out.zip", ["a.gcode", "b.gcode"], store_only=True
        ),
        "server.files.zip",
        {"dest": "out.zip", "items": ["a.gcode", "b.gcode"], "store_only": True},
    ),
    (
        "server_files_delete",
        lambda r: r.server_files_delete("a.gcode"),
        "server.files.delete_file",
        {"path": "a.gcode"},
    ),
    # ---- Authorization ----
    (
        "access_login",
        lambda r: r.access_login("alice", "hunter2"),
        "access.login",
        {"username": "alice", "password": "hunter2", "source": "moonraker"},
    ),
    (
        "access_logout",
        lambda r: r.access_logout(),
        "access.logout",
        NO_PARAMS,
    ),
    (
        "access_get_user",
        lambda r: r.access_get_user(),
        "access.get_user",
        NO_PARAMS,
    ),
    (
        "access_post_user",
        lambda r: r.access_post_user("alice", "hunter2"),
        "access.post_user",
        {"username": "alice", "password": "hunter2"},
    ),
    (
        "access_delete_user",
        lambda r: r.access_delete_user("alice"),
        "access.delete_user",
        {"username": "alice"},
    ),
    (
        "access_users_list",
        lambda r: r.access_users_list(),
        "access.users.list",
        NO_PARAMS,
    ),
    (
        "access_user_password",
        lambda r: r.access_user_password("old", "new"),
        "access.user.password",
        {"password": "old", "new_password": "new"},
    ),
    (
        "access_refresh_jwt",
        lambda r: r.access_refresh_jwt("refresh-token"),
        "access.refresh_jwt",
        {"refresh_token": "refresh-token"},
    ),
    (
        "access_oneshot_token",
        lambda r: r.access_oneshot_token(),
        "access.oneshot_token",
        NO_PARAMS,
    ),
    ("access_info", lambda r: r.access_info(), "access.info", NO_PARAMS),
    (
        "access_get_api_key",
        lambda r: r.access_get_api_key(),
        "access.get_api_key",
        NO_PARAMS,
    ),
    (
        "access_post_api_key",
        lambda r: r.access_post_api_key(),
        "access.post_api_key",
        NO_PARAMS,
    ),
    # ---- Database APIs ----
    (
        "server_database_list",
        lambda r: r.server_database_list(),
        "server.database.list",
        NO_PARAMS,
    ),
    (
        "server_database_get_item",
        lambda r: r.server_database_get_item("ns", "key"),
        "server.database.get_item",
        {"namespace": "ns", "key": "key"},
    ),
    (
        "server_database_post_item",
        lambda r: r.server_database_post_item("ns", "key", {"a": 1}),
        "server.database.post_item",
        {"namespace": "ns", "key": "key", "value": {"a": 1}},
    ),
    (
        "server_database_delete_item",
        lambda r: r.server_database_delete_item("ns", "key"),
        "server.database.delete_item",
        {"namespace": "ns", "key": "key"},
    ),
    (
        "server_database_compact",
        lambda r: r.server_database_compact(),
        "server.database.compact",
        NO_PARAMS,
    ),
    (
        "server_database_post_backup",
        lambda r: r.server_database_post_backup("backup.db"),
        "server.database.post_backup",
        {"filename": "backup.db"},
    ),
    (
        "server_database_delete_backup",
        lambda r: r.server_database_delete_backup("backup.db"),
        "server.database.delete_backup",
        {"filename": "backup.db"},
    ),
    (
        "server_database_restore",
        lambda r: r.server_database_restore("backup.db"),
        "server.database.restore",
        {"filename": "backup.db"},
    ),
    # ---- Job Queue APIs ----
    (
        "server_job_queue_status",
        lambda r: r.server_job_queue_status(),
        "server.job_queue.status",
        NO_PARAMS,
    ),
    (
        "server_job_queue_post_job",
        lambda r: r.server_job_queue_post_job(["a.gcode", "b.gcode"], reset=True),
        "server.job_queue.post_job",
        {"filenames": ["a.gcode", "b.gcode"], "reset": True},
    ),
    (
        "server_job_queue_delete_job",
        lambda r: r.server_job_queue_delete_job(["1", "2"]),
        "server.job_queue.delete_job",
        {"job_ids": ["1", "2"]},
    ),
    (
        "server_job_queue_pause",
        lambda r: r.server_job_queue_pause(),
        "server.job_queue.pause",
        NO_PARAMS,
    ),
    (
        "server_job_queue_start",
        lambda r: r.server_job_queue_start(),
        "server.job_queue.start",
        NO_PARAMS,
    ),
    (
        "server_job_queue_jump",
        lambda r: r.server_job_queue_jump("1"),
        "server.job_queue.jump",
        {"job_id": "1"},
    ),
    # ---- Announcement APIs ----
    (
        "server_announcements_list",
        lambda r: r.server_announcements_list(include_dismissed=True),
        "server.announcements.list",
        {"include_dismissed": True},
    ),
    (
        "server_announcements_update",
        lambda r: r.server_announcements_update(),
        "server.announcements.update",
        NO_PARAMS,
    ),
    (
        "server_announcements_dismiss",
        lambda r: r.server_announcements_dismiss("entry-1", wake_time=60),
        "server.announcements.dismiss",
        {"entry_id": "entry-1", "wake_time": 60},
    ),
    (
        "server_announcements_feeds",
        lambda r: r.server_announcements_feeds(),
        "server.announcements.feeds",
        NO_PARAMS,
    ),
    (
        "server_announcements_post_feed",
        lambda r: r.server_announcements_post_feed("moonraker"),
        "server.announcements.post_feed",
        {"name": "moonraker"},
    ),
    (
        "server_announcements_delete_feed",
        lambda r: r.server_announcements_delete_feed("moonraker"),
        "server.announcements.delete_feed",
        {"name": "moonraker"},
    ),
    # ---- Webcam APIs ----
    (
        "server_webcams_list",
        lambda r: r.server_webcams_list(),
        "server.webcams.list",
        NO_PARAMS,
    ),
    (
        "server_webcams_get_item",
        lambda r: r.server_webcams_get_item("cam-1"),
        "server.webcams.get_item",
        {"uid": "cam-1"},
    ),
    (
        "server_webcams_post_item",
        lambda r: r.server_webcams_post_item("cam-1", "http://snap", "http://stream"),
        "server.webcams.post_item",
        {"name": "cam-1", "snapshot_url": "http://snap", "stream_url": "http://stream"},
    ),
    (
        "server_webcams_delete_item",
        lambda r: r.server_webcams_delete_item("cam-1"),
        "server.webcams.delete_item",
        {"uid": "cam-1"},
    ),
    (
        "server_webcams_test",
        lambda r: r.server_webcams_test("cam-1"),
        "server.webcams.test",
        {"uid": "cam-1"},
    ),
    # ---- Notifier APIs ----
    (
        "server_notifiers_list",
        lambda r: r.server_notifiers_list(),
        "server.notifiers.list",
        NO_PARAMS,
    ),
    # ---- Update Manager APIs ----
    (
        "machine_update_status",
        lambda r: r.machine_update_status(refresh=True),
        "machine.update.status",
        {"refresh": True},
    ),
    (
        "machine_update_refresh",
        lambda r: r.machine_update_refresh("klipper"),
        "machine.update.refresh",
        {"name": "klipper"},
    ),
    (
        "machine_update_full",
        lambda r: r.machine_update_full(),
        "machine.update.full",
        NO_PARAMS,
    ),
    (
        "machine_update_moonraker",
        lambda r: r.machine_update_moonraker(),
        "machine.update.moonraker",
        NO_PARAMS,
    ),
    (
        "machine_update_klipper",
        lambda r: r.machine_update_klipper(),
        "machine.update.klipper",
        NO_PARAMS,
    ),
    (
        "machine_update_client",
        lambda r: r.machine_update_client("mainsail"),
        "machine.update.client",
        {"name": "mainsail"},
    ),
    (
        "machine_update_system",
        lambda r: r.machine_update_system(),
        "machine.update.system",
        NO_PARAMS,
    ),
    (
        "machine_update_recover",
        lambda r: r.machine_update_recover("klipper", hard=True),
        "machine.update.recover",
        {"name": "klipper", "hard": True},
    ),
    (
        "machine_update_rollback",
        lambda r: r.machine_update_rollback("klipper"),
        "machine.update.rollback",
        {"name": "klipper"},
    ),
    # ---- Power APIs ----
    (
        "machine_device_power_devices",
        lambda r: r.machine_device_power_devices(),
        "machine.device_power.devices",
        NO_PARAMS,
    ),
    (
        "machine_device_power_get_device",
        lambda r: r.machine_device_power_get_device("psu"),
        "machine.device_power.get_device",
        {"device": "psu"},
    ),
    (
        "machine_device_power_post_device",
        lambda r: r.machine_device_power_post_device("psu", "on"),
        "machine.device_power.post_device",
        {"device": "psu", "action": "on"},
    ),
    (
        "machine_device_power_status",
        lambda r: r.machine_device_power_status(["psu", "leds"]),
        "machine.device_power.status",
        {"psu": None, "leds": None},
    ),
    (
        "machine_device_power_on",
        lambda r: r.machine_device_power_on(["psu", "leds"]),
        "machine.device_power.on",
        {"psu": None, "leds": None},
    ),
    (
        "machine_device_power_off",
        lambda r: r.machine_device_power_off(["psu", "leds"]),
        "machine.device_power.off",
        {"psu": None, "leds": None},
    ),
    # ---- WLED APIs ----
    (
        "machine_wled_strips",
        lambda r: r.machine_wled_strips(),
        "machine.wled.strips",
        NO_PARAMS,
    ),
    (
        "machine_wled_status",
        lambda r: r.machine_wled_status(["strip1"]),
        "machine.wled.status",
        {"strip1": None},
    ),
    (
        "machine_wled_on",
        lambda r: r.machine_wled_on(["strip1"]),
        "machine.wled.on",
        {"strip1": None},
    ),
    (
        "machine_wled_off",
        lambda r: r.machine_wled_off(["strip1"]),
        "machine.wled.off",
        {"strip1": None},
    ),
    (
        "machine_wled_toggle",
        lambda r: r.machine_wled_toggle(["strip1"]),
        "machine.wled.toggle",
        {"strip1": None},
    ),
    # ---- Sensor APIs ----
    (
        "server_sensors_list",
        lambda r: r.server_sensors_list(extended=True),
        "server.sensors.list",
        {"extended": True},
    ),
    (
        "server_sensors_info",
        lambda r: r.server_sensors_info("temp0", extended=True),
        "server.sensors.info",
        {"sensor": "temp0", "extended": True},
    ),
    (
        "server_sensors_measurement",
        lambda r: r.server_sensors_measurement("temp0"),
        "server.sensors.measurements",
        {"sensor": "temp0"},
    ),
    (
        "server_sensors_measurements",
        lambda r: r.server_sensors_measurements(),
        "server.sensors.measurements",
        NO_PARAMS,
    ),
    # ---- History APIs ----
    (
        "server_history_list",
        lambda r: r.server_history_list(limit=10, start=5, order="desc"),
        "server.history.list",
        {"limit": 10, "start": 5, "order": "desc"},
    ),
    (
        "server_history_totals",
        lambda r: r.server_history_totals(),
        "server.history.totals",
        NO_PARAMS,
    ),
    (
        "server_history_reset_totals",
        lambda r: r.server_history_reset_totals(),
        "server.history.reset_totals",
        NO_PARAMS,
    ),
    (
        "server_history_get_job",
        lambda r: r.server_history_get_job("job-1"),
        "server.history.get_job",
        {"uid": "job-1"},
    ),
    (
        "server_history_delete_job",
        lambda r: r.server_history_delete_job("job-1"),
        "server.history.delete_job",
        {"uid": "job-1"},
    ),
    # ---- request_sub_to_objs / server_connection_identify get their own
    # dedicated test classes below (branching behavior worth naming
    # explicitly), but still need one row each here so the completeness
    # check passes.
    (
        "request_sub_to_objs",
        lambda r: r.request_sub_to_objs(["toolhead"]),
        "printer.objects.subscribe",
        {"objects": {"toolhead": None}},
    ),
    (
        "server_connection_identify",
        lambda r: r.server_connection_identify("tap", "1.0", "web", "http://x"),
        "server.connection.identify",
        {"client_name": "tap", "version": "1.0", "type": "web", "url": "http://x"},
    ),
    (
        "server_files_list",
        lambda r: r.server_files_list(),
        "server.files.list",
        {},
    ),
]


@pytest.fixture
def requests() -> MoonrakerRequests:
    """A fresh builder instance -- these methods are pure, but stay tidy.

    Returns:
        A fresh `MoonrakerRequests` instance.
    """
    return MoonrakerRequests()


class TestGenRequest:
    """`gen_request` is the shared envelope every other builder goes through."""

    def test_no_params_omits_params_key(self, requests: MoonrakerRequests) -> None:
        request = requests.gen_request("printer.info")

        assert "params" not in request

    def test_params_dict_is_included_verbatim(
        self, requests: MoonrakerRequests
    ) -> None:
        request = requests.gen_request("printer.gcode.script", {"script": "G28"})

        assert request["params"] == {"script": "G28"}

    def test_empty_params_dict_is_still_included(
        self, requests: MoonrakerRequests
    ) -> None:
        # `{}` is not `None`, so it must survive -- distinguishing "no
        # params" from "params, but none supplied" (server_files_list()
        # relies on exactly this).
        request = requests.gen_request("server.files.list", {})

        assert request["params"] == {}

    def test_jsonrpc_version(self, requests: MoonrakerRequests) -> None:
        assert requests.gen_request("server.info")["jsonrpc"] == "2.0"

    def test_method_is_passed_through(self, requests: MoonrakerRequests) -> None:
        assert requests.gen_request("server.info")["method"] == "server.info"

    def test_id_is_a_string(self, requests: MoonrakerRequests) -> None:
        assert isinstance(requests.gen_request("server.info")["id"], str)

    def test_id_is_unique_per_call(self, requests: MoonrakerRequests) -> None:
        ids = {requests.gen_request("server.info")["id"] for _ in range(10)}

        assert len(ids) == 10


@pytest.mark.parametrize(
    ("name", "call", "expected_method", "expected_params"),
    _BUILDER_CALLS,
    ids=[row[0] for row in _BUILDER_CALLS],
)
def test_builder_shape(
    requests: MoonrakerRequests,
    name: str,
    call: Callable[[MoonrakerRequests], dict[str, Any]],
    expected_method: str,
    expected_params: Any,
) -> None:
    """Every builder must produce its documented `method`/`params` shape."""
    request = call(requests)

    assert request["method"] == expected_method, f"{name}: wrong RPC method"
    if expected_params is NO_PARAMS:
        assert "params" not in request, f"{name}: expected no 'params' key"
    else:
        assert request["params"] == expected_params, f"{name}: wrong params shape"


def test_builder_call_table_matches_moonraker_requests_exactly() -> None:
    """`_BUILDER_CALLS` above must cover every public `MoonrakerRequests` builder.

    Mirrors `test_builder_call_table_matches_control_requests_exactly` in
    `tests/daemon/test_control_server_dispatch_completeness.py` -- a new
    builder added without a row here would otherwise sit at 0% coverage
    silently.
    """
    all_builders = {
        name
        for name in dir(MoonrakerRequests)
        if not name.startswith("_")
        and name not in ("JSON_RPC_VERSION", "SUBSCRIBABLE", "gen_request")
    }
    covered = {row[0] for row in _BUILDER_CALLS}

    missing = all_builders - covered
    stale = covered - all_builders
    assert not missing, (
        f"MoonrakerRequests builders missing from _BUILDER_CALLS: {sorted(missing)}"
    )
    assert not stale, (
        f"_BUILDER_CALLS names not found on MoonrakerRequests: {sorted(stale)} "
        "-- MoonrakerRequests must have been renamed/removed."
    )


class TestRequestSubToObjs:
    """`request_sub_to_objs` filters against `SUBSCRIBABLE` and reshapes to a dict."""

    def test_filters_out_non_subscribable_objects(
        self, requests: MoonrakerRequests
    ) -> None:
        request = requests.request_sub_to_objs([
            "toolhead",
            "not_a_real_object",
            "print_stats",
        ])

        assert request["params"]["objects"] == {"toolhead": None, "print_stats": None}

    def test_empty_list_yields_empty_objects(self, requests: MoonrakerRequests) -> None:
        request = requests.request_sub_to_objs([])

        assert request["params"]["objects"] == {}

    def test_all_non_subscribable_yields_empty_objects(
        self, requests: MoonrakerRequests
    ) -> None:
        request = requests.request_sub_to_objs(["not_real", "also_not_real"])

        assert request["params"]["objects"] == {}


class TestServerConnectionIdentify:
    """Optional `access_token`/`api_key` are omitted unless truthy."""

    def test_omits_optional_credentials_by_default(
        self, requests: MoonrakerRequests
    ) -> None:
        request = requests.server_connection_identify("tap", "1.0", "web", "http://x")

        assert "access_token" not in request["params"]
        assert "api_key" not in request["params"]

    def test_includes_optional_credentials_when_given(
        self, requests: MoonrakerRequests
    ) -> None:
        request = requests.server_connection_identify(
            "tap", "1.0", "web", "http://x", access_token="tok", api_key="key"
        )

        assert request["params"]["access_token"] == "tok"
        assert request["params"]["api_key"] == "key"

    def test_empty_string_credentials_are_falsy_and_omitted(
        self, requests: MoonrakerRequests
    ) -> None:
        # The implementation checks `if access_token:`, not `is not None`
        # -- an empty string is indistinguishable from "not given". Locking
        # this in since it's a real (if minor) footgun for a future caller.
        request = requests.server_connection_identify(
            "tap", "1.0", "web", "http://x", access_token="", api_key=""
        )

        assert "access_token" not in request["params"]
        assert "api_key" not in request["params"]


class TestServerFilesList:
    """`root` is the only optional field, added only when not `None`."""

    def test_root_omitted_by_default(self, requests: MoonrakerRequests) -> None:
        request = requests.server_files_list()

        assert request["params"] == {}

    def test_root_included_when_given(self, requests: MoonrakerRequests) -> None:
        request = requests.server_files_list("gcodes")

        assert request["params"] == {"root": "gcodes"}


class TestServerHistoryList:
    """`since`/`before` are optional filters layered onto the base params."""

    def test_since_and_before_omitted_by_default(
        self, requests: MoonrakerRequests
    ) -> None:
        request = requests.server_history_list()

        assert request["params"] == {"limit": 50, "start": 0, "order": "asc"}

    def test_since_included_when_given(self, requests: MoonrakerRequests) -> None:
        request = requests.server_history_list(since=1000.0)

        assert request["params"]["since"] == pytest.approx(1000.0)
        assert "before" not in request["params"]

    def test_before_included_when_given(self, requests: MoonrakerRequests) -> None:
        request = requests.server_history_list(before=2000.0)

        assert request["params"]["before"] == pytest.approx(2000.0)
        assert "since" not in request["params"]


class TestSensorsMeasurementMethodCollision:
    """`_measurement`/`_measurements` intentionally share one RPC method name."""

    def test_singular_targets_one_sensor(self, requests: MoonrakerRequests) -> None:
        request = requests.server_sensors_measurement("temp0")

        assert request["method"] == "server.sensors.measurements"
        assert request["params"] == {"sensor": "temp0"}

    def test_plural_has_no_params(self, requests: MoonrakerRequests) -> None:
        request = requests.server_sensors_measurements()

        assert request["method"] == "server.sensors.measurements"
        assert "params" not in request


class TestDeviceGroupHelpers:
    """`dict.fromkeys`-based builders preserve order and dedupe repeats."""

    def test_device_power_status_preserves_order(
        self, requests: MoonrakerRequests
    ) -> None:
        request = requests.machine_device_power_status(["b", "a"])

        assert list(request["params"].keys()) == ["b", "a"]

    def test_wled_status_dedupes_repeated_names(
        self, requests: MoonrakerRequests
    ) -> None:
        request = requests.machine_wled_status(["strip1", "strip1"])

        assert request["params"] == {"strip1": None}


class TestMethodRegistries:
    """`SUBSCRIBABLE` is plain data, but shouldn't silently rot."""

    def test_subscribable_list_has_no_duplicates(self) -> None:
        assert len(MoonrakerRequests.SUBSCRIBABLE) == len(
            set(MoonrakerRequests.SUBSCRIBABLE)
        )

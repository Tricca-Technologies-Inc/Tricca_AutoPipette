#!/usr/bin/env python3
"""Holds the requests for the pipette server."""


class MoonrakerRequests():
    """A data class holding all the requests for Moonraker."""

    jsonrpc: str = "2.0"
    methods: list[str] = [
        # Server
        "server.info",
        "server.config",
        "server.temperature_store",
        "server.gcode_store",
        "server.logs.rollover",
        "server.restart",
        "server.connection.identify",
        "server.websocket.id",
        # Printer Administration
        "printer.info",
        "printer.emergency_stop",
        "printer.restart",
        # Printer Status
        "printer.objects.list",
        "printer.objects.query",
        "printer.objects.subscribe",
        "printer.query_endstops.status",
        # GCode API
        "printer.gcode.script",
        "printer.gcode.help",
        # Print Management
        "printer.print.start",           # Done
        "printer.print.pause",           # Done
        "printer.print.resume",          # Done
        "printer.print.cancel",          # Done
        # Machine Requests
        "machine.system_info",
        "machine.shutdown",
        "machine.reboot",
        "machine.services.restart",
        "machine.services.stop",
        "machine.services.start",
        "machine.proc_stats",
        "machine.sudo.info",
        "machine.sudo.password",
        "machine.peripherals.usb",
        "machine.peripherals.serial",
        "machine.peripherals.video",
        "machine.peripherals.canbus",
        # File Operations
        "server.files.list",
        "server.files.roots",
        "server.files.metadata",
        "server.files.metascan",
        "server.files.thumbnails",
        "server.files.get_directory",
        "server.files.post_directory",
        "server.files.delete_directory",
        "server.files.move",
        "server.files.copy",
        "server.files.zip",
        "server.files.delete_file",
        # Authorization
        "access.login",
        "access.logout",
        "access.get_user",
        "access.post_user",
        "access.delete_user",
        "access.users.list",
        "access.user.password",
        "access.refresh_jwt",
        "access.oneshot_token",
        "access.info",
        "access.get_api_key",
        "access.post_api_key",
        # History APIs
        "server.history.list",
        "server.history.totals",
        "server.history.reset_totals",
        "server.history.get_job",
        "server.history.delete_job",
        # Database APIs
        "server.database.list",
        "server.database.get_item",
        "server.database.post_item",
        "server.database.delete_item",
        "server.database.compact",
        "server.database.post_backup",
        "server.database.delete_backup",
        "server.database.restore",
        # Job Queue APIs
        "server.job_queue.status",
        "server.job_queue.post_job",
        "server.job_queue.delete_job",
        "server.job_queue.pause",
        "server.job_queue.start",
        "server.job_queue.jump",
        # Announcement
        "server.announcements.list",
        "server.announcements.update",
        "server.announcements.dismiss",
        "server.announcements.feeds",
        "server.announcements.post_feed",
        "server.announcements.delete_feed",
        # Webcam APIs
        "server.webcams.list",
        "server.webcams.get_item",
        "server.webcams.post_item",
        "server.webcams.delete_item",
        "server.webcams.test",
        # Notifier APIs
        "server.notifiers.list",
        # Update Manager APIs
        "machine.update.status",
        "machine.update.refresh",
        "machine.update.full",
        "machine.update.moonraker",
        "machine.update.klipper",
        "machine.update.client",
        "machine.update.system",
        "machine.update.recover",
        "machine.update.rollback",
        # Power APIs
        "machine.device_power.devices",
        "machine.device_power.get_device",
        "machine.device_power.post_device",
        "machine.device_power.status",
        "machine.device_power.on",
        "machine.device_power.off",
        # WLED APIs
        "machine.wled.strips",
        "machine.wled.status",
        "machine.wled.on",
        "machine.wled.off",
        "machine.wled.toggle",
        # Sensor APIs
        "server.sensors.list",
        "server.sensors.info",
        "server.sensors.measurements",
        "server.sensors.measurements",
    ]
    id: int = 0
    subscribable: list[str] = [
        "angle"
        "bed_mesh",
        "bed_screws",
        "configfile",
        "display_status",
        "endstop_phase",
        "exclude_object",
        "extruder_stepper",
        "fan",
        "filament_switch_sensor",
        "filament_motion_sensor",
        "firmware_retraction",
        "gcode",
        "gcode_button",
        "gcode_macro",
        "gcode_move",
        "hall_filament_width_sensor",
        "heater",
        "heaters",
        "idle_timeout",
        "led",
        "manual_probe",
        "mcu",
        "motion_report",
        "output_pin",
        "palette2",
        "pause_resume",
        "print_stats",
        "probe",
        "pwm_cycle_time",
        "quad_gantry_level",
        "query_endstops",
        "screws_tilt_adjust",
        "servo",
        "stepper_enable",
        "system_stats",
        "temperature sensors",
        "temperature_fan",
        "temperature_sensor",
        "tmc drivers",
        "toolhead",
        "dual_carriage",
        "virtual_sdcard",
        "webhooks",
        "z_thermal_adjust",
        "z_tilt",
        ]

    def __init__(self):
        """Initialize the data class."""
        pass

    def gen_request(self, method: str, params: dict = None) -> dict:
        """Return a dictionary object representative of a moonraker request."""
        if params is None:
            request = {
                "jsonrpc": self.jsonrpc,
                "method": method,
                "id": self.gen_id(),
            }
        else:
            request = {
                "jsonrpc": self.jsonrpc,
                "method": method,
                "params": params,
                "id": self.gen_id(),
            }
        return request

    def gen_id(self) -> str:
        """Generate a unique id."""
        self.id += 1
        return self.id

    def request_sub_to_objs(self, objs: list[str]) -> None:
        """Create a subsciption request to monitor objects on the pipette."""
        objects = {}
        for obj in objs:
            if obj not in self.subscribable:
                continue
            objects[obj] = None
        params = {}
        params["objects"] = objects
        return self.gen_request("printer.objects.subscribe", params)

    # ------Server Administration----------------------------------------------
    request_server_info = {
        "jsonrpc": "2.0",
        "method": "server.info",
        "id": 9546
    }
    request_server_config = {
        "jsonrpc": "2.0",
        "method": "server.config",
        "id": 5616
    }
    request_temperature_store = {
        "jsonrpc": "2.0",
        "method": "server.temperature_store",
        "params": {
            "include_monitors": False
        },
        "id": 2313
    }
    request_gcode_store = {
        "jsonrpc": "2.0",
        "method": "server.gcode_store",
        "params": {
            "count": 100
        },
        "id": 7643
    }
    request_roll_over = {
        "jsonrpc": "2.0",
        "method": "server.logs.rollover",
        "params": {
            "application": "moonraker"
        },
        "id": 4656
    }
    request_restart = {
        "jsonrpc": "2.0",
        "method": "server.restart",
        "id": 4656
    }
    request_identify_connection = {
        "jsonrpc": "2.0",
        "method": "server.connection.identify",
        "params": {
            "client_name": "moontest",
            "version": "0.0.1",
            "type": "web",
            "url": "http://github.com/arksine/moontest",
            "access_token": "<base64 encoded token>",
            "api_key": "<system api key>"
        },
        "id": 4656
    }
    request_websocket_id = {
        "jsonrpc": "2.0",
        "method": "server.websocket.id",
        "id": 4656
    }

    # ------printer administration---------------------------------------------
    request_info = {
        "jsonrpc": "2.0",
        "method": "printer.info",
        "id": 5445
    }
    request_emergency_stop = {
        "jsonrpc": "2.0",
        "method": "printer.emergency_stop",
        "id": 4564
    }
    request_restart = {
        "jsonrpc": "2.0",
        "method": "printer.restart",
        "id": 4894
    }
    # ------printer status-----------------------------------------------------
    request_objs_list = {
        "jsonrpc": "2.0",
        "method": "printer.objects.list",
        "id": 1454
    }
    request_objs_query = {
        "jsonrpc": "2.0",
        "method": "printer.objects.query",
        "params": {
            "objects": {
                "gcode_move": None,
                "toolhead": ["position", "status"]
            }
        },
        "id": 4654
    }
    request_objs_sub = {
        "jsonrpc": "2.0",
        "method": "printer.objects.subscribe",
        "params": {
            "objects": {
                "gcode_move": None,
                "toolhead": ["position", "status"]
            }
        },
        "id": 5434
    }
    request_query_endstops = {
        "jsonrpc": "2.0",
        "method": "printer.query_endstops.status",
        "id": 3456
    }
    # ------gcode api----------------------------------------------------------
    request_gcode_script = {
        "jsonrpc": "2.0",
        "method": "printer.gcode.script",
        "params": {
            "script": "g28"
        },
        "id": 7466
    }
    request_gcode_help = {
        "jsonrpc": "2.0",
        "method": "printer.gcode.help",
        "id": 4645
    }
    # ------print management--------------------------------------------------
    request_print_start = {
        "jsonrpc": "2.0",
        "method": "printer.print.start",
        "params": {
            "filename": "test_pring.gcode"
        },
        "id": 4654
    }
    request_print_pause = {
        "jsonrpc": "2.0",
        "method": "printer.print.pause",
        "id": 4564
    }
    request_print_resume = {
        "jsonrpc": "2.0",
        "method": "printer.print.resume",
        "id": 1465
    }
    request_print_cancel = {
        "jsonrpc": "2.0",
        "method": "printer.print.cancel",
        "id": 2578
    }
    # ------machine requests---------------------------------------------------
    request_machine_sys_info = {
        "jsonrpc": "2.0",
        "method": "machine.system_info",
        "id": 4665
    }
    request_machine_shutdown = {
        "jsonrpc": "2.0",
        "method": "machine.shutdown",
        "id": 4665
    }
    request_machine_reboot = {
        "jsonrpc": "2.0",
        "method": "machine.reboot",
        "id": 4665
    }
    request_machine_services_restart = {
        "jsonrpc": "2.0",
        "method": "machine.services.restart",
        "params": {
            "service": "{name}"
        },
        "id": 4656
    }
    request_machine_services_stop = {
        "jsonrpc": "2.0",
        "method": "machine.services.stop",
        "params": {
            "service": "{name}"
            },
        "id": 4645
    }
    request_machine_services_start = {
        "jsonrpc": "2.0",
        "method": "machine.services.start",
        "params": {
            "service": "{name}"
        },
        "id": 4645
    }
    request_machine_proc_stats = {
        "jsonrpc": "2.0",
        "method": "machine.proc_stats",
        "id": 7896
    }
    request_sudo_info = {
        "jsonrpc": "2.0",
        "method": "machine.sudo.info",
        "params": {
            "check_access": False
        },
        "id": 7896
    }
    request_sudo_password = {
        "jsonrpc": "2.0",
        "method": "machine.sudo.password",
        "params": {
            "password": "linux_user_password"
        },
        "id": 7896
    }
    request_peripherals_usb = {
        "jsonrpc": "2.0",
        "method": "machine.peripherals.usb",
        "id": 7896
    }
    request_peripherals_serial = {
        "jsonrpc": "2.0",
        "method": "machine.peripherals.serial",
        "id": 7896
    }
    request_peripherals_video = {
        "jsonrpc": "2.0",
        "method": "machine.peripherals.video",
        "id": 7896
    }
    request_peripherals_canbus = {
        "jsonrpc": "2.0",
        "method": "machine.peripherals.canbus",
        "params": {
            "interface": "can0"
        },
        "id": 7896
    }
    # ------file operations----------------------------------------------------
    request_files_list = {
        "jsonrpc": "2.0",
        "method": "server.files.list",
        "params": {
            "root": "{root_folder}"
        },
        "id": 4644
    }
    request_files_roots = {
        "jsonrpc": "2.0",
        "method": "server.files.roots",
        "id": 4644
    }
    request_files_metadata = {
        "jsonrpc": "2.0",
        "method": "server.files.metadata",
        "params": {
            "filename": "{filename}"
        },
        "id": 3545
    }
    request_files_metascan = {
        "jsonrpc": "2.0",
        "method": "server.files.metascan",
        "params": {
            "filename": "{filename}"
        },
        "id": 3545
    }
    request_files_thumbnail = {
        "jsonrpc": "2.0",
        "method": "server.files.thumbnails",
        "params": {
            "filename": "{filename}"
        },
        "id": 3545
    }
    request_files_get_directory = {
        "jsonrpc": "2.0",
        "method": "server.files.get_directory",
        "params": {
            "path": "gcodes/my_subdir",
            "extended": True
        },
        "id": 5644
    }
    request_files_post_directory = {
        "jsonrpc": "2.0",
        "method": "server.files.post_directory",
        "params": {
            "path": "gcodes/my_new_dir"
        },
        "id": 6548
    }
    request_files_delete_directory = {
        "jsonrpc": "2.0",
        "method": "server.files.delete_directory",
        "params": {
            "path": "gcodes/my_subdir",
            "force": False
        },
        "id": 6545
    }
    request_files_move = {
        "jsonrpc": "2.0",
        "method": "server.files.move",
        "params": {
            "source": "gcodes/testdir/my_file.gcode",
            "dest": "gcodes/subdir/my_file.gcode"
        },
        "id": 5664
    }
    request_files_copy = {
        "jsonrpc": "2.0",
        "method": "server.files.copy",
        "params": {
            "source": "gcodes/my_file.gcode",
            "dest": "gcodes/subdir/my_file.gcode"
        },
        "id": 5623
    }
    request_files_zip = {
        "jsonrpc": "2.0",
        "method": "server.files.zip",
        "params": {
            "dest": "config/errorlogs.zip",
            "items": [
                "config/printer.cfg",
                "logs",
                "gcodes/subfolder"
            ],
            "store_only": False
        },
        "id": 5623
    }
    # upload / download done through http request
    request_files_delete = {
        "jsonrpc": "2.0",
        "method": "server.files.delete_file",
        "params": {
            "path": "{root}/{filename}"
        },
        "id": 1323
    }
    # ------authorization------------------------------------------------------
    request_access_login = {
        "jsonrpc": "2.0",
        "method": "access.login",
        "params": {
            "username": "my_user",
            "password": "my_password",
            "source": "moonraker"
        },
        "id": 1323
    }
    request_access_logout = {
        "jsonrpc": "2.0",
        "method": "access.logout",
        "id": 1323
    }
    request_get_user = {
        "jsonrpc": "2.0",
        "method": "access.get_user",
        "id": 1323
    }
    request_access_post_user = {
        "jsonrpc": "2.0",
        "method": "access.post_user",
        "params": {
            "username": "my_user",
            "password": "my_password"
        },
        "id": 1323
    }
    request_access_delete_user = {
        "jsonrpc": "2.0",
        "method": "access.delete_user",
        "params": {
            "username": "my_username"
        },
        "id": 1323
    }
    request_access_users_list = {
        "jsonrpc": "2.0",
        "method": "access.users.list",
        "id": 1323
    }
    request_access_user_password = {
        "jsonrpc": "2.0",
        "method": "access.user.password",
        "params": {
            "password": "my_current_password",
            "new_password": "my_new_pass"
        },
        "id": 1323
    }
    request_access_refesh_jwt = {
        "jsonrpc": "2.0",
        "method": "access.refresh_jwt",
        "params": {
            "refresh_token": "long-string-looking-thing"
        },
        "id": 1323
    }
    request_access_oneshot_token = {
        "jsonrpc": "2.0",
        "method": "access.oneshot_token",
        "id": 1323
    }
    request_access_info = {
        "jsonrpc": "2.0",
        "method": "access.info",
        "id": 1323
    }
    request_access_get_api_key = {
        "jsonrpc": "2.0",
        "method": "access.get_api_key",
        "id": 1323
    }
    request_access_post_api_key = {
        "jsonrpc": "2.0",
        "method": "access.post_api_key",
        "id": 1323
    }
    # ------database apis------------------------------------------------------
    request_database_list = {
        "jsonrpc": "2.0",
        "method": "server.database.list",
        "id": 8694
    }
    request_database_get_item = {
        "jsonrpc": "2.0",
        "method": "server.database.get_item",
        "params": {
            "namespace": "{namespace}",
            "key": "{key}"
        },
        "id": 5644
    }
    request_database_post_item = {
        "jsonrpc": "2.0",
        "method": "server.database.post_item",
        "params": {
            "namespace": "{namespace}",
            "key": "{key}",
            "value": 100
        },
        "id": 4654
    }
    request_database_delete_item = {
        "jsonrpc": "2.0",
        "method": "server.database.delete_item",
        "params": {
            "namespace": "{namespace}",
            "key": "{key}"
        },
        "id": 4654
    }
    request_database_compact = {
        "jsonrpc": "2.0",
        "method": "server.database.compact",
        "id": 4654
    }
    request_database_post_backup = {
        "jsonrpc": "2.0",
        "method": "server.database.post_backup",
        "params": {
            "filename": "sql-db-backup.db"
        },
        "id": 4654
    }
    request_database_delete_backup = {
        "jsonrpc": "2.0",
        "method": "server.database.delete_backup",
        "params": {
            "filename": "sql-db-backup.db"
        },
        "id": 4654
    }
    request_database_restore = {
        "jsonrpc": "2.0",
        "method": "server.database.restore",
        "params": {
            "filename": "sql-db-backup.db"
        },
        "id": 4654
    }
    # ------job queue apis-----------------------------------------------------
    request_job_queue_status = {
        "jsonrpc": "2.0",
        "method": "server.job_queue.status",
        "id": 4654
    }
    request_job_queue_post_job = {
        "jsonrpc": "2.0",
        "method": "server.job_queue.post_job",
        "params": {
            "filenames": [
                "job1.gcode",
                "job2.gcode",
                "subdir/job3.gcode"
            ],
            "reset": False
        },
        "id": 4654
    }
    request_job_queue_delete_job = {
        "jsonrpc": "2.0",
        "method": "server.job_queue.delete_job",
        "params": {
            "job_ids": [
                "0000000066d991f0",
                "0000000066d99d80"
            ]
        },
        "id": 4654
    }
    request_job_queue_pause = {
        "jsonrpc": "2.0",
        "method": "server.job_queue.pause",
        "id": 4654
    }
    request_job_queue_start = {
        "jsonrpc": "2.0",
        "method": "server.job_queue.start",
        "id": 4654
    }
    request_job_queue_jump = {
        "jsonrpc": "2.0",
        "method": "server.job_queue.jump",
        "params": {
            "job_id": "0000000066d991f0"
        },
        "id": 4654
    }
    # ------announcement apis--------------------------------------------------
    request_announcements_list = {
        "jsonrpc": "2.0",
        "method": "server.announcements.list",
        "params": {
            "include_dismissed": False
        },
        "id": 4654
    }
    request_announcements_update = {
        "jsonrpc": "2.0",
        "method": "server.announcements.update",
        "id": 4654
    }
    request_announcements_dismiss = {
        "jsonrpc": "2.0",
        "method": "server.announcements.dismiss",
        "params": {
            "entry_id": "arksine/moonlight/issue/1",
            "wake_time": 600
        },
        "id": 4654
    }
    request_announcements_feeds = {
        "jsonrpc": "2.0",
        "method": "server.announcements.feeds",
        "id": 4654
    }
    requests_announcements_post_feed = {
        "jsonrpc": "2.0",
        "method": "server.announcements.post_feed",
        "params": {
            "name": "my_feed"
        },
        "id": 4654
    }
    request_announcements_delete_feed = {
        "jsonrpc": "2.0",
        "method": "server.announcements.delete_feed",
        "params": {
            "name": "my_feed"
        },
        "id": 4654
    }
    # ------webcam apis--------------------------------------------------------
    request_webcams_list ={
        "jsonrpc": "2.0",
        "method": "server.webcams.list",
        "id": 4654
    }
    request_webcams_get_item = {
        "jsonrpc": "2.0",
        "method": "server.webcams.get_item",
        "params": {
            "uid": "341778f9-387f-455b-8b69-ff68442d41d9"
        },
        "id": 4654
    }
    request_webcams_post_item = {
        "jsonrpc": "2.0",
        "method": "server.webcams.post_item",
        "params": {
            "name": "cam_name",
            "snapshot_url": "/webcam?action=snapshot",
            "stream_url": "/webcam?action=stream"
        },
        "id": 4654
    }
    request_webcams_delete_item = {
        "jsonrpc": "2.0",
        "method": "server.webcams.delete_item",
        "params": {
            "uid": "341778f9-387f-455b-8b69-ff68442d41d9"
        },
        "id": 4654
    }
    request_webcams_test = {
        "jsonrpc": "2.0",
        "method": "server.webcams.test",
        "params": {
            "uid": "341778f9-387f-455b-8b69-ff68442d41d9"
        },
        "id": 4654
    }
    # ------notifier apis------------------------------------------------------
    request_notifiers_list = {
        "jsonrpc": "2.0",
        "method": "server.notifiers.list",
        "id": 4654
    }
    # ------update manager apis------------------------------------------------
    request_update_status = {
        "jsonrpc": "2.0",
        "method": "machine.update.status",
        "params": {
            "refresh": False
        },
        "id": 4644
    }
    request_update_refresh = {
        "jsonrpc": "2.0",
        "method": "machine.update.refresh",
        "params": {
            "name": "klipper"
        },
        "id": 4644
    }
    request_update_full = {
        "jsonrpc": "2.0",
        "method": "machine.update.full",
        "id": 4645
    }
    request_update_moonraker = {
        "jsonrpc": "2.0",
        "method": "machine.update.moonraker",
        "id": 4645
    }
    request_update_klipper = {
        "jsonrpc": "2.0",
        "method": "machine.update.klipper",
        "id": 5745
    }
    request_update_client = {
        "jsonrpc": "2.0",
        "method":  "machine.update.client",
        "params": {
            "name": "client_name"
        },
        "id": 8546
    }
    request_update_system = {
        "jsonrpc": "2.0",
        "method": "machine.update.system",
        "id": 4564
    }
    request_update_recover = {
        "jsonrpc": "2.0",
        "method": "machine.update.recover",
        "params": {
            "name": "moonraker",
            "hard": False
        },
        "id": 4564
    }
    request_update_rollback = {
        "jsonrpc": "2.0",
        "method": "machine.update.rollback",
        "params": {
            "name": "moonraker"
        },
        "id": 4564
    }
    # ------power apis---------------------------------------------------------
    request_device_power_devices = {
        "jsonrpc": "2.0",
        "method": "machine.device_power.devices",
        "id": 5646
    }
    request_device_power_get_device = {
        "jsonrpc": "2.0",
        "method": "machine.device_power.get_device",
        "params": {
            "device": "green_led"
        },
        "id": 4564
    }
    request_device_power_post_device = {
        "jsonrpc": "2.0",
        "method": "machine.device_power.post_device",
        "params": {
            "device": "green_led",
            "action": "on"
        },
        "id": 4564
    }
    request_device_power_status = {
        "jsonrpc": "2.0",
        "method": "machine.device_power.status",
        "params": {
            "dev_one": None,
            "dev_two": None
        },
        "id": 4564
    }
    request_device_power_on = {
        "jsonrpc": "2.0",
        "method": "machine.device_power.on",
        "params": {
            "dev_one": None,
            "dev_two": None
        },
        "id": 4564
    }
    request_device_power_off = {
        "jsonrpc": "2.0",
        "method": "machine.device_power.off",
        "params": {
            "dev_one": None,
            "dev_two": None
        },
        "id": 4564
    }
    # ------wled apis----------------------------------------------------------
    request_wled_strips = {
        "jsonrpc": "2.0",
        "method": "machine.wled.strips",
        "id": 7123
    }
    request_wled_status = {
        "jsonrpc": "2.0",
        "method": "machine.wled.status",
        "params": {
            "lights": None,
            "desk": None
        },
        "id": 7124
    }
    request_wled_on = {
        "jsonrpc": "2.0",
        "method": "machine.wled.on",
        "params": {
            "lights": None,
            "desk": None
        },
        "id": 7125
    }
    request_wled_off = {
        "jsonrpc": "2.0",
        "method": "machine.wled.off",
        "params": {
            "lights": None,
            "desk": None
        },
        "id": 7126
    }
    request_wled_toggle = {
        "jsonrpc": "2.0",
        "method": "machine.wled.toggle",
        "params": {
            "lights": None,
            "desk": None
        },
        "id": 7127
    }
    # ------sensor apis--------------------------------------------------------
    request_sensors_list = {
        "jsonrpc": "2.0",
        "method": "server.sensors.list",
        "params": {
            "extended": False
        },
        "id": 5646
    }
    request_sensors_info = {
        "jsonrpc": "2.0",
        "method": "server.sensors.info",
        "params": {
            "sensor": "sensor1",
            "extended": False
        },
        "id": 4564
    }
    request_sensors_measurement = {
        "jsonrpc": "2.0",
        "method": "server.sensors.measurements",
        "params": {
            "sensor": "sensor1"
        },
        "id": 4564
    }
    request_sensors_measurements = {
        "jsonrpc": "2.0",
        "method": "server.sensors.measurements",
        "id": 4564
    }
    # ------spoolman apis------------------------------------------------------
    # n/a
    # ------octoprint api emulation--------------------------------------------
    # n/a
    # ------history apis-------------------------------------------------------
    request_history_list = {
        "jsonrpc": "2.0",
        "method": "server.history.list",
        "params":{
            "limit": 50,
            "start": 10,
            "since": 464.54,
            "before": 1322.54,
            "order": "asc"
        },
        "id": 5656
    }
    request_history_totals = {
        "jsonrpc": "2.0",
        "method": "server.history.totals",
        "id": 5656
    }
    request_history_reset_totals = {
        "jsonrpc": "2.0",
        "method": "server.history.reset_totals",
        "id": 5534
    }
    request_history_get_job = {
        "jsonrpc": "2.0",
        "method": "server.history.get_job",
        "params":{"uid": "{uid}"},
        "id": 4564
    }
    request_history_delete_job = {
        "jsonrpc": "2.0",
        "method": "server.history.delete_job",
        "params":{
            "uid": "{uid}"
        },
        "id": 5534
    }
    # ------mqtt apis----------------------------------------------------------
    # n/a
    # ------extension apis-----------------------------------------------------
    # n/a note, maybe this should be an extension
    # ------debug apis---------------------------------------------------------
    # n/a
    # ------websocket notifications--------------------------------------------

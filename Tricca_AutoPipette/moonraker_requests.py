#!/usr/bin/env python3
"""Holds the requests for the pipette server."""
import uuid
from typing import Dict, List, Optional, Union


class MoonrakerRequests:
    """A data class holding all the requests for Moonraker."""

    JSON_RPC_VERSION: str = "2.0"
    METHODS: List[str] = [
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
        "printer.print.start",
        "printer.print.pause",
        "printer.print.resume",
        "printer.print.cancel",
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
    SUBSCRIBABLE: List[str] = [
        "angle", "bed_mesh", "bed_screws", "configfile", "display_status",
        "endstop_phase", "exclude_object", "extruder_stepper", "fan",
        "filament_switch_sensor", "filament_motion_sensor",
        "firmware_retraction", "gcode", "gcode_button", "gcode_macro",
        "gcode_move", "hall_filament_width_sensor", "heater", "heaters",
        "idle_timeout", "led", "manual_probe", "mcu", "motion_report",
        "output_pin", "palette2", "pause_resume", "print_stats", "probe",
        "pwm_cycle_time", "quad_gantry_level", "query_endstops",
        "screws_tilt_adjust", "servo", "stepper_enable", "system_stats",
        "temperature sensors", "temperature_fan", "temperature_sensor",
        "tmc drivers", "toolhead", "dual_carriage", "virtual_sdcard",
        "webhooks", "z_thermal_adjust", "z_tilt",
    ]

    def gen_request(
        self,
        method: str,
        params: Optional[Dict] = None
    ) -> Dict[str, Union[str, Dict]]:
        """
        Generate a Moonraker JSON-RPC request.

        Args:
            method: The Moonraker method to call
            params: Optional parameters for the method

        Returns:
            Dictionary representing the JSON-RPC request
        """
        request = {
            "jsonrpc": self.JSON_RPC_VERSION,
            "method": method,
            "id": str(uuid.uuid4()),
        }
        if params is not None:
            request["params"] = params
        return request

    def request_sub_to_objs(self, objs: List[str]) -> Dict:
        """
        Create subscription request for printer objects.

        Args:
           objs: List of objects to subscribe to

        Returns:
            Subscription request dictionary
        """
        objects = {obj: None for obj in objs if obj in self.SUBSCRIBABLE}
        return self.gen_request("printer.objects.subscribe",
                                {"objects": objects})

    # ------ Server Administration --------------------------------------------
    def server_info(self) -> Dict:
        """Get server information."""
        return self.gen_request("server.info")

    def server_config(self) -> Dict:
        """Get server configuration."""
        return self.gen_request("server.config")

    def server_temperature_store(self, include_monitors: bool = False) -> Dict:
        """Get temperature store data."""
        return self.gen_request("server.temperature_store",
                                {"include_monitors": include_monitors})

    def server_gcode_store(self, count: int = 100) -> Dict:
        """Get stored GCode commands."""
        return self.gen_request("server.gcode_store", {"count": count})

    def server_logs_rollover(self, application: str = "moonraker") -> Dict:
        """Roll over log files."""
        return self.gen_request("server.logs.rollover",
                                {"application": application})

    def server_restart(self) -> Dict:
        """Restart Moonraker service."""
        return self.gen_request("server.restart")

    def server_connection_identify(
        self,
        client_name: str,
        version: str,
        client_type: str,
        url: str,
        access_token: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> Dict:
        """Identify client connection."""
        params = {
            "client_name": client_name,
            "version": version,
            "type": client_type,
            "url": url,
        }
        if access_token:
            params["access_token"] = access_token
        if api_key:
            params["api_key"] = api_key
        return self.gen_request("server.connection.identify", params)

    def server_websocket_id(self) -> Dict:
        """Get WebSocket connection ID."""
        return self.gen_request("server.websocket.id")

    # ------ Printer Administration -------------------------------------------
    def printer_info(self) -> Dict:
        """Get printer information."""
        return self.gen_request("printer.info")

    def printer_emergency_stop(self) -> Dict:
        """Execute emergency stop."""
        return self.gen_request("printer.emergency_stop")

    def printer_restart(self) -> Dict:
        """Restart printer/firmware."""
        return self.gen_request("printer.restart")

    # ------ Printer Status ---------------------------------------------------
    def printer_objects_list(self) -> Dict:
        """List available printer objects."""
        return self.gen_request("printer.objects.list")

    def printer_objects_query(self,
                              objects: Dict[str, Optional[List[str]]]) -> Dict:
        """
        Query printer objects.

        Args:
            objects: Dictionary of objects to query {object: [fields]}
        """
        return self.gen_request("printer.objects.query", {"objects": objects})

    def printer_query_endstops_status(self) -> Dict:
        """Query endstop status."""
        return self.gen_request("printer.query_endstops.status")

    # ------ GCode API --------------------------------------------------------
    def printer_gcode_script(self, script: str) -> Dict:
        """Execute GCode script."""
        return self.gen_request("printer.gcode.script", {"script": script})

    def printer_gcode_help(self) -> Dict:
        """Get GCode help."""
        return self.gen_request("printer.gcode.help")

    # ------ Print Management -------------------------------------------------
    def printer_print_start(self, filename: str) -> Dict:
        """Start a print job."""
        return self.gen_request("printer.print.start", {"filename": filename})

    def printer_print_pause(self) -> Dict:
        """Pause current print."""
        return self.gen_request("printer.print.pause")

    def printer_print_resume(self) -> Dict:
        """Resume paused print."""
        return self.gen_request("printer.print.resume")

    def printer_print_cancel(self) -> Dict:
        """Cancel current print."""
        return self.gen_request("printer.print.cancel")

    # ------ Machine Requests -------------------------------------------------
    def machine_system_info(self) -> Dict:
        """Get system information."""
        return self.gen_request("machine.system_info")

    def machine_shutdown(self) -> Dict:
        """Shutdown system."""
        return self.gen_request("machine.shutdown")

    def machine_reboot(self) -> Dict:
        """Reboot system."""
        return self.gen_request("machine.reboot")

    def machine_services_restart(self, service: str) -> Dict:
        """Restart system service."""
        return self.gen_request("machine.services.restart",
                                {"service": service})

    def machine_services_stop(self, service: str) -> Dict:
        """Stop system service."""
        return self.gen_request("machine.services.stop", {"service": service})

    def machine_proc_stats(self) -> Dict:
        """Request system usage."""
        return self.gen_request("machine.proc_stats")

    def machine_sudo_info(self, check_access: bool = False) -> Dict:
        """Retrieve sudo information status."""
        return self.gen_request("machine.sudo.info",
                                {"check_access": check_access})

    def machine_sudo_password(self, password: str) -> Dict:
        """Set the sudo password currently used by Moonraker."""
        return self.gen_request("machine.sudo.password",
                                {"password": password})

    def machine_peripherals_usb(self) -> Dict:
        """List all USB devices currently detected on system."""
        return self.gen_request("machine.peripheral.usb")

    def machine_peripherals_serial(self) -> Dict:
        """List all serial devices currently detected on system."""
        return self.gen_request("machine.peripherals.serial")

    def machine_peripherals_video(self) -> Dict:
        """List all V4L2 video capture devices on the system."""
        return self.gen_request("machine.peripherals.video")

    def machine_peripherals_canbus(self, interface: str = "can0") -> Dict:
        """Query the provided canbus interface."""
        return self.gen_request("machine.peripherals.canbus",
                                {"interface": interface})

    # ------ File Operations -------------------------------------------------
    def server_files_list(self, root: Optional[str] = None) -> Dict:
        """List files in a directory."""
        params = {}
        if root is not None:
            params["root"] = root
        return self.gen_request("server.files.list", params)

    def server_files_roots(self) -> Dict:
        """Get available file roots."""
        return self.gen_request("server.files.roots")

    def server_files_metadata(self, filename: str) -> Dict:
        """Get file metadata."""
        return self.gen_request("server.files.metadata",
                                {"filename": filename})

    def server_files_metascan(self, filename: str) -> Dict:
        """Scan file for metadata."""
        return self.gen_request("server.files.metascan",
                                {"filename": filename})

    def server_files_thumbnails(self, filename: str) -> Dict:
        """Get file thumbnails."""
        return self.gen_request("server.files.thumbnails",
                                {"filename": filename})

    def server_files_get_directory(self,
                                   path: str,
                                   extended: bool = True) -> Dict:
        """Get directory contents."""
        return self.gen_request("server.files.get_directory", {
            "path": path,
            "extended": extended
        })

    def server_files_post_directory(self, path: str) -> Dict:
        """Create a directory."""
        return self.gen_request("server.files.post_directory", {"path": path})

    def server_files_delete_directory(self,
                                      path: str,
                                      force: bool = False) -> Dict:
        """Delete a directory."""
        return self.gen_request("server.files.delete_directory", {
            "path": path,
            "force": force
        })

    def server_files_move(self, source: str, dest: str) -> Dict:
        """Move a file or directory."""
        return self.gen_request("server.files.move", {
            "source": source,
            "dest": dest
        })

    def server_files_copy(self, source: str, dest: str) -> Dict:
        """Copy a file or directory."""
        return self.gen_request("server.files.copy", {
            "source": source,
            "dest": dest
        })

    def server_files_zip(
        self,
        dest: str,
        items: List[str],
        store_only: bool = False
    ) -> Dict:
        """Create a zip archive."""
        return self.gen_request("server.files.zip", {
            "dest": dest,
            "items": items,
            "store_only": store_only
        })

    def server_files_delete(self, path: str) -> Dict:
        """Delete a file."""
        return self.gen_request("server.files.delete_file", {"path": path})

    # ------ Authorization ---------------------------------------------------
    def access_login(
        self,
        username: str,
        password: str,
        source: str = "moonraker"
    ) -> Dict:
        """Login to Moonraker."""
        return self.gen_request("access.login", {
            "username": username,
            "password": password,
            "source": source
        })

    def access_logout(self) -> Dict:
        """Logout from Moonraker."""
        return self.gen_request("access.logout")

    def access_get_user(self) -> Dict:
        """Get current user information."""
        return self.gen_request("access.get_user")

    def access_post_user(self, username: str, password: str) -> Dict:
        """Create a new user."""
        return self.gen_request("access.post_user", {
            "username": username,
            "password": password
        })

    def access_delete_user(self, username: str) -> Dict:
        """Delete a user."""
        return self.gen_request("access.delete_user", {"username": username})

    def access_users_list(self) -> Dict:
        """List all users."""
        return self.gen_request("access.users.list")

    def access_user_password(self, password: str, new_password: str) -> Dict:
        """Change user password."""
        return self.gen_request("access.user.password", {
            "password": password,
            "new_password": new_password
        })

    def access_refresh_jwt(self, refresh_token: str) -> Dict:
        """Refresh JWT token."""
        return self.gen_request("access.refresh_jwt",
                                {"refresh_token": refresh_token})

    def access_oneshot_token(self) -> Dict:
        """Get one-shot token."""
        return self.gen_request("access.oneshot_token")

    def access_info(self) -> Dict:
        """Get access information."""
        return self.gen_request("access.info")

    def access_get_api_key(self) -> Dict:
        """Get API key."""
        return self.gen_request("access.get_api_key")

    def access_post_api_key(self) -> Dict:
        """Generate new API key."""
        return self.gen_request("access.post_api_key")

    # ------ Database APIs ---------------------------------------------------
    def server_database_list(self) -> Dict:
        """List databases."""
        return self.gen_request("server.database.list")

    def server_database_get_item(self, namespace: str, key: str) -> Dict:
        """Get database item."""
        return self.gen_request("server.database.get_item", {
            "namespace": namespace,
            "key": key
        })

    def server_database_post_item(
        self,
        namespace: str,
        key: str,
        value: str,
    ) -> Dict:
        """Set database item."""
        return self.gen_request("server.database.post_item", {
            "namespace": namespace,
            "key": key,
            "value": value
        })

    def server_database_delete_item(self, namespace: str, key: str) -> Dict:
        """Delete database item."""
        return self.gen_request("server.database.delete_item", {
            "namespace": namespace,
            "key": key
        })

    def server_database_compact(self) -> Dict:
        """Compact database."""
        return self.gen_request("server.database.compact")

    def server_database_post_backup(self, filename: str) -> Dict:
        """Backup database."""
        return self.gen_request("server.database.post_backup",
                                {"filename": filename})

    def server_database_delete_backup(self, filename: str) -> Dict:
        """Delete database backup."""
        return self.gen_request("server.database.delete_backup",
                                {"filename": filename})

    def server_database_restore(self, filename: str) -> Dict:
        """Restore database from backup."""
        return self.gen_request("server.database.restore",
                                {"filename": filename})

    # ------ Job Queue APIs --------------------------------------------------
    def server_job_queue_status(self) -> Dict:
        """Get job queue status."""
        return self.gen_request("server.job_queue.status")

    def server_job_queue_post_job(
        self,
        filenames: List[str],
        reset: bool = False
    ) -> Dict:
        """Add jobs to queue."""
        return self.gen_request("server.job_queue.post_job", {
            "filenames": filenames,
            "reset": reset
        })

    def server_job_queue_delete_job(self, job_ids: List[str]) -> Dict:
        """Delete jobs from queue."""
        return self.gen_request("server.job_queue.delete_job",
                                {"job_ids": job_ids})

    def server_job_queue_pause(self) -> Dict:
        """Pause job queue."""
        return self.gen_request("server.job_queue.pause")

    def server_job_queue_start(self) -> Dict:
        """Start job queue."""
        return self.gen_request("server.job_queue.start")

    def server_job_queue_jump(self, job_id: str) -> Dict:
        """Jump to a specific job in queue."""
        return self.gen_request("server.job_queue.jump", {"job_id": job_id})

    # ------ Announcement APIs -----------------------------------------------
    def server_announcements_list(self,
                                  include_dismissed: bool = False) -> Dict:
        """List announcements."""
        return self.gen_request("server.announcements.list", {
            "include_dismissed": include_dismissed
        })

    def server_announcements_update(self) -> Dict:
        """Update announcements."""
        return self.gen_request("server.announcements.update")

    def server_announcements_dismiss(
        self,
        entry_id: str,
        wake_time: int = 600
    ) -> Dict:
        """Dismiss announcement."""
        return self.gen_request("server.announcements.dismiss", {
            "entry_id": entry_id,
            "wake_time": wake_time
        })

    def server_announcements_feeds(self) -> Dict:
        """Get announcement feeds."""
        return self.gen_request("server.announcements.feeds")

    def server_announcements_post_feed(self, name: str) -> Dict:
        """Add announcement feed."""
        return self.gen_request("server.announcements.post_feed",
                                {"name": name})

    def server_announcements_delete_feed(self, name: str) -> Dict:
        """Delete announcement feed."""
        return self.gen_request("server.announcements.delete_feed",
                                {"name": name})

    # ------ Webcam APIs -----------------------------------------------------
    def server_webcams_list(self) -> Dict:
        """List webcams."""
        return self.gen_request("server.webcams.list")

    def server_webcams_get_item(self, uid: str) -> Dict:
        """Get webcam by UID."""
        return self.gen_request("server.webcams.get_item", {"uid": uid})

    def server_webcams_post_item(
        self,
        name: str,
        snapshot_url: str,
        stream_url: str
    ) -> Dict:
        """Add webcam."""
        return self.gen_request("server.webcams.post_item", {
            "name": name,
            "snapshot_url": snapshot_url,
            "stream_url": stream_url
        })

    def server_webcams_delete_item(self, uid: str) -> Dict:
        """Delete webcam."""
        return self.gen_request("server.webcams.delete_item", {"uid": uid})

    def server_webcams_test(self, uid: str) -> Dict:
        """Test webcam."""
        return self.gen_request("server.webcams.test", {"uid": uid})

    # ------ Notifier APIs ---------------------------------------------------
    def server_notifiers_list(self) -> Dict:
        """List notifiers."""
        return self.gen_request("server.notifiers.list")

    # ------ Update Manager APIs ---------------------------------------------
    def machine_update_status(self, refresh: bool = False) -> Dict:
        """Get update status."""
        return self.gen_request("machine.update.status", {"refresh": refresh})

    def machine_update_refresh(self, name: str) -> Dict:
        """Refresh update information."""
        return self.gen_request("machine.update.refresh", {"name": name})

    def machine_update_full(self) -> Dict:
        """Perform full update."""
        return self.gen_request("machine.update.full")

    def machine_update_moonraker(self) -> Dict:
        """Update Moonraker."""
        return self.gen_request("machine.update.moonraker")

    def machine_update_klipper(self) -> Dict:
        """Update Klipper."""
        return self.gen_request("machine.update.klipper")

    def machine_update_client(self, name: str) -> Dict:
        """Update client."""
        return self.gen_request("machine.update.client", {"name": name})

    def machine_update_system(self) -> Dict:
        """Update system packages."""
        return self.gen_request("machine.update.system")

    def machine_update_recover(self, name: str, hard: bool = False) -> Dict:
        """Recover update."""
        return self.gen_request("machine.update.recover", {
            "name": name,
            "hard": hard
        })

    def machine_update_rollback(self, name: str) -> Dict:
        """Rollback update."""
        return self.gen_request("machine.update.rollback", {"name": name})

    # ------ Power APIs ------------------------------------------------------
    def machine_device_power_devices(self) -> Dict:
        """Get power devices."""
        return self.gen_request("machine.device_power.devices")

    def machine_device_power_get_device(self, device: str) -> Dict:
        """Get power device status."""
        return self.gen_request("machine.device_power.get_device",
                                {"device": device})

    def machine_device_power_post_device(self,
                                         device: str,
                                         action: str) -> Dict:
        """Control power device."""
        return self.gen_request("machine.device_power.post_device", {
            "device": device,
            "action": action
        })

    def machine_device_power_status(self, devices: List[str]) -> Dict:
        """Get status of multiple devices."""
        params = {dev: None for dev in devices}
        return self.gen_request("machine.device_power.status", params)

    def machine_device_power_on(self, devices: List[str]) -> Dict:
        """Turn on multiple devices."""
        params = {dev: None for dev in devices}
        return self.gen_request("machine.device_power.on", params)

    def machine_device_power_off(self, devices: List[str]) -> Dict:
        """Turn off multiple devices."""
        params = {dev: None for dev in devices}
        return self.gen_request("machine.device_power.off", params)

    # ------ WLED APIs -------------------------------------------------------
    def machine_wled_strips(self) -> Dict:
        """Get WLED strips."""
        return self.gen_request("machine.wled.strips")

    def machine_wled_status(self, strips: List[str]) -> Dict:
        """Get WLED strip status."""
        params = {strip: None for strip in strips}
        return self.gen_request("machine.wled.status", params)

    def machine_wled_on(self, strips: List[str]) -> Dict:
        """Turn on WLED strips."""
        params = {strip: None for strip in strips}
        return self.gen_request("machine.wled.on", params)

    def machine_wled_off(self, strips: List[str]) -> Dict:
        """Turn off WLED strips."""
        params = {strip: None for strip in strips}
        return self.gen_request("machine.wled.off", params)

    def machine_wled_toggle(self, strips: List[str]) -> Dict:
        """Toggle WLED strips."""
        params = {strip: None for strip in strips}
        return self.gen_request("machine.wled.toggle", params)

    # ------ Sensor APIs -----------------------------------------------------
    def server_sensors_list(self, extended: bool = False) -> Dict:
        """List sensors."""
        return self.gen_request("server.sensors.list", {"extended": extended})

    def server_sensors_info(
        self,
        sensor: str,
        extended: bool = False
    ) -> Dict:
        """Get sensor information."""
        return self.gen_request("server.sensors.info", {
            "sensor": sensor,
            "extended": extended
        })

    def server_sensors_measurement(self, sensor: str) -> Dict:
        """Get sensor measurements."""
        return self.gen_request("server.sensors.measurements",
                                {"sensor": sensor})

    def server_sensors_measurements(self) -> Dict:
        """Get all sensor measurements."""
        return self.gen_request("server.sensors.measurements")

    # ------ History APIs -----------------------------------------------------
    def server_history_list(
        self,
        limit: int = 50,
        start: int = 0,
        since: Optional[float] = None,
        before: Optional[float] = None,
        order: str = "asc"
    ) -> Dict:
        """List print history."""
        params = {"limit": limit, "start": start, "order": order}
        if since is not None:
            params["since"] = since
        if before is not None:
            params["before"] = before
        return self.gen_request("server.history.list", params)

    def server_history_totals(self) -> Dict:
        """Get print history totals."""
        return self.gen_request("server.history.totals")

    def server_history_reset_totals(self) -> Dict:
        """Reset history totals."""
        return self.gen_request("server.history.reset_totals")

    def server_history_get_job(self, uid: str) -> Dict:
        """Get job by UID."""
        return self.gen_request("server.history.get_job", {"uid": uid})

    def server_history_delete_job(self, uid: str) -> Dict:
        """Delete job by UID."""
        return self.gen_request("server.history.delete_job", {"uid": uid})

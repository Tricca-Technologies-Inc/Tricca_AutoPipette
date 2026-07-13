#!/usr/bin/env python3
"""Moonraker JSON-RPC request builder for pipette server communication.

This module provides a comprehensive interface for generating JSON-RPC requests
to communicate with a Moonraker server controlling the automated pipette hardware.

Example:
    >>> mrr = MoonrakerRequests()
    >>> request = mrr.printer_print_start("protocol.gcode")
    >>> # Send request via WebSocket or HTTP
"""

from __future__ import annotations

import uuid
from typing import Any


class MoonrakerRequests:
    """JSON-RPC request builder for Moonraker API.

    Provides type-safe methods for constructing JSON-RPC 2.0 requests for all
    Moonraker API endpoints. Each method returns a properly formatted request
    dictionary ready to be serialized and sent to the Moonraker server.

    Attributes:
        JSON_RPC_VERSION: JSON-RPC protocol version (always "2.0").
        METHODS: List of all available Moonraker API methods.
        SUBSCRIBABLE: List of printer objects that support subscriptions.

    Example:
        >>> mrr = MoonrakerRequests()
        >>>
        >>> # Start a print
        >>> start_request = mrr.printer_print_start("my_protocol.gcode")
        >>>
        >>> # Subscribe to printer objects
        >>> sub_request = mrr.request_sub_to_objs(["toolhead", "extruder"])
        >>>
        >>> # Execute G-code
        >>> gcode_request = mrr.printer_gcode_script("G28")
    """

    # Protocol version
    JSON_RPC_VERSION: str = "2.0"

    # All available Moonraker API methods
    METHODS: list[str] = [
        # Server Administration
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
        # Announcement APIs
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
    ]

    # Printer objects available for subscription
    SUBSCRIBABLE: list[str] = [
        "angle",
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

    def gen_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Generate a JSON-RPC 2.0 request.

        Args:
            method: The Moonraker API method to call.
            params: Optional parameters dictionary for the method.

        Returns:
            Dictionary representing the JSON-RPC request with jsonrpc, method,
            id, and optionally params fields.

        Example:
            >>> request = mrr.gen_request("printer.info")
            >>> # {'jsonrpc': '2.0', 'method': 'printer.info', 'id': '...'}

            >>> request = mrr.gen_request("printer.print.start", {"filename": "test.gcode"})
            >>> # {'jsonrpc': '2.0', 'method': 'printer.print.start', 'id': '...',
            >>> #  'params': {'filename': 'test.gcode'}}
        """
        request: dict[str, Any] = {
            "jsonrpc": self.JSON_RPC_VERSION,
            "method": method,
            "id": str(uuid.uuid4()),
        }
        if params is not None:
            request["params"] = params
        return request

    def request_sub_to_objs(self, objs: list[str]) -> dict[str, Any]:
        """Create subscription request for printer objects.

        Only subscribable objects (those in SUBSCRIBABLE list) will be included.

        Args:
            objs: List of object names to subscribe to.

        Returns:
            JSON-RPC request for subscribing to the specified objects.

        Example:
            >>> request = mrr.request_sub_to_objs(["toolhead", "extruder", "heaters"])
            >>> # Subscribe to status updates for these objects
        """
        objects = {obj: None for obj in objs if obj in self.SUBSCRIBABLE}
        return self.gen_request("printer.objects.subscribe", {"objects": objects})

    # ==================== Server Administration ====================

    def server_info(self) -> dict[str, Any]:
        """Get server information and status.

        Returns:
            Request for server info including version and capabilities.
        """
        return self.gen_request("server.info")

    def server_config(self) -> dict[str, Any]:
        """Get server configuration.

        Returns:
            Request for complete server configuration.
        """
        return self.gen_request("server.config")

    def server_temperature_store(
        self, include_monitors: bool = False
    ) -> dict[str, Any]:
        """Get temperature store data.

        Args:
            include_monitors: Whether to include temperature monitors.

        Returns:
            Request for historical temperature data.
        """
        return self.gen_request(
            "server.temperature_store", {"include_monitors": include_monitors}
        )

    def server_gcode_store(self, count: int = 100) -> dict[str, Any]:
        """Get stored G-code commands.

        Args:
            count: Number of recent commands to retrieve (default: 100).

        Returns:
            Request for recent G-code command history.
        """
        return self.gen_request("server.gcode_store", {"count": count})

    def server_logs_rollover(self, application: str = "moonraker") -> dict[str, Any]:
        """Roll over log files.

        Args:
            application: Application name for log rollover (default: "moonraker").

        Returns:
            Request to roll over log files.
        """
        return self.gen_request("server.logs.rollover", {"application": application})

    def server_restart(self) -> dict[str, Any]:
        """Restart Moonraker service.

        Returns:
            Request to restart the Moonraker service.
        """
        return self.gen_request("server.restart")

    def server_connection_identify(
        self,
        client_name: str,
        version: str,
        client_type: str,
        url: str,
        access_token: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """Identify client connection to server.

        Args:
            client_name: Name of the client application.
            version: Client version string.
            client_type: Type of client (e.g., "web", "mobile").
            url: Client URL or endpoint.
            access_token: Optional access token for authentication.
            api_key: Optional API key for authentication.

        Returns:
            Request to identify client connection.
        """
        params: dict[str, Any] = {
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

    def server_websocket_id(self) -> dict[str, Any]:
        """Get WebSocket connection ID.

        Returns:
            Request for the current WebSocket connection identifier.
        """
        return self.gen_request("server.websocket.id")

    # ==================== Printer Administration ====================

    def printer_info(self) -> dict[str, Any]:
        """Get printer information and state.

        Returns:
            Request for printer status and capabilities.
        """
        return self.gen_request("printer.info")

    def printer_emergency_stop(self) -> dict[str, Any]:
        """Execute emergency stop.

        Returns:
            Request to immediately halt all printer operations.
        """
        return self.gen_request("printer.emergency_stop")

    def printer_restart(self) -> dict[str, Any]:
        """Restart printer firmware.

        Returns:
            Request to restart the printer/firmware.
        """
        return self.gen_request("printer.restart")

    # ==================== Printer Status ====================

    def printer_objects_list(self) -> dict[str, Any]:
        """List available printer objects.

        Returns:
            Request for list of all queryable printer objects.
        """
        return self.gen_request("printer.objects.list")

    def printer_objects_query(
        self, objects: dict[str, list[str] | None]
    ) -> dict[str, Any]:
        """Query specific printer objects and their fields.

        Args:
            objects: Dictionary mapping object names to field lists.
                    Use None for all fields of an object.

        Returns:
            Request to query specified objects and fields.

        Example:
            >>> request = mrr.printer_objects_query({
            ...     "toolhead": ["position", "max_velocity"],
            ...     "extruder": None  # All fields
            ... })
        """
        return self.gen_request("printer.objects.query", {"objects": objects})

    def printer_query_endstops_status(self) -> dict[str, Any]:
        """Query endstop status.

        Returns:
            Request for current state of all endstops.
        """
        return self.gen_request("printer.query_endstops.status")

    # ==================== G-code API ====================

    def printer_gcode_script(self, script: str) -> dict[str, Any]:
        """Execute G-code script.

        Args:
            script: G-code command(s) to execute.

        Returns:
            Request to execute the specified G-code.

        Example:
            >>> request = mrr.printer_gcode_script("G28")  # Home all axes
            >>> request = mrr.printer_gcode_script("G1 X10 Y20 F3000")  # Move
        """
        return self.gen_request("printer.gcode.script", {"script": script})

    def printer_gcode_help(self) -> dict[str, Any]:
        """Get G-code help information.

        Returns:
            Request for available G-code commands and their descriptions.
        """
        return self.gen_request("printer.gcode.help")

    # ==================== Print Management ====================

    def printer_print_start(self, filename: str) -> dict[str, Any]:
        """Start a print job.

        Args:
            filename: Name of the G-code file to print.

        Returns:
            Request to start printing the specified file.

        Example:
            >>> request = mrr.printer_print_start("protocol_001.gcode")
        """
        return self.gen_request("printer.print.start", {"filename": filename})

    def printer_print_pause(self) -> dict[str, Any]:
        """Pause current print job.

        Returns:
            Request to pause the active print.
        """
        return self.gen_request("printer.print.pause")

    def printer_print_resume(self) -> dict[str, Any]:
        """Resume paused print job.

        Returns:
            Request to resume a paused print.
        """
        return self.gen_request("printer.print.resume")

    def printer_print_cancel(self) -> dict[str, Any]:
        """Cancel current print job.

        Returns:
            Request to cancel the active print.
        """
        return self.gen_request("printer.print.cancel")

    # ==================== Machine Requests ====================

    def machine_system_info(self) -> dict[str, Any]:
        """Get system information.

        Returns:
            Request for host system hardware and software info.
        """
        return self.gen_request("machine.system_info")

    def machine_shutdown(self) -> dict[str, Any]:
        """Shutdown host system.

        Returns:
            Request to shut down the host machine.
        """
        return self.gen_request("machine.shutdown")

    def machine_reboot(self) -> dict[str, Any]:
        """Reboot host system.

        Returns:
            Request to reboot the host machine.
        """
        return self.gen_request("machine.reboot")

    def machine_services_restart(self, service: str) -> dict[str, Any]:
        """Restart a system service.

        Args:
            service: Name of the service to restart.

        Returns:
            Request to restart the specified service.
        """
        return self.gen_request("machine.services.restart", {"service": service})

    def machine_services_stop(self, service: str) -> dict[str, Any]:
        """Stop a system service.

        Args:
            service: Name of the service to stop.

        Returns:
            Request to stop the specified service.
        """
        return self.gen_request("machine.services.stop", {"service": service})

    def machine_proc_stats(self) -> dict[str, Any]:
        """Request system usage statistics.

        Returns:
            Request for CPU, memory, and process statistics.
        """
        return self.gen_request("machine.proc_stats")

    def machine_sudo_info(self, check_access: bool = False) -> dict[str, Any]:
        """Retrieve sudo status information.

        Args:
            check_access: Whether to check sudo access.

        Returns:
            Request for sudo configuration and access status.
        """
        return self.gen_request("machine.sudo.info", {"check_access": check_access})

    def machine_sudo_password(self, password: str) -> dict[str, Any]:
        """Set the sudo password for Moonraker.

        Args:
            password: Sudo password to set.

        Returns:
            Request to configure sudo password.
        """
        return self.gen_request("machine.sudo.password", {"password": password})

    def machine_peripherals_usb(self) -> dict[str, Any]:
        """List all detected USB devices.

        Returns:
            Request for USB device enumeration.
        """
        return self.gen_request("machine.peripherals.usb")

    def machine_peripherals_serial(self) -> dict[str, Any]:
        """List all detected serial devices.

        Returns:
            Request for serial device enumeration.
        """
        return self.gen_request("machine.peripherals.serial")

    def machine_peripherals_video(self) -> dict[str, Any]:
        """List all V4L2 video capture devices.

        Returns:
            Request for video device enumeration.
        """
        return self.gen_request("machine.peripherals.video")

    def machine_peripherals_canbus(self, interface: str = "can0") -> dict[str, Any]:
        """Query CAN bus interface.

        Args:
            interface: CAN interface name (default: "can0").

        Returns:
            Request for CAN bus device information.
        """
        return self.gen_request("machine.peripherals.canbus", {"interface": interface})

    # ==================== File Operations ====================

    def server_files_list(self, root: str | None = None) -> dict[str, Any]:
        """List files in a directory.

        Args:
            root: Optional root directory to list (e.g., "gcodes").

        Returns:
            Request for directory contents.
        """
        params: dict[str, Any] = {}
        if root is not None:
            params["root"] = root
        return self.gen_request("server.files.list", params)

    def server_files_roots(self) -> dict[str, Any]:
        """Get available file roots.

        Returns:
            Request for list of available file root directories.
        """
        return self.gen_request("server.files.roots")

    def server_files_metadata(self, filename: str) -> dict[str, Any]:
        """Get file metadata.

        Args:
            filename: Name of the file to get metadata for.

        Returns:
            Request for file metadata including size, date, etc.
        """
        return self.gen_request("server.files.metadata", {"filename": filename})

    def server_files_metascan(self, filename: str) -> dict[str, Any]:
        """Scan file for metadata.

        Args:
            filename: Name of the file to scan.

        Returns:
            Request to scan and extract file metadata.
        """
        return self.gen_request("server.files.metascan", {"filename": filename})

    def server_files_thumbnails(self, filename: str) -> dict[str, Any]:
        """Get file thumbnails.

        Args:
            filename: Name of the file to get thumbnails for.

        Returns:
            Request for file thumbnail images.
        """
        return self.gen_request("server.files.thumbnails", {"filename": filename})

    def server_files_get_directory(
        self, path: str, extended: bool = True
    ) -> dict[str, Any]:
        """Get directory contents.

        Args:
            path: Directory path to list.
            extended: Whether to include extended information (default: True).

        Returns:
            Request for detailed directory listing.
        """
        return self.gen_request(
            "server.files.get_directory", {"path": path, "extended": extended}
        )

    def server_files_post_directory(self, path: str) -> dict[str, Any]:
        """Create a directory.

        Args:
            path: Path of the directory to create.

        Returns:
            Request to create a new directory.
        """
        return self.gen_request("server.files.post_directory", {"path": path})

    def server_files_delete_directory(
        self, path: str, force: bool = False
    ) -> dict[str, Any]:
        """Delete a directory.

        Args:
            path: Path of the directory to delete.
            force: Whether to force delete non-empty directory (default: False).

        Returns:
            Request to delete the specified directory.
        """
        return self.gen_request(
            "server.files.delete_directory", {"path": path, "force": force}
        )

    def server_files_move(self, source: str, dest: str) -> dict[str, Any]:
        """Move a file or directory.

        Args:
            source: Source path.
            dest: Destination path.

        Returns:
            Request to move file or directory.
        """
        return self.gen_request("server.files.move", {"source": source, "dest": dest})

    def server_files_copy(self, source: str, dest: str) -> dict[str, Any]:
        """Copy a file or directory.

        Args:
            source: Source path.
            dest: Destination path.

        Returns:
            Request to copy file or directory.
        """
        return self.gen_request("server.files.copy", {"source": source, "dest": dest})

    def server_files_zip(
        self, dest: str, items: list[str], store_only: bool = False
    ) -> dict[str, Any]:
        """Create a zip archive.

        Args:
            dest: Destination path for the zip file.
            items: List of paths to include in the archive.
            store_only: Whether to store without compression (default: False).

        Returns:
            Request to create a zip archive.
        """
        return self.gen_request(
            "server.files.zip", {"dest": dest, "items": items, "store_only": store_only}
        )

    def server_files_delete(self, path: str) -> dict[str, Any]:
        """Delete a file.

        Args:
            path: Path of the file to delete.

        Returns:
            Request to delete the specified file.
        """
        return self.gen_request("server.files.delete_file", {"path": path})

    # ==================== Authorization ====================

    def access_login(
        self, username: str, password: str, source: str = "moonraker"
    ) -> dict[str, Any]:
        """Login to Moonraker.

        Args:
            username: Username for authentication.
            password: Password for authentication.
            source: Authentication source (default: "moonraker").

        Returns:
            Request to authenticate and receive access token.
        """
        return self.gen_request(
            "access.login",
            {"username": username, "password": password, "source": source},
        )

    def access_logout(self) -> dict[str, Any]:
        """Logout from Moonraker.

        Returns:
            Request to invalidate current session.
        """
        return self.gen_request("access.logout")

    def access_get_user(self) -> dict[str, Any]:
        """Get current user information.

        Returns:
            Request for current user details.
        """
        return self.gen_request("access.get_user")

    def access_post_user(self, username: str, password: str) -> dict[str, Any]:
        """Create a new user.

        Args:
            username: Username for the new user.
            password: Password for the new user.

        Returns:
            Request to create a new user account.
        """
        return self.gen_request(
            "access.post_user", {"username": username, "password": password}
        )

    def access_delete_user(self, username: str) -> dict[str, Any]:
        """Delete a user.

        Args:
            username: Username of the user to delete.

        Returns:
            Request to delete the specified user.
        """
        return self.gen_request("access.delete_user", {"username": username})

    def access_users_list(self) -> dict[str, Any]:
        """List all users.

        Returns:
            Request for list of all user accounts.
        """
        return self.gen_request("access.users.list")

    def access_user_password(self, password: str, new_password: str) -> dict[str, Any]:
        """Change user password.

        Args:
            password: Current password.
            new_password: New password to set.

        Returns:
            Request to change the current user's password.
        """
        return self.gen_request(
            "access.user.password", {"password": password, "new_password": new_password}
        )

    def access_refresh_jwt(self, refresh_token: str) -> dict[str, Any]:
        """Refresh JWT token.

        Args:
            refresh_token: Refresh token for getting new access token.

        Returns:
            Request to refresh JWT authentication token.
        """
        return self.gen_request("access.refresh_jwt", {"refresh_token": refresh_token})

    def access_oneshot_token(self) -> dict[str, Any]:
        """Get one-shot token.

        Returns:
            Request for a single-use authentication token.
        """
        return self.gen_request("access.oneshot_token")

    def access_info(self) -> dict[str, Any]:
        """Get access information.

        Returns:
            Request for authentication and authorization info.
        """
        return self.gen_request("access.info")

    def access_get_api_key(self) -> dict[str, Any]:
        """Get API key.

        Returns:
            Request for the current user's API key.
        """
        return self.gen_request("access.get_api_key")

    def access_post_api_key(self) -> dict[str, Any]:
        """Generate new API key.

        Returns:
            Request to generate a new API key.
        """
        return self.gen_request("access.post_api_key")

    # ==================== Database APIs ====================

    def server_database_list(self) -> dict[str, Any]:
        """List database namespaces.

        Returns:
            Request for list of all database namespaces.
        """
        return self.gen_request("server.database.list")

    def server_database_get_item(self, namespace: str, key: str) -> dict[str, Any]:
        """Get database item.

        Args:
            namespace: Database namespace.
            key: Item key within the namespace.

        Returns:
            Request to retrieve a database item.
        """
        return self.gen_request(
            "server.database.get_item", {"namespace": namespace, "key": key}
        )

    def server_database_post_item(
        self,
        namespace: str,
        key: str,
        value: str,
    ) -> dict[str, Any]:
        """Set database item.

        Args:
            namespace: Database namespace.
            key: Item key within the namespace.
            value: Value to store.

        Returns:
            Request to store a database item.
        """
        return self.gen_request(
            "server.database.post_item",
            {"namespace": namespace, "key": key, "value": value},
        )

    def server_database_delete_item(self, namespace: str, key: str) -> dict[str, Any]:
        """Delete database item.

        Args:
            namespace: Database namespace.
            key: Item key to delete.

        Returns:
            Request to delete a database item.
        """
        return self.gen_request(
            "server.database.delete_item", {"namespace": namespace, "key": key}
        )

    def server_database_compact(self) -> dict[str, Any]:
        """Compact database.

        Returns:
            Request to compact and optimize the database.
        """
        return self.gen_request("server.database.compact")

    def server_database_post_backup(self, filename: str) -> dict[str, Any]:
        """Backup database.

        Args:
            filename: Name for the backup file.

        Returns:
            Request to create a database backup.
        """
        return self.gen_request("server.database.post_backup", {"filename": filename})

    def server_database_delete_backup(self, filename: str) -> dict[str, Any]:
        """Delete database backup.

        Args:
            filename: Name of the backup file to delete.

        Returns:
            Request to delete a database backup.
        """
        return self.gen_request("server.database.delete_backup", {"filename": filename})

    def server_database_restore(self, filename: str) -> dict[str, Any]:
        """Restore database from backup.

        Args:
            filename: Name of the backup file to restore from.

        Returns:
            Request to restore database from backup.
        """
        return self.gen_request("server.database.restore", {"filename": filename})

    # ==================== Job Queue APIs ====================

    def server_job_queue_status(self) -> dict[str, Any]:
        """Get job queue status.

        Returns:
            Request for current job queue state and contents.
        """
        return self.gen_request("server.job_queue.status")

    def server_job_queue_post_job(
        self, filenames: list[str], reset: bool = False
    ) -> dict[str, Any]:
        """Add jobs to queue.

        Args:
            filenames: List of G-code filenames to add to queue.
            reset: Whether to clear queue before adding (default: False).

        Returns:
            Request to add jobs to the print queue.
        """
        return self.gen_request(
            "server.job_queue.post_job", {"filenames": filenames, "reset": reset}
        )

    def server_job_queue_delete_job(self, job_ids: list[str]) -> dict[str, Any]:
        """Delete jobs from queue.

        Args:
            job_ids: List of job IDs to remove from queue.

        Returns:
            Request to delete specified jobs from queue.
        """
        return self.gen_request("server.job_queue.delete_job", {"job_ids": job_ids})

    def server_job_queue_pause(self) -> dict[str, Any]:
        """Pause job queue.

        Returns:
            Request to pause automatic job queue processing.
        """
        return self.gen_request("server.job_queue.pause")

    def server_job_queue_start(self) -> dict[str, Any]:
        """Start job queue.

        Returns:
            Request to start/resume automatic job queue processing.
        """
        return self.gen_request("server.job_queue.start")

    def server_job_queue_jump(self, job_id: str) -> dict[str, Any]:
        """Jump to a specific job in queue.

        Args:
            job_id: ID of the job to jump to.

        Returns:
            Request to make specified job next in queue.
        """
        return self.gen_request("server.job_queue.jump", {"job_id": job_id})

    # ==================== Announcement APIs ====================

    def server_announcements_list(
        self, include_dismissed: bool = False
    ) -> dict[str, Any]:
        """List announcements.

        Args:
            include_dismissed: Whether to include dismissed announcements
                              (default: False).

        Returns:
            Request for list of server announcements.
        """
        return self.gen_request(
            "server.announcements.list", {"include_dismissed": include_dismissed}
        )

    def server_announcements_update(self) -> dict[str, Any]:
        """Update announcements.

        Returns:
            Request to refresh announcement feeds.
        """
        return self.gen_request("server.announcements.update")

    def server_announcements_dismiss(
        self, entry_id: str, wake_time: int = 600
    ) -> dict[str, Any]:
        """Dismiss announcement.

        Args:
            entry_id: ID of the announcement to dismiss.
            wake_time: Time in seconds before it can reappear (default: 600).

        Returns:
            Request to dismiss an announcement.
        """
        return self.gen_request(
            "server.announcements.dismiss",
            {"entry_id": entry_id, "wake_time": wake_time},
        )

    def server_announcements_feeds(self) -> dict[str, Any]:
        """Get announcement feeds.

        Returns:
            Request for list of announcement feed sources.
        """
        return self.gen_request("server.announcements.feeds")

    def server_announcements_post_feed(self, name: str) -> dict[str, Any]:
        """Add announcement feed.

        Args:
            name: Name or URL of the feed to add.

        Returns:
            Request to add a new announcement feed.
        """
        return self.gen_request("server.announcements.post_feed", {"name": name})

    def server_announcements_delete_feed(self, name: str) -> dict[str, Any]:
        """Delete announcement feed.

        Args:
            name: Name of the feed to delete.

        Returns:
            Request to remove an announcement feed.
        """
        return self.gen_request("server.announcements.delete_feed", {"name": name})

    # ==================== Webcam APIs ====================

    def server_webcams_list(self) -> dict[str, Any]:
        """List configured webcams.

        Returns:
            Request for list of all configured webcams.
        """
        return self.gen_request("server.webcams.list")

    def server_webcams_get_item(self, uid: str) -> dict[str, Any]:
        """Get webcam by UID.

        Args:
            uid: Unique identifier of the webcam.

        Returns:
            Request for specific webcam configuration.
        """
        return self.gen_request("server.webcams.get_item", {"uid": uid})

    def server_webcams_post_item(
        self, name: str, snapshot_url: str, stream_url: str
    ) -> dict[str, Any]:
        """Add webcam configuration.

        Args:
            name: Display name for the webcam.
            snapshot_url: URL for still image snapshots.
            stream_url: URL for video stream.

        Returns:
            Request to add a new webcam.
        """
        return self.gen_request(
            "server.webcams.post_item",
            {"name": name, "snapshot_url": snapshot_url, "stream_url": stream_url},
        )

    def server_webcams_delete_item(self, uid: str) -> dict[str, Any]:
        """Delete webcam configuration.

        Args:
            uid: Unique identifier of the webcam to delete.

        Returns:
            Request to delete a webcam.
        """
        return self.gen_request("server.webcams.delete_item", {"uid": uid})

    def server_webcams_test(self, uid: str) -> dict[str, Any]:
        """Test webcam connection.

        Args:
            uid: Unique identifier of the webcam to test.

        Returns:
            Request to test webcam connectivity.
        """
        return self.gen_request("server.webcams.test", {"uid": uid})

    # ==================== Notifier APIs ====================

    def server_notifiers_list(self) -> dict[str, Any]:
        """List configured notifiers.

        Returns:
            Request for list of all notification services.
        """
        return self.gen_request("server.notifiers.list")

    # ==================== Update Manager APIs ====================

    def machine_update_status(self, refresh: bool = False) -> dict[str, Any]:
        """Get update status.

        Args:
            refresh: Whether to refresh update information (default: False).

        Returns:
            Request for available updates status.
        """
        return self.gen_request("machine.update.status", {"refresh": refresh})

    def machine_update_refresh(self, name: str) -> dict[str, Any]:
        """Refresh update information for a component.

        Args:
            name: Name of the component to refresh.

        Returns:
            Request to refresh update info for specific component.
        """
        return self.gen_request("machine.update.refresh", {"name": name})

    def machine_update_full(self) -> dict[str, Any]:
        """Perform full system update.

        Returns:
            Request to update all components.
        """
        return self.gen_request("machine.update.full")

    def machine_update_moonraker(self) -> dict[str, Any]:
        """Update Moonraker.

        Returns:
            Request to update Moonraker server.
        """
        return self.gen_request("machine.update.moonraker")

    def machine_update_klipper(self) -> dict[str, Any]:
        """Update Klipper firmware.

        Returns:
            Request to update Klipper.
        """
        return self.gen_request("machine.update.klipper")

    def machine_update_client(self, name: str) -> dict[str, Any]:
        """Update a client application.

        Args:
            name: Name of the client to update.

        Returns:
            Request to update specified client.
        """
        return self.gen_request("machine.update.client", {"name": name})

    def machine_update_system(self) -> dict[str, Any]:
        """Update system packages.

        Returns:
            Request to update OS packages.
        """
        return self.gen_request("machine.update.system")

    def machine_update_recover(self, name: str, hard: bool = False) -> dict[str, Any]:
        """Recover from failed update.

        Args:
            name: Name of the component to recover.
            hard: Whether to perform hard recovery (default: False).

        Returns:
            Request to recover from failed update.
        """
        return self.gen_request("machine.update.recover", {"name": name, "hard": hard})

    def machine_update_rollback(self, name: str) -> dict[str, Any]:
        """Rollback an update.

        Args:
            name: Name of the component to rollback.

        Returns:
            Request to rollback a component update.
        """
        return self.gen_request("machine.update.rollback", {"name": name})

    # ==================== Power APIs ====================

    def machine_device_power_devices(self) -> dict[str, Any]:
        """Get list of power devices.

        Returns:
            Request for list of controllable power devices.
        """
        return self.gen_request("machine.device_power.devices")

    def machine_device_power_get_device(self, device: str) -> dict[str, Any]:
        """Get power device status.

        Args:
            device: Name of the power device.

        Returns:
            Request for specific device power status.
        """
        return self.gen_request("machine.device_power.get_device", {"device": device})

    def machine_device_power_post_device(
        self, device: str, action: str
    ) -> dict[str, Any]:
        """Control power device.

        Args:
            device: Name of the power device.
            action: Action to perform ("on", "off", or "toggle").

        Returns:
            Request to control power device.
        """
        return self.gen_request(
            "machine.device_power.post_device", {"device": device, "action": action}
        )

    def machine_device_power_status(self, devices: list[str]) -> dict[str, Any]:
        """Get status of multiple power devices.

        Args:
            devices: List of device names.

        Returns:
            Request for status of multiple devices.
        """
        params = {dev: None for dev in devices}
        return self.gen_request("machine.device_power.status", params)

    def machine_device_power_on(self, devices: list[str]) -> dict[str, Any]:
        """Turn on multiple power devices.

        Args:
            devices: List of device names to turn on.

        Returns:
            Request to turn on specified devices.
        """
        params = {dev: None for dev in devices}
        return self.gen_request("machine.device_power.on", params)

    def machine_device_power_off(self, devices: list[str]) -> dict[str, Any]:
        """Turn off multiple power devices.

        Args:
            devices: List of device names to turn off.

        Returns:
            Request to turn off specified devices.
        """
        params = {dev: None for dev in devices}
        return self.gen_request("machine.device_power.off", params)

    # ==================== WLED APIs ====================

    def machine_wled_strips(self) -> dict[str, Any]:
        """Get list of WLED strips.

        Returns:
            Request for list of configured WLED LED strips.
        """
        return self.gen_request("machine.wled.strips")

    def machine_wled_status(self, strips: list[str]) -> dict[str, Any]:
        """Get WLED strip status.

        Args:
            strips: List of strip names.

        Returns:
            Request for status of specified WLED strips.
        """
        params = {strip: None for strip in strips}
        return self.gen_request("machine.wled.status", params)

    def machine_wled_on(self, strips: list[str]) -> dict[str, Any]:
        """Turn on WLED strips.

        Args:
            strips: List of strip names to turn on.

        Returns:
            Request to turn on specified WLED strips.
        """
        params = {strip: None for strip in strips}
        return self.gen_request("machine.wled.on", params)

    def machine_wled_off(self, strips: list[str]) -> dict[str, Any]:
        """Turn off WLED strips.

        Args:
            strips: List of strip names to turn off.

        Returns:
            Request to turn off specified WLED strips.
        """
        params = {strip: None for strip in strips}
        return self.gen_request("machine.wled.off", params)

    def machine_wled_toggle(self, strips: list[str]) -> dict[str, Any]:
        """Toggle WLED strips.

        Args:
            strips: List of strip names to toggle.

        Returns:
            Request to toggle specified WLED strips.
        """
        params = {strip: None for strip in strips}
        return self.gen_request("machine.wled.toggle", params)

    # ==================== Sensor APIs ====================

    def server_sensors_list(self, extended: bool = False) -> dict[str, Any]:
        """List configured sensors.

        Args:
            extended: Whether to include extended information (default: False).

        Returns:
            Request for list of all sensors.
        """
        return self.gen_request("server.sensors.list", {"extended": extended})

    def server_sensors_info(
        self, sensor: str, extended: bool = False
    ) -> dict[str, Any]:
        """Get sensor information.

        Args:
            sensor: Name of the sensor.
            extended: Whether to include extended information (default: False).

        Returns:
            Request for specific sensor configuration.
        """
        return self.gen_request(
            "server.sensors.info", {"sensor": sensor, "extended": extended}
        )

    def server_sensors_measurement(self, sensor: str) -> dict[str, Any]:
        """Get sensor measurements.

        Args:
            sensor: Name of the sensor.

        Returns:
            Request for current sensor readings.
        """
        return self.gen_request("server.sensors.measurements", {"sensor": sensor})

    def server_sensors_measurements(self) -> dict[str, Any]:
        """Get all sensor measurements.

        Returns:
            Request for readings from all sensors.
        """
        return self.gen_request("server.sensors.measurements")

    # ==================== History APIs ====================

    def server_history_list(
        self,
        limit: int = 50,
        start: int = 0,
        since: float | None = None,
        before: float | None = None,
        order: str = "asc",
    ) -> dict[str, Any]:
        """List print history.

        Args:
            limit: Maximum number of results (default: 50).
            start: Starting offset for pagination (default: 0).
            since: Unix timestamp to filter jobs after this time.
            before: Unix timestamp to filter jobs before this time.
            order: Sort order, "asc" or "desc" (default: "asc").

        Returns:
            Request for print job history with optional filters.
        """
        params: dict[str, Any] = {"limit": limit, "start": start, "order": order}
        if since is not None:
            params["since"] = since
        if before is not None:
            params["before"] = before
        return self.gen_request("server.history.list", params)

    def server_history_totals(self) -> dict[str, Any]:
        """Get print history totals.

        Returns:
            Request for aggregate print statistics.
        """
        return self.gen_request("server.history.totals")

    def server_history_reset_totals(self) -> dict[str, Any]:
        """Reset history totals.

        Returns:
            Request to reset aggregate statistics.
        """
        return self.gen_request("server.history.reset_totals")

    def server_history_get_job(self, uid: str) -> dict[str, Any]:
        """Get job by UID.

        Args:
            uid: Unique identifier of the job.

        Returns:
            Request for specific job details.
        """
        return self.gen_request("server.history.get_job", {"uid": uid})

    def server_history_delete_job(self, uid: str) -> dict[str, Any]:
        """Delete job from history.

        Args:
            uid: Unique identifier of the job to delete.

        Returns:
            Request to delete job from history.
        """
        return self.gen_request("server.history.delete_job", {"uid": uid})

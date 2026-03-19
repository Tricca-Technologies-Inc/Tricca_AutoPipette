#!/usr/bin/env python3
"""Tricca AutoPipette Shell - Interactive command-line interface for pipette control.

This module provides a cmd2-based shell for controlling an automated pipetting
system. It handles G-code generation, WebSocket communication with the pipette,
and protocol execution.
"""
import json
import logging
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from autopipette import AutoPipette
from cmd2 import Cmd, plugin
from commands import (
    ConfigurationCommands,
    MovementCommands,
    PipetteCommands,
    ProtocolCommands,
    UtilityCommands,
    WebSocketCommands,
)
from gcode_manager import GCodeManager
from json_config_manager import JsonConfigManager
from location_manager import LocationManager
from moonraker_requests import MoonrakerRequests
from pipette_constants import ConfigKey, DefaultFilenames, DefaultPaths
from res.string_constants import TAP_CLR_BANNER
from rich import print as rprint
from rich.console import Console
from websocket_client import WebSocketClient

logger = logging.getLogger(__name__)

# Constants
WEBSOCKET_TIMEOUT_SECONDS = 10


class TriccaAutoPipetteShell(Cmd):
    """Interactive terminal shell for controlling the Tricca AutoPipette.

    Provides a command-line interface with commands for pipetting operations,
    movement control, plate management, and protocol execution. Communicates
    with the pipette hardware via WebSocket and generates G-code commands.

    Commands are organized into separate command sets for better modularity:
    - MovementCommands: home, move, move_loc, move_rel
    - PipetteCommands: pipette, next_tip, eject_tip, dispose_tip
    - ConfigurationCommands: set, coor, plate, ls, save, load_conf
    - ProtocolCommands: run, stop, pause, resume, cancel, break
    - WebSocketCommands: send, notify, upload, read, reconnect
    - UtilityCommands: trigger, print, gcode_print, vol_to_steps, webcam

    Attributes:
        GCODE_PATH: Directory for generated G-code files.
        PROTOCOL_PATH: Directory containing protocol script files.
        intro: Introduction message (empty by default).
        prompt: Command prompt string.
        _autopipette: AutoPipette instance managing pipette state.
        hostname: Network hostname or IP of the pipette.
        console: Rich console for formatted output.
        mrr: Moonraker request generator for JSON-RPC commands.
        uri: WebSocket URI for pipette connection.
        client: WebSocket client for real-time communication.
        gcode_manager: Manager for G-code generation and buffering.
    """

    GCODE_PATH: Path = DefaultPaths.DIR_GCODE
    PROTOCOL_PATH: Path = DefaultPaths.DIR_PROTOCOL

    # Remove the built-in do_set so ConfigurationCommands can register its own.
    # Per cmd2 docs, this must be done at class definition time.
    del Cmd.do_set

    def __init__(
        self,
        config_system: Path,
        config_gantry: Path | None,
        config_pipette: Path | None,
        config_locations: Path | None,
        config_liquids: Path | None,
        connect_websocket: bool = True,
        connect_local_websocket: bool = False,
    ) -> None:
        """Initialize the AutoPipette shell and WebSocket connection.

        Sets up the command interface, loads configuration, establishes
        connection to the pipette hardware, and registers all command sets.

        Args:
            config_system: Path to master configuration file.
            config_gantry: Path to gantry configuration file (optional).
            config_pipette: Path to pipette model configuration file (optional).
            config_locations: Path to named locations configuration file (optional).
            config_liquids: Path to liquids configuration file (optional).
            connect_websocket: Whether to connect to WebSocket on startup
                               (default: True).
            connect_local_websocket: Whether to connect to local WebSocket for testing
                                     (default: False).

        Example:
            >>> shell = TriccaAutoPipetteShell(
            ...     config_system=Path("config/system/system.json"),
            ...     config_gantry=None,
            ...     config_pipette=None,
            ...     config_locations=None,
            ...     config_liquids=None,
            ... )
        """
        history_file = str(DefaultPaths.DIR_SHELL / ".tap_history")
        startup_script = str(DefaultPaths.DIR_SHELL / ".init_pipette")
        super().__init__(
            allow_cli_args=False,
            persistent_history_file=history_file,
            startup_script=startup_script,
            auto_load_commands=False,
        )

        # Prompt configuration
        self.intro = ""
        self.prompt: str = "autopipette >> "

        # Initialize AutoPipette with config
        json_config_manager = JsonConfigManager()
        fn_system = (
            config_system.name if config_system else DefaultFilenames.CONFIG_SYSTEM
        )
        if config_gantry is None:
            fn_gantry = DefaultFilenames.CONFIG_GANTRY
        else:
            fn_gantry = config_gantry.name
        if config_pipette is None:
            fn_pipette = DefaultFilenames.CONFIG_PIPETTE
        else:
            fn_pipette = config_pipette.name
        if config_locations is None:
            fn_locations = DefaultFilenames.CONFIG_LOCATIONS
        else:
            fn_locations = config_locations.name
        if config_liquids is None:
            fn_liquids = DefaultFilenames.CONFIG_LIQUIDS
        else:
            fn_liquids = config_liquids.name
        json_config_manager.load_configs(
            fn_system,
            fn_gantry,
            fn_pipette,
            fn_liquids,
        )
        location_manager = LocationManager()
        location_manager.load_from_json(fn_locations)
        self._autopipette = AutoPipette(json_config_manager, location_manager)

        # Network configuration
        self.hostname = self._get_hostname()
        self.console = Console()

        # WebSocket setup
        self.mrr = MoonrakerRequests()
        if connect_local_websocket:
            self.uri = "ws://localhost/websocket"
        else:
            self.uri = f"ws://{self.hostname}/websocket"
        if connect_websocket:
            self.client = WebSocketClient(self.uri)
        else:
            self.client = None

        # G-code management
        self.gcode_manager = GCodeManager(DefaultPaths.DIR_GCODE, self._autopipette)

        # Register all command sets
        self._register_command_sets()

        # Register lifecycle hooks
        self._register_hooks()

    def _get_hostname(self) -> str:
        """Retrieve hostname from AutoPipette configuration.

        Returns:
            Hostname or IP address from configuration.

        Raises:
            RuntimeError: If no hostname or IP configured.

        Example:
            >>> hostname = self._get_hostname()
            >>> # Returns 'tap-tyson.local' or '192.168.1.100'
        """
        network = self._autopipette.system_config.network

        # Try IP first, then hostname. Keys are lowercase to match JSON convention;
        # ConfigKey.Network defines the canonical names for reference.
        ip_key = ConfigKey.Network.IP.lower()  # "ip"
        hostname_key = ConfigKey.Network.HOSTNAME.lower()  # "hostname"
        hostname = network.get(ip_key) or network.get(hostname_key)

        if not hostname:
            raise RuntimeError(
                f"No hostname or IP configured in system.network. "
                f"Please set '{hostname_key}' or '{ip_key}' in "
                f"config/system/system.json"
            )

        return hostname

    def _register_command_sets(self) -> None:
        """Register all command sets with the shell.

        Command sets are registered in logical groups for organized
        command availability.
        """
        self.register_command_set(MovementCommands())
        self.register_command_set(PipetteCommands())
        self.register_command_set(ConfigurationCommands())
        self.register_command_set(ProtocolCommands())
        self.register_command_set(WebSocketCommands())
        self.register_command_set(UtilityCommands())

    def _register_hooks(self) -> None:
        """Register lifecycle hooks for shell startup/shutdown & command validation."""
        self.register_preloop_hook(self._preloop_hook)
        self.register_postloop_hook(self._postloop_hook)
        self.register_precmd_hook(self._precommand_hook)
        self.register_postcmd_hook(self._postcommand_hook)

    # ==================== Lifecycle Hooks ====================

    def _preloop_hook(self) -> None:
        """Initialize shell environment before entering command loop.

        Performs the following initialization steps:
        1. Clears the screen
        2. Displays the application banner
        3. Establishes WebSocket connection to the pipette
        4. Updates prompt if connection fails
        """
        self.console.print("\033c", end="")
        self.console.print(TAP_CLR_BANNER)
        self.console.print("[green]Connecting to Pipette...[/]")

        if self.client is not None:
            self.client.start()
            connected = self.client.wait_for_connection(
                timeout=WEBSOCKET_TIMEOUT_SECONDS
            )

            if not connected:
                self.perror("Failed to connect to WebSocket.")
                self.prompt = "autopipette (disconnected) >> "
                logger.error("WebSocket connection failed during startup")
            else:
                logger.info("WebSocket connection established")

        self.console.print("[green]Initializing Pipette...[/]")
        self.console.print("[green]Loading commands...[/]")

    def _postloop_hook(self) -> None:
        """Clean up resources when exiting the shell.

        Closes WebSocket connection and performs cleanup to ensure
        graceful shutdown.
        """
        self.poutput("Shutting down...")
        self.poutput("Closing WebSocket client...")
        if self.client is not None:
            self.client.stop()
        self.poutput("WebSocket client closed.")
        self.poutput("Exited.")
        logger.info("Shell shutdown complete")

    def _precommand_hook(self, data: plugin.PrecommandData) -> plugin.PrecommandData:
        """Validate commands before execution.

        Checks that movement commands are only executed when the pipette
        has been homed. This safety check prevents damage to equipment.

        Args:
            data: Pre-command data containing the statement to validate.

        Returns:
            Modified pre-command data, potentially with stop flag set.
        """
        # Commands that require the pipette to be homed.
        # Note: "home", "init", "home_x/y/z" etc. are intentionally excluded
        # as they are the commands used to perform homing.
        movement_commands = {
            # Movement
            "move",
            "move_loc",
            "move_rel",
            # Pipetting
            "pipette",
            "aspirate",
            "dispense",
            "next_tip",
            "eject_tip",
            "dispose_tip",
            "change_tip",
            # Protocol execution
            "run",
        }

        if data.statement.command not in movement_commands:
            return data

        if not self._autopipette.state.homed:
            rprint("[red]Pipette not homed. Run 'init' or 'home all' first.[/]")
            logger.warning(
                f"Command '{data.statement.command}' blocked - pipette not homed"
            )
            return replace(data, stop=True)
        return data

    def _postcommand_hook(self, data: plugin.PostcommandData) -> plugin.PostcommandData:
        """Process data after command execution.

        Currently a no-op, but provides a hook for future post-command
        processing such as logging, metrics, or state updates.

        Args:
            data: Post-command data from executed command.

        Returns:
            Unmodified post-command data.
        """
        return data

    # ==================== JSON-RPC Communication ====================

    def send_rpc(self, payload: dict[str, Any]) -> None:
        """Send a JSON-RPC request asynchronously.

        Sends the request in a background thread to avoid blocking the shell.
        Displays the response when received via async alert.

        Args:
            payload: JSON-RPC request payload dictionary.

        Note:
            Responses are displayed asynchronously via terminal alerts.
            Errors are logged and displayed to the user.
        """

        def worker() -> None:
            try:
                # Can't run if self.client is None
                response = self.client.send_jsonrpc(payload)  # type: ignore[union-attr]
                with self.terminal_lock:
                    self.async_alert(f"Response: {response}")
                logger.debug(f"RPC response: {response}")
            except json.JSONDecodeError as jde:
                error_msg = f"JSON decode error in params: {jde}"
                self.perror(error_msg)
                logger.error(error_msg)
            except Exception as e:
                error_msg = f"RPC error: {e}"
                self.perror(error_msg)
                logger.exception("Unexpected error during RPC call")

        if self.client is None:
            self.perror("WebSocket client not initialized. Cannot send RPC.")
            logger.error("Attempted to send RPC without WebSocket client")
            return
        threading.Thread(target=worker, daemon=True).start()

    # ==================== G-code File Management ====================

    def upload_gcode(self, filename: str, file_path: Path) -> None:
        """Upload a G-code file to the pipette.

        Uploads the file asynchronously and displays the server path
        when complete. Does not start execution.

        Args:
            filename: Name for the file on the server.
            file_path: Local path to the G-code file.

        Note:
            Upload happens in a background thread.
        """

        def worker() -> None:
            # Can't run if self.client is None
            future = self.client.upload_gcode_file(filename, str(file_path))  # type: ignore[union-attr]
            try:
                server_path = future.result()
                with self.terminal_lock:
                    self.async_alert(f"Upload successful. Server path: {server_path}")
                logger.info(f"Uploaded {filename} to {server_path}")
            except Exception as e:
                error_msg = f"Upload failed: {e}"
                self.perror(error_msg)
                logger.exception(f"Failed to upload {filename}")

        if self.client is None:
            self.perror("WebSocket client not initialized. Cannot upload G-code.")
            logger.error("Attempted to upload G-code without WebSocket client")
            return
        threading.Thread(target=worker, daemon=True).start()

    def upload_and_execute_gcode(
        self, filename: str, file_path: Path, delete_file: bool = False
    ) -> None:
        """Upload G-code file and immediately start execution.

        Uploads the file, starts execution via JSON-RPC, and optionally
        deletes the local file after successful upload.

        Args:
            filename: Name for the file on the server.
            file_path: Local path to the G-code file.
            delete_file: Whether to delete local file after upload (default: False).

        Note:
            Execution starts automatically after successful upload.
            Local file is only deleted after successful upload if delete_file=True.
        """

        def worker() -> None:
            # Can't run if self.client is None
            future = self.client.upload_gcode_file(filename, str(file_path))  # type: ignore[union-attr]
            try:
                server_path = future.result()
                with self.terminal_lock:
                    self.async_alert(f"Upload successful. Server path: {server_path}")

                self.send_rpc(self.mrr.printer_print_start(filename))
                logger.info(f"Started execution of {filename}")

                if delete_file:
                    file_path.unlink()
                    logger.debug(f"Deleted local file: {file_path}")
            except Exception as e:
                error_msg = f"Upload or execution failed: {e}"
                self.perror(error_msg)
                logger.exception(f"Failed to upload and execute {filename}")

        if self.client is None:
            self.perror("WebSocket client not initialized. Cannot upload G-code.")
            logger.error(
                "Attempted to upload and execute G-code without WebSocket client"
            )
            return
        threading.Thread(target=worker, daemon=True).start()

    def output_gcode(
        self,
        gcode: list[str],
        filename: str | None = None,
        append_header: bool = False,
    ) -> None:
        """Write G-code to file and upload for execution.

        Operates in two modes based on GCodeManager state:
        1. Batch mode: Appends to buffer for later combined upload
        2. Immediate mode: Writes to file and uploads immediately

        Args:
            gcode: List of G-code command strings.
            filename: Output filename, or None to auto-generate timestamp.
            append_header: Whether to prepend configuration header.

        Note:
            Batch mode is activated via context manager when executing protocols.
            In immediate mode, files are uploaded to GCODE_PATH/temp/ and deleted
            after execution starts.
        """
        # Batch mode: accumulate G-code for protocol execution
        if self.gcode_manager.is_batch_mode:
            self.gcode_manager.add_gcode(gcode)
            return

        # Immediate mode: write and upload
        try:
            file_path = self.gcode_manager.write_gcode_file(
                gcode, filename, append_header
            )
            logger.debug(f"Wrote G-code to {file_path}")
            self.upload_and_execute_gcode(file_path.name, file_path, delete_file=True)
        except IOError as e:
            error_msg = f"Failed to write G-code file: {e}"
            self.perror(error_msg)
            logger.exception("Failed to write G-code file")

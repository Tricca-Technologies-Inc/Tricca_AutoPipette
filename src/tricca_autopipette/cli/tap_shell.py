#!/usr/bin/env python3
"""Tricca AutoPipette Shell - Interactive command-line interface for pipette control.

This module provides a cmd2-based shell for controlling an automated pipetting
system. As of migration Phase 4 (see CLAUDE.md's ports-and-adapters notes),
all business logic (G-code generation, WebSocket communication, protocol
execution) lives on the ``AutoPipetteService`` this class constructs and owns
-- this class itself is purely the cmd2-specific driving adapter for
standalone/local-scripting use (the daemon talks to an ``AutoPipetteService``
directly, with no cmd2 shell involved at all).
"""

from __future__ import annotations

import logging
from pathlib import Path

from cmd2 import Cmd
from rich.console import Console

from tricca_autopipette.commands import (
    ConfigurationCommands,
    MovementCommands,
    PipetteCommands,
    ProtocolCommands,
    UtilityCommands,
    WebSocketCommands,
)
from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.service import AutoPipetteService
from tricca_autopipette.resources.string_constants import TAP_CLR_BANNER

logger = logging.getLogger(__name__)


class TriccaAutoPipetteShell(Cmd):
    """Interactive terminal shell for controlling the Tricca AutoPipette.

    Provides a command-line interface with commands for pipetting operations,
    movement control, plate management, and protocol execution. Commands are
    thin cmd2 adapters (parse args, call ``self.service``, render the
    result) -- see ``commands/*.py``.

    Commands are organized into separate command sets for better modularity:

    - MovementCommands: init, home, move, move_loc, move_rel
    - PipetteCommands: pipette, aspirate, dispense, next_tip, eject_tip,
      dispose_tip, change_tip
    - ConfigurationCommands: set, coor, plate, ls, switch_liquid/list_liquids/
      load_liquid, save_locations/load_locations/unload_locations,
      reset_plate(s), del_loc, clear_locs, tips/reset_tips/reset_tips_all/
      set_tips
    - ProtocolCommands: run, stop, pause, resume, cancel, break
    - WebSocketCommands: ws_status, ping, send, notify, subscribe,
      unsubscribe, upload, read, read_all, clear_queue, reconnect
    - UtilityCommands: wait, trigger, gcode_print, webcam, vol_to_steps,
      steps_to_vol

    Attributes:
        GCODE_PATH: Directory for generated G-code files.
        PROTOCOL_PATH: Directory containing protocol script files.
        intro: Introduction message (empty by default).
        prompt: Command prompt string.
        console: Rich console for formatted output.
        service: The ``AutoPipetteService`` owning all business logic,
            config, and the Moonraker connection.
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
        """Initialize the AutoPipette shell and its backing service.

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
            ...     config_system=Path("default_system.json"),
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
        self.console = Console()

        # AutoPipetteService owns config loading, the AutoPipette domain
        # object, the Moonraker connection, and G-code generation -- built
        # here (not by the daemon) since this is a standalone/local-
        # scripting shell instance, but it's the exact same class the
        # daemon builds directly (no cmd2 involved on that path).
        self.service: AutoPipetteService = AutoPipetteService(
            config_system=config_system,
            config_gantry=config_gantry,
            config_pipette=config_pipette,
            config_locations=config_locations,
            config_liquids=config_liquids,
            connect_websocket=connect_websocket,
            connect_local_websocket=connect_local_websocket,
        )

        # Register all command sets
        self._register_command_sets()

        # Register lifecycle hooks
        self._register_hooks()

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
        """Register lifecycle hooks for shell startup/shutdown.

        Unlike earlier versions of this class, there is no precmd-based
        homed-safety-interlock hook here anymore: that check now lives in
        ``daemon/service.py``'s ``require_homed`` decorator, applied
        directly to ``AutoPipetteService``'s gated methods, so it's
        enforced identically here (standalone use) and in the daemon --
        the old interlock hook here was also broken against the installed
        cmd2 4.0 API (``PrecommandData`` has no ``stop`` field) and never
        actually blocked anything.
        """
        self.register_preloop_hook(self._preloop_hook)
        self.register_postloop_hook(self._postloop_hook)

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

        connected = self.service.connect()
        if not connected:
            self.perror("Failed to connect to WebSocket.")
            self.prompt = "autopipette (disconnected) >> "
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
        self.service.disconnect()
        self.poutput("WebSocket client closed.")
        self.poutput("Exited.")
        logger.info("Shell shutdown complete")

"""Protocol execution commands for the Tricca AutoPipette Shell.

This module provides shell commands for running protocol scripts,
controlling execution (pause, resume, cancel), and handling emergency stops.
"""

from __future__ import annotations

from pathlib import Path

from cmd2 import Statement, with_argparser
from pipette_constants import DefaultPaths
from rich import print as rprint

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import RunArgs, TAPCmdParsers


class ProtocolCommands(TAPCommandSet):
    """Commands for executing and controlling protocols.

    Provides shell commands for:
    - Running protocol script files
    - Emergency stop operations
    - Pausing and resuming execution
    - Canceling active protocols
    - Interactive breakpoints

    Example:
        >>> run my_protocol.tap
        >>> pause
        >>> resume
        >>> cancel
        >>> stop
    """

    def __init__(self) -> None:
        """Initialize protocol commands."""
        super().__init__()

    # =========================================================================
    # PROTOCOL EXECUTION
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_run)  # type: ignore[arg-type]
    def do_run(self, args: RunArgs) -> None:
        """Execute a protocol script file.

        Reads the protocol file, executes each command in batch mode to
        accumulate G-code, then uploads and runs the result as a single
        file on the pipette.

        Args:
            args: Parsed arguments containing filename.

        Example:
            >>> run my_protocol.tap
            >>> run protocols/calibration.tap

        Note:
            Protocol files contain TAP shell commands, one per line.
            Lines starting with # and blank lines are ignored.
        """
        filename: str = args.filename
        proto_path = DefaultPaths.DIR_PROTOCOL / filename

        if not proto_path.exists():
            rprint(f"[red]Protocol file not found: {proto_path}[/red]")
            rprint(
                f"[dim]Hint: Check '{DefaultPaths.DIR_PROTOCOL}' for "
                f"available protocols.[/dim]"
            )
            return

        if not proto_path.is_file():
            rprint(f"[red]'{proto_path}' is a directory, not a file.[/red]")
            return

        rprint(f"[cyan]Running protocol: {filename}[/cyan]")

        try:
            lines = proto_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as e:
            rprint(f"[red]Error reading protocol file (encoding issue): {e}[/red]")
            return

        commands = [
            line + "\n"
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]

        if not commands:
            rprint("[yellow]Protocol file is empty or contains only comments.[/yellow]")
            return

        rprint(f"[dim]Executing {len(commands)} command(s)...[/dim]")

        try:
            with self.shell.gcode_manager.batch_mode():
                self.shell.runcmds_plus_hooks(
                    commands,
                    add_to_history=False,
                    stop_on_keyboard_interrupt=True,
                )

            gcode_buffer = self.shell.gcode_manager.get_buffer()

            if not gcode_buffer:
                rprint("[yellow]No G-code generated from protocol.[/yellow]")
                self.shell.gcode_manager.clear_buffer()
                return

            # Output filename is always a flat .gcode file regardless of
            # any subdirectory in the input path — intentional.
            output_filename = Path(filename).with_suffix(".gcode").name

            file_path = self.shell.gcode_manager.write_gcode_file(
                gcode_buffer, output_filename, append_header=True
            )

            rprint(
                f"[green]G-code generated: {output_filename} "
                f"({len(gcode_buffer)} lines)[/green]"
            )

            self.shell.upload_and_execute_gcode(
                output_filename, file_path, delete_file=True
            )

            rprint(
                f"[bold green]✓ Protocol '{filename}' executed "
                f"successfully.[/bold green]"
            )

        except IOError as e:
            self.shell.perror(f"Failed to write protocol G-code: {e}")
        except Exception as e:
            self.shell.perror(f"Error executing protocol: {e}")
        finally:
            # Always clear the buffer, whether the run succeeded or failed.
            self.shell.gcode_manager.clear_buffer()

    # =========================================================================
    # INTERACTIVE BREAKPOINT
    # =========================================================================

    def do_break(self, _: Statement) -> None:
        """Pause protocol execution for user confirmation.

        Inserts an interactive breakpoint into a running protocol.
        The user is prompted to continue or abort. Intended for use
        inside protocol files to allow manual intervention mid-run.

        Example:
            In a protocol file::

                move_loc plate_a
                break
                pipette 100 source dest

        Raises:
            KeyboardInterrupt: If the user selects "No", stopping
                ``runcmds_plus_hooks`` when run with
                ``stop_on_keyboard_interrupt=True``.
        """
        result = self.shell.select(["Yes", "No"], prompt="Continue protocol execution?")

        if result == "No":
            rprint("[yellow]Protocol execution stopped by user.[/yellow]")
            raise KeyboardInterrupt
        else:
            rprint("[green]Continuing protocol execution...[/green]")

    # =========================================================================
    # WEBSOCKET CONTROL COMMANDS
    # =========================================================================

    def _check_websocket(self) -> bool:
        """Check if the WebSocket client is connected and ready.

        Returns:
            True if connected, False otherwise.

        Note:
            Uses ``self.shell.client`` to match the attribute name used by
            WebSocketCommands. If the shell stores the client under a
            different name, update both this method and WebSocketCommands
            to match.
        """
        # NOTE: must match the attribute name used in tap_shell.py.
        # websocket_commands.py uses `self.shell.client` — kept consistent.
        ws_client = getattr(self.shell, "client", None)

        if not ws_client or not ws_client.is_connected():
            rprint(
                "[yellow]WebSocket not connected. "
                "Cannot communicate with pipette.[/yellow]"
            )
            return False

        return True

    def do_stop(self, _: Statement) -> None:
        """Send an emergency stop to the pipette.

        Immediately halts all motion. The pipette must be re-homed
        before resuming normal operation.

        Example:
            >>> stop
        """
        rprint("[bold red]⚠ EMERGENCY STOP ⚠[/bold red]")

        if not self._check_websocket():
            return

        try:
            request = self.shell.mrr.printer_emergency_stop()
            self.shell.send_rpc(request)
            rprint("[bold red]Emergency stop sent.[/bold red]")
            rprint("[yellow]Re-home the pipette before continuing.[/yellow]")
        except Exception as e:
            rprint(f"[red]Failed to send emergency stop: {e}[/red]")

    def do_pause(self, _: Statement) -> None:
        """Pause the current protocol execution.

        Example:
            >>> pause
        """
        rprint("[yellow]⏸ Pausing protocol...[/yellow]")

        if not self._check_websocket():
            return

        try:
            request = self.shell.mrr.printer_print_pause()
            self.shell.send_rpc(request)
            rprint("[green]Protocol paused.[/green]")
            rprint("[dim]Use 'resume' to continue.[/dim]")
        except Exception as e:
            rprint(f"[red]Failed to pause protocol: {e}[/red]")

    def do_resume(self, _: Statement) -> None:
        """Resume paused protocol execution.

        Example:
            >>> resume
        """
        rprint("[cyan]▶ Resuming protocol...[/cyan]")

        if not self._check_websocket():
            return

        try:
            request = self.shell.mrr.printer_print_resume()
            self.shell.send_rpc(request)
            rprint("[green]Protocol resumed.[/green]")
        except Exception as e:
            rprint(f"[red]Failed to resume protocol: {e}[/red]")

    def do_cancel(self, _: Statement) -> None:
        """Cancel the current protocol execution.

        Example:
            >>> cancel
        """
        rprint("[yellow]⏹ Canceling protocol...[/yellow]")

        if not self._check_websocket():
            return

        try:
            request = self.shell.mrr.printer_print_cancel()
            self.shell.send_rpc(request)
            rprint("[red]Protocol canceled.[/red]")
        except Exception as e:
            rprint(f"[red]Failed to cancel protocol: {e}[/red]")

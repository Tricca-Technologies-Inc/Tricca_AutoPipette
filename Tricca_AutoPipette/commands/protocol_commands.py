"""Protocol execution commands for the Tricca AutoPipette Shell.

This module provides shell commands for running protocol scripts,
controlling execution (pause, resume, cancel), and handling emergency stops.
"""

from __future__ import annotations

from pathlib import Path

from cmd2 import Statement, with_argparser
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
        >>> stop
    """

    def __init__(self) -> None:
        """Initialize protocol commands."""
        super().__init__()

    @with_argparser(TAPCmdParsers.parser_run)  # type: ignore[arg-type]
    def do_run(self, args: RunArgs) -> None:
        """Execute a protocol script file.

        Runs all commands in the protocol file, batches the G-code,
        and uploads as a single file for execution on the pipette.

        Args:
            args: Parsed arguments containing filename.

        Example:
            >>> run my_protocol.tap
            >>> run protocols/calibration.tap

        Note:
            Protocol files should contain TAP shell commands, one per line.
            Comments (lines starting with #) are ignored.
        """
        filename: str = args.filename

        # Resolve protocol file path
        proto_path = self.shell.PROTOCOL_PATH / filename

        # Validate file exists
        if not proto_path.exists():
            rprint(f"[red]Protocol file not found: {proto_path}[/red]")
            rprint(
                f"[dim]Hint: Check '{self.shell.PROTOCOL_PATH}' for "
                f"available protocols.[/dim]"
            )
            return

        # Validate file is readable
        if not proto_path.is_file():
            rprint(f"[red]'{proto_path}' is not a file.[/red]")
            return

        rprint(f"[cyan]Running protocol: {filename}[/cyan]")

        try:
            # Read protocol commands
            lines = proto_path.read_text(encoding="utf-8").splitlines()

            # Filter out empty lines and comments
            commands = [
                line + "\n"
                for line in lines
                if line.strip() and not line.strip().startswith("#")
            ]

            if not commands:
                rprint(
                    "[yellow]Protocol file is empty or contains only "
                    "comments.[/yellow]"
                )
                return

            rprint(f"[dim]Executing {len(commands)} command(s)...[/dim]")

            # Execute commands in batch mode
            with self.shell.gcode_manager.batch_mode():
                self.shell.runcmds_plus_hooks(
                    commands,
                    add_to_history=False,
                    stop_on_keyboard_interrupt=True,
                )

            # Get accumulated G-code
            gcode_buffer = self.shell.gcode_manager.get_buffer()

            if not gcode_buffer:
                rprint("[yellow]No G-code generated from protocol.[/yellow]")
                return

            # Generate output filename
            output_filename = Path(filename).with_suffix(".gcode").name

            # Write G-code to file with header
            try:
                file_path = self.shell.gcode_manager.write_gcode_file(
                    gcode_buffer, output_filename, append_header=True
                )

                rprint(
                    f"[green]G-code generated: {output_filename} "
                    f"({len(gcode_buffer)} lines)[/green]"
                )

                # Upload and execute
                self.shell.upload_and_execute_gcode(
                    output_filename, file_path, delete_file=True
                )

                rprint(
                    f"[bold green]✓ Protocol '{filename}' executed "
                    f"successfully[/bold green]"
                )

            except IOError as e:
                self.shell.perror(f"Failed to write protocol G-code: {e}")
            except Exception as e:
                self.shell.perror(f"Failed to upload/execute protocol: {e}")
            finally:
                # Ensure buffer is cleared even if upload fails
                self.shell.gcode_manager.clear_buffer()

        except UnicodeDecodeError as e:
            rprint(f"[red]Error reading protocol file (encoding issue): " f"{e}[/red]")
        except Exception as e:
            rprint(f"[red]Error executing protocol: {e}[/red]")
            # Clear buffer on error
            self.shell.gcode_manager.clear_buffer()

    def _check_websocket(self) -> bool:
        """Check if WebSocket is connected and ready.

        Returns:
            True if connected, False otherwise.
        """
        ws_client = getattr(self.shell, "ws_client", None)

        if not ws_client or not ws_client.is_connected():
            rprint(
                "[yellow]WebSocket not connected. "
                "Cannot communicate with pipette.[/yellow]"
            )
            return False

        return True

    def do_stop(self, _: Statement) -> None:
        """Send emergency stop to the pipette."""
        rprint("[bold red]⚠ EMERGENCY STOP ⚠[/bold red]")

        if not self._check_websocket():
            return

        try:
            request = self.shell.mrr.printer_emergency_stop()
            self.shell.send_rpc(request)

            rprint("[bold red]Emergency stop sent.[/bold red]")
            rprint("[yellow]Please re-home the pipette before continuing." "[/yellow]")
        except Exception as e:
            rprint(f"[red]Failed to send emergency stop: {e}[/red]")

    def do_pause(self, _: Statement) -> None:
        """Pause the current protocol execution."""
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
        """Resume paused protocol execution."""
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
        """Cancel the current protocol execution."""
        rprint("[yellow]⏹ Canceling protocol...[/yellow]")

        if not self._check_websocket():
            return

        try:
            request = self.shell.mrr.printer_print_cancel()
            self.shell.send_rpc(request)

            rprint("[red]Protocol canceled.[/red]")
        except Exception as e:
            rprint(f"[red]Failed to cancel protocol: {e}[/red]")

    def do_break(self, _: Statement) -> None:
        """Pause protocol execution for user confirmation.

        Inserts an interactive breakpoint in protocol execution.
        Useful for debugging protocols or manual interventions.

        Raises:
            KeyboardInterrupt: If user chooses not to continue execution.

        Example:
            In a protocol file:
        ```
            move_loc plate_a
            break
            pipette 100 source dest
        ```

        Note:
            This command is intended for use within protocol files.
            Selecting "No" will abort the protocol execution.
        """
        result = self.shell.select(["Yes", "No"], prompt="Continue protocol execution?")

        if result == "No":
            rprint("[yellow]Protocol execution stopped by user.[/yellow]")
            # Could raise an exception to stop protocol execution
            raise KeyboardInterrupt("User stopped protocol at breakpoint")
        else:
            rprint("[green]Continuing protocol execution...[/green]")

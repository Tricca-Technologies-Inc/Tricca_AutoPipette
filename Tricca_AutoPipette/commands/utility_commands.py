#!/usr/bin/env python3
"""Utility commands for the Tricca AutoPipette Shell.

This module provides miscellaneous utility commands including trigger control,
G-code printing, volume conversion, and diagnostic tools.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from rich import print as rprint

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import GcodePrintArgs, TAPCmdParsers, VolToStepsArgs


class UtilityCommands(TAPCommandSet):
    """Miscellaneous utility commands.

    Provides shell commands for:
    - Controlling auxiliary triggers (air, shake, aux)
    - Sending messages to the pipette display
    - Converting volumes to motor steps
    - Accessing webcam stream
    - Testing and diagnostics

    Example:
        >>> trigger air on
        >>> gcode_print "Protocol started"
        >>> vol_to_steps 100
        >>> webcam
    """

    # Valid trigger channels
    VALID_CHANNELS = {"air", "shake", "aux"}

    # Valid trigger states
    VALID_STATES = {"on", "off"}

    def __init__(self) -> None:
        """Initialize utility commands."""
        super().__init__()

    def do_trigger(self, arg: str) -> None:
        """Control auxiliary triggers (air, shake, aux).

        Activates or deactivates auxiliary control channels for
        pneumatics, shakers, or other auxiliary equipment.

        Usage:
            trigger <channel> <state>

        Args:
            arg: Space-separated channel and state.

        Example:
            >>> trigger air on
            >>> trigger shake off
            >>> trigger aux on

        Note:
            Valid channels: air, shake, aux
            Valid states: on, off
            This feature is not yet implemented.
        """
        # autopipette = self.shell._autopipette

        # Parse arguments
        parts = arg.split()
        if len(parts) != 2:
            rprint("[yellow]Usage: trigger <air|shake|aux> <on|off>[/yellow]")
            rprint(f"[cyan]Valid channels: {', '.join(self.VALID_CHANNELS)}" f"[/cyan]")
            rprint(f"[cyan]Valid states: {', '.join(self.VALID_STATES)}[/cyan]")
            return

        channel, state = parts
        channel = channel.lower()
        state = state.lower()

        # Validate channel
        if channel not in self.VALID_CHANNELS:
            rprint(f"[yellow]Invalid channel '{channel}'.[/yellow]")
            rprint(f"[cyan]Valid channels: {', '.join(self.VALID_CHANNELS)}" f"[/cyan]")
            return

        # Validate state
        if state not in self.VALID_STATES:
            rprint(f"[yellow]Invalid state '{state}'.[/yellow]")
            rprint(f"[cyan]Valid states: {', '.join(self.VALID_STATES)}" f"[/cyan]")
            return

        # TODO: Implement trigger functionality in AutoPipette
        rprint("[yellow]Trigger functionality not yet implemented.[/yellow]")
        rprint(f"[dim]Would turn '{channel}' {state}[/dim]")

        # Future implementation:
        # try:
        #     autopipette.set_trigger(channel, state)
        #     self.shell.output_gcode(autopipette.get_gcode())
        #
        #     emoji = "✓" if state == "on" else "✗"
        #     rprint(
        #         f"[green]{emoji} Trigger '{channel}' turned {state}[/green]"
        #     )
        # except Exception as e:
        #     rprint(f"[red]Trigger error: {e}[/red]")

    def do_print(self, _: Statement) -> None:
        """Test print command for debugging.

        Simple diagnostic command to test shell output.

        Example:
            >>> print
        """
        rprint("[cyan]Print command executed successfully.[/cyan]")

    @with_argparser(TAPCmdParsers.parser_gcode_print)  # type: ignore[arg-type]
    def do_gcode_print(self, args: GcodePrintArgs) -> None:
        """Send a message to be displayed by the pipette.

        Sends a message that will be displayed on the pipette's
        display or logged in the G-code output.

        Args:
            args: Parsed arguments containing message.

        Example:
            >>> gcode_print "Protocol started"
            >>> gcode_print "Dispensing sample 1"

        Note:
            Messages are embedded in G-code as comments and/or
            M117 display commands.
        """
        autopipette = self.shell._autopipette
        msg: str = args.msg

        if not msg.strip():
            rprint("[yellow]Message cannot be empty.[/yellow]")
            return

        try:
            autopipette.gcode_print(msg)
            self.shell.output_gcode(autopipette.get_gcode())

            rprint(f"[dim]Message: {msg}[/dim]")
            rprint("[green]Message sent to pipette.[/green]")
        except Exception as e:
            rprint(f"[red]Error sending message: {e}[/red]")

    def do_webcam(self, _: Statement) -> None:
        """Open or display webcam stream URL.

        Provides the URL for accessing the pipette's webcam stream.

        Example:
            >>> webcam
            http://192.168.1.100/webcam/?action=stream

        Note:
            In future versions, this may automatically open the
            stream in a browser or viewer.
        """
        hostname = getattr(self.shell, "hostname", "localhost")
        url = f"http://{hostname}/webcam/?action=stream"

        rprint("[bold cyan]Webcam Stream URL:[/bold cyan]")
        rprint(f"[link={url}]{url}[/link]")
        rprint()
        rprint("[dim]Copy this URL to your browser to view the stream.[/dim]")

        # Future implementation:
        # try:
        #     import webbrowser
        #     webbrowser.open(url)
        #     rprint("[green]Opening webcam in browser...[/green]")
        # except Exception as e:
        #     rprint(f"[yellow]Could not open browser: {e}[/yellow]")

    def do_request(self, _: Statement) -> None:
        """Test JSON-RPC request (diagnostic command).

        Placeholder for testing JSON-RPC communication with the
        pipette server.

        Example:
            >>> request

        Note:
            This is a diagnostic command. Full implementation pending.
        """
        rprint("[yellow]Request command not yet implemented.[/yellow]")
        rprint(
            "[dim]This command is reserved for testing JSON-RPC " "communication.[/dim]"
        )

    @with_argparser(TAPCmdParsers.parser_vol_to_steps)  # type: ignore[arg-type]
    def do_vol_to_steps(self, args: VolToStepsArgs) -> None:
        """Convert volume to motor steps.

        Calculates the number of motor steps required to dispense
        a given volume based on the current calibration.

        Args:
            args: Parsed arguments containing volume in microliters.

        Example:
            >>> vol_to_steps 100
            100 µL = 4523 steps

            >>> vol_to_steps 250
            250 µL = 11307 steps

        Note:
            Conversion depends on the volume calibration in the
            configuration file.
        """
        vol: float = args.vol

        if vol < 0:
            rprint("[yellow]Volume cannot be negative.[/yellow]")
            return

        try:
            autopipette = self.shell._autopipette
            converter = autopipette.volume_converter

            if converter is None:
                rprint("[yellow]Volume converter not initialized.[/yellow]")
                rprint("[dim]Check that VOLUME_CONV section is in config.[/dim]")
                return

            steps = converter.vol_to_steps(vol)

            rprint(f"[cyan]{vol} µL[/cyan] = " f"[green]{steps} steps[/green]")

            # Show reverse conversion for verification
            actual_vol = converter.steps_to_vol(steps)
            if abs(actual_vol - vol) > 0.01:
                rprint(
                    f"[dim]Note: {steps} steps = {actual_vol:.2f} µL "
                    f"(rounding difference)[/dim]"
                )
        except Exception as e:
            rprint(f"[red]Conversion error: {e}[/red]")

    def do_steps_to_vol(self, arg: str) -> None:
        """Convert motor steps to volume.

        Inverse of vol_to_steps. Calculates the volume that would
        be dispensed by a given number of motor steps.

        Usage:
            steps_to_vol <steps>

        Args:
            arg: Number of steps (integer).

        Example:
            >>> steps_to_vol 4523
            4523 steps = 100.00 µL
        """
        if not arg.strip():
            rprint("[yellow]Usage: steps_to_vol <steps>[/yellow]")
            return

        try:
            steps = int(arg.strip())

            if steps < 0:
                rprint("[yellow]Steps cannot be negative.[/yellow]")
                return

            autopipette = self.shell._autopipette
            converter = autopipette.volume_converter

            if converter is None:
                rprint("[yellow]Volume converter not initialized.[/yellow]")
                rprint("[dim]Check that VOLUME_CONV section is in config.[/dim]")
                return

            vol = converter.steps_to_vol(steps)

            rprint(f"[cyan]{steps} steps[/cyan] = " f"[green]{vol:.2f} µL[/green]")
        except ValueError:
            rprint(
                f"[yellow]Invalid steps value: '{arg}'. "
                f"Must be an integer.[/yellow]"
            )
        except Exception as e:
            rprint(f"[red]Conversion error: {e}[/red]")

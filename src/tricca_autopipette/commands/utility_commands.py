"""Utility commands for the Tricca AutoPipette Shell.

This module provides miscellaneous utility commands including trigger control,
G-code printing, volume conversion, timed waits, and diagnostics.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from rich import print as rprint

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import (
    GcodePrintArgs,
    TAPCmdParsers,
    TriggerArgs,
    VolToStepsArgs,
    WaitArgs,
)


class UtilityCommands(TAPCommandSet):
    """Miscellaneous utility commands.

    Provides shell commands for:
    - Inserting timed pauses into G-code output
    - Controlling auxiliary triggers (air, shake, aux)
    - Sending messages to the pipette display
    - Converting volumes to motor steps and vice versa
    - Accessing the webcam stream URL

    Example:
        >>> wait 500
        >>> trigger air on
        >>> gcode_print "Protocol started"
        >>> vol_to_steps 100
        >>> steps_to_vol 4523
        >>> webcam
    """

    # Valid trigger channels and states — kept as class constants so they
    # remain a single source of truth if trigger support is added later.
    VALID_CHANNELS: frozenset[str] = frozenset({"air", "shake", "aux"})
    VALID_STATES: frozenset[str] = frozenset({"on", "off"})

    def __init__(self) -> None:
        """Initialize utility commands."""
        super().__init__()

    # =========================================================================
    # TIMING
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_wait)  # type: ignore[arg-type]
    def do_wait(self, args: WaitArgs) -> None:
        """Insert a timed pause into the G-code output.

        Emits a dwell command that pauses pipette execution for the
        specified duration. Useful in protocol files between steps that
        require settling time.

        Args:
            args: Parsed arguments containing duration in milliseconds.

        Example:
            >>> wait 500
            >>> wait 2000
        """
        if args.ms <= 0:
            rprint("[yellow]Wait duration must be greater than zero.[/yellow]")
            return

        try:
            autopipette = self.shell._autopipette
            autopipette.gcode_wait(args.ms)
            self.shell.output_gcode(autopipette.get_gcode())
            rprint(f"[green]✓ Wait: {args.ms:.0f} ms[/green]")
        except Exception as e:
            rprint(f"[red]Wait error: {e}[/red]")

    # =========================================================================
    # TRIGGERS
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_trigger)  # type: ignore[arg-type]
    def do_trigger(self, args: TriggerArgs) -> None:
        """Control auxiliary triggers (air, shake, aux).

        Activates or deactivates auxiliary control channels for
        pneumatics, shakers, or other auxiliary equipment.

        Args:
            args: Parsed arguments containing channel and state.

        Example:
            >>> trigger air on
            >>> trigger shake off
            >>> trigger aux on

        Note:
            Valid channels: air, shake, aux
            Valid states: on, off
            This feature is not yet implemented.
        """
        channel = args.channel.lower()
        state = args.state.lower()

        if channel not in self.VALID_CHANNELS:
            rprint(f"[yellow]Invalid channel '{channel}'.[/yellow]")
            rprint(
                f"[cyan]Valid channels: {', '.join(sorted(self.VALID_CHANNELS))}[/cyan]"
            )
            return

        if state not in self.VALID_STATES:
            rprint(f"[yellow]Invalid state '{state}'.[/yellow]")
            rprint(f"[cyan]Valid states: {', '.join(sorted(self.VALID_STATES))}[/cyan]")
            return

        # TODO: Implement trigger functionality in AutoPipette.
        # autopipette = self.shell._autopipette
        # autopipette.set_trigger(channel, state)
        # self.shell.output_gcode(autopipette.get_gcode())
        # emoji = "✓" if state == "on" else "✗"
        # rprint(f"[green]{emoji} Trigger '{channel}' turned {state}[/green]")
        rprint("[yellow]Trigger functionality not yet implemented.[/yellow]")
        rprint(f"[dim]Would turn '{channel}' {state}.[/dim]")

    # =========================================================================
    # G-CODE / DISPLAY
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_gcode_print)  # type: ignore[arg-type]
    def do_gcode_print(self, args: GcodePrintArgs) -> None:
        """Send a message to be displayed on the pipette screen.

        Embeds an M117 display command in the G-code output so the
        message appears on the controller screen during execution.

        Args:
            args: Parsed arguments containing the message string.

        Example:
            >>> gcode_print "Protocol started"
            >>> gcode_print "Dispensing sample 1"
        """
        msg: str = args.msg

        if not msg.strip():
            rprint("[yellow]Message cannot be empty.[/yellow]")
            return

        try:
            autopipette = self.shell._autopipette
            autopipette.gcode_print(msg)
            self.shell.output_gcode(autopipette.get_gcode())
            rprint(f"[green]✓ Display message queued:[/green] [dim]{msg}[/dim]")
        except Exception as e:
            rprint(f"[red]Error sending message: {e}[/red]")

    # =========================================================================
    # WEBCAM
    # =========================================================================

    def do_webcam(self, _: Statement) -> None:
        """Print the webcam stream URL for this pipette.

        Constructs the Moonraker webcam stream URL from the configured
        hostname and prints it for use in a browser or viewer.

        Example:
            >>> webcam
            Webcam Stream URL:
            http://192.168.1.100/webcam/?action=stream
        """
        hostname = getattr(self.shell, "hostname", "localhost")
        url = f"http://{hostname}/webcam/?action=stream"

        rprint("[bold cyan]Webcam Stream URL:[/bold cyan]")
        rprint(f"[link={url}]{url}[/link]")
        rprint("[dim]Copy this URL to your browser to view the stream.[/dim]")
        # TODO: consider auto-opening via webbrowser.open(url)

    # =========================================================================
    # VOLUME / STEP CONVERSION
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_vol_to_steps)  # type: ignore[arg-type]
    def do_vol_to_steps(self, args: VolToStepsArgs) -> None:
        """Convert a volume in µL to motor steps.

        Calculates the number of motor steps required to move the given
        volume based on the active liquid's calibration curve.

        Args:
            args: Parsed arguments containing volume in microliters.

        Example:
            >>> vol_to_steps 100
            100.0 µL = 4523 steps

            >>> vol_to_steps 250
            250.0 µL = 11307 steps
        """
        if args.vol <= 0:
            rprint("[yellow]Volume must be greater than zero.[/yellow]")
            return

        try:
            autopipette = self.shell._autopipette
            converter = autopipette.volume_converter

            if converter is None:
                rprint("[yellow]Volume converter not initialised.[/yellow]")
                rprint("[dim]Check calibration data is present in config.[/dim]")
                return

            steps = converter.vol_to_steps(args.vol)
            rprint(f"[cyan]{args.vol} µL[/cyan] = [green]{steps} steps[/green]")

            # Show reverse conversion to surface any rounding difference
            actual_vol = converter.steps_to_vol(steps)
            if abs(actual_vol - args.vol) > 0.01:
                rprint(
                    f"[dim]Note: {steps} steps → {actual_vol:.2f} µL "
                    f"(rounding difference)[/dim]"
                )
        except Exception as e:
            rprint(f"[red]Conversion error: {e}[/red]")

    def do_steps_to_vol(self, arg: str) -> None:
        """Convert motor steps to volume in µL.

        Inverse of ``vol_to_steps``. Calculates the volume that would be
        displaced by the given number of motor steps under the active
        liquid's calibration.

        Usage:
            steps_to_vol <steps>

        Args:
            arg: Number of steps (integer or float, truncated to int).

        Example:
            >>> steps_to_vol 4523
            4523 steps = 100.00 µL

        Note:
            A ``StepsToVolArgs`` parser will be added to TAPCmdParsers in
            a future pass so this command gains tab-completion and --help.
        """
        if not arg.strip():
            rprint("[yellow]Usage: steps_to_vol <steps>[/yellow]")
            return

        try:
            # Accept floats (e.g. 4523.0) and truncate to int
            steps = int(float(arg.strip()))
        except ValueError:
            rprint(
                f"[yellow]Invalid steps value: '{arg.strip()}'. "
                "Must be a number.[/yellow]"
            )
            return

        if steps < 0:
            rprint("[yellow]Steps cannot be negative.[/yellow]")
            return

        try:
            autopipette = self.shell._autopipette
            converter = autopipette.volume_converter

            if converter is None:
                rprint("[yellow]Volume converter not initialised.[/yellow]")
                rprint("[dim]Check calibration data is present in config.[/dim]")
                return

            vol = converter.steps_to_vol(steps)
            rprint(f"[cyan]{steps} steps[/cyan] = [green]{vol:.2f} µL[/green]")
        except Exception as e:
            rprint(f"[red]Conversion error: {e}[/red]")

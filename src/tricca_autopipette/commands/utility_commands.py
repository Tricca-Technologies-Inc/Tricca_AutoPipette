"""Utility commands for the Tricca AutoPipette Shell.

This module provides miscellaneous utility commands including trigger control,
G-code printing, volume conversion, timed waits, and diagnostics.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from rich import print as rprint

from tricca_autopipette.cli.report_tables import build_calibration_table
from tricca_autopipette.commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import (
    GcodePrintArgs,
    SeeCalibrationArgs,
    TAPCmdParsers,
    TriggerArgs,
    VolToStepsArgs,
    WaitArgs,
)


class UtilityCommands(TAPCommandSet):
    """Miscellaneous utility commands.

    Thin cmd2 adapter: each ``do_*`` method only parses arguments and
    renders the result -- the actual logic lives on ``AutoPipetteService``
    (``daemon/service.py``), reached via ``self.service`` (see
    ``base_command_set.py``'s ``TAPCommandSet.service`` property for why
    this indirection is temporary).

    Provides shell commands for:
    - Inserting timed pauses into G-code output
    - Controlling auxiliary triggers (air, shake, aux)
    - Sending messages to the pipette display
    - Converting volumes to motor steps and vice versa
    - Accessing the webcam stream URL
    - Showing a liquid's calibration curve and fitted line

    Example:
        wait 500
        trigger air on
        gcode_print "Protocol started"
        vol_to_steps 100
        steps_to_vol 4523
        webcam
        see_calibration
    """

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
            wait 500
            wait 2000
        """
        try:
            result = self.service.wait(args)
            if result.ok:
                rprint(f"[green]✓ {result.message}[/green]")
            else:
                rprint(f"[yellow]{result.message}[/yellow]")
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
            trigger air on
            trigger shake off
            trigger aux on

        Note:
            Valid channels: air, shake, aux
            Valid states: on, off
            This feature is not yet implemented.
        """
        result = self.service.trigger(args)
        rprint(f"[yellow]{result.message}[/yellow]")

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
            gcode_print "Protocol started"
            gcode_print "Dispensing sample 1"
        """
        try:
            result = self.service.gcode_print(args)
            if result.ok:
                rprint(
                    f"[green]✓ Display message queued:[/green] [dim]{args.msg}[/dim]"
                )
            else:
                rprint(f"[yellow]{result.message}[/yellow]")
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
            webcam
            Webcam Stream URL:
            http://192.168.1.100/webcam/?action=stream
        """
        result = self.service.webcam_url()
        url = result.message

        rprint("[bold cyan]Webcam Stream URL:[/bold cyan]")
        rprint(f"[link={url}]{url}[/link]")
        rprint("[dim]Copy this URL to your browser to view the stream.[/dim]")

    # =========================================================================
    # VOLUME / STEP CONVERSION
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_vol_to_steps)  # type: ignore[arg-type]
    def do_vol_to_steps(self, args: VolToStepsArgs) -> None:
        """Convert a volume in μL to motor steps.

        Calculates the number of motor steps required to move the given
        volume based on the active liquid's calibration curve.

        Args:
            args: Parsed arguments containing volume in microliters.

        Example:
            vol_to_steps 100
            100.0 μL = 4523 steps

            vol_to_steps 250
            250.0 μL = 11307 steps
        """
        try:
            result = self.service.vol_to_steps(args)
            if not result.ok:
                rprint(f"[yellow]{result.message}[/yellow]")
                return

            data = result.data or {}
            rprint(
                f"[cyan]{args.vol} μL[/cyan] = [green]{data.get('steps')} steps[/green]"
            )

            # Show reverse conversion to surface any rounding difference
            actual_vol = data.get("round_trip_vol")
            if actual_vol is not None and abs(actual_vol - args.vol) > 0.01:
                rprint(
                    f"[dim]Note: {data.get('steps')} steps → {actual_vol:.2f} μL "
                    f"(rounding difference)[/dim]"
                )
        except Exception as e:
            rprint(f"[red]Conversion error: {e}[/red]")

    def do_steps_to_vol(self, arg: str) -> None:
        """Convert motor steps to volume in μL.

        Inverse of ``vol_to_steps``. Calculates the volume that would be
        displaced by the given number of motor steps under the active
        liquid's calibration.

        Usage:
            steps_to_vol <steps>

        Args:
            arg: Number of steps (integer or float, truncated to int).

        Example:
            steps_to_vol 4523
            4523 steps = 100.00 μL

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

        try:
            result = self.service.steps_to_vol(steps)
            if not result.ok:
                rprint(f"[yellow]{result.message}[/yellow]")
                return

            vol = (result.data or {}).get("vol")
            rprint(f"[cyan]{steps} steps[/cyan] = [green]{vol:.2f} μL[/green]")
        except Exception as e:
            rprint(f"[red]Conversion error: {e}[/red]")

    # =========================================================================
    # CALIBRATION
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_see_calibration)  # type: ignore[arg-type]
    def do_see_calibration(self, args: SeeCalibrationArgs) -> None:
        """Show a liquid's calibration curve and its fitted line.

        Displays the (volume, plunger-travel) points a liquid's motion is
        actually fit from -- the liquid's own override if it has one,
        otherwise the pipette's base curve -- plus the resulting linear
        equation ``travel_mm = A * volume_ul + B``.

        Args:
            args: Liquid profile to inspect, or None for the active liquid.

        Example:
            see_calibration
            see_calibration methanol
        """
        try:
            result = self.service.see_calibration(args.liquid)
        except (ValueError, RuntimeError) as e:
            rprint(f"[red]{e}[/red]")
            return

        data = result.data or {}
        volumes_ul: list[float] = data.get("volumes_ul") or []
        travel_mm: list[float] = data.get("travel_mm") or []
        if not volumes_ul:
            rprint(f"[yellow]{result.message}[/yellow]")
            return

        rprint(f"[bold]{data.get('liquid')}[/bold] [dim]({data.get('source')})[/dim]")
        rprint(build_calibration_table(volumes_ul, travel_mm))
        rprint(
            f"[cyan]travel_mm = {data.get('slope'):.6f} * volume_ul "
            f"+ {data.get('intercept'):.6f}[/cyan]"
        )

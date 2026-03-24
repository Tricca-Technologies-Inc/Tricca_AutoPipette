"""Pipetting-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for core pipetting operations including
liquid transfer, tip management, and advanced dispensing patterns.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from pipette_exceptions import NoTipboxError, NoWasteContainerError, TipAlreadyOnError
from pipette_models import TipState
from rich import print as rprint

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import AspirateArgs, DispenseArgs, PipetteArgs, TAPCmdParsers


class PipetteCommands(TAPCommandSet):
    """Commands for pipetting operations.

    Provides shell commands for:
    - Complete liquid transfer (aspirate, dispense, tip disposal)
    - Tip management (pickup, eject, dispose, change)
    - Advanced features (prewet, wiggle, touch-off, air gap)

    Example:
        >>> next_tip
        >>> aspirate 100 reservoir
        >>> dispense 50 plate_a --dest_row 0 --dest_col 0
        >>> dispense 50 plate_a --dest_row 0 --dest_col 1
        >>> dispose_tip
        >>> pipette 200 source dest --prewet 2 --wiggle
    """

    def __init__(self) -> None:
        """Initialize pipette commands."""
        super().__init__()

    # =========================================================================
    # ASPIRATE / DISPENSE (manual multi-step)
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_aspirate)  # type: ignore[arg-type]
    def do_aspirate(self, args: AspirateArgs) -> None:
        """Aspirate liquid from a source without dispensing.

        Useful for multi-dispense operations where you aspirate once then
        dispense to several destinations. A tip must already be attached.

        Args:
            args: Parsed arguments containing source and volume.

        Example:
            >>> next_tip
            >>> aspirate 100 reservoir
            >>> dispense 50 plate_a --dest_row 0 --dest_col 0
            >>> dispense 50 plate_a --dest_row 0 --dest_col 1
            >>> dispose_tip

        Note:
            Remember to dispose or eject the tip when done.
        """
        autopipette = self.shell._autopipette

        if autopipette.state.tip_state != TipState.ATTACHED:
            rprint("[yellow]No tip attached. Use 'next_tip' first.[/yellow]")
            return

        if args.vol_ul <= 0:
            rprint("[yellow]Volume must be greater than zero.[/yellow]")
            return

        if not autopipette.location_manager.has_location(args.source):
            rprint(f"[yellow]Source location '{args.source}' does not exist.[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        try:
            autopipette.aspirate_volume(
                volume=args.vol_ul,
                source=args.source,
                src_row=args.src_row,
                src_col=args.src_col,
                pre_aspirate_air=args.pre_aspirate_air,
                post_aspirate_air=args.post_aspirate_air,
                prewet=args.prewet,
                prewet_vol=args.prewet_vol,
            )
            self.shell.output_gcode(autopipette.get_gcode())
            rprint(f"[green]✓ Aspirated {args.vol_ul} µL from {args.source}[/green]")

        except Exception as e:
            rprint(f"[red]Aspiration error: {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_dispense)  # type: ignore[arg-type]
    def do_dispense(self, args: DispenseArgs) -> None:
        """Dispense liquid to a destination.

        Dispenses liquid that was previously aspirated. Useful for
        multi-dispense operations.

        Args:
            args: Parsed arguments containing destination and options.

        Example:
            >>> aspirate 100 reservoir
            >>> dispense 25 plate_a --dest_row 0 --dest_col 0
            >>> dispense 25 plate_a --dest_row 0 --dest_col 1
            >>> dispense 25 plate_a --dest_row 0 --dest_col 2
            >>> dispense 25 plate_a --dest_row 0 --dest_col 3
            >>> dispose_tip

        Note:
            Omit --volume to dispense all remaining liquid.
        """
        autopipette = self.shell._autopipette

        if not autopipette.location_manager.has_location(args.dest):
            rprint(f"[yellow]Destination '{args.dest}' does not exist.[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        if not autopipette.state.has_liquid:
            rprint("[yellow]No liquid in tip. Use 'aspirate' first.[/yellow]")
            return

        try:
            autopipette.dispense_volume(
                dest=args.dest,
                dest_row=args.dest_row,
                dest_col=args.dest_col,
                volume=args.volume,
                wiggle=args.wiggle,
                touch=args.touch,
            )
            self.shell.output_gcode(autopipette.get_gcode())

            if args.volume is not None:
                rprint(f"[green]✓ Dispensed {args.volume} µL to {args.dest}[/green]")
            else:
                rprint(f"[green]✓ Dispensed all liquid to {args.dest}[/green]")

        except Exception as e:
            rprint(f"[red]Dispense error: {e}[/red]")

    # =========================================================================
    # FULL TRANSFER
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_pipette)  # type: ignore[arg-type]
    def do_pipette(self, args: PipetteArgs) -> None:
        """Transfer liquid from source to destination.

        Performs a complete pipetting operation: tip pickup (if needed),
        aspiration, dispensing, and tip disposal. Large volumes are
        automatically chunked into multiple aspirate/dispense cycles.

        Args:
            args: Parsed arguments containing transfer parameters.

        Example:
            >>> pipette 100 plate_a plate_b
            >>> pipette 200 source dest --prewet 2 --wiggle --touch
            >>> pipette 150 src dest --keep_tip
            >>> pipette 300 src dest --dispense_vol 100 --src_row 0 --src_col 0
        """
        autopipette = self.shell._autopipette

        if args.vol_ul <= 0:
            rprint("[yellow]Volume must be greater than zero.[/yellow]")
            return

        if not autopipette.location_manager.has_location(args.source):
            rprint(f"[yellow]Source location '{args.source}' does not exist.[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        if not autopipette.location_manager.has_location(args.dest):
            rprint(f"[yellow]Destination '{args.dest}' does not exist.[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        try:
            autopipette.pipette(
                vol_ul=args.vol_ul,
                source=args.source,
                dest=args.dest,
                disp_vol_ul=args.disp_vol_ul,
                src_row=args.src_row,
                src_col=args.src_col,
                dest_row=args.dest_row,
                dest_col=args.dest_col,
                tipbox_name=args.tipbox_name,
                pre_aspirate_air=args.pre_aspirate_air,
                post_aspirate_air=args.post_aspirate_air,
                prewet=args.prewet,
                prewet_vol=args.prewet_vol,
                wiggle=args.wiggle,
                touch=args.touch,
                keep_tip=args.keep_tip,
            )

            # Build a descriptive G-code comment
            features = []
            if args.prewet:
                features.append(f"prewet×{args.prewet}")
            if args.wiggle:
                features.append("wiggle")
            if args.touch:
                features.append("touch")
            if args.keep_tip:
                features.append("keep-tip")

            comment = f"\n; Pipette {args.vol_ul} µL from {args.source} to {args.dest}"
            if features:
                comment += f" [{', '.join(features)}]"
            comment += "\n"

            self.shell.output_gcode([comment] + autopipette.get_gcode() + ["\n"])
            rprint(
                f"[green]✓ Pipetting complete "
                f"({args.vol_ul} µL: {args.source} → {args.dest})[/green]"
            )

        except NoTipboxError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Define a tipbox plate in your configuration.[/dim]")
        except TipAlreadyOnError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Use 'dispose_tip' or 'eject_tip' first.[/dim]")
        except NoWasteContainerError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint(
                "[dim]Hint: Define a waste container plate in your configuration,"
                " or use --keep_tip.[/dim]"
            )
        except Exception as e:
            rprint(f"[red]Pipetting error: {e}[/red]")

    # =========================================================================
    # TIP MANAGEMENT
    # =========================================================================

    def do_next_tip(self, _: Statement) -> None:
        """Pick up the next available tip from the tipbox.

        Moves to the tipbox and picks up a tip from the next available
        position. The tipbox automatically tracks which tips have been used.

        Example:
            >>> next_tip

        Note:
            Requires a tipbox to be defined in the configuration.
            Raises an error if a tip is already attached.
        """
        autopipette = self.shell._autopipette

        try:
            autopipette.next_tip()
            self.shell.output_gcode(autopipette.get_gcode())
            rprint("[green]✓ Tip picked up.[/green]")

        except NoTipboxError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Define a tipbox plate in your configuration.[/dim]")
        except TipAlreadyOnError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Use 'dispose_tip' or 'eject_tip' first.[/dim]")
        except Exception as e:
            rprint(f"[red]Error picking up tip: {e}[/red]")

    def do_eject_tip(self, _: Statement) -> None:
        """Eject the current tip in place (does not move to waste).

        Releases the tip at the current position. Useful for returning
        tips to a rack or debugging. Use ``dispose_tip`` for normal
        tip disposal during a protocol.

        Example:
            >>> eject_tip

        Warning:
            The tip is left at the current pipette position, not in the
            waste container.
        """
        autopipette = self.shell._autopipette

        if autopipette.state.tip_state != TipState.ATTACHED:
            rprint("[yellow]No tip attached — nothing to eject.[/yellow]")
            return

        try:
            autopipette.eject_tip()
            self.shell.output_gcode(autopipette.get_gcode())
            rprint("[green]✓ Tip ejected at current position.[/green]")
            rprint("[yellow]Note: Tip was not moved to the waste container.[/yellow]")

        except Exception as e:
            rprint(f"[red]Error ejecting tip: {e}[/red]")

    def do_dispose_tip(self, _: Statement) -> None:
        """Dispose the current tip in the waste container.

        Moves to the waste container and ejects the tip. This is the
        standard way to discard used tips during a protocol.

        Example:
            >>> dispose_tip

        Note:
            Requires a waste container to be defined in the configuration.
        """
        autopipette = self.shell._autopipette

        if autopipette.state.tip_state != TipState.ATTACHED:
            rprint("[yellow]No tip attached — nothing to dispose.[/yellow]")
            return

        try:
            autopipette.dispose_tip()
            self.shell.output_gcode(autopipette.get_gcode())
            rprint("[green]✓ Tip disposed.[/green]")

        except NoWasteContainerError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint(
                "[dim]Hint: Define a waste container plate in your "
                "configuration.[/dim]"
            )
        except Exception as e:
            rprint(f"[red]Error disposing tip: {e}[/red]")

    def do_change_tip(self, _: Statement) -> None:
        """Dispose the current tip and pick up a fresh one.

        Convenience command that combines ``dispose_tip`` and ``next_tip``.
        If no tip is currently attached, skips straight to pickup.

        Example:
            >>> change_tip

        Note:
            Requires both a tipbox and a waste container to be configured.
        """
        autopipette = self.shell._autopipette

        try:
            if autopipette.state.tip_state == TipState.ATTACHED:
                autopipette.dispose_tip()

            autopipette.next_tip()
            self.shell.output_gcode(autopipette.get_gcode())
            rprint("[green]✓ Tip changed.[/green]")

        except NoTipboxError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Define a tipbox plate in your configuration.[/dim]")
        except NoWasteContainerError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint(
                "[dim]Hint: Define a waste container plate in your "
                "configuration.[/dim]"
            )
        except Exception as e:
            rprint(f"[red]Error changing tip: {e}[/red]")

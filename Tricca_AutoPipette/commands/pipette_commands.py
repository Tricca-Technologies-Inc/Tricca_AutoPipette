"""Pipetting-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for core pipetting operations including
liquid transfer, tip management, and advanced dispensing patterns.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from pipette_exceptions import NoTipboxError, NoWasteContainerError, TipAlreadyOnError
from rich import print as rprint

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import AspirateArgs, DispenseArgs, PipetteArgs, TAPCmdParsers


class PipetteCommands(TAPCommandSet):
    """Commands for pipetting operations.

    Provides shell commands for:
    - Complete liquid transfer (aspirate, dispense, tip disposal)
    - Tip management (pickup, eject, dispose)
    - Split dispensing to multiple destinations
    - Advanced features (prewet, wiggle, touch-off)

    Example:
        >>> pipette 100 plate_a plate_b
        >>> pipette 200 source dest --prewet --wiggle
        >>> pipette 300 src "well1:100,well2:200" --splits
        >>> next_tip
        >>> dispose_tip
    """

    def __init__(self) -> None:
        """Initialize pipette commands."""
        super().__init__()

    @with_argparser(TAPCmdParsers.parser_aspirate)  # type: ignore[arg-type]
    def do_aspirate(self, args: AspirateArgs) -> None:
        """Aspirate liquid from a source without dispensing.

        Useful for multi-dispense operations or when you want to
        manually control dispensing.

        Args:
            args: Parsed arguments containing source and volume.

        Example:
            >>> aspirate 100 plate_a
            >>> dispense 50 plate_b --row 0 --col 0
            >>> dispense 50 plate_b --row 0 --col 1
            >>> dispose_tip

        Note:
            Remember to dispose or eject the tip when done.
        """
        autopipette = self.shell._autopipette

        vol_ul: float = args.vol_ul
        source: str = args.source
        src_row: int | None = args.src_row
        src_col: int | None = args.src_col
        prewet: int = args.prewet
        prewet_vol: float = args.prewet_vol
        aspirate_air: float = args.aspirate_air

        # Validate
        if vol_ul <= 0:
            rprint("[yellow]Volume must be greater than zero.[/yellow]")
            return

        if not autopipette.location_manager.has_location(source):
            rprint(f"[yellow]Source location '{source}' does not exist.[/yellow]")
            return

        try:
            autopipette.aspirate_volume(
                volume=vol_ul,
                source=source,
                src_row=src_row,
                src_col=src_col,
                aspirate_air=aspirate_air,
                prewet=prewet,
                prewet_vol=prewet_vol,
            )

            self.shell.output_gcode(autopipette.get_gcode())
            rprint(f"[green]✓ Aspirated {vol_ul} µL from {source}[/green]")

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
            >>> dispense 25 plate_a --row 0 --col 0
            >>> dispense 25 plate_a --row 0 --col 1
            >>> dispense 25 plate_a --row 0 --col 2
            >>> dispense 25 plate_a --row 0 --col 3
            >>> dispose_tip

        Note:
            If no volume specified, dispenses all remaining liquid.
        """
        autopipette = self.shell._autopipette

        dest: str = args.dest
        dest_row: int | None = args.dest_row
        dest_col: int | None = args.dest_col
        volume: float | None = args.volume
        wiggle: bool = args.wiggle
        touch: bool = args.touch

        # Validate
        if not autopipette.location_manager.has_location(dest):
            rprint(f"[yellow]Destination '{dest}' does not exist.[/yellow]")
            return

        if not autopipette.state.has_liquid:
            rprint("[yellow]No liquid in tip. Aspirate first.[/yellow]")
            return

        try:
            autopipette.dispense_volume(
                dest=dest,
                dest_row=dest_row,
                dest_col=dest_col,
                volume=volume,
                wiggle=wiggle,
                touch=touch,
            )

            self.shell.output_gcode(autopipette.get_gcode())

            if volume:
                rprint(f"[green]✓ Dispensed {volume} µL to {dest}[/green]")
            else:
                rprint(f"[green]✓ Dispensed all liquid to {dest}[/green]")

        except Exception as e:
            rprint(f"[red]Dispense error: {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_pipette)  # type: ignore[arg-type]
    def do_pipette(self, args: PipetteArgs) -> None:
        """Transfer liquid from source to destination.

        Performs a complete pipetting operation including tip pickup,
        aspiration, dispensing, and optional tip disposal. Supports
        split dispensing to multiple destinations and advanced features.

        Args:
            args: Parsed arguments containing transfer parameters.

        Example:
            >>> pipette 100 plate_a plate_b
            >>> pipette 200 source dest --prewet --wiggle --touch
            >>> pipette 300 src "well1:100,well2:200" --splits
            >>> pipette 150 src dest --keep-tip

        Note:
            When using --splits, dest argument is ignored. Specify
            destinations in the splits string: "dest1:vol1,dest2:vol2"
        """
        autopipette = self.shell._autopipette
        # Extract arguments
        vol_ul: float = args.vol_ul
        source: str = args.source
        dest: str = args.dest
        prewet: int = args.prewet
        prewet_vol: float = args.prewet_vol
        disp_vol_ul: float | None = args.disp_vol_ul
        aspirate_air: float = args.aspirate_air
        keep_tip: bool = args.keep_tip
        wiggle: bool = args.wiggle
        touch: bool = args.touch
        src_row: int | None = args.src_row
        src_col: int | None = args.src_col
        dest_row: int | None = args.dest_row
        dest_col: int | None = args.dest_col
        tipbox_name: str | None = args.tipbox_name

        # Validate volume
        if vol_ul <= 0:
            rprint("[yellow]Volume must be greater than zero.[/yellow]")
            return

        # Validate source location
        if not autopipette.location_manager.has_location(source):
            rprint(f"[yellow]Source location '{source}' does not exist.[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        # Validate waste infrastructure
        if autopipette.location_manager.waste_container is None:
            rprint("[yellow]No plate set as waste container.[/yellow]")
            rprint(
                "[dim]Hint: Define a waste container plate in your "
                "configuration.[/dim]"
            )
            return

        # Execute pipetting operation
        try:
            autopipette.pipette(
                vol_ul=vol_ul,
                source=source,
                dest=dest,
                disp_vol_ul=disp_vol_ul,
                src_row=src_row,
                src_col=src_col,
                dest_row=dest_row,
                dest_col=dest_col,
                tipbox_name=tipbox_name,
                aspirate_air=aspirate_air,
                prewet=prewet,
                prewet_vol=prewet_vol,
                wiggle=wiggle,
                touch=touch,
                keep_tip=keep_tip,
            )

            comment = f"\n; Pipette {vol_ul} µL from {source} to {dest}\n"

            # Add feature flags to comment
            features = []
            if prewet:
                features.append("prewet")
            if wiggle:
                features.append("wiggle")
            if touch:
                features.append("touch")
            if keep_tip:
                features.append("keep-tip")

            if features:
                comment += f"; Options: {', '.join(features)}\n"

            # Output G-code
            self.shell.output_gcode([comment] + autopipette.get_gcode() + ["\n"])

            # Success feedback
            rprint(f"[green]✓ Pipetting operation generated " f"({vol_ul} µL)[/green]")

        except NoTipboxError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Define a tipbox plate in your configuration.[/dim]")
        except TipAlreadyOnError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Use 'dispose_tip' or 'eject_tip' first.[/dim]")
        except NoWasteContainerError as e:
            rprint(f"[yellow]{e}[/yellow]")
        except Exception as e:
            rprint(f"[red]Pipetting error: {e}[/red]")

    def do_next_tip(self, _: Statement) -> None:
        """Pick up the next available tip from the tip box.

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

            rprint("[green]✓ Tip pickup operation generated[/green]")

        except NoTipboxError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Define a tipbox plate in your configuration.[/dim]")
        except TipAlreadyOnError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Use 'dispose_tip' or 'eject_tip' first.[/dim]")
        except Exception as e:
            rprint(f"[red]Error picking up tip: {e}[/red]")

    def do_eject_tip(self, _: Statement) -> None:
        """Eject the current tip (leave in place).

        Releases the tip at the current position without moving to
        the waste container. Useful for returning tips or debugging.

        Example:
            >>> eject_tip

        Warning:
            The tip will be left at the current pipette position.
            This does not dispose the tip in the waste container.
        """
        autopipette = self.shell._autopipette

        try:
            autopipette.eject_tip()
            self.shell.output_gcode(autopipette.get_gcode())

            rprint("[green]✓ Tip ejection operation generated[/green]")
            rprint(
                "[yellow]Note: Tip ejected at current position "
                "(not in waste)[/yellow]"
            )

        except Exception as e:
            rprint(f"[red]Error ejecting tip: {e}[/red]")

    def do_dispose_tip(self, _: Statement) -> None:
        """Dispose the current tip in the waste container.

        Moves to the waste container and ejects the tip. This is the
        standard way to discard used tips.

        Example:
            >>> dispose_tip

        Note:
            Requires a waste container to be defined in the configuration.
        """
        autopipette = self.shell._autopipette

        try:
            autopipette.dispose_tip()
            self.shell.output_gcode(autopipette.get_gcode())

            rprint("[green]✓ Tip disposal operation generated[/green]")

        except NoWasteContainerError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint(
                "[dim]Hint: Define a waste container plate in your "
                "configuration.[/dim]"
            )
        except Exception as e:
            rprint(f"[red]Error disposing tip: {e}[/red]")

    def do_change_tip(self, _: Statement) -> None:
        """Dispose current tip and pick up a new one.

        Convenience command that combines dispose_tip and next_tip.

        Example:
            >>> change_tip

        Note:
            Requires both tipbox and waste container to be configured.
        """
        autopipette = self.shell._autopipette

        try:
            # Dispose current tip if present
            if autopipette.state.has_tip:
                autopipette.dispose_tip()

            # Pick up new tip
            autopipette.next_tip()

            self.shell.output_gcode(autopipette.get_gcode())
            rprint("[green]✓ Tip changed successfully[/green]")

        except NoTipboxError as e:
            rprint(f"[yellow]{e}[/yellow]")
        except NoWasteContainerError as e:
            rprint(f"[yellow]{e}[/yellow]")
        except Exception as e:
            rprint(f"[red]Error changing tip: {e}[/red]")

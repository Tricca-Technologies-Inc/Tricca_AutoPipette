"""Pipetting-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for core pipetting operations including
liquid transfer, tip management, and advanced dispensing patterns.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from pipette_exceptions import NoTipboxError, NoWasteContainerError, TipAlreadyOnError
from rich import print as rprint
from tap_cmd_parsers import PipetteArgs, TAPCmdParsers

from commands.base_command_set import TAPCommandSet


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
        src: str = args.src
        dest: str = args.dest
        prewet: bool = args.prewet
        disp_vol: float | None = args.disp_vol_ul
        keep_tip: bool = args.keep_tip
        wiggle: bool = args.wiggle
        touch: bool = args.touch
        src_row: int | None = args.src_row
        src_col: int | None = args.src_col
        dest_row: int | None = args.dest_row
        dest_col: int | None = args.dest_col
        splits_spec: str | None = args.splits
        leftover_action: str = args.leftover
        tipbox_name: str | None = args.tipbox_name

        # Validate volume
        if vol_ul <= 0:
            rprint("[yellow]Volume must be greater than zero.[/yellow]")
            return

        # Validate source location
        if not autopipette.location_manager.has_location(src):
            rprint(f"[yellow]Source location '{src}' does not exist.[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
            return

        # Validate destination for single-dispense mode
        if not splits_spec:
            if not autopipette.location_manager.has_location(dest):
                rprint(
                    f"[yellow]Destination location '{dest}' does not exist."
                    f"[/yellow]"
                )
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

        # Validate split destinations and volumes
        if splits_spec:
            try:
                split_list = autopipette._parse_splits_spec(splits_spec)  # type: ignore[attr-defined]
            except ValueError as e:
                rprint(f"[yellow]Invalid --splits format: {e}[/yellow]")
                rprint(
                    "[dim]Format: 'dest1:vol1,dest2:vol2' "
                    "(e.g., 'well1:50,well2:50')[/dim]"
                )
                return
            except Exception as e:
                rprint(f"[red]Error parsing splits: {e}[/red]")
                return

            # Validate each split destination
            for split in split_list:
                if not autopipette.location_manager.has_location(split.dest):
                    rprint(
                        f"[yellow]Split destination '{split.dest}' "
                        f"does not exist.[/yellow]"
                    )
                    return

            # Validate total split volume
            total_split = sum(s.vol_ul for s in split_list)
            if total_split > vol_ul + 1e-6:  # Allow small floating point error
                rprint(
                    f"[yellow]Split volumes total ({total_split:.2f} µL) "
                    f"exceeds aspirate volume ({vol_ul:.2f} µL).[/yellow]"
                )
                return

            # Show split summary
            rprint(
                f"[cyan]Split dispensing: {len(split_list)} destinations, "
                f"{total_split:.2f} µL total[/cyan]"
            )

        # Execute pipetting operation
        try:
            autopipette.pipette(
                vol_ul,
                src,
                dest,
                disp_vol,
                src_row,
                src_col,
                dest_row,
                dest_col,
                keep_tip,
                prewet,
                wiggle,
                splits=splits_spec,
                leftover_action=leftover_action,
                tipbox_name=tipbox_name,
                touch=touch,
            )

            # Build descriptive comment
            if splits_spec:
                dest_desc = f"{len(split_list)} destinations"
            else:
                dest_desc = dest

            comment = f"\n; Pipette {vol_ul} µL from {src} to {dest_desc}\n"

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

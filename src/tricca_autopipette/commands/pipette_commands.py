"""Pipetting-related commands for the Tricca AutoPipette Shell.

This module provides shell commands for core pipetting operations including
liquid transfer, tip management, and advanced dispensing patterns.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from rich import print as rprint

from tricca_autopipette.commands.base_command_set import TAPCommandSet
from tricca_autopipette.core.pipette_exceptions import (
    NotALocationError,
    NoTipboxError,
    NoWasteContainerError,
    TipAlreadyOnError,
)

from .tap_cmd_parsers import AspirateArgs, DispenseArgs, PipetteArgs, TAPCmdParsers


class PipetteCommands(TAPCommandSet):
    """Commands for pipetting operations.

    Thin cmd2 adapter: each ``do_*`` method only parses arguments and
    renders the result -- the actual logic lives on ``AutoPipetteService``
    (``daemon/service.py``), reached via ``self.service`` (see
    ``base_command_set.py``'s ``TAPCommandSet.service`` property for why
    this indirection is temporary).

    Provides shell commands for:
    - Complete liquid transfer (aspirate, dispense, tip disposal)
    - Tip management (pickup, eject, dispose, change)
    - Advanced features (prewet, wiggle, air gap)

    Example:
        next_tip
        aspirate 100 reservoir
        dispense 50 plate_a --dest_row 0 --dest_col 0
        dispense 50 plate_a --dest_row 0 --dest_col 1
        dispose_tip
        pipette 200 source dest --prewet 2 --wiggle
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
            next_tip
            aspirate 100 reservoir
            dispense 50 plate_a --dest_row 0 --dest_col 0
            dispense 50 plate_a --dest_row 0 --dest_col 1
            dispose_tip

        Note:
            Remember to dispose or eject the tip when done.
        """
        try:
            result = self.service.aspirate(args)
            if result.ok:
                rprint(f"[green]✓ {result.message}[/green]")
            else:
                rprint(f"[yellow]{result.message}[/yellow]")
        except NotALocationError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
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
            aspirate 100 reservoir
            dispense 25 plate_a --dest_row 0 --dest_col 0
            dispense 25 plate_a --dest_row 0 --dest_col 1
            dispense 25 plate_a --dest_row 0 --dest_col 2
            dispense 25 plate_a --dest_row 0 --dest_col 3
            dispose_tip

        Note:
            Omit --volume to dispense all remaining liquid.
        """
        try:
            result = self.service.dispense(args)
            if result.ok:
                rprint(f"[green]✓ {result.message}[/green]")
            else:
                rprint(f"[yellow]{result.message}[/yellow]")
        except NotALocationError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
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

        ``--splits`` (a ``DEST:VOL[@WELL];...`` spec) takes over from a plain
        single ``dest`` and does one aspirate followed by N metered dispenses
        instead of chunking, saving a tip pickup and a source trip per
        destination. ``--leftover keep|waste`` is required whenever the
        splits don't consume the whole aspirate. ``--tipbox`` names a
        specific tipbox to draw the tip from instead of the default
        draw order.

        Args:
            args: Parsed arguments containing transfer parameters.

        Example:
            pipette 100 plate_a plate_b
            pipette 200 source dest --prewet 2 --wiggle
            pipette 150 src dest --keep_tip
            pipette 300 src dest --dispense_vol 100 --src_row 0 --src_col 0
            pipette 100 src plate_a --splits 'plate_a:12@A1;plate_b:8@C3' \
                --leftover waste
        """
        try:
            result = self.service.transfer(args)
            if result.ok:
                rprint(f"[green]✓ {result.message}[/green]")
            else:
                rprint(f"[yellow]{result.message}[/yellow]")
        except NotALocationError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Use 'ls locs' to see defined locations.[/dim]")
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
            next_tip

        Note:
            Requires a tipbox to be defined in the configuration.
            Raises an error if a tip is already attached.
        """
        try:
            result = self.service.next_tip()
            rprint(f"[green]✓ {result.message}[/green]")
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
            eject_tip

        Warning:
            The tip is left at the current pipette position, not in the
            waste container.
        """
        try:
            result = self.service.eject_tip()
            if result.ok:
                rprint(f"[green]✓ {result.message}[/green]")
            else:
                rprint(f"[yellow]{result.message}[/yellow]")
        except Exception as e:
            rprint(f"[red]Error ejecting tip: {e}[/red]")

    def do_dispose_tip(self, _: Statement) -> None:
        """Dispose the current tip in the waste container.

        Moves to the waste container and ejects the tip. This is the
        standard way to discard used tips during a protocol.

        Example:
            dispose_tip

        Note:
            Requires a waste container to be defined in the configuration.
        """
        try:
            result = self.service.dispose_tip()
            if result.ok:
                rprint(f"[green]✓ {result.message}[/green]")
            else:
                rprint(f"[yellow]{result.message}[/yellow]")
        except NoWasteContainerError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint(
                "[dim]Hint: Define a waste container plate in your configuration.[/dim]"
            )
        except Exception as e:
            rprint(f"[red]Error disposing tip: {e}[/red]")

    def do_change_tip(self, _: Statement) -> None:
        """Dispose the current tip and pick up a fresh one.

        Convenience command that combines ``dispose_tip`` and ``next_tip``.
        If no tip is currently attached, skips straight to pickup.

        Example:
            change_tip

        Note:
            Requires both a tipbox and a waste container to be configured.
        """
        try:
            result = self.service.change_tip()
            rprint(f"[green]✓ {result.message}[/green]")
        except NoTipboxError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint("[dim]Hint: Define a tipbox plate in your configuration.[/dim]")
        except NoWasteContainerError as e:
            rprint(f"[yellow]{e}[/yellow]")
            rprint(
                "[dim]Hint: Define a waste container plate in your configuration.[/dim]"
            )
        except Exception as e:
            rprint(f"[red]Error changing tip: {e}[/red]")

"""Protocol execution commands for the Tricca AutoPipette Shell.

This module provides shell commands for running protocol scripts,
controlling execution (pause, resume, cancel), and handling emergency stops.

Thin cmd2 adapter: each ``do_*`` method only parses arguments and renders
the result -- the actual logic lives on ``AutoPipetteService``
(``daemon/service.py``), reached via ``self.service`` (see
``base_command_set.py``'s ``TAPCommandSet.service`` property). As of
migration Phase 4 (see CLAUDE.md), ``do_run`` replays a protocol file via
``AutoPipetteService.run_protocol_blocking`` -- the exact same per-line
dispatch loop the daemon's ``run.start`` RPC uses -- rather than its own,
independent implementation built on cmd2's ``runcmds_plus_hooks``.
"""

from __future__ import annotations

from cmd2 import Statement, with_argparser
from rich import print as rprint

from tricca_autopipette.commands.base_command_set import TAPCommandSet
from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_exceptions import ProtocolAbortedError

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
        file on the pipette. Blocks until the protocol finishes (or is
        aborted at a breakpoint).

        Args:
            args: Parsed arguments containing filename.

        Example:
            >>> run my_protocol.tap
            >>> run protocols/calibration.tap
        """
        rprint(f"[cyan]Running protocol: {args.filename}[/cyan]")
        try:
            result = self.service.run_protocol_blocking(args.filename)
            rprint(f"[bold green]✓ {result.message}[/bold green]")
        except ProtocolAbortedError as e:
            rprint(f"[yellow]{e}[/yellow]")
        except FileNotFoundError as e:
            rprint(f"[red]{e}[/red]")
            rprint(
                f"[dim]Hint: Check '{DefaultPaths.DIR_PROTOCOL}' for "
                "available protocols.[/dim]"
            )
        except OSError as e:
            rprint(f"[red]Failed to write protocol G-code: {e}[/red]")
        except Exception as e:
            rprint(f"[red]Error executing protocol: {e}[/red]")

    # =========================================================================
    # INTERACTIVE BREAKPOINT
    # =========================================================================

    def do_break(self, _: Statement) -> None:
        """Manually invoke the breakpoint-confirmation flow.

        Inside a running protocol, ``break`` lines are handled directly by
        ``AutoPipetteService``'s per-line dispatch loop (which calls
        ``request_breakpoint`` itself, never reaching this method) -- this
        ``do_break`` is only reachable by typing ``break`` directly at the
        interactive prompt, mostly useful for manually testing the
        confirmation flow outside of a protocol run.

        Example:
            >>> break
        """
        handler = self.service.breakpoint_handler
        if handler is not None:
            rprint("[yellow]⏸ Waiting for remote confirmation...[/yellow]")
            proceed = handler()
        else:
            result = self.shell.select(
                ["Yes", "No"], prompt="Continue protocol execution?"
            )
            proceed = result == "Yes"

        if proceed:
            rprint("[green]Continuing protocol execution...[/green]")
        else:
            rprint("[yellow]Protocol execution stopped by user.[/yellow]")

    # =========================================================================
    # RUN CONTROL COMMANDS
    # =========================================================================

    def do_stop(self, _: Statement) -> None:
        """Send an emergency stop to the pipette.

        Immediately halts all motion. The pipette must be re-homed
        before resuming normal operation.

        Example:
            >>> stop
        """
        rprint("[bold red]⚠ EMERGENCY STOP ⚠[/bold red]")
        try:
            result = self.service.emergency_stop()
            rprint(f"[bold red]{result.message}[/bold red]")
        except Exception as e:
            rprint(f"[red]Failed to send emergency stop: {e}[/red]")

    def do_pause(self, _: Statement) -> None:
        """Pause the current protocol execution.

        Example:
            >>> pause
        """
        rprint("[yellow]⏸ Pausing protocol...[/yellow]")
        try:
            result = self.service.send_pause()
            rprint(f"[green]{result.message}[/green]")
            rprint("[dim]Use 'resume' to continue.[/dim]")
        except Exception as e:
            rprint(f"[red]Failed to pause protocol: {e}[/red]")

    def do_resume(self, _: Statement) -> None:
        """Resume paused protocol execution.

        Example:
            >>> resume
        """
        rprint("[cyan]▶ Resuming protocol...[/cyan]")
        try:
            result = self.service.send_resume()
            rprint(f"[green]{result.message}[/green]")
        except Exception as e:
            rprint(f"[red]Failed to resume protocol: {e}[/red]")

    def do_cancel(self, _: Statement) -> None:
        """Cancel the current protocol execution.

        Example:
            >>> cancel
        """
        rprint("[yellow]⏹ Canceling protocol...[/yellow]")
        try:
            result = self.service.send_cancel()
            rprint(f"[red]{result.message}[/red]")
        except Exception as e:
            rprint(f"[red]Failed to cancel protocol: {e}[/red]")

"""WebSocket communication commands for the Tricca AutoPipette Shell.

This module provides shell commands for managing WebSocket connections,
sending JSON-RPC requests and notifications, uploading G-code files,
and monitoring server communications.

Thin cmd2 adapter: each ``do_*`` method only parses arguments and renders
the result -- the actual logic lives on ``AutoPipetteService``
(``daemon/service.py``), reached via ``self.service`` (see
``base_command_set.py``'s ``TAPCommandSet.service`` property). Migrated off
direct ``self.shell.client``/``self.shell.mrr`` access in migration Phase 4
(see CLAUDE.md) so this group works identically whether reached through
this standalone shell or through ``tap``/``RemoteTapShell`` talking to the
daemon over the control plane.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cmd2 import Statement, with_argparser
from rich import print as rprint

from tricca_autopipette.cli.report_tables import build_endstops_table
from tricca_autopipette.commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import NotifyArgs, SendArgs, TAPCmdParsers, UploadArgs


class WebSocketCommands(TAPCommandSet):
    """Commands for WebSocket communication with the pipette.

    Provides shell commands for:
    - Sending JSON-RPC requests and notifications
    - Managing notification subscriptions
    - Uploading G-code files to the server
    - Reading messages from the WebSocket queue
    - Monitoring connection status
    - Querying live endstop trigger state
    - Reconnecting and restoring subscriptions

    Example:
        ws_status
        ping
        query_endstops
        subscribe notify_status_update
        notify printer.info
        send server.config
        upload protocol.gcode /path/to/file.gcode
        read
        reconnect
    """

    def __init__(self) -> None:
        """Initialize WebSocket commands."""
        super().__init__()

    # =========================================================================
    # STATUS / DIAGNOSTICS
    # =========================================================================

    def do_ws_status(self, _: Statement) -> None:
        """Display WebSocket connection status and statistics.

        Shows current connection state, queued messages, registered
        handlers, and pending requests.

        Example:
            ws_status
        """
        result = self.service.ws_status()
        data = result.data or {}
        if not data:
            rprint(f"[yellow]{result.message}[/yellow]")
            return

        rprint(
            "[green]✓ WebSocket connected[/green]"
            if data.get("connected")
            else "[red]✗ WebSocket disconnected[/red]"
        )
        rprint(f"[dim]Server:[/dim] {data.get('uri')}")
        rprint()

        msg_count = data.get("queued_messages", 0)
        if msg_count > 0:
            rprint(f"[yellow]📬 {msg_count} unread message(s)[/yellow]")
        else:
            rprint("[dim]📭 No queued messages[/dim]")

        handlers: list[str] = data.get("handlers") or []
        if handlers:
            rprint(f"[cyan]🔔 {len(handlers)} notification handler(s):[/cyan]")
            for method in handlers:
                rprint(f"  • {method}")
        else:
            rprint("[dim]🔕 No notification handlers[/dim]")

        pending = data.get("pending_requests", 0)
        if pending > 0:
            rprint(f"[yellow]⏳ {pending} pending request(s)[/yellow]")

    def do_ping(self, _: Statement) -> None:
        """Ping the server to check connection health and measure round-trip time.

        Example:
            ping
            ✓ Pong! (Round-trip: 23.4ms)
        """
        try:
            result = self.service.ping_moonraker()
            color = "green" if result.ok else "yellow"
            rprint(f"[{color}]{'✓ ' if result.ok else ''}{result.message}[/{color}]")
        except TimeoutError:
            rprint("[red]✗ Ping timed out[/red]")
        except Exception as e:
            rprint(f"[red]✗ Ping failed: {e}[/red]")

    def do_query_endstops(self, _: Statement) -> None:
        """Query live endstop trigger state from Klipper.

        Nearly identical to Klipper's own ``QUERY_ENDSTOPS``, but via
        Moonraker's structured ``printer.query_endstops.status`` RPC
        rather than parsing G-code text -- shows every endstop Klipper
        reports (each axis, and the pipette's ``MANUAL_STEPPER`` endstop),
        using Klipper's own "open"/"TRIGGERED" wording. Works before
        homing; not gated by the homed interlock.

        Example:
            query_endstops
        """
        try:
            result = self.service.query_endstops()
        except (RuntimeError, TimeoutError) as e:
            rprint(f"[red]Error querying endstops: {e}[/red]")
            return

        endstops: dict[str, str] = (result.data or {}).get("endstops") or {}
        if not endstops:
            rprint("[yellow]No endstops reported.[/yellow]")
            return
        rprint(build_endstops_table(endstops))

    # =========================================================================
    # SEND / NOTIFY
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_send)  # type: ignore[arg-type]
    def do_send(self, args: SendArgs) -> None:
        """Send a JSON-RPC request and await a response.

        Synchronous — blocks until a response is received or the
        request times out after 5 seconds.

        Args:
            args: Parsed arguments containing method and optional params.

        Example:
            send printer.info
            send server.config
            send gcode.script '{"script": "G28"}'
        """
        try:
            params: dict[str, Any] | None = None
            if args.params and args.params.strip():
                params = json.loads(args.params.strip())

            rprint(f"[cyan]Sending request: {args.method}...[/cyan]")
            result = self.service.send_raw(args.method, params)

            rprint("[green]✓ Response received:[/green]")
            data = result.data or {}
            rprint(json.dumps(data.get("response"), indent=2))

        except json.JSONDecodeError as e:
            rprint(f"[red]Invalid JSON in params: {e}[/red]")
            rprint(
                "[yellow]Tip: Use single quotes around JSON: "
                '\'{{"key": "value"}}\'[/yellow]'
            )
        except TimeoutError:
            rprint("[red]Request timed out (no response within 5 seconds).[/red]")
        except Exception as e:
            rprint(f"[red]Error sending request: {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_notify)  # type: ignore[arg-type]
    def do_notify(self, args: NotifyArgs) -> None:
        """Send a JSON-RPC notification (fire-and-forget).

        Does not wait for or expect a response from the server.

        Args:
            args: Parsed arguments containing method and optional params.

        Example:
            notify printer.restart
            notify gcode.script '{"script": "G28"}'

        Note:
            Parameters must be valid JSON. Use single quotes around
            the JSON string to avoid shell escaping issues.
        """
        try:
            params: dict[str, Any] | None = None
            if args.params and args.params.strip():
                params = json.loads(args.params.strip())

            result = self.service.notify_raw(args.method, params)
            rprint(f"[green]✓ {result.message}[/green]")

        except json.JSONDecodeError as e:
            rprint(f"[red]Invalid JSON in params: {e}[/red]")
            rprint(
                "[yellow]Tip: Use single quotes around JSON: "
                '\'{{"key": "value"}}\'[/yellow]'
            )
        except Exception as e:
            rprint(f"[red]Error sending notification: {e}[/red]")

    # =========================================================================
    # SUBSCRIPTIONS
    # =========================================================================

    def do_subscribe(self, arg: str) -> None:
        """Subscribe to server notifications for a specific method.

        Prints matching notifications as they arrive.

        Usage:
            subscribe <method>

        Args:
            arg: The notification method to subscribe to.

        Example:
            subscribe notify_status_update
            subscribe notify_gcode_response
        """
        if not arg.strip():
            rprint("[yellow]Usage: subscribe <method>[/yellow]")
            rprint("[dim]Example: subscribe notify_status_update[/dim]")
            return

        try:
            result = self.service.subscribe_raw(arg.strip())
            rprint(f"[green]✓ {result.message}[/green]")
            rprint("[dim]Notifications will be displayed as they arrive.[/dim]")
        except Exception as e:
            rprint(f"[red]Error subscribing: {e}[/red]")

    def do_unsubscribe(self, arg: str) -> None:
        """Unsubscribe from server notifications for a specific method.

        Usage:
            unsubscribe <method>

        Args:
            arg: The notification method to unsubscribe from.

        Example:
            unsubscribe notify_status_update
        """
        if not arg.strip():
            rprint("[yellow]Usage: unsubscribe <method>[/yellow]")
            return

        try:
            result = self.service.unsubscribe_raw(arg.strip())
            color = "green" if result.ok else "yellow"
            rprint(f"[{color}]{result.message}[/{color}]")
        except Exception as e:
            rprint(f"[red]Error unsubscribing: {e}[/red]")

    # =========================================================================
    # FILE UPLOAD
    # =========================================================================

    @with_argparser(TAPCmdParsers.parser_upload)  # type: ignore[arg-type]
    def do_upload(self, args: UploadArgs) -> None:
        """Upload a G-code file to the pipette server.

        Transfers a local G-code file to the server via HTTP.

        Args:
            args: Parsed arguments containing server filename and local path.

        Example:
            upload protocol.gcode /tmp/protocol.gcode
            upload calibration.gcode ./calibration.gcode

        Note:
            ``file_name`` is the name assigned on the server.
            ``file_path`` is the local path to the file to upload -- local
            to the process running this command (the daemon's host, when
            reached via ``tap``).
        """
        file_name: str = args.file_name
        file_path: Path = args.file_path

        try:
            server_path = self.service.upload_gcode(file_name, file_path)
            rprint(f"[green]✓ Upload successful. Server path: {server_path}[/green]")
        except Exception as e:
            rprint(f"[red]Upload failed: {e}[/red]")

    # =========================================================================
    # MESSAGE QUEUE
    # =========================================================================

    def do_read(self, _: Statement) -> None:
        """Read and display the next message from the WebSocket queue.

        Retrieves and displays the first unhandled message. All remaining
        messages are returned to the queue.

        Example:
            read
        """
        try:
            result = self.service.read_message()
        except Exception as e:
            rprint(f"[red]Error reading message: {e}[/red]")
            return

        if not result.ok:
            rprint(f"[dim]{result.message}[/dim]")
            return

        data = result.data or {}
        rprint("[bold cyan]Message from queue:[/bold cyan]")
        rprint(f"[dim]Type:[/dim] {data.get('type')}")
        if data.get("message_data"):
            rprint("[dim]Data:[/dim]")
            rprint(json.dumps(data["message_data"], indent=2))

        remaining = data.get("remaining", 0)
        if remaining > 0:
            rprint(f"[dim]({remaining} more message(s) in queue)[/dim]")

    def do_read_all(self, _: Statement) -> None:
        """Read and display all messages from the WebSocket queue.

        Example:
            read_all
        """
        try:
            result = self.service.read_all_messages()
        except Exception as e:
            rprint(f"[red]Error reading messages: {e}[/red]")
            return

        messages = (result.data or {}).get("messages", [])
        if not messages:
            rprint("[dim]No messages in queue.[/dim]")
            return

        rprint(f"[bold cyan]{len(messages)} message(s) in queue:[/bold cyan]\n")
        for i, message in enumerate(messages, 1):
            rprint(f"[bold]Message {i}:[/bold]")
            rprint(f"  [dim]Type:[/dim] {message.get('type')}")
            if message.get("message_data"):
                formatted = json.dumps(message["message_data"], indent=4)
                indented = "\n".join(f"  {line}" for line in formatted.split("\n"))
                rprint(indented)
            rprint()

    def do_clear_queue(self, _: Statement) -> None:
        """Discard all messages from the WebSocket queue.

        Example:
            clear_queue
        """
        try:
            result = self.service.clear_message_queue()
            data = result.data or {}
            if data.get("cleared"):
                rprint(f"[green]✓ {result.message}[/green]")
            else:
                rprint("[dim]Queue was already empty.[/dim]")
        except Exception as e:
            rprint(f"[red]Error clearing queue: {e}[/red]")

    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================

    def do_reconnect(self, _: Statement) -> None:
        """Reconnect the WebSocket and restore notification handlers.

        Closes the current connection, opens a new one to the same URI,
        and re-registers all previously registered notification handlers.

        Example:
            reconnect

        Note:
            Client-side handlers are restored automatically. Server-side
            subscriptions (e.g. Moonraker printer.objects.subscribe) must
            be re-sent separately if required — see ``send`` or ``notify``.
        """
        rprint("[cyan]Reconnecting WebSocket...[/cyan]")
        try:
            result = self.service.reconnect_websocket()
            if result.ok:
                rprint(f"[green]✓ {result.message}[/green]")
                restored = (result.data or {}).get("handlers_restored", 0)
                if restored:
                    rprint(
                        f"[dim]{restored} handler(s) restored. "
                        f"Re-send any server subscriptions if needed.[/dim]"
                    )
            else:
                rprint(f"[red]{result.message}[/red]")
        except Exception as e:
            rprint(f"[red]Reconnection error: {e}[/red]")

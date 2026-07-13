"""WebSocket communication commands for the Tricca AutoPipette Shell.

This module provides shell commands for managing WebSocket connections,
sending JSON-RPC requests and notifications, uploading G-code files,
and monitoring server communications.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from cmd2 import Statement, with_argparser
from rich import print as rprint
from websocket_client import WebSocketClient

from commands.base_command_set import TAPCommandSet

from .tap_cmd_parsers import NotifyArgs, SendArgs, TAPCmdParsers, UploadArgs


class WebSocketCommands(TAPCommandSet):
    """Commands for WebSocket communication with the pipette.

    Provides shell commands for:
    - Sending JSON-RPC requests and notifications
    - Managing notification subscriptions
    - Uploading G-code files to the server
    - Reading messages from the WebSocket queue
    - Monitoring connection status
    - Reconnecting and restoring subscriptions

    Example:
        >>> ws_status
        >>> ping
        >>> subscribe notify_status_update
        >>> notify printer.info
        >>> send server.config
        >>> upload protocol.gcode /path/to/file.gcode
        >>> read
        >>> reconnect
    """

    def __init__(self) -> None:
        """Initialize WebSocket commands."""
        super().__init__()

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _get_client(self) -> WebSocketClient | None:
        """Return the WebSocket client, or None if unavailable.

        Prints a warning and returns None if the client has not been
        initialised on the shell.

        Returns:
            WebSocket client if available, None otherwise.
        """
        client = getattr(self.shell, "client", None)

        if not client:
            rprint("[yellow]WebSocket client not available.[/yellow]")
            return None

        return client

    def _ensure_connected(self) -> WebSocketClient | None:
        """Return the WebSocket client only if it is currently connected.

        Returns:
            Connected WebSocket client, or None if not connected.
        """
        client = self._get_client()
        if not client:
            return None

        if not client.is_connected():
            rprint("[yellow]WebSocket not connected. Use 'reconnect' first.[/yellow]")
            return None

        return client

    # =========================================================================
    # STATUS / DIAGNOSTICS
    # =========================================================================

    def do_ws_status(self, _: Statement) -> None:
        """Display WebSocket connection status and statistics.

        Shows current connection state, queued messages, registered
        handlers, and pending requests.

        Example:
            >>> ws_status
        """
        client = self._get_client()
        if not client:
            return

        # Connection status
        if client.is_connected():
            rprint("[green]✓ WebSocket connected[/green]")
        else:
            rprint("[red]✗ WebSocket disconnected[/red]")

        uri = getattr(self.shell, "uri", "Unknown")
        rprint(f"[dim]Server:[/dim] {uri}")
        rprint()

        # len(client) calls __len__ → message_queue.qsize(), non-destructive.
        msg_count = len(client)
        if msg_count > 0:
            rprint(f"[yellow]📬 {msg_count} unread message(s)[/yellow]")
        else:
            rprint("[dim]📭 No queued messages[/dim]")

        handlers = client.handlers
        if handlers:
            rprint(f"[cyan]🔔 {len(handlers)} notification handler(s):[/cyan]")
            for method in handlers:
                rprint(f"  • {method}")
        else:
            rprint("[dim]🔕 No notification handlers[/dim]")

        if client.pending_count > 0:
            rprint(f"[yellow]⏳ {client.pending_count} pending request(s)[/yellow]")

    def do_ping(self, _: Statement) -> None:
        """Ping the server to check connection health and measure round-trip time.

        Example:
            >>> ping
            ✓ Pong! (Round-trip: 23.4ms)
        """
        client = self._ensure_connected()
        if not client:
            return

        mrr = getattr(self.shell, "mrr", None)
        if not mrr:
            rprint("[yellow]MoonrakerRequests not available.[/yellow]")
            return

        try:
            request = mrr.server_info()
            start = time.time()
            response = client.send_jsonrpc(request, timeout=5.0)
            elapsed = (time.time() - start) * 1000

            if "result" in response:
                rprint(f"[green]✓ Pong! (Round-trip: {elapsed:.1f}ms)[/green]")
            else:
                rprint("[yellow]Response received but contained no result.[/yellow]")

        except TimeoutError:
            rprint("[red]✗ Ping timed out[/red]")
        except Exception as e:
            rprint(f"[red]✗ Ping failed: {e}[/red]")

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
            >>> send printer.info
            >>> send server.config
            >>> send gcode.script '{"script": "G28"}'
        """
        client = self._ensure_connected()
        if not client:
            return

        mrr = getattr(self.shell, "mrr", None)
        if not mrr:
            rprint("[yellow]MoonrakerRequests not available.[/yellow]")
            return

        try:
            params: dict[str, Any] | None = None
            if args.params and args.params.strip():
                params = json.loads(args.params.strip())

            request = mrr.gen_request(args.method, params)

            rprint(f"[cyan]Sending request: {args.method}...[/cyan]")
            response = client.send_jsonrpc(request, timeout=5.0)

            rprint("[green]✓ Response received:[/green]")
            rprint(json.dumps(response, indent=2))

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
            >>> notify printer.restart
            >>> notify gcode.script '{"script": "G28"}'

        Note:
            Parameters must be valid JSON. Use single quotes around
            the JSON string to avoid shell escaping issues.
        """
        client = self._ensure_connected()
        if not client:
            return

        try:
            params: dict[str, Any] | None = None
            if args.params and args.params.strip():
                params = json.loads(args.params.strip())

            client.send_notification(args.method, params)
            rprint(f"[green]✓ Notification sent: {args.method}[/green]")

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

        Registers a handler that prints incoming notifications for the
        given method as they arrive.

        Usage:
            subscribe <method>

        Args:
            arg: The notification method to subscribe to.

        Example:
            >>> subscribe notify_status_update
            >>> subscribe notify_gcode_response
        """
        if not arg.strip():
            rprint("[yellow]Usage: subscribe <method>[/yellow]")
            rprint("[dim]Example: subscribe notify_status_update[/dim]")
            return

        method = arg.strip()
        client = self._get_client()
        if not client:
            return

        def notification_handler(params: dict[str, Any] | None) -> None:
            rprint(f"[bold cyan]📨 {method}:[/bold cyan]")
            if params:
                rprint(json.dumps(params, indent=2))
            else:
                rprint("[dim](no parameters)[/dim]")

        client.register_handler(method, notification_handler)
        rprint(f"[green]✓ Subscribed to '{method}'[/green]")
        rprint("[dim]Notifications will be displayed as they arrive.[/dim]")

    def do_unsubscribe(self, arg: str) -> None:
        """Unsubscribe from server notifications for a specific method.

        Removes the handler for the specified notification method.

        Usage:
            unsubscribe <method>

        Args:
            arg: The notification method to unsubscribe from.

        Example:
            >>> unsubscribe notify_status_update
        """
        if not arg.strip():
            rprint("[yellow]Usage: unsubscribe <method>[/yellow]")
            return

        method = arg.strip()
        client = self._get_client()
        if not client:
            return

        if method in client.handlers:
            client.unregister_handler(method)
            rprint(f"[green]✓ Unsubscribed from '{method}'[/green]")
        else:
            rprint(f"[yellow]Not currently subscribed to '{method}'.[/yellow]")

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
            >>> upload protocol.gcode /tmp/protocol.gcode
            >>> upload calibration.gcode ./calibration.gcode

        Note:
            ``file_name`` is the name assigned on the server.
            ``file_path`` is the local path to the file to upload.
        """
        file_name: str = args.file_name
        file_path: Path = args.file_path

        try:
            self.shell.upload_gcode(file_name, file_path)
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
            >>> read
        """
        client = self._get_client()
        if not client:
            return

        message = client.pop_message()

        if message is None:
            rprint("[dim]No messages in queue.[/dim]")
            return

        rprint("[bold cyan]Message from queue:[/bold cyan]")
        rprint(f"[dim]Type:[/dim] {message.type.value}")

        if message.data:
            rprint("[dim]Data:[/dim]")
            rprint(json.dumps(message.data, indent=2))

        remaining = len(client)
        if remaining > 0:
            rprint(f"[dim]({remaining} more message(s) in queue)[/dim]")

    def do_read_all(self, _: Statement) -> None:
        """Read and display all messages from the WebSocket queue.

        Example:
            >>> read_all
        """
        client = self._get_client()
        if not client:
            return

        messages = client.get_queued_messages()

        if not messages:
            rprint("[dim]No messages in queue.[/dim]")
            return

        rprint(f"[bold cyan]{len(messages)} message(s) in queue:[/bold cyan]\n")

        for i, message in enumerate(messages, 1):
            rprint(f"[bold]Message {i}:[/bold]")
            rprint(f"  [dim]Type:[/dim] {message.type.value}")
            if message.data:
                formatted = json.dumps(message.data, indent=4)
                indented = "\n".join(f"  {line}" for line in formatted.split("\n"))
                rprint(indented)
            rprint()

    def do_clear_queue(self, _: Statement) -> None:
        """Discard all messages from the WebSocket queue.

        Example:
            >>> clear_queue
        """
        client = self._get_client()
        if not client:
            return

        count = client.clear_queue()

        if count > 0:
            rprint(f"[green]✓ Cleared {count} message(s) from queue.[/green]")
        else:
            rprint("[dim]Queue was already empty.[/dim]")

    # =========================================================================
    # CONNECTION MANAGEMENT
    # =========================================================================

    def do_reconnect(self, _: Statement) -> None:
        """Reconnect the WebSocket and restore notification handlers.

        Closes the current connection, opens a new one to the same URI,
        and re-registers all previously registered notification handlers.

        Example:
            >>> reconnect

        Note:
            Client-side handlers are restored automatically. Server-side
            subscriptions (e.g. Moonraker printer.objects.subscribe) must
            be re-sent separately if required — see ``send`` or ``notify``.
        """
        client = self._get_client()
        if not client:
            return

        rprint("[cyan]Reconnecting WebSocket...[/cyan]")

        try:
            existing_handlers = client.handlers

            uri = getattr(self.shell, "uri", None)
            if not uri:
                rprint("[red]WebSocket URI not available.[/red]")
                return

            client.stop()
            rprint("[dim]Old connection closed.[/dim]")

            new_client = WebSocketClient(uri)

            # Restore client-side handlers on the new client.
            # Server-side subscriptions are NOT re-sent here — Moonraker
            # subscriptions use printer.objects.subscribe, not outbound
            # notifications, so re-sending method names as notifications
            # would be incorrect.
            for method, callback in existing_handlers.items():
                new_client.register_handler(method, callback)

            new_client.start()

            if new_client.wait_for_connection(timeout=10):
                self.shell.client = new_client
                rprint("[green]✓ WebSocket reconnected.[/green]")
                if existing_handlers:
                    rprint(
                        f"[dim]{len(existing_handlers)} handler(s) restored. "
                        f"Re-send any server subscriptions if needed.[/dim]"
                    )
            else:
                rprint("[red]Failed to reconnect — reverting to old client.[/red]")
                # NOTE: the old client was stopped above; restarting it may
                # not fully restore its previous state depending on the
                # WebSocketClient implementation.
                self.shell.client = client
                client.start()

        except Exception as e:
            rprint(f"[red]Reconnection error: {e}[/red]")

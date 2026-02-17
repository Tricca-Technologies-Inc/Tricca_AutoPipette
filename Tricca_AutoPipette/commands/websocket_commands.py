#!/usr/bin/env python3
"""WebSocket communication commands for the Tricca AutoPipette Shell.

This module provides shell commands for managing WebSocket connections,
sending JSON-RPC requests and notifications, uploading G-code files,
and monitoring server communications.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from cmd2 import Statement, with_argparser
from rich import print as rprint
from tap_cmd_parsers import NotifyArgs, SendArgs, TAPCmdParsers, UploadArgs
from websocket_client import WebSocketClient

from commands.base_command_set import TAPCommandSet


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

    def _get_client(self) -> WebSocketClient | None:
        """Get WebSocket client with validation.

        Returns:
            WebSocket client if available, None otherwise.
        """
        client = getattr(self.shell, "client", None)

        if not client:
            rprint("[yellow]WebSocket client not available.[/yellow]")
            return None

        return client

    def _ensure_connected(self) -> WebSocketClient | None:
        """Ensure WebSocket is connected.

        Returns:
            Connected WebSocket client, or None if not connected.
        """
        client = self._get_client()
        if not client:
            return None

        if not client.is_connected():
            rprint(
                "[yellow]WebSocket not connected. " "Use 'reconnect' first.[/yellow]"
            )
            return None

        return client

    def do_ws_status(self, _: Statement) -> None:
        """Display WebSocket connection status and statistics.

        Shows current connection state, queued messages, registered
        handlers, and other diagnostic information.

        Example:
            >>> ws_status
            ✓ WebSocket connected
            Server: ws://192.168.1.100:7125/websocket
            📭 No queued messages
            🔔 2 notification handler(s):
              • notify_status_update
              • notify_gcode_response
        """
        client = self._get_client()

        if not client:
            rprint("[red]✗ WebSocket client not initialized[/red]")
            return

        # Connection status
        if client.is_connected():
            rprint("[green]✓ WebSocket connected[/green]")
        else:
            rprint("[red]✗ WebSocket disconnected[/red]")

        # Server URI
        uri = getattr(self.shell, "uri", "Unknown")
        rprint(f"[dim]Server:[/dim] {uri}")
        rprint()

        # Message queue
        messages = client.get_queued_messages()
        # Put them back for later reading
        for msg in messages:
            client.message_queue.put(msg)

        msg_count = len(messages)
        if msg_count > 0:
            rprint(f"[yellow]📬 {msg_count} unread message(s)[/yellow]")
        else:
            rprint("[dim]📭 No queued messages[/dim]")

        # Registered handlers
        handler_count = len(client._handlers)
        if handler_count > 0:
            rprint(f"[cyan]🔔 {handler_count} notification handler(s):[/cyan]")
            for method in client._handlers.keys():
                rprint(f"  • {method}")
        else:
            rprint("[dim]🔕 No notification handlers[/dim]")

        # Pending requests
        pending_count = len(client._pending)
        if pending_count > 0:
            rprint(f"[yellow]⏳ {pending_count} pending request(s)[/yellow]")

    def do_ping(self, _: Statement) -> None:
        """Ping the server to check connection health.

        Sends a simple request to verify the connection is working
        and measure round-trip time.

        Example:
            >>> ping
            ✓ Pong! (Round-trip: 23.4ms)
        """
        client = self._ensure_connected()
        if not client:
            return

        try:
            mrr = getattr(self.shell, "mrr", None)
            if not mrr:
                rprint("[yellow]MoonrakerRequests not available.[/yellow]")
                return

            # Send server.info as a simple ping
            request = mrr.server_info()

            start = time.time()
            response = client.send_jsonrpc(request, timeout=5.0)
            elapsed = (time.time() - start) * 1000  # Convert to ms

            if "result" in response:
                rprint(f"[green]✓ Pong! (Round-trip: {elapsed:.1f}ms)[/green]")
            else:
                rprint("[yellow]Response received but no result.[/yellow]")

        except TimeoutError:
            rprint("[red]✗ Ping timeout[/red]")
        except Exception as e:
            rprint(f"[red]✗ Ping failed: {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_send)  # type: ignore[arg-type]
    def do_send(self, args: SendArgs) -> None:
        """Send a JSON-RPC request and await response.

        Sends a request to the pipette server and waits for the response.
        This is synchronous and will block until a response is received
        or the request times out.

        Args:
            args: Parsed arguments for RPC request.

        Example:
            >>> send printer.info
            >>> send server.config
        """
        client = self._ensure_connected()
        if not client:
            return

        # Get method from args
        method = getattr(args, "method", None)
        params_str = getattr(args, "params", None)

        if not method:
            rprint("[yellow]No method specified.[/yellow]")
            return

        try:
            # Parse params if provided
            params = None
            if params_str and params_str.strip():
                params = json.loads(params_str.strip())

            # Get MoonrakerRequests instance
            mrr = getattr(self.shell, "mrr", None)
            if not mrr:
                rprint("[yellow]MoonrakerRequests not available.[/yellow]")
                return

            # Build request
            request = mrr.gen_request(method, params)

            # Send and wait for response
            rprint(f"[cyan]Sending request: {method}...[/cyan]")
            response = client.send_jsonrpc(request, timeout=5.0)

            # Display response
            rprint("[green]✓ Response received:[/green]")
            formatted = json.dumps(response, indent=2)
            rprint(formatted)

        except json.JSONDecodeError as e:
            rprint(f"[red]Invalid JSON in params: {e}[/red]")
            rprint(
                "[yellow]Tip: Use single quotes around JSON: "
                '\'{{"key": "value"}}\'[/yellow]'
            )
        except TimeoutError:
            rprint("[red]Request timed out (no response within 5 seconds)[/red]")
        except Exception as e:
            rprint(f"[red]Error sending request: {e}[/red]")

    @with_argparser(TAPCmdParsers.parser_notify)  # type: ignore[arg-type]
    def do_notify(self, args: NotifyArgs) -> None:
        """Send a JSON-RPC notification without awaiting response.

        Sends a fire-and-forget notification to the pipette server.
        Does not wait for or expect a response.

        Args:
            args: Parsed arguments containing method and optional params.

        Example:
            >>> notify printer.restart
            >>> notify gcode.script '{"script": "G28"}'
            >>> notify custom.method '{"param1": "value1"}'

        Note:
            Parameters must be valid JSON. Use single quotes around
            the JSON string to avoid shell escaping issues.
        """

        def worker() -> None:
            """Worker thread to send notification asynchronously."""
            client = self._ensure_connected()
            if not client:
                return

            try:
                # Parse parameters if provided
                params: dict[str, Any] | None = None
                if args.params and args.params.strip():
                    try:
                        params = json.loads(args.params.strip())
                    except json.JSONDecodeError as e:
                        self.shell.perror(f"Invalid JSON in params: {e}")
                        rprint(
                            "[yellow]Tip: Use single quotes around JSON: "
                            '\'{{"key": "value"}}\'[/yellow]'
                        )
                        return

                # Send notification
                client.send_notification(args.method, params)
                rprint(f"[green]✓ Notification sent: {args.method}[/green]")

            except Exception as e:
                self.shell.perror(f"Error sending notification: {e}")

        # Run in background thread to avoid blocking
        threading.Thread(target=worker, daemon=True).start()

    def do_subscribe(self, arg: str) -> None:
        """Subscribe to server notifications for a specific method.

        Registers a handler to receive and display notifications
        from the server for the specified method.

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

        # Define a simple handler that prints the notification
        def notification_handler(params: dict[str, Any] | None) -> None:
            rprint(f"[bold cyan]📨 {method}:[/bold cyan]")
            if params:
                formatted = json.dumps(params, indent=2)
                rprint(formatted)
            else:
                rprint("[dim](no parameters)[/dim]")

        # Register the handler
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

        if method in client._handlers:
            client.unregister_handler(method)
            rprint(f"[green]✓ Unsubscribed from '{method}'[/green]")
        else:
            rprint(f"[yellow]Not subscribed to '{method}'[/yellow]")

    @with_argparser(TAPCmdParsers.parser_upload)  # type: ignore[arg-type]
    def do_upload(self, args: UploadArgs) -> None:
        """Upload a G-code file to the pipette server.

        Uploads a local G-code file to the server for execution.
        The file is transferred via HTTP and stored on the server.

        Args:
            args: Parsed arguments containing filename and local path.

        Example:
            >>> upload protocol.gcode /tmp/protocol.gcode
            >>> upload calibration.gcode ./calibration.gcode

        Note:
            The file_name is what the file will be called on the server.
            The file_path is the local path to the file to upload.
        """
        file_name: str = args.file_name
        file_path: Path = args.file_path

        # Delegate to shell's upload method
        if hasattr(self.shell, "upload_gcode"):
            try:
                self.shell.upload_gcode(file_name, file_path)
            except Exception as e:
                rprint(f"[red]Upload failed: {e}[/red]")
        else:
            rprint("[yellow]Upload functionality not available.[/yellow]")

    def do_read(self, _: Statement) -> None:
        """Read and display next message from WebSocket queue.

        Retrieves and displays the next unhandled message from the
        WebSocket message queue. Useful for debugging and monitoring
        server notifications.

        Example:
            >>> read
            Message from queue:
            Type: notification
            Data:
            {
              "method": "status_update",
              "params": {...}
            }
            (2 more message(s) in queue)
        """
        client = self._get_client()
        if not client:
            return

        # Get all queued messages
        messages = client.get_queued_messages()

        if not messages:
            rprint("[dim]No messages in queue.[/dim]")
            return

        # Display the first message
        message = messages[0]

        rprint("[bold cyan]Message from queue:[/bold cyan]")
        rprint(f"[dim]Type:[/dim] {message.type.value}")

        # Format data based on message type
        if message.data:
            rprint("[dim]Data:[/dim]")
            # Pretty print JSON
            formatted = json.dumps(message.data, indent=2)
            rprint(formatted)

        # Show remaining message count
        if len(messages) > 1:
            rprint(f"[dim]({len(messages) - 1} more message(s) in queue)[/dim]")

    def do_read_all(self, _: Statement) -> None:
        """Read and display all messages from WebSocket queue.

        Retrieves and displays all unhandled messages from the
        WebSocket message queue.

        Example:
            >>> read_all
            3 message(s) in queue:

            Message 1:
              Type: notification
              {
                "method": "...",
                ...
              }

            Message 2:
              ...
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
                # Indent all lines
                indented = "\n".join(f"  {line}" for line in formatted.split("\n"))
                rprint(indented)
            rprint()  # Blank line between messages

    def do_clear_queue(self, _: Statement) -> None:
        """Clear all messages from the WebSocket queue.

        Removes all unread messages from the message queue.
        Useful for clearing old notifications.

        Example:
            >>> clear_queue
            ✓ Cleared 5 message(s) from queue
        """
        client = self._get_client()
        if not client:
            return

        messages = client.get_queued_messages()
        count = len(messages)

        if count > 0:
            rprint(f"[green]✓ Cleared {count} message(s) from queue[/green]")
        else:
            rprint("[dim]Queue was already empty.[/dim]")

    def do_reconnect(self, _: Statement) -> None:
        """Reconnect WebSocket and restore subscriptions.

        Closes the current WebSocket connection, creates a new one,
        and restores all registered notification handlers and
        subscriptions.

        Example:
            >>> reconnect
            Reconnecting WebSocket...
            Old connection closed.
            ✓ WebSocket reconnected and subscriptions restored.

        Note:
            This is useful when the connection has been lost or
            is experiencing issues.
        """
        client = self._get_client()
        if not client:
            return

        rprint("[cyan]Reconnecting WebSocket...[/cyan]")

        try:
            # Save existing handlers
            existing_handlers = dict(client._handlers)

            # Get URI for new connection
            uri = getattr(self.shell, "uri", None)
            if not uri:
                rprint("[red]WebSocket URI not available.[/red]")
                return

            # Stop old client
            client.stop()
            rprint("[dim]Old connection closed.[/dim]")

            # Create new client
            new_client = WebSocketClient(uri)

            # Restore handlers
            for method, callback in existing_handlers.items():
                new_client.register_handler(method, callback)

            # Start new client
            new_client.start()

            # Wait for connection
            if new_client.wait_for_connection(timeout=10):
                # Update shell's client reference
                self.shell.client = new_client

                # Try to restore subscriptions
                for method in existing_handlers.keys():
                    try:
                        new_client.send_notification(method, None)
                    except Exception:
                        pass  # Ignore errors in subscription restoration

                rprint(
                    "[green]✓ WebSocket reconnected and subscriptions "
                    "restored.[/green]"
                )
            else:
                rprint("[red]Failed to reconnect to WebSocket.[/red]")
                # Restore old client on failure
                self.shell.client = client
                client.start()

        except Exception as e:
            rprint(f"[red]Reconnection error: {e}[/red]")

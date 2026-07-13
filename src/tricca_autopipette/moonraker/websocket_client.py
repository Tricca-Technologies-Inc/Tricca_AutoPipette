#!/usr/bin/env python3
r"""WebSocket client for real-time communication with the AutoPipette server.

This module provides an asynchronous WebSocket client that runs in a background
thread, handling JSON-RPC requests, file uploads, and message dispatching.

Example:
    >>> client = WebSocketClient("ws://192.168.1.100:7125/websocket")
    >>> client.start()
    >>>
    >>> # Send JSON-RPC request
    >>> response = client.send_jsonrpc(
    >>>                 {"jsonrpc": "2.0", "method": "server.info", "id": "123"})
    >>>
    >>> # Upload G-code file
    >>> future = client.upload_gcode_file("protocol.gcode", "/path/to/file.gcode")
    >>> server_path = future.result()
    >>>
    >>> client.stop()
    >>>
    >>> # Or use context manager
    >>> with WebSocketClient("ws://192.168.1.100:7125/websocket") as client:
    ...     client.wait_for_connection()
    ...     response = client.send_jsonrpc(request)
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from types import TracebackType
from typing import Any, Callable
from urllib.parse import urlparse

import aiohttp
from aiohttp import ClientSession, ClientWebSocketResponse, FormData, WSMsgType


class MessageType(str, Enum):
    """Types of messages that can appear in the message queue.

    Attributes:
        FATAL_ERROR: Unrecoverable error in background loop.
        CONNECTION_ERROR: WebSocket connection failure.
        HANDLER_ERROR: Exception in notification handler.
        NOTIFICATION: Unhandled server notification.
        PARSE_ERROR: Failed to parse incoming message.
    """

    FATAL_ERROR = "fatal_error"
    CONNECTION_ERROR = "error"
    HANDLER_ERROR = "handler_error"
    NOTIFICATION = "notification"
    PARSE_ERROR = "parse_error"


@dataclass
class QueuedMessage:
    """Message placed in the queue for later retrieval.

    Attributes:
        type: Type of message.
        data: Message payload with type-specific fields.

    Example:
        >>> msg = QueuedMessage.connection_error("Connection refused")
        >>> print(msg.type)  # MessageType.CONNECTION_ERROR
        >>> print(msg.data["text"])  # "Connection refused"
    """

    type: MessageType
    data: dict[str, Any]

    @classmethod
    def fatal_error(cls, text: str) -> QueuedMessage:
        """Create a fatal error message.

        Args:
            text: Error description.

        Returns:
            QueuedMessage with FATAL_ERROR type.
        """
        return cls(MessageType.FATAL_ERROR, {"text": text})

    @classmethod
    def connection_error(cls, text: str) -> QueuedMessage:
        """Create a connection error message.

        Args:
            text: Error description.

        Returns:
            QueuedMessage with CONNECTION_ERROR type.
        """
        return cls(MessageType.CONNECTION_ERROR, {"text": text})

    @classmethod
    def handler_error(cls, method: str, error: str) -> QueuedMessage:
        """Create a handler error message.

        Args:
            method: The notification method that failed.
            error: Error description.

        Returns:
            QueuedMessage with HANDLER_ERROR type.
        """
        return cls(MessageType.HANDLER_ERROR, {"method": method, "error": error})

    @classmethod
    def notification(cls, data: dict[str, Any]) -> QueuedMessage:
        """Create an unhandled notification message.

        Args:
            data: The notification payload.

        Returns:
            QueuedMessage with NOTIFICATION type.
        """
        return cls(MessageType.NOTIFICATION, {"data": data})

    @classmethod
    def parse_error(cls, error: str) -> QueuedMessage:
        """Create a parse error message.

        Args:
            error: Error description.

        Returns:
            QueuedMessage with PARSE_ERROR type.
        """
        return cls(MessageType.PARSE_ERROR, {"error": error})


class WebSocketClient:
    """Asynchronous WebSocket client with thread-safe JSON-RPC support.

    Manages a persistent WebSocket connection in a background thread with
    automatic reconnection, JSON-RPC request/response handling, server
    notification dispatch, and HTTP file upload capabilities.

    The client maintains an internal event loop and handles all async
    operations transparently, providing a synchronous interface to callers.

    Attributes:
        url: WebSocket server URL.
        loop: Internal asyncio event loop running in background thread.
        session: Aiohttp client session for HTTP and WebSocket.
        ws: Active WebSocket connection (None when disconnected).
        message_queue: Queue for unhandled messages and errors.
        logger: Logger instance for debugging and error tracking.

    Example:
        >>> # Manual lifecycle
        >>> client = WebSocketClient("ws://localhost:7125/websocket")
        >>> client.start()
        >>> client.wait_for_connection()
        >>> response = client.send_jsonrpc(request)
        >>> client.stop()

        >>> # Or use context manager
        >>> with WebSocketClient("ws://localhost:7125/websocket") as client:
        ...     client.wait_for_connection()
        ...     response = client.send_jsonrpc(request)
    """

    class UploadError(Exception):
        """Raised when G-code file upload fails.

        This exception indicates a problem during the HTTP upload process,
        such as file not found, network error, or server rejection.
        """

    # Reconnection parameters
    INITIAL_RECONNECT_DELAY = 1.0  # seconds
    MAX_RECONNECT_DELAY = 60.0  # seconds
    RECONNECT_BACKOFF_FACTOR = 2.0

    def __init__(self, url: str) -> None:
        """Initialize WebSocket client with server URL.

        Args:
            url: WebSocket server URL (e.g., "ws://192.168.1.100:7125/websocket").

        Raises:
            ValueError: If URL is empty or invalid.

        Note:
            The client is not connected until start() is called.

        Example:
            >>> client = WebSocketClient("ws://localhost:7125/websocket")
        """
        # Validate URL
        if not url or not url.strip():
            raise ValueError("WebSocket URL cannot be empty")

        # Logging
        self.logger = logging.getLogger(__name__)

        # Connection state
        self._connected = threading.Event()
        self.url = url.strip()
        self._reconnect_delay = self.INITIAL_RECONNECT_DELAY

        # Async runtime
        self.loop = asyncio.new_event_loop()
        self.session: ClientSession | None = None
        self.ws: ClientWebSocketResponse | None = None

        # Background thread
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self._shutdown_event = threading.Event()
        self._wrapper_task: asyncio.Task[None] | None = None

        # Message handling
        self.message_queue: Queue[QueuedMessage] = Queue()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._handlers: dict[str, Callable[[Any], None]] = {}

    def __repr__(self) -> str:
        """Return string representation of WebSocketClient.

        Example:
            >>> client = WebSocketClient("ws://localhost:7125/websocket")
            >>> repr(client)
            'WebSocketClient(url=ws://localhost:7125/websocket, connected=False)'
        """
        return f"WebSocketClient(url={self.url}, " f"connected={self.is_connected()})"

    def __len__(self) -> int:
        """Return number of queued messages.

        Returns:
            Number of unhandled messages in the queue.

        Example:
            >>> client = WebSocketClient(url)
            >>> len(client)
            3  # 3 unhandled messages
        """
        return self.message_queue.qsize()

    def __enter__(self) -> WebSocketClient:
        """Enter context manager and start the client.

        Returns:
            Self for use in with statement.

        Example:
            >>> with WebSocketClient("ws://localhost:7125/websocket") as client:
            ...     client.wait_for_connection()
            ...     # Use client
        """
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager and stop the client.

        Args:
            exc_type: Exception type if an exception occurred, None otherwise.
            exc_val: Exception instance if an exception occurred, None otherwise.
            exc_tb: Exception traceback if an exception occurred, None otherwise.
        """
        _ = exc_type
        _ = exc_val
        _ = exc_tb
        self.stop()

    def start(self) -> None:
        """Start the background thread and begin WebSocket connection.

        Launches the internal event loop in a daemon thread and initiates
        connection to the server. The method returns immediately; use
        wait_for_connection() to block until connected.

        Example:
            >>> client.start()
            >>> # Client is now connecting in background
        """
        self.logger.info(f"Starting WebSocket client for {self.url}")
        self.thread.start()

    def stop(self) -> None:
        """Stop the client and clean up all resources."""
        self.logger.info("Stopping WebSocket client")
        self._shutdown_event.set()
        self._connected.clear()

        # Cancel background wrapper task if running
        if self._wrapper_task:
            self.loop.call_soon_threadsafe(self._wrapper_task.cancel)

        # Run cleanup coroutine
        cleanup_future = asyncio.run_coroutine_threadsafe(self._cleanup(), self.loop)
        try:
            cleanup_future.result(timeout=5)
        except TimeoutError:
            self.logger.warning("Cleanup timed out after 5 seconds")
        except Exception as e:
            self.logger.error("Error during cleanup: %s", e, exc_info=True)

        # Stop event loop and join thread
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            self.logger.warning("Background thread did not terminate cleanly")
        else:
            self.logger.info("WebSocket client stopped")

    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """Wait for WebSocket connection to be established.

        Args:
            timeout: Maximum time to wait in seconds (default: 10.0).

        Returns:
            True if connected within timeout, False otherwise.

        Example:
            >>> client.start()
            >>> if client.wait_for_connection(timeout=5):
            ...     print("Connected!")
            ... else:
            ...     print("Connection timeout")
        """
        return self._connected.wait(timeout=timeout)

    def is_connected(self) -> bool:
        """Check if WebSocket is currently connected.

        Returns:
            True if connection is active, False otherwise.

        Example:
            >>> if client.is_connected():
            ...     client.send_notification("ping")
        """
        return self._connected.is_set()

    @property
    def handlers(self) -> dict[str, Callable[[Any], None]]:
        """Read-only snapshot of registered notification handlers.

        Returns a shallow copy so callers cannot mutate the internal dict.

        Returns:
            Dictionary mapping method names to their handler callbacks.

        Example:
            >>> for method in client.handlers:
            ...     print(f"Handling: {method}")
        """
        return dict(self._handlers)

    @property
    def pending_count(self) -> int:
        """Number of JSON-RPC requests currently awaiting a response.

        Returns:
            Count of in-flight requests.

        Example:
            >>> if client.pending_count > 0:
            ...     print("Waiting for responses...")
        """
        return len(self._pending)

    def _run_loop(self) -> None:
        """Run the asyncio event loop in the background thread.

        This is the entry point for the daemon thread. It configures
        the event loop, starts the main wrapper task, and runs until
        stop() is called.

        Note:
            This method should not be called directly. Use start() instead.
        """
        asyncio.set_event_loop(self.loop)
        self._wrapper_task = self.loop.create_task(self._main_wrapper())
        self.loop.run_forever()

        # Clean up after loop stops
        self.loop.close()

    async def _main_wrapper(self) -> None:
        """Wrapper that restarts main coroutine on errors.

        Continuously runs the main connection coroutine, catching and
        logging any fatal errors without terminating the event loop.
        This ensures the client can recover from unexpected failures.
        """
        while not self._shutdown_event.is_set():
            try:
                await self._main()
            except Exception as e:
                self.logger.error(
                    "Fatal error in background loop: %s", e, exc_info=True
                )
                self.message_queue.put(QueuedMessage.fatal_error(str(e)))
                await asyncio.sleep(1)

    async def _main(self) -> None:
        """Main connection loop with automatic reconnection.

        Establishes HTTP session and WebSocket connection, then maintains
        the connection with automatic reconnection on failure. Implements
        exponential backoff between reconnection attempts.
        """
        self.session = aiohttp.ClientSession()
        try:
            while not self._shutdown_event.is_set():
                self._connected.clear()
                try:
                    # Establish WebSocket connection
                    self.logger.debug(f"Attempting to connect to {self.url}")
                    self.ws = await self.session.ws_connect(self.url)
                    self._connected.set()
                    self._reconnect_delay = (
                        self.INITIAL_RECONNECT_DELAY
                    )  # Reset on success
                    self.logger.info("WebSocket connected successfully")

                    # Run message receive loop
                    await self._receive_loop()

                except Exception as e:
                    self.logger.warning(
                        "Connection error (will retry in %.1fs): %s",
                        self._reconnect_delay,
                        e,
                    )
                    self.message_queue.put(QueuedMessage.connection_error(str(e)))

                    # Exponential backoff
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * self.RECONNECT_BACKOFF_FACTOR,
                        self.MAX_RECONNECT_DELAY,
                    )

                finally:
                    # Clean up WebSocket connection
                    if self.ws and not self.ws.closed:
                        await self.ws.close()
                    self.ws = None
        finally:
            # Clean up HTTP session
            if self.session and not self.session.closed:
                await self.session.close()
            self.session = None
            self._connected.clear()

    async def _cleanup(self) -> None:
        """Cancel pending requests and close all connections.

        Called during shutdown to ensure all resources are released:
        - Cancels all pending request futures
        - Closes WebSocket connection
        - Closes HTTP session
        - Clears connection state
        """
        self.logger.debug("Cleaning up WebSocket client resources")

        # Cancel all pending futures
        for request_id, fut in self._pending.items():
            if not fut.done():
                self.logger.debug(f"Cancelling pending request: {request_id}")
                fut.cancel()
        self._pending.clear()

        # Close connections
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session and not self.session.closed:
            await self.session.close()

        self._connected.clear()

    async def _receive_loop(self) -> None:
        """Receive and dispatch WebSocket messages.

        Continuously receives messages from the WebSocket and routes them:
        - Responses with matching ID go to pending futures
        - Notifications with registered handlers go to callbacks
        - Unhandled messages go to the message queue

        Exits when connection is closed or shutdown is signaled.
        """
        while not self._shutdown_event.is_set() and self.ws:
            msg = await self.ws.receive()

            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_id = data.get("id")
                    method = data.get("method")

                    # Check if this is a response to a pending request
                    if msg_id and msg_id in self._pending:
                        fut = self._pending.pop(msg_id)
                        if "error" in data:
                            self.logger.warning(
                                "Server error for request %s: %s", msg_id, data["error"]
                            )
                            fut.set_exception(
                                RuntimeError(f"Server error: {data['error']}")
                            )
                        else:
                            self.logger.debug(f"Received response for request {msg_id}")
                            fut.set_result(data)

                    # Check if this is a notification with a registered handler
                    elif method and method in self._handlers:
                        self.logger.debug(f"Dispatching notification: {method}")
                        try:
                            self._handlers[method](data.get("params"))
                        except Exception as e:
                            self.logger.error(
                                "Error in handler for %s: %s", method, e, exc_info=True
                            )
                            self.message_queue.put(
                                QueuedMessage.handler_error(method, str(e))
                            )

                    # Queue unhandled messages
                    else:
                        self.logger.debug(f"Unhandled message: {data}")
                        self.message_queue.put(QueuedMessage.notification(data))

                except Exception as e:
                    self.logger.error("Failed to parse message: %s", e, exc_info=True)
                    self.message_queue.put(QueuedMessage.parse_error(str(e)))

            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                self.logger.info("WebSocket closed or error received")
                break

    def _ensure_connection(self) -> None:
        """Verify WebSocket connection is established.

        Raises:
            RuntimeError: If WebSocket handshake is not complete.

        Note:
            Called before sending any data to ensure connection is ready.
        """
        if not self._connected.is_set():
            raise RuntimeError(
                "WebSocket not connected. Call start() and wait_for_connection() first."
            )

    async def _send_and_receive(
        self,
        request_id: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Send JSON-RPC request and wait for response.

        Args:
            request_id: Unique request identifier.
            payload: Complete JSON-RPC request dictionary.
            timeout: Maximum time to wait for response in seconds.

        Returns:
            JSON-RPC response dictionary.

        Raises:
            RuntimeError: If server returns an error response or WebSocket
                          not connected.
        """  # Create future for this request
        fut: asyncio.Future[dict[str, Any]] = self.loop.create_future()
        self._pending[request_id] = fut

        # Send request
        if self.ws is None:
            raise RuntimeError("WebSocket not connected")

        self.logger.debug(f"Sending request {request_id}: {payload.get('method')}")
        await self.ws.send_str(json.dumps(payload))

        # Wait for response
        result = await asyncio.wait_for(fut, timeout)
        return result

    def send_jsonrpc(
        self,
        payload: dict[str, Any],
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Send JSON-RPC request and return response synchronously.

        Blocks until response is received or timeout occurs. Thread-safe
        and can be called from any thread.

        Args:
            payload: JSON-RPC request with "jsonrpc", "method", and "id" fields.
            timeout: Maximum time to wait for response in seconds (default: 5.0).

        Returns:
            JSON-RPC response dictionary.

        Raises:
            RuntimeError: If WebSocket is not connected.
            TimeoutError: If response not received within timeout.

        Example:
            >>> request = {
            ...     "jsonrpc": "2.0",
            ...     "method": "printer.info",
            ...     "id": "123"
            ... }
            >>> response = client.send_jsonrpc(request)
            >>> print(response["result"])
        """
        self._ensure_connection()

        request_id = payload["id"]
        coro = self._send_and_receive(request_id, payload, timeout)
        concurrent_future = asyncio.run_coroutine_threadsafe(coro, self.loop)

        try:
            return concurrent_future.result(timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            method = payload.get("method", "unknown")
            self.logger.warning(f"Request timeout for method '{method}'")
            raise TimeoutError(
                f"Timed out waiting for response to method '{method}'"
            ) from None
        except Exception as e:
            self._pending.pop(request_id, None)
            self.logger.error("Error sending JSON-RPC: %s", e, exc_info=True)
            raise RuntimeError(f"Unexpected error sending JSON-RPC: {e}") from e

    def send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        """Send JSON-RPC notification without expecting response.

        Notifications are fire-and-forget messages that don't include an ID
        and don't expect a response from the server.

        Args:
            method: JSON-RPC method name.
            params: Optional parameters dictionary.

        Raises:
            RuntimeError: If WebSocket is not connected.

        Example:
            >>> client.send_notification("notify_klippy_ready")
            >>> client.send_notification("notify_gcode_response", {"message": "ok"})
        """
        self._ensure_connection()

        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params

        if self.ws is None:
            raise RuntimeError("WebSocket not connected")

        self.logger.debug(f"Sending notification: {method}")
        asyncio.run_coroutine_threadsafe(
            self.ws.send_str(json.dumps(payload)), self.loop
        )

    def register_handler(self, method: str, callback: Callable[[Any], None]) -> None:
        """Register callback for server-initiated notifications.

        When the server sends a notification (message without ID) with the
        specified method, the callback will be invoked with the params.

        Args:
            method: JSON-RPC method name to handle.
            callback: Function to call with notification params.

        Note:
            Only one handler can be registered per method. Registering a new
            handler replaces any existing handler for that method.

        Example:
            >>> def on_status(params):
            ...     print(f"Printer status: {params}")
            >>>
            >>> client.register_handler("notify_status_update", on_status)
        """
        self.logger.debug(f"Registering handler for method: {method}")
        self._handlers[method] = callback

    def unregister_handler(self, method: str) -> None:
        """Remove handler for a notification method.

        Args:
            method: JSON-RPC method name to stop handling.

        Example:
            >>> client.unregister_handler("notify_status_update")
        """
        if method in self._handlers:
            self.logger.debug(f"Unregistering handler for method: {method}")
            self._handlers.pop(method)

    async def _upload_gcode_file_async(
        self, file_name: str, file_path: str | Path
    ) -> str:
        """Upload G-code file to server asynchronously using shared session.

        Args:
            file_name: Name to use for the uploaded file on server.
            file_path: Local path to the file to upload.

        Returns:
            Server-side file path where the file was stored.

        Raises:
            UploadError: If upload fails for any reason.
            RuntimeError: If client session is not initialized.

        Note:
            This is an internal async method. Use upload_gcode_file() instead.
        """
        if not file_path:
            raise WebSocketClient.UploadError("File path not provided.")

        if not self.session:
            raise RuntimeError("Client session not initialized")

        file_path = Path(file_path)

        try:
            # Construct upload URL from WebSocket URL
            parsed = urlparse(self.url)
            host = parsed.hostname
            upload_url = f"http://{host}/server/files/upload"

            self.logger.debug(f"Uploading file {file_name} to {upload_url}")

            # Read file content (using async context manager for safety)
            loop = asyncio.get_running_loop()

            # Read file in executor
            def read_file() -> bytes:
                with file_path.open("rb") as f:  # ✅ Use context manager
                    return f.read()

            file_content = await loop.run_in_executor(None, read_file)

            # Prepare multipart form data
            data = FormData()
            data.add_field(
                "file",
                file_content,
                filename=file_name,
                content_type="application/octet-stream",
            )

            # Upload file via HTTP POST using shared session
            async with self.session.post(upload_url, data=data) as response:
                if response.status != 201:
                    text = await response.text()
                    self.logger.error(
                        f"Upload failed with status {response.status}: {text}"
                    )
                    raise WebSocketClient.UploadError(
                        f"Upload failed (status {response.status}): {text}"
                    )

                # Parse response to get server path
                try:
                    payload = await response.json()
                except Exception as e:
                    raise WebSocketClient.UploadError(
                        "Upload response was not valid JSON."
                    ) from e

                server_fp = payload.get("item", {}).get("path")
                if not server_fp:
                    raise WebSocketClient.UploadError(
                        "Upload succeeded but no 'item.path' returned."
                    )

                self.logger.info(f"File uploaded successfully to: {server_fp}")
                return server_fp

        except FileNotFoundError as e:
            self.logger.error(f"File not found: {file_path}")
            raise WebSocketClient.UploadError(
                f"File not found at path: {file_path}"
            ) from e
        except WebSocketClient.UploadError:
            raise
        except Exception as e:
            self.logger.error("Unexpected upload error: %s", e, exc_info=True)
            raise WebSocketClient.UploadError(
                f"Unexpected error during upload: {e}"
            ) from e

    def upload_gcode_file(self, file_name: str, file_path: str | Path) -> Future[str]:
        """Upload G-code file to server and return Future.

        Schedules the upload to run in the background event loop and
        returns a Future that will contain the server-side path when
        complete.

        Args:
            file_name: Name to use for file on server.
            file_path: Local path to the file to upload.

        Returns:
            Future that resolves to server-side file path.

        Note:
            The Future will raise UploadError if upload fails (when
            Future.result() is called).

        Example:
            >>> future = client.upload_gcode_file(
            ...     "protocol.gcode",
            ...     "/tmp/file.gcode"
            ... )
            >>> server_path = future.result()
            >>> print(f"Uploaded to: {server_path}")
        """
        coro = self._upload_gcode_file_async(file_name, file_path)
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def get_queued_messages(self) -> list[QueuedMessage]:
        """Retrieve all queued unhandled messages.

        Returns:
            List of QueuedMessage objects from the queue.

        Note:
            Drains the message queue, removing all messages.

        Example:
            >>> messages = client.get_queued_messages()
            >>> for msg in messages:
            ...     if msg.type == MessageType.CONNECTION_ERROR:
            ...         print(f"Error: {msg.data['text']}")
        """
        messages: list[QueuedMessage] = []
        while not self.message_queue.empty():
            messages.append(self.message_queue.get_nowait())
        return messages

    def clear_queue(self) -> int:
        """Clear all queued messages.

        Returns:
            Number of messages that were cleared.

        Example:
            >>> count = client.clear_queue()
            >>> print(f"Cleared {count} messages")
        """
        count = 0
        while not self.message_queue.empty():
            try:
                self.message_queue.get_nowait()
                count += 1
            except Empty:
                break
        return count

    def pop_message(self) -> QueuedMessage | None:
        """Remove and return the next queued message, or None if empty.

        Unlike ``get_queued_messages()``, this removes only a single message
        so the rest of the queue is undisturbed.

        Returns:
            The next QueuedMessage, or None if the queue is empty.

        Example:
            >>> msg = client.pop_message()
            >>> if msg is not None:
            ...     print(msg.type, msg.data)
        """
        try:
            return self.message_queue.get_nowait()
        except Empty:
            return None

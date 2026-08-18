"""A duck-typed stand-in for :class:`moonraker.websocket_client.WebSocketClient`.

`WebSocketClient` runs a real asyncio event loop on a background thread and
talks to a real Moonraker instance. Service-layer tests (Phase 1 onward of
the ports-and-adapters migration) should depend on this fake instead, so
they can run without any network I/O or background threads.

Not a subclass of `WebSocketClient` -- it only implements the subset of the
public API the daemon/service layer actually calls: `send_jsonrpc`,
`send_notification`, `upload_gcode_file`, `is_connected`, `register_handler`,
`unregister_handler`, `handlers`, `pending_count`, `__len__`, `pop_message`,
`get_queued_messages`, `clear_queue`, `start`/`stop`/`wait_for_connection`.
Extend this fake's surface as later phases need more of it.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from tricca_autopipette.moonraker.websocket_client import MessageType, QueuedMessage


class FakeWebSocketClient:
    """In-memory fake of `WebSocketClient` for service-layer unit tests.

    Attributes:
        sent_requests: Every JSON-RPC payload passed to `send_jsonrpc`, in
            call order -- inspect this to assert what a service method sent
            to "Moonraker".
        sent_notifications: Every `(method, params)` pair passed to
            `send_notification`.
        uploaded_files: Every `(file_name, file_path)` pair passed to
            `upload_gcode_file`.
    """

    def __init__(self, *, connected: bool = True) -> None:
        """Initialize the fake with an empty canned-response queue.

        Args:
            connected: Initial value `is_connected()` should report.
        """
        self._connected = connected
        self._responses: deque[dict[str, Any]] = deque()
        self._handlers: dict[str, Callable[[Any], None]] = {}
        self.sent_requests: list[dict[str, Any]] = []
        self.sent_notifications: list[tuple[str, dict[str, Any] | None]] = []
        self.uploaded_files: list[tuple[str, str]] = []
        self._message_queue: deque[QueuedMessage] = deque()

    def queue_response(self, response: dict[str, Any]) -> None:
        """Queue a canned response for the next `send_jsonrpc` call.

        Args:
            response: The dict `send_jsonrpc` should return, e.g.
                ``{"result": {...}}``.
        """
        self._responses.append(response)

    def send_jsonrpc(
        self, payload: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any]:
        """Record the request and return the next queued canned response.

        Returns:
            The next queued canned response, or ``{"result": {}}`` if the
            queue is empty.
        """
        del timeout
        self.sent_requests.append(payload)
        if self._responses:
            return self._responses.popleft()
        return {"result": {}}

    def send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        """Record a fire-and-forget notification."""
        self.sent_notifications.append((method, params))

    def upload_gcode_file(self, file_name: str, file_path: str | Path) -> Future[str]:
        """Record the upload and return an already-resolved Future.

        Returns:
            An already-resolved `Future` holding the uploaded file's path.
        """
        self.uploaded_files.append((file_name, str(file_path)))
        future: Future[str] = Future()
        future.set_result(f"gcodes/{file_name}")
        return future

    def register_handler(self, method: str, callback: Callable[[Any], None]) -> None:
        """Record a notification handler so tests can trigger it directly."""
        self._handlers[method] = callback

    def unregister_handler(self, method: str) -> None:
        """Remove a previously-registered notification handler, if present."""
        self._handlers.pop(method, None)

    @property
    def handlers(self) -> dict[str, Callable[[Any], None]]:
        """Return a snapshot of currently-registered handlers."""
        return dict(self._handlers)

    @property
    def pending_count(self) -> int:
        """Always 0: this fake resolves every `send_jsonrpc` synchronously."""
        return 0

    def __len__(self) -> int:
        """Return the number of queued messages."""
        return len(self._message_queue)

    def queue_message(
        self,
        message_type: MessageType = MessageType.NOTIFICATION,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Push a message onto the queue for `pop_message`/`get_queued_messages`.

        Args:
            message_type: The `MessageType` to tag the message with.
            data: The message payload, or None for an empty dict.
        """
        self._message_queue.append(QueuedMessage(type=message_type, data=data or {}))

    def pop_message(self) -> QueuedMessage | None:
        """Pop and return the oldest queued message, or None if empty.

        Returns:
            The oldest queued message, or None if the queue is empty.
        """
        return self._message_queue.popleft() if self._message_queue else None

    def get_queued_messages(self) -> list[QueuedMessage]:
        """Drain and return every queued message, in FIFO order.

        Returns:
            Every message that was queued, in FIFO order. The queue is
            empty afterwards.
        """
        messages = list(self._message_queue)
        self._message_queue.clear()
        return messages

    def clear_queue(self) -> int:
        """Discard all queued messages, returning how many were removed.

        Returns:
            The number of messages that were discarded.
        """
        count = len(self._message_queue)
        self._message_queue.clear()
        return count

    def trigger_notification(self, method: str, params: Any) -> None:
        """Invoke a previously-registered handler, simulating a server push.

        Args:
            method: The method name the handler was registered under.
            params: Params to pass through to the handler.

        Raises:
            KeyError: If no handler was registered for `method`.
        """  # ruff: ignore[docstring-extraneous-exception]
        self._handlers[method](params)

    def is_connected(self) -> bool:
        """Return the fake's configured connection state."""
        return self._connected

    def set_connected(self, connected: bool) -> None:
        """Flip the fake's connection state, e.g. to simulate a drop."""
        self._connected = connected

    def start(self) -> None:
        """No-op: there is no real background thread/event loop to start."""

    def stop(self) -> None:
        """No-op: there is no real background thread/event loop to stop."""

    def wait_for_connection(self, timeout: float = 10.0) -> bool:
        """Return the fake's configured connection state immediately."""
        del timeout
        return self._connected

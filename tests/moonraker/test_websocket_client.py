"""Tests exercising the real ``WebSocketClient`` against a real local server.

Every other daemon/core test talks to `FakeWebSocketClient`
(`tests/fakes/fake_websocket_client.py`) instead -- these are the ones that
actually open a socket, so they're the ones that can catch a race between
`WebSocketClient`'s background thread and its callers (issue #38).

The server side (`_RealServer`) is a real `websockets.serve` instance run in
its own background thread with its own event loop, deliberately mirroring
`WebSocketClient`'s own background-thread-plus-loop shape rather than an
async pytest fixture on a per-test loop: every test body here stays a plain
synchronous function that calls `WebSocketClient`'s blocking public API
(`send_jsonrpc`, `wait_for_connection`, ...) from the main test thread, so
the server has to keep servicing I/O on a loop of its own the whole time --
not just at fixture await points, which a same-loop async fixture couldn't
do once the synchronous test body took over the thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, cast

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from tricca_autopipette.moonraker.websocket_client import MessageType, WebSocketClient

Handler = Callable[[websockets.WebSocketServerProtocol], Awaitable[None]]
ServerFactory = Callable[[Handler], str]


class _RealServer:
    """A `websockets` server run on its own thread, for tests only.

    Mirrors `WebSocketClient`'s own background-thread/event-loop shape so a
    test exercises two independent real threads talking over a real loopback
    socket, rather than one loop juggling both the client and the server.
    """

    def __init__(self, handler: Handler) -> None:
        """Store the connection handler; nothing runs until `start()`.

        Args:
            handler: Coroutine function invoked with each accepted
                connection, in the shape `websockets.serve` expects.
        """
        self._handler = handler
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._server: websockets.WebSocketServer | None = None
        self._port = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def url(self) -> str:
        """The `ws://localhost:<port>/websocket` URL this server is bound to."""
        return f"ws://localhost:{self._port}/websocket"

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        self._server = await websockets.serve(self._handler, "localhost", 0)
        sock = next(iter(self._server.sockets))
        addr = cast("tuple[str, int]", sock.getsockname())
        self._port = addr[1]
        self._ready.set()
        await self._server.wait_closed()

    def start(self) -> None:
        """Start the server thread and block until it's accepting connections.

        Raises:
            RuntimeError: If the server doesn't start accepting connections
                within 5 seconds.
        """
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Test WebSocket server failed to start")

    def stop(self) -> None:
        """Close the listening socket/connections and join the server thread."""
        if self._server is not None:
            self._loop.call_soon_threadsafe(self._server.close)
        self._thread.join(timeout=5)
        self._loop.close()


@pytest.fixture
def real_server() -> Iterator[ServerFactory]:
    """A factory for real, per-test `websockets` servers.

    Returns a callable that takes a connection handler and returns the
    `ws://...` URL a `WebSocketClient` can connect to. Every server started
    through it is torn down automatically at the end of the test.

    Yields:
        A factory that starts a real server for the given handler and
        returns its URL.
    """
    servers: list[_RealServer] = []

    def _start(handler: Handler) -> str:
        server = _RealServer(handler)
        server.start()
        servers.append(server)
        return server.url

    yield _start

    for server in servers:
        server.stop()


def _poll_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> bool:
    """Poll `predicate` until it's true or `timeout` seconds have elapsed.

    Returns:
        True if `predicate` became true before `timeout` elapsed, else False.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestConcurrentRequests:
    """Many threads calling `send_jsonrpc` on one client at once."""

    def test_routes_each_threads_response_to_the_right_caller(
        self, real_server: ServerFactory
    ) -> None:
        """20 threads race `send_jsonrpc`; the server answers out of order.

        Exercises the thread-safety of `WebSocketClient`'s `_pending` dict:
        if two threads' requests were ever cross-wired, one of them would
        get back another thread's echoed payload instead of its own.
        """

        async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
            async def respond(raw: str | bytes) -> None:
                data = json.loads(raw)
                # Vary the delay so responses can arrive out of send order,
                # not just out of thread-start order.
                await asyncio.sleep(0.01 * (data["params"]["n"] % 3))
                with contextlib.suppress(ConnectionClosed):
                    await websocket.send(
                        json.dumps({
                            "jsonrpc": "2.0",
                            "id": data["id"],
                            "result": {"echo": data["params"]},
                        })
                    )

            async for raw in websocket:
                asyncio.get_running_loop().create_task(respond(raw))

        url = real_server(handler)
        client = WebSocketClient(url)
        client.start()
        try:
            assert client.wait_for_connection(timeout=5)

            results: dict[int, dict[str, Any]] = {}
            errors: list[Exception] = []
            lock = threading.Lock()

            def worker(n: int) -> None:
                try:
                    response = client.send_jsonrpc(
                        {
                            "jsonrpc": "2.0",
                            "method": "echo",
                            "id": f"req-{n}",
                            "params": {"n": n},
                        },
                        timeout=5.0,
                    )
                    with lock:
                        results[n] = response
                except Exception as exc:
                    with lock:
                        errors.append(exc)

            threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

            assert errors == []
            assert set(results) == set(range(20))
            for n, response in results.items():
                assert response["result"]["echo"] == {"n": n}
        finally:
            client.stop()


class TestNotificationDelivery:
    """Server-pushed notifications, dispatched through registered handlers."""

    def test_preserves_send_order_through_the_registered_handler(
        self, real_server: ServerFactory
    ) -> None:
        async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
            for i in range(20):
                await websocket.send(
                    json.dumps({
                        "jsonrpc": "2.0",
                        "method": "notify_seq",
                        "params": {"i": i},
                    })
                )
            await websocket.wait_closed()

        url = real_server(handler)
        client = WebSocketClient(url)
        received: list[int] = []
        lock = threading.Lock()

        def on_seq(params: dict[str, Any]) -> None:
            with lock:
                received.append(params["i"])

        client.register_handler("notify_seq", on_seq)
        client.start()
        try:
            assert client.wait_for_connection(timeout=5)
            assert _poll_until(lambda: len(received) >= 20)
            assert received == list(range(20))
        finally:
            client.stop()

    def test_unregistering_stops_delivery_to_the_handler(
        self, real_server: ServerFactory
    ) -> None:
        release = threading.Event()

        async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
            await websocket.send(
                json.dumps({"jsonrpc": "2.0", "method": "notify_x", "params": {}})
            )
            await asyncio.get_running_loop().run_in_executor(None, release.wait, 5)
            await websocket.send(
                json.dumps({"jsonrpc": "2.0", "method": "notify_x", "params": {}})
            )
            await websocket.wait_closed()

        url = real_server(handler)
        client = WebSocketClient(url)
        call_count = 0
        lock = threading.Lock()

        def on_x(params: dict[str, Any]) -> None:
            nonlocal call_count
            del params
            with lock:
                call_count += 1

        client.register_handler("notify_x", on_x)
        client.start()
        try:
            assert client.wait_for_connection(timeout=5)
            assert _poll_until(lambda: call_count >= 1)

            client.unregister_handler("notify_x")
            release.set()

            # Give the second push a moment to arrive; it should land in the
            # message queue as unhandled, not re-invoke the removed handler.
            assert _poll_until(lambda: len(client) >= 1)
            assert call_count == 1
            messages = client.get_queued_messages()
            assert any(m.type == MessageType.NOTIFICATION for m in messages)
        finally:
            client.stop()

    def test_unhandled_notification_lands_in_the_message_queue(
        self, real_server: ServerFactory
    ) -> None:
        async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
            await websocket.send(
                json.dumps({
                    "jsonrpc": "2.0",
                    "method": "notify_unhandled",
                    "params": {"x": 1},
                })
            )
            await websocket.wait_closed()

        url = real_server(handler)
        client = WebSocketClient(url)
        client.start()
        try:
            assert client.wait_for_connection(timeout=5)
            assert _poll_until(lambda: len(client) >= 1)

            message = client.pop_message()
            assert message is not None
            assert message.type == MessageType.NOTIFICATION
            assert message.data["data"]["method"] == "notify_unhandled"
        finally:
            client.stop()


class TestConnectionDrop:
    """Behavior when the server side disappears mid-request or between calls."""

    def test_pending_request_times_out_rather_than_hanging_forever(
        self, real_server: ServerFactory
    ) -> None:
        """The server reads a request, then drops the connection without

        answering. `WebSocketClient` has no fast-fail path for this today --
        `_pending` futures are only resolved by a matching response or
        cancelled in `stop()`'s cleanup -- so the caller's own `timeout`
        (not the drop itself) is what ends the call. Documents current
        behavior; see issue #38 if that's ever worth changing.
        """

        async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
            await websocket.recv()
            await websocket.close()

        url = real_server(handler)
        client = WebSocketClient(url)
        client.start()
        try:
            assert client.wait_for_connection(timeout=5)
            with pytest.raises(TimeoutError):
                client.send_jsonrpc(
                    {"jsonrpc": "2.0", "method": "ping", "id": "abc"},
                    timeout=1.0,
                )
        finally:
            client.stop()

    def test_reconnects_after_a_graceful_drop_and_completes_a_fresh_request(
        self, real_server: ServerFactory
    ) -> None:
        """First connection is dropped immediately; the client should

        transparently reconnect and successfully complete a request against
        the second connection.
        """
        connection_count = 0

        async def handler(websocket: websockets.WebSocketServerProtocol) -> None:
            nonlocal connection_count
            connection_count += 1
            if connection_count == 1:
                await websocket.close()
                return
            async for raw in websocket:
                data = json.loads(raw)
                await websocket.send(
                    json.dumps({
                        "jsonrpc": "2.0",
                        "id": data["id"],
                        "result": {"ok": True},
                    })
                )

        url = real_server(handler)
        client = WebSocketClient(url)
        client.start()
        try:
            assert client.wait_for_connection(timeout=5)

            deadline = time.monotonic() + 5
            response: dict[str, Any] | None = None
            last_error: Exception | None = None
            while response is None and time.monotonic() < deadline:
                try:
                    response = client.send_jsonrpc(
                        {"jsonrpc": "2.0", "method": "ping", "id": "retry"},
                        timeout=0.5,
                    )
                except (TimeoutError, RuntimeError) as exc:
                    last_error = exc
                    time.sleep(0.05)

            assert response is not None, f"never reconnected: {last_error}"
            assert response["result"] == {"ok": True}
        finally:
            client.stop()

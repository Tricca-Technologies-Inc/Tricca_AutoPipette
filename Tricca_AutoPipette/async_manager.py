"""Holds classes to regulate async code and provides a bridge for sync code."""
import asyncio
import threading
import uuid
import json
import websockets
import janus
import queue
from typing import Any, Dict, Optional, List
from concurrent.futures import Future


class AsyncJSONRPCClient:
    """Send and receive JSONRPC through a websocket."""

    def __init__(self, uri: str):
        """Initialize self."""
        self.uri = uri
        self.request_queue: Optional[janus.Queue] = None
        self.response_futures: Dict[str, Future] = {}
        self.lock = threading.Lock()
        self.ws_task: Optional[asyncio.Task] = None
        self.shutdown_event = asyncio.Event()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def connect(self, loop: asyncio.AbstractEventLoop):
        """Initialize queues and start WebSocket task."""
        self.loop = loop
        self.request_queue = janus.Queue()
        # Create task using the provided event loop
        self.ws_task = loop.create_task(self._websocket_loop())

    async def _websocket_loop(self):
        """Handle main WebSocket with reconnection logic."""
        backoff_delay = 1
        max_backoff = 60

        while not self.shutdown_event.is_set():
            try:
                async with websockets.connect(self.uri) as ws:
                    backoff_delay = 1  # Reset backoff on successful connection
                    await self._handle_connection(ws)
            except (websockets.ConnectionClosed, OSError) as e:
                await asyncio.sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, max_backoff)
            except Exception:
                break

    async def _handle_connection(self, ws):
        """Process messages for a single connection."""
        sender = asyncio.create_task(self._send_messages(ws))
        receiver = asyncio.create_task(self._receive_messages(ws))
        done, _ = await asyncio.wait(
            [sender, receiver],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel any remaining tasks
        for task in [sender, receiver]:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _send_messages(self, ws):
        """Process outgoing messages from request queue."""
        while not self.shutdown_event.is_set():
            try:
                request = await self.request_queue.async_q.get()
                await ws.send(json.dumps(request))
            except (janus.QueueClosed, asyncio.CancelledError):
                break
            except Exception as e:
                self._set_exception_for_request(request, e)

    def _set_exception_for_request(self, request: Dict[str, Any], exc: Exception):
        """Thread-safe exception handling for failed requests."""
        with self.lock:
            if request_id := request.get('id'):
                if future := self.response_futures.pop(request_id, None):
                    future.set_exception(exc)

    async def _receive_messages(self, ws):
        """Process incoming messages and resolve futures."""
        while not self.shutdown_event.is_set():
            try:
                response = await ws.recv()
                data = json.loads(response)
                self._process_response(data)
            except (websockets.ConnectionClosed, json.JSONDecodeError) as e:
                raise
            except asyncio.CancelledError:
                raise
            except Exception:
                raise

    def _process_response(self, data: Dict[str, Any]):
        """Process JSON-RPC response and complete future."""
        if 'id' not in data:
            return  # Not a standard JSON-RPC response

        with self.lock:
            future = self.response_futures.pop(data['id'], None)

        if not future or future.done():
            return

        if 'result' in data:
            future.set_result(data['result'])
        elif 'error' in data:
            future.set_exception(Exception(data['error']))

    def send_request(self, method: str, params: List[Any]) -> Future:
        """Send JSON-RPC request and return response future."""
        request_id = str(uuid.uuid4())
        request = {
            "jsonrpc": "2.0",
            "method": method,
            # "params": params,
            "id": request_id
        }

        future = Future()
        with self.lock:
            self.response_futures[request_id] = future

        if self.request_queue:
            self.request_queue.sync_q.put(request)
        return future

    async def shutdown(self):
        """Graceful shutdown procedure."""
        self.shutdown_event.set()
        if self.ws_task:
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass

        self._cleanup_futures(RuntimeError("Client shutting down"))

        if self.request_queue:
            self.request_queue.close()
            await self.request_queue.wait_closed()

    def _cleanup_futures(self, exc: Exception):
        """Clean up all pending futures with exception."""
        with self.lock:
            futures = self.response_futures.values()
            self.response_futures.clear()

        for future in futures:
            if not future.done():
                future.set_exception(exc)


class AsyncManager:
    """Manages async components and thread synchronization."""

    def __init__(self, rpc_uri: str):
        """Initialize manager."""
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="AsyncManagerThread"
        )
        self.rpc_client = AsyncJSONRPCClient(rpc_uri)
        self.callback_queue = queue.Queue()
        self.thread.start()

    def _run_loop(self):
        """Run async event loop in dedicated thread."""
        asyncio.set_event_loop(self.loop)
        # Pass the loop to the client for task creation
        self.rpc_client.connect(self.loop)
        self.loop.run_forever()

    def send_request(self, method: str, params: List[Any]) -> Future:
        """Public method to send RPC requests."""
        return self.rpc_client.send_request(method, params)

    def schedule_shutdown(self):
        """Initiate graceful shutdown from any thread."""
        future = asyncio.run_coroutine_threadsafe(
            self.rpc_client.shutdown(),
            self.loop
        )
        self.loop.call_soon_threadsafe(self.loop.stop)
        return future

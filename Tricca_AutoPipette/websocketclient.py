#!/usr/bin/env python3
"""Holds the WebSocket class which manages connection to the autopipette."""
import asyncio
import json
import threading
import uuid
from queue import Queue
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse
import aiohttp
from aiohttp import ClientSession, WSMsgType, FormData


class WebSocketClient:
    """
    WebSocketClient manages a WebSocket connection in a background thread.

    It handles:
      - Establishing and re-establishing the connection (with automatic reconnect on failure).
      - Sending JSON-RPC requests and waiting for responses.
      - Sending JSON-RPC notifications without awaiting a response.
      - Uploading G-code files via HTTP and returning the server-side path.
      - Dispatching incoming messages either to awaiting futures (for request/response)
        or to registered handlers (for notifications), and queuing any unhandled messages
        for later retrieval.
      - Gracefully shutting down all pending tasks, closing the WebSocket and HTTP sessions,
        and stopping its internal event loop.
    """

    class UploadError(Exception):
        """Exception raised when file upload fails."""

        pass

    def __init__(self, url: str):
        """Initialize WebSocketClient with the given URL and prepare internal state."""
        self._connected = threading.Event()
        self.url = url
        self.loop = asyncio.new_event_loop()
        self.session: Optional[ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None

        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self._shutdown_event = threading.Event()
        self._wrapper_task: Optional[asyncio.Task] = None

        self.message_queue: Queue = Queue()
        self._pending: Dict[str, asyncio.Future] = {}
        self._handlers: Dict[str, Callable[[Any], None]] = {}

    def start(self) -> None:
        """Start the background thread and event loop for WebSocket communication."""
        self.thread.start()

    def stop(self) -> None:
        """Signal shutdown and clean up resources, stopping the background thread and event loop."""
        self._shutdown_event.set()
        self._connected.clear()

        # Cancel background wrapper task if it exists
        if self._wrapper_task:
            self.loop.call_soon_threadsafe(self._wrapper_task.cancel)

        cleanup_future = asyncio.run_coroutine_threadsafe(self._cleanup(),
                                                          self.loop)
        try:
            cleanup_future.result(timeout=5)
        except Exception as e:
            print(f"Error during cleanup: {e}")

        # Stop and close the loop
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()

    def _run_loop(self) -> None:
        """Configure and run the asyncio event loop in the background thread."""
        asyncio.set_event_loop(self.loop)
        self._wrapper_task = self.loop.create_task(self._main_wrapper())
        self.loop.run_forever()

        # Once run_forever() returns, close the loop
        self.loop.close()

    async def _main_wrapper(self) -> None:
        """Continuously run the main coroutine and handle unexpected errors without exiting."""
        while not self._shutdown_event.is_set():
            try:
                await self._main()
            except Exception as e:
                self.message_queue.put(
                    {"type": "fatal_error",
                     "text": f"Fatal error in background loop: {e}"})
                await asyncio.sleep(1)

    async def _main(self) -> None:
        """Establish and maintain the WebSocket connection, reconnecting on failure."""
        self.session = aiohttp.ClientSession()
        try:
            while not self._shutdown_event.is_set():
                self._connected.clear()
                try:
                    self.ws = await self.session.ws_connect(self.url)
                    self._connected.set()
                    await self._receive_loop()
                except Exception as e:
                    self.message_queue.put(
                        {"type": "error", "text": f"Connection error: {e}"})
                    await asyncio.sleep(5)
                finally:
                    if self.ws and not self.ws.closed:
                        await self.ws.close()
                    self.ws = None
        finally:
            if self.session and not self.session.closed:
                await self.session.close()
            self.session = None
            self._connected.clear()

    async def _cleanup(self) -> None:
        """Cancel pending futures and close WebSocket and HTTP session."""
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session and not self.session.closed:
            await self.session.close()
        self._connected.clear()

    async def _receive_loop(self) -> None:
        """Receive messages from WebSocket and dispatch to pending requests or handlers."""
        while not self._shutdown_event.is_set() and self.ws:
            msg = await self.ws.receive()
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_id = data.get("id")
                    method = data.get("method")

                    if msg_id and msg_id in self._pending:
                        fut = self._pending.pop(msg_id)
                        if "error" in data:
                            fut.set_exception(
                                RuntimeError(f"Server error: {data['error']}"))
                        else:
                            fut.set_result(data)
                    elif method and method in self._handlers:
                        try:
                            self._handlers[method](data.get("params"))
                        except Exception as e:
                            self.message_queue.put(
                                {"type": "handler_error",
                                 "method": method,
                                 "error": str(e)})
                    else:
                        self.message_queue.put(
                            {"type": "notification",
                             "data": data})
                except Exception as e:
                    self.message_queue.put({"type": "parse_error",
                                            "error": str(e)})
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break

    def _ensure_connection(self) -> None:
        """Verify that WebSocket handshake is complete before sending data."""
        if not self._connected.is_set():
            raise RuntimeError("WebSocket handshake not complete.")

    async def _send_and_receive(
        self,
        request_id: str,
        payload: Dict[str, Any],
        timeout: float,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC payload and wait for response up to timeout."""
        fut = self.loop.create_future()
        self._pending[request_id] = fut
        await self.ws.send_str(json.dumps(payload))
        result = await asyncio.wait_for(fut, timeout)
        return result

    def send_jsonrpc(
        self,
        payload: Dict[str, any],
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Send a JSON-RPC request with unique ID and return the response."""
        self._ensure_connection()
        request_id = payload["id"]
        coro = self._send_and_receive(request_id, payload, timeout)
        concurrent_future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return concurrent_future.result(timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            method = payload["method"]
            raise TimeoutError(
                f"Timed out waiting for response to method {method}")
        except Exception as e:
            self._pending.pop(request_id, None)
            raise RuntimeError(f"Unexpected error sending JSON-RPC: {e}")

    def send_notification(self,
                          method: str,
                          params: Optional[Dict[str, Any]] = None) -> None:
        """Send a JSON-RPC notification without expecting a response."""
        self._ensure_connection()
        payload = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        asyncio.run_coroutine_threadsafe(
            self.ws.send_str(json.dumps(payload)), self.loop)

    def register_handler(self,
                         method: str,
                         callback: Callable[[Any], None]) -> None:
        """Register a callback to handle server notifications for a specific method."""
        self._handlers[method] = callback

    async def _upload_gcode_file_async(self,
                                       file_name: str,
                                       file_path: str) -> str:
        """Upload a G-code file asynchronously and return the server-side path."""
        if not file_path:
            raise WebSocketClient.UploadError("File path not provided.")
        try:
            parsed = urlparse(self.url)
            host = parsed.hostname
            upload_url = f"http://{host}/server/files/upload"

            # Use the currently running loop explicitly
            loop = asyncio.get_running_loop()
            file_content = await loop.run_in_executor(None,
                                                      open,
                                                      file_path,
                                                      "rb")
            try:
                data = FormData()
                data.add_field("file",
                               file_content,
                               filename=file_name,
                               content_type="application/octet-stream")
                async with aiohttp.ClientSession() as session:
                    async with session.post(upload_url, data=data) as response:
                        if response.status != 201:
                            text = await response.text()
                            raise WebSocketClient.UploadError(
                                f"Upload failed (status {response.status}): "
                                f"{text}")
                        try:
                            payload = await response.json()
                        except Exception:
                            raise WebSocketClient.UploadError(
                                "Upload response was not valid JSON.")
                        server_fp = payload.get("item", {}).get("path")
                        if not server_fp:
                            raise WebSocketClient.UploadError(
                                "Upload succeeded but no 'item.path' returned."
                                )
                        return server_fp
            finally:
                file_content.close()
        except FileNotFoundError:
            raise WebSocketClient.UploadError(
                f"File not found at path: {file_path}")
        except WebSocketClient.UploadError:
            raise
        except Exception as e:
            raise WebSocketClient.UploadError(
                f"Unexpected error during upload: {e}")

    def upload_gcode_file(self,
                          file_name: str,
                          file_path: str) -> asyncio.Future:
        """Schedule an async upload of a G-code file and return a Future."""
        coro = self._upload_gcode_file_async(file_name, file_path)
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

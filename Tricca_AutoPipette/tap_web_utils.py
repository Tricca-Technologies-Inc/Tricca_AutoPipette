#!/usr/bin/env python
"""Holds classes and methods for web based activity in the shell."""
import threading
import requests
from asyncio import run_coroutine_threadsafe, AbstractEventLoop, all_tasks, \
    current_task, gather, set_event_loop, new_event_loop, Queue, \
    CancelledError, create_task, sleep, wait_for
import json
import websockets
from rich import print as rprint
from moonraker_requests import MoonrakerRequests


class MoonrakerClientError(Exception):
    """Base exception for MoonrakerClient errors."""

    pass


class UploadError(MoonrakerClientError):
    """Exception raised for errors during file upload."""

    pass


class GcodeStartError(MoonrakerClientError):
    """Exception raised for errors when starting a gcode file."""

    pass


class TAPWebUtils():
    """Handle web interactions between the prompt and the pipette."""

    ip: str = None

    loop: AbstractEventLoop = None
    ws_thread: threading.Thread = None
    shutdown_event: threading.Event = None
    send_queue: Queue = None
    recv_queue: Queue = None

    mrrequests: MoonrakerRequests = None

    def __init__(self, ip: str = "0.0.0.0"):
        """Initialize self, AutoPipette and ProtocolCommands objects."""
        self.ip = ip
        # ---------Websocket---------------------------------------------------
        self.shutdown_event = threading.Event()
        self.send_queue = Queue()
        self.recv_queue = Queue()
        self.mrrequests = MoonrakerRequests()
        uri = "ws://" + self.ip + ":7125/websocket"
        # Start the WebSocket listener in a separate thread
        self.run_websocket_listener(uri)
        request_sub = self.mrrequests.request_sub_to_objs(["gcode_move"])
        self.append_to_send(request_sub)

    def run_websocket_listener(self, uri: str):
        """Start the async WebSocket listener in a separate thread."""
        self.loop = new_event_loop()
        self.ws_thread = threading.Thread(
            target=self.start_async_loop, args=(self.loop,))
        self.ws_thread.start()
        # Run the async websocket listener coroutine in the new loop
        run_coroutine_threadsafe(
            self.send_receive_ws(uri),
            self.loop)

    def start_async_loop(self, loop):
        """Start a new event loop for the async code."""
        set_event_loop(loop)
        loop.run_forever()

    def stop_websocket_listener(self):
        """Stop the WebSocket listener and the event loop."""
        self.shutdown_event.set()
        # Put sentinel values in queues to unblock get() calls
        self.send_queue.put_nowait(None)
        self.recv_queue.put_nowait(None)
        if self.loop:
            # Stop the loop
            shutdown_future = run_coroutine_threadsafe(self.shutdown_tasks(),
                                                       self.loop)
            shutdown_future.result()  # Ensure shutdown tasks complete
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.ws_thread:
            self.ws_thread.join()

    async def shutdown_tasks(self):
        """Cancel all tasks."""
        tasks = [t for t in all_tasks(self.loop) if t is not current_task()]
        [task.cancel() for task in tasks]
        await gather(*tasks, return_exceptions=True)

    async def send_receive_ws(self, uri: str):
        """Manage WebSocket connection and communication."""
        while not self.shutdown_event.is_set():
            try:
                # Built-in retry and backoff mechanism with `async for`
                async for websocket in websockets.connect(uri):
                    rprint(
                        f"[bold blue]Connected to WebSocket: {uri}[/]")

                    if not await self.moonraker_startup_sequence():
                        rprint(
                            "Moonraker startup failed. Retrying...")
                        break  # Close the current connection and retry

                    # Run producer and consumer tasks
                    await self._run_websocket_tasks(websocket)

            except websockets.exceptions.InvalidURI:
                rprint(
                    f"Invalid URI: {uri}. Check your IP address.")
                break  # Exit the loop as the URI is not recoverable
            except websockets.exceptions.InvalidHandshake as e:
                rprint(
                    f"Invalid WebSocket Handshake: {e}")
                break  # Exit on invalid handshake, likely a config issue
            except Exception as e:
                rprint(
                    f"WebSocket error: {e}. Retrying...")
                # Let the built-in backoff handle retries

        rprint(
            "WebSocket task terminated from shutdown event.")

    async def _run_websocket_tasks(self, websocket):
        """Run producer and consumer tasks for the WebSocket."""
        send_task = create_task(self.send_messages(websocket))
        receive_task = create_task(self.receive_messages(websocket))

        try:
            await self._process_received_messages()
        finally:
            send_task.cancel()
            receive_task.cancel()
            await gather(send_task, receive_task, return_exceptions=True)

    async def _process_received_messages(self):
        """Process received messages from the queue."""
        while not self.shutdown_event.is_set():
            try:
                message = await wait_for(self.recv_queue.get(), timeout=1.0)
                if message:
                    # await self.process_message(message)
                    self.recv_queue.task_done()
            except TimeoutError:
                continue
            except CancelledError:
                rprint(
                    "Message processing cancelled.")
                break
            except Exception as e:
                rprint(
                    f"Error processing message: {e}")
                break

    async def moonraker_startup_sequence(self) -> bool:
        """Check the status of klipper."""
        while not self.shutdown_event.is_set():
            try:
                response = requests.get(
                    f"http://{self.ip}:7125/server/info", timeout=1)
                if response.status_code == 200:
                    data = response.json()
                    klippy_state = data["result"].get("klippy_state")
                    state_message = data["result"].get(
                        "state_message", "No message provided.")

                    if klippy_state == "ready":
                        rprint(
                            "[bold blue]Klippy connected.[/]")
                        return True
                    elif klippy_state == "error":
                        rprint(
                            f"Klippy error state: {state_message}")
                        return False
                    elif klippy_state == "shutdown":
                        rprint(
                            f"Klippy shutdown state: {state_message}")
                        return False
                    elif klippy_state == "startup":
                        rprint(
                            "Klippy is starting up. Rechecking in 2 seconds...")
                        await sleep(2)
                    else:
                        rprint(
                            f"Unexpected Klippy state: {klippy_state}")
                        return False
                else:
                    rprint(
                        f"Failed to query server info. Status code: {response.status_code}")
                    return False
            except requests.exceptions.RequestException as e:
                rprint(
                    f"Error querying server info: {e}")
                await sleep(2)
                return False

    async def send_messages(self, websocket):
        """Take requests from send_queue and sends them over the WebSocket."""
        try:
            while not self.shutdown_event.is_set():
                message = await self.send_queue.get()
                if message is None:
                    continue
                try:
                    await websocket.send(message)
                    rprint("Sent:", message)
                except websockets.exceptions.ConnectionClosed as e:
                    rprint(f"Failed to send message, connection closed: {e}")
                    break
                except Exception as e:
                    rprint(f"Error sending message: {e}")
                finally:
                    self.send_queue.task_done()
        except CancelledError:
            pass
        except Exception as e:
            rprint(f"Unexpected error in send_messages: {e}")

    async def receive_messages(self, websocket):
        """Receive messages from WebSocket and add them to receive queue."""
        try:
            while not self.shutdown_event.is_set():
                try:
                    message = await websocket.recv()
                    await self.recv_queue.put(message)
                except websockets.exceptions.ConnectionClosed as e:
                    rprint(f"Connection closed while receiving message: {e}")
                    break
                except Exception as e:
                    rprint(f"Error receiving message: {e}")
                except CancelledError:
                    pass
                except Exception as e:
                    rprint(f"Error receiving message: {e}")
        except CancelledError:
            pass
        except Exception as e:
            rprint(f"Unexpected error in receive_messages: {e}")

    async def process_message(self, message: str):
        """Process the recceived message."""
        data = json.loads(message)
        if 'method' in data.keys():
            method = data['method']
            if 'notify_proc_stat_update' == method:
                await self.process_proc_stat_update(data)
                return
            elif 'notify_history_changed' == method:
                await self.process_history_changed(data)
                return
            elif 'notify_filelist_changed' == method:
                await self.process_filelist_changed(data)
                return
            elif 'notify_status_update' == method:
                await self.process_status_update(data)
                return
            elif 'notify_gcode_response' == method:
                await self.process_gcode_response(data)
                return
            elif 'notify_service_state_changed' == method:
                await self.process_service_state_changed(data)
                return
            else:
                rprint(method)
        rprint("Process Msg: ", end="")
        rprint(data)

    async def process_proc_stat_update(self, data):
        """Process the data from a notify_stat_proc_update message."""
        # await self.alert_queue.put("Notify Proc Stat Update")
        return

    async def process_history_changed(self, data):
        """Process the data from a notify_history_changed update message."""
        rprint(
            "[blue]Notify History Changed[/]")

    async def process_filelist_changed(self, data):
        """Process the data from a notify_filelist_changed update message."""
        rprint(
            "[blue]Notify Filelist Changed[/]")

    async def process_status_update(self, data):
        """Process the data from a notify_status_update message."""
        message = data['params'][0]
        if "gcode_move" in message.keys():
            if "position" in message["gcode_move"].keys():
                position = message["gcode_move"]["position"]
                rprint(
                    f"[magenta]X:{position[0]} Y:{position[1]} Z:{position[3]}[/]")

    async def process_gcode_response(self, data):
        """Process the data from a notify_gcode_response message."""
        message = str(data['params'][0])
        if message == "Done printing file":
            message = "GCode executed."
        alert = "[bold magenta]" + message + "[/]"
        rprint(alert)

    async def process_service_state_changed(self, data):
        """Process the data from a notify_status_update message."""
        rprint(
            "[blue]Notify Service State Changed[/]")

    async def async_append_to_send(self, message: str):
        """Append a message to the send queue."""
        await self.send_queue.put(json.dumps(message))

    def append_to_send(self, message: str):
        """Append a message to the send queue."""
        run_coroutine_threadsafe(self.async_append_to_send(message),
                                 self.loop)

    def upload_gcode_file(self, file_name, file_path):
        """Upload a file to the pipette."""
        url = f'http://{self.ip}:7125/server/files/upload'
        try:
            with open(file_path, 'rb') as file:
                response = \
                    requests.post(url,
                                  files={'file': (file_name,
                                                  file,
                                                  'application/octet-stream')})
            if response.status_code != 201:
                raise UploadError(
                    f"Upload failed (status {response.status_code}): \
                    {response.text}")

            server_fp = response.json().get('item', {}).get('path')
            if not server_fp:
                raise UploadError("File path not returned in upload response.")
            return server_fp
        except requests.RequestException as e:
            raise UploadError(f"Network error during upload: {e}")
        except FileNotFoundError:
            raise UploadError("File not found.")
        except Exception as e:
            raise UploadError(f"Unexpected error during upload: {e}")

    def start_gcode(self, server_fp):
        """Start executing a gcode file."""
        url = f'http://{self.ip}:7125/printer/print/start?filename={server_fp}'
        try:
            response = requests.post(url)
            if response.status_code != 200:
                raise GcodeStartError(
                    f"Failed to start print (status {response.status_code}): \
                    {response.text}")

        except requests.RequestException as e:
            raise GcodeStartError(f"Network error starting print: {e}")
        except Exception as e:
            raise GcodeStartError(f"Unexpected error starting print: {e}")

    def exec_gcode_file(self, file_path: str, filename: str):
        """Send a gcode file and execute it.

        Args:
            file_path (str): File to upload to the pipette.
        """
        try:
            uploaded_file_path = self.upload_gcode_file(filename,
                                                        file_path)
            # TODO Add to job queue and start that. Use proper request
            self.start_gcode(uploaded_file_path)

        except MoonrakerClientError as e:
            rprint(f"Error: {e}")

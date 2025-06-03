import asyncio
import threading
import aiohttp
from aiohttp import ClientError

class SimpleController:
    """
    Async controller that connects to Moonraker (port 80) and issues
    G28 X (home X axis) over JSON-RPC at /server/jsonrpc—all in the background,
    so the Tkinter UI never blocks.
    """

    def __init__(self, ip="192.168.34.101", status_cb=None):
        """
        Args:
            ip (str): IP or hostname of the Moonraker host (default port 80).
            status_cb (callable): function(msg) to display status messages.
        """
        self.ip = ip
        self.status_cb = status_cb

        # URL for JSON-RPC (no explicit port)
        self.jsonrpc_url = f"http://{self.ip}/server/jsonrpc"

        # 1) Create a new asyncio loop in a background thread:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._start_loop, daemon=True)
        self._thread.start()

        # 2) Schedule session + initial connectivity check on that loop:
        asyncio.run_coroutine_threadsafe(self._initialize(), self.loop)

    def _start_loop(self):
        """Target for the background thread: run the asyncio event loop forever."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _initialize(self):
        """
        Runs inside the background event loop:
        - Creates an aiohttp session
        - Tests connectivity by GET /server/info
        """
        self.session = aiohttp.ClientSession()

        # Report “testing…” back to the UI thread:
        self._report_status(f"Testing connection to http://{self.ip}/server/info…")

        try:
            async with self.session.get(f"http://{self.ip}/server/info", timeout=5) as resp:
                if resp.status == 200:
                    self._report_status("Connected to Moonraker on port 80.")
                else:
                    self._report_status(f"Error: /server/info returned HTTP {resp.status}")
        except asyncio.TimeoutError:
            self._report_status("Timeout when connecting to /server/info.")
        except ClientError as e:
            self._report_status(f"Connection error: {e}")

    def _report_status(self, msg: str):
        """
        Safely send a status message back to the UI thread.
        Because status_cb updates Tkinter, we must schedule it on the main thread via after().
        """
        if not self.status_cb:
            return

        try:
            # status_cb is expected to be something like root._show_status(msg),
            # so we must call it on the main (Tk) thread. We assume status_cb was
            # bound from the Tk object, so we can queue it with `.after()`:
            tk_root = self.status_cb.__self__  # the Tk instance
            tk_root.after(0, lambda: self.status_cb(msg))
        except Exception:
            # Fallback: call directly (risking cross-thread GUI access, but better than losing it)
            try:
                self.status_cb(msg)
            except Exception:
                pass

    def home_x(self):
        """
        Public method to home X. Schedules an async task on our loop to send
        G28 X over JSON-RPC. Returns immediately.
        """
        # Schedule the coroutine; no need to await here.
        asyncio.run_coroutine_threadsafe(self._home_x_rpc(), self.loop)

    async def _home_x_rpc(self):
        """
        Runs on the background loop: sends the JSON-RPC call to home X.
        We catch and report any errors back via _report_status().
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "printer.gcode.script",
            "params": {"script": "G28 X"},
            "id": 1
        }

        try:
            async with self.session.post(self.jsonrpc_url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    # We assume Moonraker returns quickly once the command is accepted.
                    self._report_status("Sent G28 X successfully.")
                else:
                    self._report_status(f"Home X failed: HTTP {resp.status}")
        except asyncio.TimeoutError:
            # If Moonraker takes too long to respond, assume it accepted the command.
            self._report_status("Home X accepted (Moonraker still processing).")
        except ClientError as e:
            self._report_status(f"Home X error: {e}")

    def close(self):
        """
        Call this when the application is shutting down, so we close
        the aiohttp session and stop the loop cleanly.
        """
        # 1) Schedule session close
        if hasattr(self, "session"):
            asyncio.run_coroutine_threadsafe(self.session.close(), self.loop)
        # 2) Stop the loop
        self.loop.call_soon_threadsafe(self.loop.stop)

# backend/controller.py
import threading
import configparser
import shlex
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Any, Dict

from .autopipette import (
    AutoPipette, Coordinate, TipAlreadyOnError, NoTipboxError, NotALocationError
)
from .moonraker_requests import MoonrakerRequests
from .websocketclient import WebSocketClient


class Controller:
    def __init__(self, status_cb: Callable[[str], None]):
        self.ap = AutoPipette()
        self.mrr = MoonrakerRequests()
        self.client: Optional[WebSocketClient] = None
        self.status_cb = status_cb

        #stash UI callbacks:
        self._pos_listeners = []
        self._prog_listeners = []
        self._conn_listeners: list[Callable[[bool],None]] = []

    def _wait_for_ws(self):
        if self.client._connected.wait(timeout=10):
            self.status_cb("WebSocket connected")
        else:
            self.status_cb("WebSocket failed to connect")

    def _send_gcode(self, gcode: list[str], filename: Optional[str]):
        # ensure temp folder exists
        gcode_dir = Path(__file__).parent.parent / "backend" / "gcode" / "temp"
        gcode_dir.mkdir(parents=True, exist_ok=True)
        name = filename or datetime.now().strftime("%Y-%m-%d-%H-%M-%S.gcode")
        path = gcode_dir / name
        with open(path, "w") as f:
            for line in gcode:
                f.write(line if line.endswith("\n") else line + "\n")

        def _worker():
            try:
                fut = self.client.upload_gcode_file(name, path)
                server_path = fut.result(timeout=30)
                self.status_cb(f"Uploaded → {server_path}")
                payload = self.mrr.printer_print_start(name)
                resp = self.client.send_jsonrpc(payload)
                self.status_cb(f"Print started: {resp}")
            except Exception as e:
                self.status_cb(f"Error: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    # ───── Motion / Homing ─────
    def home_all(self):
        self.ap.home_axis()
        self.ap.home_pipette_motors()
        self.ap.homed = True
        self._send_gcode(self.ap.get_gcode(), "home_all.gcode")

    def home_x(self):
        self.ap.home_x()
        self._send_gcode(self.ap.get_gcode(), "home_x.gcode")

    def home_y(self):
        self.ap.home_y()
        self._send_gcode(self.ap.get_gcode(), "home_y.gcode")

    def home_z(self):
        self.ap.home_z()
        self._send_gcode(self.ap.get_gcode(), "home_z.gcode")

    def home_servo(self):
        self.ap.home_servo()
        self._send_gcode(self.ap.get_gcode(), "home_servo.gcode")

    def move_to(self, x: float, y: float, z: float):
        self.ap.move_to(Coordinate(x, y, z))
        self._send_gcode(self.ap.get_gcode(), "move.gcode")

    def move_to_location(self, name: str):
        try:
            coor = self.ap.get_location_coor(name)
        except NotALocationError as e:
            self.status_cb(str(e))
            return
        self.ap.move_to(coor)
        self._send_gcode(self.ap.get_gcode(), f"move_{name}.gcode")

    def move_relative(self, dx: float, dy: float, dz: float):
        self.ap.set_coor_sys("relative")
        self.ap.move_to(Coordinate(dx, dy, dz))
        self.ap.set_coor_sys("absolute")
        self._send_gcode(self.ap.get_gcode(), "move_rel.gcode")

    # ───── Tip Handling ─────
    def next_tip(self):
        try:
            self.ap.next_tip()
            self._send_gcode(self.ap.get_gcode(), "next_tip.gcode")
        except (NoTipboxError, TipAlreadyOnError) as e:
            self.status_cb(str(e))

    def eject_tip(self):
        self.ap.eject_tip()
        self._send_gcode(self.ap.get_gcode(), "eject_tip.gcode")

    # ───── Pipetting ─────
    def pipette(
        self,
        vol_ul: float,
        src: str,
        dest: str,
        disp_vol_ul: Optional[float] = None,
        src_row: Optional[int] = None,
        src_col: Optional[int] = None,
        dest_row: Optional[int] = None,
        dest_col: Optional[int] = None,
        keep_tip: bool = False,
        prewet: bool = False,
        wiggle: bool = False
    ):
        for loc in (src, dest):
            if not self.ap.is_location(loc):
                self.status_cb(f"Location {loc!r} not found")
                return
        if self.ap.waste_container is None:
            self.status_cb("No waste container set")
            return
        if self.ap.tipboxes is None:
            self.status_cb("No tip box set")
            return

        self.ap.pipette(
            vol_ul, src, dest,
            disp_vol_ul, src_row, src_col,
            dest_row, dest_col, keep_tip, prewet, wiggle
        )
        self._send_gcode(self.ap.get_gcode(), "pipette.gcode")

    def _run_lines(self, lines: list[str], out_name: str):
        """
        Core helper to take a list of G-code lines, upload & start them.
        Mirrors what do_run does with output_gcode.
        """
        #collect into buffer with a newline appended
        self.ap._gcode_buffer = []
        for ln in lines:
            self.ap._gcode_buffer.append(ln if ln.endswith("\n") else ln + "\n")

        # actually send to printer
        header = self.ap.get_header()
        body   = self.ap._gcode_buffer
        self._send_gcode(header + body, out_name)

        #clear buffer for next time
        self.ap._gcode_buffer = []

    # ───── Protocols ─────
    def run_program(self, filename: str):
        """
        1) Parse & validate the file exists
        2) Read its lines
        3) Call shared _run_lines helper
        """
        proto_path = (Path(__file__).parent.parent.parent
                      / "backend" / "programs" / filename)
        if not proto_path.exists():
            self.status_cb(f"Program not found: {filename}")
            return

        # 1) read all lines
        raw_lines = proto_path.read_text().splitlines()

        # 2) filter out blanks & comments
        lines = [
            ln for ln in raw_lines
            if ln.strip() and not ln.strip().startswith("#")
        ]

        # 3) run
        out_name = Path(filename).with_suffix('.gcode').name
        self._run_lines(lines, out_name)
        self.status_cb(f"Running protocol: {filename}")

    # ───── Flow Control ─────
    def stop(self):
        self.status_cb("Emergency Stop!")
        payload = self.mrr.gen_request("printer.emergency_stop")
        self.send_rpc(payload)

    def pause(self):
        payload = self.mrr.gen_request("printer.print.pause")
        self.send_rpc(payload)

    def resume(self):
        payload = self.mrr.gen_request("printer.print.resume")
        self.send_rpc(payload)

    def cancel(self):
        payload = self.mrr.gen_request("printer.print.cancel")
        self.send_rpc(payload)

    # ───── Config & Utility ─────
    def save_config(self):
        self.ap.save_config_file()
        self.status_cb("Config saved")

    def reset_plate(self, plate_name: str):
        if plate_name not in self.ap.get_plate_locations():
            self.status_cb(f"{plate_name!r} is not a plate")
            return
        self.ap.locations[plate_name].curr = 0
        self.status_cb(f"Plate {plate_name} reset")

    def reset_all_plates(self):
        for p in self.ap.get_plate_locations():
            self.ap.locations[p].curr = 0
        self.status_cb("All plates reset")

    def print_message(self, msg: str):
        self.ap.gcode_print(msg)
        self._send_gcode(self.ap.get_gcode(), "print_msg.gcode")

    def vol_to_steps(self, vol: float):
        steps = self.ap.volume_converter.vol_to_steps(vol)
        self.status_cb(f"{vol} µL → {steps} steps")

    # ───── Listings & Config Loading ─────
    def list_locations(self) -> list[str]:
        return list(self.ap.locations.keys())

    def list_plate_locations(self) -> list[str]:
        return self.ap.get_plate_locations()

    def load_config(self, filepath: str):
        """
        1) Load the .conf (absolute path or packaged)
        2) Parse NETWORK.IP / HOSTNAME
        3) Spin up WebSocketClient to ws://<host>:7125/websocket
        """
        path = Path(filepath)

        # ── 1) Load the config file itself ─────────────────────────────
        if path.is_file():
            # User gave us a full path: read it directly
            parser = configparser.ConfigParser(
                interpolation=configparser.ExtendedInterpolation()
            )
            parser.read(path)
            self.ap.config = parser  # overwrite the AutoPipette.ConfigParser

            # Now replicate the post-load hooks from AutoPipette.load_config_file:
            self.ap._parse_config_locations()
            self.ap._init_volume_converter()
            self.ap._build_header()

            self.status_cb(f"Config {path.name} loaded from {path}")
        else:
            # Fallback to the built-in config directory (same as before)
            self.ap.load_config_file(filepath)
            self.status_cb(f"Config {filepath} loaded")

        # ── 2) Extract the host / ip ───────────────────────────────────
        cfg = self.ap.config
        host = cfg["NETWORK"].get("IP") or cfg["NETWORK"].get("HOSTNAME")
        uri = f"ws://{host}:7125/websocket"

        # ── 3) Start the WebSocketClient ──────────────────────────────
        self.client = WebSocketClient(uri)
        self.client.start()

        # ── 4) Notify once we’ve successfully connected ───────────────
        threading.Thread(target=self._wait_for_ws, daemon=True).start()

    # ───── JSON-RPC Helpers ─────
    def send_rpc(self, payload: Optional[Dict[str, Any]]):
        if payload is None:
            return
        def _worker():
            try:
                resp = self.client.send_jsonrpc(payload)
                self.status_cb(f"RPC response: {resp}")
            except Exception as e:
                self.status_cb(f"RPC error: {e}")
        threading.Thread(target=_worker, daemon=True).start()

    def notify(self, method: str, params: Optional[dict] = None):
        try:
            self.client.send_notification(method, params)
            self.status_cb("Notification sent")
        except Exception as e:
            self.status_cb(f"Notify error: {e}")

    # ───── Raw Upload / Read / Reconnect ─────
    def upload(self, filename: str, file_path: Path):
        def _worker():
            try:
                future = self.client.upload_gcode_file(filename, file_path)
                server_path = future.result(timeout=30)
                self.status_cb(f"Uploaded → {server_path}")
            except Exception as e:
                self.status_cb(f"Upload error: {e}")
        threading.Thread(target=_worker, daemon=True).start()

    def read_message(self):
        if not self.client.message_queue.empty():
            msg = self.client.message_queue.get()
            self.status_cb(f"Received: {msg}")
        else:
            self.status_cb("No new messages")

    def reconnect(self):
        handlers = dict(self.client._handlers)
        self.client.stop()
        self.client = WebSocketClient(self.client.url)
        for m, cb in handlers.items():
            self.client.register_handler(m, cb)
        self.client.start()
        if self.client._connected.wait(timeout=10):
            self.status_cb("WebSocket reconnected")
        else:
            self.status_cb("Reconnect failed")

    # ─── Subscription & Handlers ────────────────────────────────────────────
    
    def connect_and_subscribe(self):
        """Kick off the WS connection and subscribe to motion_report, etc."""
        # register a single handler
        self.client.register_handler(
            "notify_printer.objects.subscribe",
            self._on_printer_objects
        )

        # subscribe
        sub = self.mrr.gen_request(
            "printer.objects.subscribe",
            {"objects": {
                "motion_report": ["live_position"],
                "display_status": ["progress"],
                "print_stats": []
            }}
        )
        self.client.send_jsonrpc(sub)

        # optional one-shot query so we get an immediate update
        qry = self.mrr.printer_objects_query({
            "motion_report": ["live_position"],
            "display_status":  ["progress"],
            "print_stats":     []
        })
        self.send_rpc(qry)

    def _on_printer_objects(self, params):
        # extract position + progress
        pos = params.get("motion_report", {}).get("live_position", [0,0,0])
        prog = params.get("display_status", {}).get("progress", 0.0)

        # fire all registered callbacks
        for cb in self._pos_listeners:
            cb(pos)
        for cb in self._prog_listeners:
            cb(prog)

    # allow frames to register callbacks:
    def add_position_listener(self, callback):
        self._pos_listeners.append(callback)

    def add_progress_listener(self, callback):
        self._prog_listeners.append(callback)

    def add_connection_listener(self, cb: Callable[[bool],None]):
        """Frames call this to get notified of connect/disconnect."""
        self._conn_listeners.append(cb)

    def start_connection_polling(self, interval: float = 1.0):
        """Background thread that checks connection every `interval` seconds."""
        def _poll_loop():
            while True:
                connected = bool(self.client and self.client._connected.is_set())
                for cb in self._conn_listeners:
                    cb(connected)
                time.sleep(interval)
        threading.Thread(target=_poll_loop, daemon=True).start()

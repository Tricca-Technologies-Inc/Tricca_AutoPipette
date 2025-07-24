# backend/controller.py
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Any, Dict
from queue import Empty

import configparser
from configparser import ConfigParser, ExtendedInterpolation

from .autopipette import (
    AutoPipette, Coordinate, TipAlreadyOnError, NoTipboxError, NotALocationError
)
from .moonraker_requests import MoonrakerRequests
from .websocketclient import WebSocketClient
from .tap_cmd_parsers import TAPCmdParsers
from .utils.gcode_manager import GCodeManager
from .utils.command_dispatcher import CommandDispatcher
from .utils.protocol_runner import ProtocolRunner

class Controller:
    def __init__(self,
                 status_cb: Callable[[str], None],
                 config_file: str | None = None):
        self.status_cb = status_cb

        # ── a) Initialize AutoPipette exactly like the shell does ───────
        if config_file:
            # Passing a config path into AutoPipette causes it to read
            # that file via load_config_file(), which runs all the hooks.
            self.ap = AutoPipette(config_file)
            self.status_cb(f"Loaded pipette config from {config_file}")
        else:
            self.ap = AutoPipette()
            self.status_cb("Loaded default pipette config")

        self.status_cb("Connecting to pipette…")
        net = self.ap.config["NETWORK"]
        host = net.get("IP", fallback=None) or net["HOSTNAME"]
        port = net.getint("PORT", 7125)
        ws_url = f"ws://{host}:{port}/websocket"

        self.mrr = MoonrakerRequests()
        self.client: Optional[WebSocketClient] = None

        # ── 3) spin up WebSocket & wait for it ───────────────────────
        self.client = WebSocketClient(ws_url)
        self.client.start()
        threading.Thread(target=self._wait_for_ws, daemon=True).start()

        # Command parsing & execution
        self.parsers = TAPCmdParsers()
        self.dispatcher = CommandDispatcher(self)
        self.runner = ProtocolRunner(self)

        # UI listener registries
        self._pos_listeners: list[Callable[[list[float]], None]] = []
        self._prog_listeners: list[Callable[[float], None]] = []
        self._conn_listeners: list[Callable[[bool], None]] = []
        self._config_reload_listeners: list[Callable[[], None]] = []
        self._step_listeners: list[Callable[[str, str], None]]  = []
        self._time_listeners: list[Callable[[str, str], None]]  = []

        temp_dir = Path(__file__).parent.parent.parent / "backend"/"gcode"/"temp"
        self.gcode = GCodeManager(
            client      = self.client,
            mrr         = self.mrr,
            autopipette = self.ap,
            status_cb   = self.status_cb,
            temp_dir    = temp_dir
        )

        # start pumping messages into your status callback
        threading.Thread(target=self._start_message_polling, daemon=True).start()
        threading.Thread(target=self.start_connection_polling, daemon=True).start()

    def _wait_for_ws(self):
        if self.client._connected.wait(timeout=10):
            self.status_cb("WebSocket connected")
            self.connect_and_subscribe()
        else:
            self.status_cb("WebSocket failed to connect")

    def reload_autopipette(self, config_path: str):
        """
        1) Tell AutoPipette to read exactly that file (absolute or in conf/).
        2) Swap the new settings into GCodeManager.
        3) Fire any UI listeners so they redraw.
        """
        # 1) load it (wipes old parser, rebuilds params+locations+volumes+header)
        self.ap.locations.clear()
        self.ap.load_config_file(config_path)

        # 2) make sure your G-code pipeline uses the updated autopipette
        self.gcode.autopipette = self.ap

        # 3) notify any frames that registered for config reloads
        for cb in self._config_reload_listeners:
            try:
                cb()
            except Exception:
                pass

        # optional status update
        self.status_cb(f"Reloaded pipette config from {config_path}")

    # ───── Motion / Homing ─────
    def home_all(self):
        self.ap.home_axis()
        self.ap.home_pipette_motors()
        self.ap.homed = True
        self.gcode.send(self.ap.get_gcode(), "home_all.gcode")

    def home_x(self):
        self.ap.home_x()
        self.gcode.send(self.ap.get_gcode(), "home_x.gcode")

    def home_y(self):
        self.ap.home_y()
        self.gcode.send(self.ap.get_gcode(), "home_y.gcode")

    def home_z(self):
        self.ap.home_z()
        self.gcode.send(self.ap.get_gcode(), "home_z.gcode")

    def home_servo(self):
        self.ap.home_servo()
        self.gcode.send(self.ap.get_gcode(), "home_servo.gcode")

    def move_to(self, x: float, y: float, z: float):
        self.ap.move_to(Coordinate(x=x, y=y, z=z))
        self.gcode.send(self.ap.get_gcode(), "move.gcode")

    def home_pipette(self):
        self.ap.home_pipette_motors()
        self.gcode.send(self.ap.get_gcode(), "home_pipette.gcode")

    def move_to_location(self, name: str):
        try:
            coor = self.ap.get_location_coor(name)
        except NotALocationError as e:
            self.status_cb(str(e))
            return
        self.ap.move_to(coor)
        self.gcode.send(self.ap.get_gcode(), f"move_{name}.gcode")

    def move_relative(self, dx: float, dy: float, dz: float):
        self.ap.set_coor_sys("relative")
        self.ap.move_to(Coordinate(x=dx, y=dy, z=dz))
        self.ap.set_coor_sys("absolute")
        self.gcode.send(self.ap.get_gcode(), "move_rel.gcode")

    # ───── Tip Handling ─────
    def next_tip(self):
        try:
            self.ap.next_tip()
            self.gcode.send(self.ap.get_gcode(), "next_tip.gcode")
        except (NoTipboxError, TipAlreadyOnError) as e:
            self.status_cb(str(e))

    def eject_tip(self):
        self.ap.eject_tip()
        self.gcode.send(self.ap.get_gcode(), "eject_tip.gcode")

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
        # validate
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

        # run pipette
        self.ap.pipette(
            vol_ul, src, dest,
            disp_vol_ul, src_row, src_col,
            dest_row, dest_col, keep_tip, prewet, wiggle
        )
        self.gcode.send(self.ap.get_gcode(), "pipette.gcode")

    # ───── Protocols ─────
    def run_cmd(self, line: str):
        self.dispatcher.dispatch(line)

    def run_protocol_file(self, filename: str):
        msg = self.runner.run_file(filename)
        self.status_cb(msg)

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

    def firmware_restart(self):
        payload = self.mrr.gen_request("printer.firmware_restart")
        self.send_rpc(payload)
        self.status_cb("Sent firmware restart command")

    # ───── Config Loading & Utility ─────
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

    def list_locations(self) -> list[str]:
        return list(self.ap.locations.keys())

    def list_plate_locations(self) -> list[str]:
        return self.ap.get_plate_locations()

    def vol_to_steps(self, vol: float):
        steps = self.ap.volume_converter.vol_to_steps(vol)
        self.status_cb(f"{vol} µL → {steps} steps")

    def add_config_reload_listener(self, cb: Callable[[],None]):
        self._config_reload_listeners.append(cb)

    # ───── JSON-RPC Helpers ─────
    def send_rpc(self, payload: Optional[Dict[str, Any]]):
        if payload is None:
            return
        def _worker():
            try:
                resp = self.client.send_jsonrpc(payload)
                self.status_cb(f"RPC response: {resp}")
            except Exception as e:
                if hasattr(e, "response"):
                    self.status_cb(f"Upload failed {e.response.status_code}: {e.response.text}")
                else:
                    self.status_cb(f"Upload failed: {e}")
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
        # register handler for printer-objects notifications
        self.client.register_handler(
            "notify_printer.objects.subscribe",
            self._on_printer_objects
        )
        # send subscribe request
        sub = self.mrr.gen_request(
            "printer.objects.subscribe",
            {"objects": {
                "motion_report": ["live_position"],
                "display_status": ["progress"],
                "print_stats": []
            }}
        )
        self.client.send_jsonrpc(sub)
        # one-shot query for initial state
        qry = self.mrr.printer_objects_query({
            "motion_report": ["live_position"],
            "display_status":  ["progress"],
            "print_stats":     []
        })
        self.send_rpc(qry)

    def _on_printer_objects(self, params):
        pos  = params.get("motion_report", {}).get("live_position", [0,0,0])
        prog = params.get("display_status", {}).get("progress", 0.0)
        for cb in self._pos_listeners:
            cb(pos)
        for cb in self._prog_listeners:
            cb(prog)

    # ───── Listeners ─────
    def add_position_listener(self, callback: Callable[[list[float]], None]):
        self._pos_listeners.append(callback)

    def add_progress_listener(self, callback: Callable[[float], None]):
        self._prog_listeners.append(callback)

    def add_connection_listener(self, cb: Callable[[bool],None]):
        self._conn_listeners.append(cb)

    def add_step_listener(self, cb: Callable[[str, str], None]):
        self._step_listeners.append(cb)

    def add_time_listener(self, cb: Callable[[str, str], None]):
        self._time_listeners.append(cb)

    def start_connection_polling(self, interval: float = 1.0):
        def _poll_loop():
            while True:
                connected = bool(self.client and self.client._connected.is_set())
                for cb in self._conn_listeners:
                    cb(connected)
                time.sleep(interval)
        threading.Thread(target=_poll_loop, daemon=True).start()

    def _start_message_polling(self, interval: float = 0.1):
        def loop():
            while True:
                try:
                    msg = self.client.message_queue.get_nowait()
                    self.status_cb(f"[notify] {msg}")
                except Empty:
                    pass
                time.sleep(interval)
        threading.Thread(target=loop, daemon=True).start()

    def show_full_protocol(self):
        """Called when the user clicks 'Show Full Protocol'."""
        # TODO: actually pop up a window or switch view
        print("Full protocol requested")
# backend/controller.py
from __future__ import annotations
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

        self.ui_post = None

        self.profile_map: dict[str, str] = {
            "P100":  "pipette_p100.conf",   # 10–100 µL
            "P1000": "pipette_p1000.conf",  # 100–1000 µL
        }
        
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
        self._complete_listeners: list[Callable[[],None]] = []
        self._runstate_listeners: list[Callable[[str], None]] = []
        self._last_job_state_raw: str | None = None

        temp_dir = Path(__file__).parent.parent.parent / "backend"/"gcode"/"temp"
        self.gcode = GCodeManager(
            client      = self.client,
            mrr         = self.mrr,
            autopipette = self.ap,
            status_cb   = self.status_cb,
            temp_dir    = temp_dir
        )

        # start pumping messages into your status callback
        threading.Thread(target=self.start_connection_polling, daemon=True).start()

    def _wait_for_ws(self):
        if self.client._connected.wait(timeout=10):
            self.status_cb("WebSocket connected")
            self.connect_and_subscribe()
        else:
            self.status_cb("WebSocket failed to connect")

    def _post_to_ui(self, fn):
        """
        Run fn() on the Tk main thread if self.ui_post is set,
        otherwise run inline.
        """
        if callable(self.ui_post):
            try:
                self.ui_post(0, fn)   # e.g. root.after(0, fn)
                return
            except Exception:
                pass
        fn()

    def reload_autopipette(
        self,
        config_path: str,
        *,
        preserve_network: bool = True,
        done_event: threading.Event | None = None
    ):
        def work():
            try:
                # snapshot current NETWORK
                old_net = None
                try:
                    if preserve_network and self.ap.config.has_section("NETWORK"):
                        old_net = dict(self.ap.config["NETWORK"])
                except Exception:
                    old_net = None

                # heavy work off the UI thread
                self.ap.load_config_file(config_path)

                # restore NETWORK if requested
                if preserve_network and old_net:
                    if not self.ap.config.has_section("NETWORK"):
                        self.ap.config.add_section("NETWORK")
                    self.ap.config["NETWORK"].clear()
                    for k, v in old_net.items():
                        self.ap.config["NETWORK"][k] = v
                    # rebuild header so it reflects preserved network
                    self.ap._build_header()

                self.gcode.autopipette = self.ap
                msg = f"Reloaded pipette config from {config_path}"
                self._post_to_ui(lambda: self.status_cb(msg))

                def fire():
                    for cb in self._config_reload_listeners:
                        try: cb()
                        except Exception: pass
                self._post_to_ui(fire)
            except Exception as e:
                self._post_to_ui(lambda: self.status_cb(f"Config reload error: {e}"))
            finally:
                if done_event is not None:
                    done_event.set()

        threading.Thread(target=work, daemon=True).start()

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

    def trigger(self, channel: str, state: str | int | bool):
        """
        Set a named trigger (e.g., 'air'/'shake'/'aux') to on/off (1/0).
        Usage: controller.trigger("air", "on")
        """
        try:
            self.ap.set_trigger(channel, state)
            header = f"\n; Trigger {channel} → {str(state).lower()}\n"
            lines = [header] + self.ap.get_gcode() + ["\n"]
            self.gcode.send(lines, f"trigger_{channel}.gcode")
        except Exception as e:
            self.status_cb(f"Trigger error: {e}")


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
        self.ap.dispose_tip()
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
        wiggle: bool = False,
        *,
        splits: Optional[str] = None,      # NEW: "DEST:VOL[@r,c];DEST2:VOL2[@r,c]"
        leftover: str = "keep",             # NEW: "keep" | "waste" | "source"
        tipbox_name: Optional[str] = None,
    ):
        # validate
        for loc in (src, dest):
            if not self.ap.is_location(loc):
                self.status_cb(f"Location {loc!r} not found")
                return
        if self.ap.waste_container is None:
            self.status_cb("No waste container set")
            return
        if not (self.ap.pooled_tipbox or self.ap.tipboxes_map):
            self.status_cb("No tip box set")
            return

        # ── multi-dispense mode ────────────────────────────────────────────────
        if splits:
            # Parse and validate splits
            try:
                split_list = self.ap._parse_splits_spec(splits)
            except Exception as e:
                self.status_cb(f"Invalid --splits: {e}")
                return

            for s in split_list:
                if not self.ap.is_location(s.dest):
                    self.status_cb(f"Split destination '{s.dest}' not found")
                    return

            total_split = sum(s.vol_ul for s in split_list)
            if total_split - vol_ul > 1e-6:
                self.status_cb(
                    f"Split volumes ({total_split} uL) exceed aspirate ({vol_ul} uL)"
                )
                return

            # Build G-code (exactly like the working path: buffer in AutoPipette, then send)
            self.ap.pipette(
                vol_ul, src, dest,              # 'dest' is ignored in splits path
                disp_vol_ul, src_row, src_col,
                dest_row, dest_col,
                keep_tip, prewet, wiggle,
                splits=splits,
                leftover_action=leftover,
                tipbox_name=tipbox_name,
            )

            header = f"\n; Pipette {vol_ul} from {src} with splits [{splits}] (leftover={leftover})\n"
            lines = [header] + self.ap.get_gcode() + ["\n"]   # ASCII header, like old code
            self.gcode.send(lines, "pipette.gcode")
            return

        # ── single-dispense mode (original behavior) ───────────────────────────
        if not self.ap.is_location(dest):
            self.status_cb(f"Location '{dest}' not found")
            return

        self.ap.pipette(
            vol_ul, src, dest,
            disp_vol_ul, src_row, src_col,
            dest_row, dest_col, keep_tip, prewet, wiggle,
            tipbox_name=tipbox_name,
        )

        header = f"\n; Pipette {vol_ul} from {src} to {dest}\n"   # keep ASCII only
        lines = [header] + self.ap.get_gcode() + ["\n"]
        self.gcode.send(lines, "pipette.gcode")

    # ───── Protocols ─────
    def run_cmd(self, line: str):
        self.dispatcher.dispatch(line)

    def run_protocol_file(self, filename: str):
        msg = self.runner.run_file(filename)
        self.status_cb(msg)

    def run_sequence(self, files: list[str]):
        self.runner.run_sequence(files)

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
        # if theres a sequence ran, cancel it and not just the single file
        try:
            self.runner.request_sequence_cancel()
        except Exception:
            pass

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

    def remove_config_reload_listener(self, cb: Callable[[],None]):
        try:
            self._config_reload_listeners.remove(cb)
        except ValueError:
            pass

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
            #self.client.send_notification(method, params)
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
            "notify_status_update",
            self._on_printer_objects
        )

        # send subscribe request
        sub = self.mrr.gen_request(
            "printer.objects.subscribe",
            {"objects": {
                "motion_report": ["live_position"],
                "display_status": ["progress"],
                "print_stats": ["print_duration", "total_duration", "state"],
                "pause_resume":   ["is_paused"]
            }}
        )
        self.client.send_jsonrpc(sub)

        # one-shot query for initial state
        qry = self.mrr.printer_objects_query({
            "motion_report": ["live_position"],
            "display_status":  ["progress"],
            "print_stats":     ["print_duration", "total_duration", "state"],
            "pause_resume":   ["is_paused"]
        })
        self.send_rpc(qry)

    def _on_printer_objects(self, params):
        # unpack the [data, timestamp] list
        data = params[0] if isinstance(params, list) else params

        # motion + progress (unchanged)
        pos  = data.get("motion_report", {}).get("live_position", [0,0,0])
        prog = data.get("display_status", {}).get("progress", 0.0)
        for cb in self._pos_listeners: cb(pos)
        for cb in self._prog_listeners: cb(prog)

        # now our new timing source
        stats = data.get("print_stats", {}) or {}
        paused = data.get("pause_resume", {}).get("is_paused", None)

        # raw state can be omitted on most updates -> fall back to last value
        raw_state = stats.get("state", None)
        if raw_state is None:
            raw_state = self._last_job_state_raw

        # If we still don't have anything, try to infer from progress
        # (not perfect, but avoids "Unknown" while printing)
        if raw_state is None:
            if isinstance(prog, (int, float)) and prog > 0:
                raw_state = "printing"
            else:
                raw_state = "standby"

        # If pause flag is present, override to paused/unpaused in human output
        # (Moonraker's print_stats.state should also change, but sometimes updates omit it)
        if paused is True:
            human = "Paused"
        else:
            # humanize
            state_map = {
                "printing":  "Running",
                "paused":    "Paused",
                "complete":  "Complete",
                "cancelled": "Cancelled",
                "standby":   "Idle",
                "error":     "Error",
            }
            human = state_map.get(raw_state, (raw_state.title() if raw_state else "Unknown"))

        # Persist last raw state for the next sparse update
        self._last_job_state_raw = raw_state

        # Notify run-state listeners
        for cb in self._runstate_listeners:
            try:
                cb(human)
            except Exception:
                pass

        elapsed = stats.get("print_duration", 0.0)
        total   = stats.get("total_duration", 0.0)

        # if Klipper hasn’t given us a total yet, infer from progress
        if total <= 0 and prog > 0:
            total = elapsed / prog

        remaining = max(0.0, total - elapsed)

        state = stats.get("state","")
        self._last_job_state_raw = raw_state

        # fire your time-listeners with floats
        for cb in self._time_listeners:
            cb(elapsed, remaining)

        # reset when something completes
        if state in ("complete", "cancelled", "error"):
            for cb in self._complete_listeners:
                try: cb()
                except: pass


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
    
    def add_complete_listener(self, cb: Callable[[],None]):
        self._complete_listeners.append(cb)

    def add_runstate_listener(self, cb: Callable[[str], None]):
        self._runstate_listeners.append(cb)
        
    def remove_complete_listener(self, cb: Callable[[],None]):
        try:
            self._complete_listeners.remove(cb)
        except ValueError:
            pass
            
    def start_connection_polling(self, interval: float = 1.0):
        def _poll_loop():
            while True:
                connected = bool(self.client and self.client._connected.is_set())
                for cb in self._conn_listeners:
                    cb(connected)
                time.sleep(interval)
        threading.Thread(target=_poll_loop, daemon=True).start()

    def show_full_protocol(self):
        """Called when the user clicks 'Show Full Protocol'."""
        # TODO: actually pop up a window or switch view
        print("Full protocol requested")

    def list_profiles(self) -> list[str]:
        return list(self.profile_map.keys())

    def get_active_profile_name(self) -> str | None:
        """Return the profile name matching the current config file, if any."""
        curr = Path(self.ap._config_file).name
        for name, cfg in self.profile_map.items():
            if Path(cfg).name == curr:
                return name
        return None

    def switch_profile(self, name: str, *, wait: bool = False, timeout: float = 3.0):
        """
        Reload AutoPipette from the config mapped to 'name'.
        If wait=True, block until the reload thread signals completion (or timeout).
        """
        cfg = self.profile_map.get(name)
        if not cfg:
            self.status_cb(
                f"Unknown profile '{name}'. Available: {', '.join(self.profile_map.keys())}"
            )
            return

        # Flush any queued gcode so buffers don't mix
        try:
            _ = self.ap.get_gcode()
        except Exception:
            pass

        evt = threading.Event() if wait else None
        self.reload_autopipette(cfg, preserve_network=True, done_event=evt)
        self.status_cb(f"Active pipette profile → {name} ({cfg})")

        if evt is not None:
            if not evt.wait(timeout=timeout):
                self.status_cb("Profile reload is taking longer than expected; will finish in background.")
        """
        Reload AutoPipette from the config mapped to 'name'.
        Safe to call from UI or .pipette 'profile NAME' command.
        """
        cfg = self.profile_map.get(name)
        if not cfg:
            self.status_cb(
                f"Unknown profile '{name}'. Available: {', '.join(self.profile_map.keys())}"
            )
            return

        # Flush any queued gcode so buffers don't mix
        try:
            _ = self.ap.get_gcode()
        except Exception:
            pass

        # Reuse hot-reload path
        self.reload_autopipette(cfg)
        self.status_cb(f"Active pipette profile → {name} ({cfg})")

    def reload_autopipette_sync(self, config_path: str, *, preserve_network: bool = True):
        """Reload config on the **current thread** and finish before returning."""
        # snapshot current NETWORK so we don't cause reconnects
        old_net = None
        try:
            if preserve_network and self.ap.config.has_section("NETWORK"):
                old_net = dict(self.ap.config["NETWORK"])
        except Exception:
            old_net = None

        # hard reload (blocking)
        self.ap.load_config_file(config_path)

        # restore NETWORK (prevents any reconnect side-effects)
        if preserve_network and old_net:
            if not self.ap.config.has_section("NETWORK"):
                self.ap.config.add_section("NETWORK")
            self.ap.config["NETWORK"].clear()
            for k, v in old_net.items():
                self.ap.config["NETWORK"][k] = v
            self.ap._build_header()  # reflect preserved network in header

        # keep gcode manager pointing to the same autopipette instance
        self.gcode.autopipette = self.ap

        # fire listeners inline (no UI thread hop)
        for cb in list(self._config_reload_listeners):
            try: cb()
            except Exception: pass

        self.status_cb(f"Reloaded pipette config (sync) from {config_path}")

    def switch_profile_sync(self, name: str):
        """Synchronous profile switch; blocks until fully loaded."""
        cfg = self.profile_map.get(name)
        if not cfg:
            self.status_cb(f"Unknown profile '{name}'. Available: {', '.join(self.profile_map.keys())}")
            return
        try:
            _ = self.ap.get_gcode()  # flush any stray buffered gcode
        except Exception:
            pass
        self.reload_autopipette_sync(cfg, preserve_network=True)
        self.status_cb(f"Active pipette profile → {name} ({cfg})")
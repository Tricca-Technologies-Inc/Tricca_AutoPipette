# backend/utils/command_dispatcher.py
import shlex
from typing import Any

class CommandDispatcher:
    """
    Given a Controller instance with:
      - `parsers` (TAPCmdParsers)
      - a bunch of methods named like home_all, move_to, pipette, next_tip, etc.
      - `status_cb` for error reporting
    this takes a raw line, parses it, and calls the right Controller method.
    """
    def __init__(self, controller: Any):
        self.ctrl    = controller
        self.parsers = controller.parsers

    def dispatch(self, line: str) -> None:
        parts = shlex.split(line)
        if not parts:
            return

        cmd = parts[0].lower()

        # ─── handle zero-argument commands immediately ────────────
        zero_arg = {
            "next_tip":    self.ctrl.next_tip,
            "eject_tip":   self.ctrl.eject_tip,
            "stop":        self.ctrl.stop,
            "pause":       self.ctrl.pause,
            "resume":      self.ctrl.resume,
            "cancel":      self.ctrl.cancel,
        }
        if cmd in zero_arg:
            try:
                zero_arg[cmd]()
            except Exception as e:
                self.ctrl.status_cb(f"Error running {cmd}: {e}")
            return

        # ─── now fall back to parser-based commands ───────────────
        parser = getattr(self.parsers, f"parser_{cmd}", None)
        if parser is None:
            self.ctrl.status_cb(f"Unknown command: '{cmd}'")
            return

        # parse arguments
        try:
            ns = parser.parse_args(parts[1:])
        except SystemExit:
            # argparse will call sys.exit on bad args; just ignore
            return
        except Exception as e:
            self.ctrl.status_cb(f"Error parsing {cmd}: {e}")
            return

        # ─── dispatch the rest ────────────────────────────────────
        try:
            if cmd == "home":
                t = (ns.motors or "all").lower()
                if t == "all":
                    self.ctrl.home_all()
                else:
                    getattr(self.ctrl, f"home_{t}")()

            elif cmd == "set":
                setattr(self.ctrl.ap, ns.pipvar, ns.pipval)
                self.ctrl.status_cb(f"Set {ns.pipvar} = {ns.pipval}")

            elif cmd == "coor":
                self.ctrl.ap.add_location(ns.name_loc, ns.x, ns.y, ns.z)
                self.ctrl.status_cb(f"Location {ns.name_loc} → ({ns.x},{ns.y},{ns.z})")

            elif cmd == "plate":
                self.ctrl.ap.add_plate(ns.name_loc, ns.plate_type, ns.row, ns.col)
                self.ctrl.status_cb(f"Plate {ns.name_loc} registered")

            elif cmd == "move":
                self.ctrl.move_to(ns.x, ns.y, ns.z)

            elif cmd == "move_loc":
                self.ctrl.move_to_location(ns.name_loc)

            elif cmd == "move_rel":
                self.ctrl.move_relative(ns.x, ns.y, ns.z)

            elif cmd == "pipette":
                self.ctrl.pipette(
                    ns.vol_ul, ns.src, ns.dest,
                    disp_vol_ul=ns.disp_vol_ul,
                    src_row=ns.src_row, src_col=ns.src_col,
                    dest_row=ns.dest_row, dest_col=ns.dest_col,
                    keep_tip=ns.keep_tip,
                    prewet=ns.prewet,
                    wiggle=ns.wiggle
                )

            elif cmd == "run":
                self.ctrl.run_protocol_file(ns.filename)

            elif cmd == "reset_plate":
                self.ctrl.reset_plate(ns.plate)

            elif cmd == "vol_to_steps":
                self.ctrl.vol_to_steps(ns.vol)

            elif cmd == "ls":
                items = self.ctrl.ap.list(ns.var)
                self.ctrl.status_cb("\n".join(items))

            #elif cmd == "load_conf":
            #    self.ctrl.load_config(ns.filename)

            elif cmd == "gcode_print":
                self.ctrl.print_message(ns.msg)

            elif cmd == "send":
                payload = self.ctrl.mrr.gen_request(ns.method, ns.params)
                self.ctrl.send_rpc(payload)

            elif cmd == "notify":
                self.ctrl.notify(ns.method, ns.params)

            elif cmd == "upload":
                # adjust to your parser’s arg names if needed
                self.ctrl.gcode.send(self.ctrl.ap.get_gcode(), ns.file_name)

            else:
                self.ctrl.status_cb(f"Command '{cmd}' not implemented")
        except Exception as e:
            self.ctrl.status_cb(f"Error running {cmd}: {e}")

from pathlib import Path
from typing import Callable, Any
from datetime import datetime, timedelta

class ProtocolRunner:
    def __init__(self, controller: Any):
        self.ctrl = controller
        self.base = Path(__file__).parent.parent.parent / "programs"

    def run_file(self, filename: str) -> str:
        proto = self.base / filename
        if not proto.exists():
            return f"Protocol not found: {filename}"

        # load & filter
        lines = [l.strip() for l in proto.read_text().splitlines()]
        cmds  = [l for l in lines if l and not l.startswith("#")]
        total = len(cmds)
        start = datetime.now()

        # buffer for all generated G-code
        buf: list[str] = []

        # monkey-patch gcode.send to collect into buf
        orig_send = self.ctrl.gcode.send  # type: ignore

        def _collect(gcode: list[str], _fname=None, _append_header=False):
            for line in gcode:
                buf.append(line if line.endswith("\n") else line + "\n")
        self.ctrl.gcode.send = _collect  # type: ignore

        # dispatch each protocol line
        for idx, cmd in enumerate(cmds):
            # 1) dispatch
            self.ctrl.status_cb(f"Running: {cmd}")
            self.ctrl.dispatcher.dispatch(cmd)

            # 2) fire step callbacks
            nxt = cmds[idx+1] if idx+1 < total else "Done"
            for cb in self.ctrl._step_listeners:
                cb(cmd, nxt)

            # 3) fire time callbacks
            elapsed = datetime.now() - start
            # avoid div-by-zero
            frac = (idx+1) / total
            if frac > 0:
                total_est = elapsed / frac
                remaining = total_est - elapsed
            else:
                remaining = timedelta(0)
            def fmt(td: timedelta):
                m, s = divmod(int(td.total_seconds()), 60)
                return f"{m:02d}:{s:02d}"
            e_str = fmt(elapsed)
            r_str = fmt(remaining)
            for cb in self.ctrl._time_listeners:
                cb(e_str, r_str)

        # restore real send
        self.ctrl.gcode.send = orig_send  # type: ignore

        # now ship the whole protocol in one file
        out_name = Path(filename).with_suffix(".gcode").name
        # append_header=True will cause GCodeManager to prepend header
        self.ctrl.gcode.send(buf, out_name, append_header=True)

        return f"Queued {out_name}"

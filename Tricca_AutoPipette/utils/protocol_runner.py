from pathlib import Path
import time
from typing import Any, Callable, Optional
import threading

class ProtocolRunner:
    def __init__(self, controller: Any):
        self.ctrl = controller
        self.base = Path(__file__).parent.parent.parent / "panelA_programs"
        self._seq_cancel = threading.Event()

    def run_file(self, filename: str) -> str:
        proto = self.base / filename
        if not proto.exists():
            return f"Protocol not found: {filename}"

        raw = proto.read_text().splitlines()

        # --- PRE-PASS: profile must be the first non-comment line -------------
        def is_comment(s: str) -> bool:
            t = s.strip()
            return (not t) or t.startswith("#") or t.startswith(";")

        # find first non-comment
        first_idx = next((i for i, ln in enumerate(raw) if not is_comment(ln)), None)
        profile_name = None

        if first_idx is not None:
            first = raw[first_idx].strip()
            low   = first.lower()

            if low.startswith(";@profile") or low.startswith("#@profile"):
                parts = first.split()
                if len(parts) < 2:
                    return "Protocol error: malformed ;@profile directive"
                profile_name = parts[1].upper()
                raw.pop(first_idx)
            elif low.startswith("profile "):
                parts = first.split(None, 1)
                if len(parts) < 2:
                    return "Protocol error: malformed profile line"
                profile_name = parts[1].strip().upper()
                raw.pop(first_idx)
            else:
                keys = {k.upper() for k in self.ctrl.profile_map.keys()}
                if first.upper() in keys:
                    profile_name = first.upper()
                    raw.pop(first_idx)

        # forbid late profile directives
        for ln in raw:
            s = ln.strip()
            if not s:
                continue
            sl = s.lower()
            if sl.startswith("profile ") or s.startswith(";@profile") or s.startswith("#@profile"):
                return "Protocol error: profile directive must be the first non-comment line"

        # ---- SYNCHRONOUS switch happens **now**, before any command parsing ---
        if profile_name:
            self.ctrl.switch_profile_sync(profile_name)

        # --- Build the TAP command list (strip comments) -----------------------
        lines = []
        for _raw in raw:
            s = _raw.strip()
            if s and not s.startswith(("#", ";")):
                lines.append(s)

        # --- Collect G-code while dispatching ---------------------------------
        buf: list[str] = []
        orig_send = self.ctrl.gcode.send

        def _collect(gcode, _fname=None, _append_header=False):
            for ln in gcode:
                buf.append(ln if ln.endswith("\n") else ln + "\n")

        try:
            self.ctrl.gcode.send = _collect
            for cmd in lines:
                self.ctrl.dispatcher.dispatch(cmd)
        finally:
            # ALWAYS restore, even if dispatch raises
            self.ctrl.gcode.send = orig_send

        if not buf:
            # helpful diagnostics so you see why nothing was sent
            self.ctrl.status_cb("No G-code generated from protocol (check command parsing).")
            return "Protocol produced no G-code; aborting upload."

        # --- Write temp .gcode then upload & start ----------------------------
        out_name = Path(filename).with_suffix(".gcode").name
        temp_path = Path(self.ctrl.gcode.temp_dir) / out_name

        # (optional) prepend header so you can confirm which config was used
        try:
            header = "".join(self.ctrl.ap.get_header())
        except Exception:
            header = ""
        temp_path.write_text(header + "\n" + "".join(buf))

        def _upload_and_start():
            try:
                fut = self.ctrl.client.upload_gcode_file(out_name, temp_path)
                server_path = fut.result(timeout=30)
                self.ctrl.status_cb(f"Uploaded -> {server_path}")
                payload = self.ctrl.mrr.gen_request("printer.print.start", {"filename": server_path})
                self.ctrl.send_rpc(payload)
            except Exception as e:
                self.ctrl.status_cb(f"Print start error: {e}")

        threading.Thread(target=_upload_and_start, daemon=True).start()
        return f"Queued and started {out_name}"
        
    def run_sequence(
        self,
        files: list[str],
        on_sequence_complete: Optional[Callable[[], None]] = None
    ) -> None:
        """
        Run each .pipette file in order, waiting for each print to finish,
        fire your ._step_listeners for each file, and then finally call
        on_sequence_complete(), if provided.
        """
        def worker():
            #start fresh and new
            self._seq_cancel.clear()

            for idx, fname in enumerate(files):
                # stop if user already cancelled sequence
                if self._seq_cancel.is_set():
                    self.ctrl.status_cb("Sequence cancelled by user.")
                    break

                nxt = files[idx+1] if idx+1 < len(files) else "Done"

                # ── File‐level step callback
                for cb in self.ctrl._step_listeners:
                    cb(fname, nxt)

                self.ctrl.status_cb(f"Starting {fname}")
                result = self.run_file(fname)
                self.ctrl.status_cb(result)

                # ── Block until print completes (using the same notify_printer.objects hook
                #    that drives your progress/time UI)
                done = threading.Event()
                def _on_complete():
                    done.set()

                self.ctrl.add_complete_listener(_on_complete)

                try:
                    # wait here; _on_complete now fires on cancel as well
                    done.wait()
                finally:
                    self.ctrl.remove_complete_listener(_on_complete)

                # Decide whether to continue
                state = (self.ctrl._last_job_state_raw or "").lower()

                if self._seq_cancel.is_set() or state in ("cancelled", "error"):
                    msg = "cancelled" if state == "cancelled" or self._seq_cancel.is_set() else "error"
                    self.ctrl.status_cb(f"Sequence stopped due to {msg} on {fname}.")
                    break

                #OK if else
                self.ctrl.status_cb(f"Finished {fname}")

            else:
                # loop didn't break -> completed all files
                self.ctrl.status_cb("Sequence completed")

            if on_sequence_complete:
                on_sequence_complete()

        threading.Thread(target=worker, daemon=True).start()

    def request_sequence_cancel(self):
        self._seq_cancel.set()
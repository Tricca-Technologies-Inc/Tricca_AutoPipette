# backend/utils/gcode_manager.py
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

class GCodeManager:
    def __init__(
        self,
        client,                # WebSocketClient
        mrr,                   # MoonrakerRequests
        autopipette,           # AutoPipette
        status_cb: Callable[[str], None],
        temp_dir: Path
    ):
        self.client    = client
        self.mrr       = mrr
        self.ap        = autopipette
        self.status_cb = status_cb
        self.temp_dir  = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        gcode: List[str],
        filename: Optional[str] = None,
        append_header: bool = False
    ):
        # pick a timestamped name
        name = filename or datetime.now().strftime("%Y-%m-%d-%H-%M-%S-%f.gcode")
        path = self.temp_dir / name

        # write file (with optional header)
        with open(path, "w") as f:
            if append_header:
                for comment in self.ap.get_header():
                    f.write(comment if comment.endswith("\n") else comment + "\n")
            for line in gcode:
                f.write(line if line.endswith("\n") else line + "\n")

        # background upload+start+cleanup
        def _worker():
            try:
                server_path = self.client.upload_gcode_file(name, path) \
                                      .result(timeout=30)
                self.status_cb(f"Uploaded → {server_path}")

                payload = self.mrr.printer_print_start(name)
                resp    = self.client.send_jsonrpc(payload)
                self.status_cb(f"Print started: {resp}")
            except Exception as e:
                self.status_cb(f"Error: {e}")
            finally:
                try: path.unlink()
                except OSError: pass

        threading.Thread(target=_worker, daemon=True).start()
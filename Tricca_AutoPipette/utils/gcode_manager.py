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
        append_header: bool = False,
        upload_and_print: bool = False
    ):
        """
        If upload_and_print is False, just write & send via WS-RPC.
        If True, write file, upload via HTTP, then start print on the server.
        """
        name = filename or datetime.now().strftime("%Y-%m-%d-%H-%M-%S-%f.gcode")
        path = self.temp_dir / name

        # 1) Write the G-code out to a temp file
        with open(path, "w") as f:
            if append_header:
                for comment in self.ap.get_header():
                    f.write(comment.rstrip("\n") + "\n")
            for line in gcode:
                f.write(line.rstrip("\n") + "\n")

        # 2) If they just want to push G-code via JSON-RPC:
        if not upload_and_print:
            # use MoonrakerRequests to batch-send as JSON-RPC upload
            payload = self.mrr.gen_request("printer.upload_gcode", {
                "filename": name,
                "content": path.read_text().splitlines()
            })
            resp = self.client.send_jsonrpc(payload)
            self.status_cb(f"Sent G-code batch → {resp}")
            path.unlink(missing_ok=True)
            return

        # 3) Otherwise, do an HTTP file upload, then kick off a print
        def _worker():
            try:
                # upload_gcode_file returns a Future[path_on_server]
                server_path = self.client.upload_gcode_file(name, str(path)) \
                                      .result(timeout=30)
                self.status_cb(f"Uploaded → {server_path}")

                # now start print via JSON-RPC
                payload = self.mrr.printer_print_start(server_path)
                resp    = self.client.send_jsonrpc(payload)
                self.status_cb(f"Print started: {resp}")

            except Exception as e:
                self.status_cb(f"Error during upload/print: {e}")

            finally:
                path.unlink(missing_ok=True)

        threading.Thread(target=_worker, daemon=True).start()

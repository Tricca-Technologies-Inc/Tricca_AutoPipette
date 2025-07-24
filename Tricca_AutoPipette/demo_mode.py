# dummy stuff for testing without connecting to klipper
import threading, queue
from datetime import datetime

class DummyFuture:
    def __init__(self):
        self._result = f"/fake/path/{datetime.now().isoformat()}.gcode"
    def result(self, timeout=None):
        return self._result

class DummyClient:
    def __init__(self, url=None):
        self._connected = threading.Event()
        self._connected.set()    # pretend “connected”
        self.message_queue = queue.Queue()
        self._handlers = {}

    def start(self): pass
    def stop(self):  pass

    def upload_gcode_file(self, name, path):
        print(f"[demo] upload {name} ← {path}")
        return DummyFuture()

    def send_jsonrpc(self, payload):
        print(f"[demo] send_jsonrpc: {payload}")
        return {"result": "ok", "id": payload.get("id")}

    def send_notification(self, method, params=None):
        print(f"[demo] notify {method} {params}")

    def register_handler(self, method, cb):
        self._handlers[method] = cb

    def __getattr__(self, attr):
        # catch-all for anything else
        def fn(*a, **k): print(f"[demo] {attr}(*{a}, **{k})")
        return fn

class DummyMoonraker:
    def gen_request(self, method, params=None):
        return {"jsonrpc":"2.0","method":method,"params":params or {}, "id": 1}

    def printer_print_start(self, name):
        return self.gen_request("printer.print.start", {"filename": name})

    def printer_objects_query(self, objs):
        return self.gen_request("printer.objects.query", {"objects": objs})

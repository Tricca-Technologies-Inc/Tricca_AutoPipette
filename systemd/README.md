# systemd units

Two services, run in this order:

- `tapd.service` — the `tapd` control daemon. Owns the single persistent
  connection to Moonraker; must be running before the kiosk starts.
- `autopipette-kiosk.service` — the FastAPI kiosk web UI. Talks to `tapd`'s
  control-plane WebSocket (`ws://127.0.0.1:8765/control` by default) instead
  of spawning its own subprocess per run. `Requires=`/`After=tapd.service`,
  so it won't start (or will stop) without the daemon.

Both `ExecStart` lines point at a placeholder path
(`/opt/tricca-autopipette/venv/bin/...`) — edit them to match your host's
actual virtualenv location and, if needed, add a `User=`/`WorkingDirectory=`
appropriate for your setup before installing.

## Install

```bash
sudo cp systemd/tapd.service systemd/autopipette-kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tapd.service
sudo systemctl enable --now autopipette-kiosk.service
```

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

## `AUTOPIPETTE_REPO_ROOT`

Both units set `Environment=AUTOPIPETTE_REPO_ROOT=/opt/tricca-autopipette`.
This is the directory holding `config/`, `protocols/` and `gcode/`; edit it
alongside the `ExecStart` paths.

It is needed because the default is derived from the package's own location
(`.../src/tricca_autopipette/core/pipette_constants.py` → four levels up),
which is only correct for a src-layout checkout. An installed package (Nix,
pip, wheel) has no `src` segment, so the default lands one directory too
high — `tapd` then dies looking for `config/system/default_system.json` under
a path with no `config/` in it, and the kiosk's `GET /protocols` returns a
500. Running from a git checkout needs no override.

The value must be an **absolute** path — a relative one is rejected at
startup with a clear error rather than being resolved against the process's
working directory (systemd starts services with `cwd=/`). An empty value is
treated as unset.

`AUTOPIPETTE_PROTOCOLS_DIR` separately overrides just the protocols
directory, if it lives somewhere other than `$AUTOPIPETTE_REPO_ROOT/protocols`.
Note the kiosk resolves it once at import time, so changing it needs a
service restart.

## Install

```bash
sudo cp systemd/tapd.service systemd/autopipette-kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tapd.service
sudo systemctl enable --now autopipette-kiosk.service
```

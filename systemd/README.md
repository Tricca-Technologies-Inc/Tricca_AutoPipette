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

## `AUTOPIPETTE_LOCAL_DIR`

A second, unrelated root (issue #68) — the per-machine **local config root**,
holding real per-rig data (hostname, deck layout, per-machine protocols) that
has no business in the shared code repo above. Defaults to
`$XDG_CONFIG_HOME/tricca-autopipette` (falling back to
`~/.config/tricca-autopipette`); override with `Environment=AUTOPIPETTE_LOCAL_DIR=...`
if it should live somewhere else on this host. Same absolute-path requirement
and empty-is-unset handling as `AUTOPIPETTE_REPO_ROOT`. Unlike
`AUTOPIPETTE_REPO_ROOT`, the default's fallback depends on `HOME`/
`XDG_CONFIG_HOME` being set, which a systemd-run service doesn't get for
free — `tapd.service` sets it explicitly rather than relying on that
fallback; do the same if you write your own unit. See
`config/README.md`'s "Shared repo vs. local per-machine config" for the full
model — six categories are a shared/local union, but `system/` is a
pick-one-active-file selector that lives in the local root exclusively.

That `system/` selector has a startup consequence specific to a headless
systemd start: if the local root's `system/` directory ever ends up with more
than one profile and `tapd.service`'s `ExecStart` passes no `--config`, the
daemon has no terminal to prompt on and **hard-fails at startup** rather than
guessing which profile to load. A single-profile machine needs no `--config`
at all; a machine that keeps more than one profile (e.g. interchangeable
pipette models on the same rig) needs an explicit `--config <name>` added to
`ExecStart` in the unit file, or `system/active.json` in the local root
pointed at the right one by hand (`ln -sf <name>.json system/active.json`) --
either way, avoid relying on the interactive prompt for anything that starts
under systemd.

### Cloning the local config root

The local root itself is a git checkout, not something `tapd` creates for
you — see `config/README.md`'s "Shared repo vs. local per-machine config"
for the model: one shared repo, `tricca-autopipette-local-config`, with one
branch per physical rig. Clone it into place **before** the first
`tapd.service` start, as whatever `User=` the unit runs as (or with
ownership matching that user afterward):

```bash
git clone git@github.com:Tricca-Technologies-Inc/tricca-autopipette-local-config.git \
  ~/.config/tricca-autopipette   # or wherever AUTOPIPETTE_LOCAL_DIR points
cd ~/.config/tricca-autopipette
git checkout <machine-branch>    # e.g. murphy — matches this rig's name
```

Cloning first matters: if `system/` in the local root is empty when `tapd`
starts, it warns and auto-copies the shared repo's generic
`config/system/default_system.json` in as a starting profile — harmless on a
brand-new rig, but not what you want on a rig that already has a real
profile committed. Clone (and `checkout` the right branch) first and that
auto-copy never triggers.

If no branch exists yet for this rig, branch it from `main` (the shared
baseline templates) instead of starting from nothing — see the local-config
repo's own README for the exact steps, and `config/README.md`'s `system/`
section for bootstrapping the profile itself (`tapd --init-local-config`)
once the checkout is in place.

## Network exposure

Both services bind **loopback only**, and that is deliberate.

- `tapd` defaults to `127.0.0.1:8765` for its control plane.
- `autopipette-kiosk` passes `--host 127.0.0.1` to uvicorn.

**Neither has any authentication** — no login, no token, no TLS, no origin
check. Their only protection is that nothing off-host can reach them. The
touchscreen runs a browser on the same host, so it needs nothing more.

This matters more here than for a typical web service: an unauthenticated
`POST /run` moves a gantry and drives a syringe. Klipper-world convention
often runs Moonraker and Mainsail unauthenticated on a trusted LAN; do not
carry that assumption over to a machine handling liquids in a lab.

If you need access from another machine, **do not** simply change the bind to
`0.0.0.0` — that publishes full unauthenticated hardware control to every
device on the network. Put it behind something that authenticates: an SSH
tunnel or a reverse proxy requiring credentials for a one-off, or a tailnet
interface with ACLs restricting which devices may connect. Real
authentication in the application, and a fleet-facing browser tool, are
tracked as issues [#31](https://github.com/Tricca-Technologies-Inc/Tricca_AutoPipette/issues/31)
and [#32](https://github.com/Tricca-Technologies-Inc/Tricca_AutoPipette/issues/32).

Earlier revisions of `autopipette-kiosk.service` shipped `--host 0.0.0.0`. If
you installed from one of those, re-copy the unit and reload — the exposure
persists in `/etc/systemd/system/` until you do.

## Install

```bash
sudo cp systemd/tapd.service systemd/autopipette-kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tapd.service
sudo systemctl enable --now autopipette-kiosk.service
```

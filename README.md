![Logo](https://www.tricca.ca/assets/logos/tricca-6bc01c5f.svg)
# Tricca AutoPipette

Tricca AutoPipette controls an automated liquid handling system (ALHS) built
on the Voron 3D-printer/Klipper platform. A long-running control daemon
(`tapd`) owns the single connection to Moonraker and drives the gantry,
syringe pump, and tip-ejection servo; an interactive shell (`tap`) and a
touchscreen kiosk web UI are both thin clients of that daemon.

## Quickstart

```bash
pip install -e ".[dev]"
```

Run the daemon first — `tap` and the kiosk are both clients of it and do
nothing useful until it's running:

```bash
tapd                          # connects to Moonraker per config/system/system.json
```

Then, in another terminal, drive it with the interactive shell:

```bash
tap
```

...or run the touchscreen kiosk web backend:

```bash
uvicorn autopipette_kiosk.main:app --host 127.0.0.1 --port 8000
```

Both the daemon's control plane and the kiosk are loopback-only by default,
with no authentication — see `systemd/README.md` before changing a bind
address.

## Further documentation

- [`CLAUDE.md`](CLAUDE.md) — architecture deep-dive: components, the `tapd`
  daemon, domain model, config system, and code style.
- [`CONTEXT.md`](CONTEXT.md) — glossary of domain terms.
- [`docs/protocol-authoring.md`](docs/protocol-authoring.md) — how to write
  a `.pipette` protocol file, with runnable examples.
- [`config/README.md`](config/README.md) — the layered JSON config system.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, checks, and how to open a PR.
- [`systemd/README.md`](systemd/README.md) — production deployment as
  systemd services, and the network-exposure decisions behind it.

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html).

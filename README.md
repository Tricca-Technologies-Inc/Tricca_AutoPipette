![Logo](https://www.tricca.ca/assets/logos/tricca-6bc01c5f.svg)
# Tricca AutoPipette

Tricca AutoPipette controls an automated liquid handling system (ALHS) built
on the Voron 3D-printer/Klipper platform. A long-running control daemon
(`tapd`) owns the single connection to Moonraker and drives the gantry,
syringe pump, and tip-ejection servo; an interactive shell (`tap`) and a
touchscreen kiosk web UI are both thin clients of that daemon.

## Quickstart

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
uv sync --extra dev
```

Run the daemon first — `tap` and the kiosk are both clients of it and do
nothing useful until it's running:

```bash
uv run tapd                   # connects to Moonraker per the active local system config
```

Then, in another terminal, drive it with the interactive shell:

```bash
uv run tap
```

...or run the touchscreen kiosk web backend:

```bash
uv run uvicorn autopipette_kiosk.main:app --host 127.0.0.1 --port 8000
```

On the Run page, the **Run protocol** button changes to **Pause** or **Resume**
for a confirmed running or paused job. **Cancel** can stop preparation or
request cancellation of the current job; the separate breakpoint
Continue/Abort prompt still applies during preparation. A request is not
confirmation until the status changes.
Cancel is **not an emergency stop**.

The progress bar estimates the fraction of the G-code file processed, not
elapsed time or physical completion. It is unavailable during preparation or
when the current job cannot be verified. Controls are disabled when the
relevant job state or daemon connection is unknown. Generated Moonraker
G-code files have a unique run ID in their names and remain on the server.
With `tapd --no-connect`, a protocol can be prepared but cannot execute;
the kiosk reports that no job was sent.

The Commands tab accepts one listed `tap`-style command at a time; it is not
an operating-system shell. Commands are refused during a protocol run and use
the same daemon homing and interlock checks. Motion and pipetting commands
require a robot connection and can operate the machine. A successful command
request does not confirm physical completion. In `--no-connect` mode, only
the `vol_to_mm` calculation is available.

Both the daemon's control plane and the kiosk are loopback-only by default,
with no authentication — see `systemd/README.md` before changing a bind
address.

## Further documentation

- [`CLAUDE.md`](CLAUDE.md) — architecture deep-dive: components, the `tapd`
  daemon, domain model, config system, and code style.
- [`CONTEXT.md`](CONTEXT.md) — glossary of domain terms.
- [`docs/protocol-authoring.md`](docs/protocol-authoring.md) — how to write a
  `.pipette` protocol file, with runnable examples.
- [`config/README.md`](config/README.md) — the layered JSON config system.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, checks, and how to open a PR.
- [`systemd/README.md`](systemd/README.md) — production deployment as
  systemd services and network-exposure decisions.
- [`systemd/ubuntu-touchscreen.md`](systemd/ubuntu-touchscreen.md) — Ubuntu/Debian
  touchscreen installation, boot launch, and safe commissioning checklist.

## License

This project is licensed under the [GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html).

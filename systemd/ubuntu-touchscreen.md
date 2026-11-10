# Ubuntu/Debian touchscreen deployment

This guide sets up the `Tyson-main` checkout on an Ubuntu/Debian x86_64 robot host with a local touchscreen. The backend runs as systemd services; the browser starts fullscreen in the desktop session after automatic login. Use the existing systemd deployment guide for service behavior and network restrictions: [README.md](README.md).

## Safety and prerequisites

- Confirm the touchscreen is recognized by the host and that the desktop session is usable with touch input.
- Install Python 3.14 and `uv`; this project requires Python 3.14 or newer. The dependency lock supports Linux x86_64.
- Confirm Moonraker is reachable from this host and that a qualified operator has verified the robot's actual network, gantry, pipette, deck, and calibration settings.
- Keep the kiosk and `tapd` bound to `127.0.0.1`. Neither has authentication; do not expose either service to the LAN.
- Do not run motion commands as an installation check. Commissioning motion requires a qualified operator, an empty deck, clear gantry travel, and an accessible emergency stop.

Automatic desktop login means anyone with physical access to the screen can use the control UI. Use a dedicated, non-administrator desktop account and physically restrict access to the robot.

## Install the code branch

Run these commands as the account that will own the checkout, adjusting `/opt` permissions if necessary:

```bash
git clone --branch Tyson-main git@github.com:Tricca-Technologies-Inc/Tricca_AutoPipette.git \
  /opt/tricca-autopipette
cd /opt/tricca-autopipette
uv python install 3.14
UV_PROJECT_ENVIRONMENT=/opt/tricca-autopipette/venv uv sync --frozen
```

If the checkout already exists, preserve any local changes; fetch and switch to `Tyson-main` rather than recloning over it. The locked install creates the virtual environment path expected by the supplied units.

## Prepare the rig-local configuration

`system/` is local-only at runtime. The `config/system/Tyson_main.json` file in this checkout is a template and is not loaded directly by `tapd`. The separate private `tricca-autopipette-local-config` repository is the local config root; its branch should be named for the physical rig. That repository currently has `main` and `murphy` branches but no `tyson` branch, so create the Tyson branch from `main` before deployment.

```bash
git clone git@github.com:Tricca-Technologies-Inc/tricca-autopipette-local-config.git \
  /path/to/tricca-autopipette-local-config
cd /path/to/tricca-autopipette-local-config
git checkout -b tyson origin/main
mkdir -p system
cp /opt/tricca-autopipette/config/system/Tyson_main.json system/Tyson_main.json
```

Have the robot owner review `system/Tyson_main.json` against the actual machine before committing it. Do not overwrite or invent mechanical calibration, deck coordinates, or network settings. The shared checkout supplies the referenced `Tyson_gantry`, `TysonP100`, `Tyson100_liquids`, and `Tyson100_locations` files, while any machine-specific overrides belong in the local config root. After review:

```bash
git add system/Tyson_main.json
git commit -m "Add Tyson rig system profile"
git push -u origin tyson
```

Set `AUTOPIPETTE_LOCAL_DIR` in `tapd.service` to the absolute path of this checkout. Ensure the systemd service account can read both the shared code checkout and local config. If the local config contains multiple profiles, set the daemon's `ExecStart` to select this one explicitly:

```ini
ExecStart=/opt/tricca-autopipette/venv/bin/tapd --config Tyson_main.json
```

The `--config` name resolves under `$AUTOPIPETTE_LOCAL_DIR/system/`. Do not rely on an interactive profile prompt in a systemd service.

## Install and start the backend

Review the service paths and account settings in `systemd/tapd.service` and `systemd/autopipette-kiosk.service`, then install them:

```bash
sudo cp systemd/tapd.service systemd/autopipette-kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tapd.service
sudo systemctl status tapd.service --no-pager
```

After confirming `tapd` started with the intended profile and connected to the expected Moonraker instance, start the kiosk backend:

```bash
sudo systemctl enable --now autopipette-kiosk.service
sudo systemctl is-active tapd.service autopipette-kiosk.service
curl --fail --silent --show-error http://127.0.0.1:8000/ >/dev/null
```

If either service fails, inspect its journal before proceeding:

```bash
sudo journalctl -u tapd.service -u autopipette-kiosk.service -b --no-pager
```

## Launch the browser fullscreen on boot

Enable automatic login for the dedicated desktop account in the desktop's user settings. Keep that account non-administrator; do not enable automatic root login. In Ubuntu GNOME, create a small launcher that waits for the kiosk backend to become available, then add it to that account's autostart:

```bash
mkdir -p ~/.local/bin ~/.config/autostart
cat > ~/.local/bin/autopipette-kiosk-browser <<'EOF'
#!/bin/sh
set -eu
url=http://127.0.0.1:8000/
browser="$(command -v chromium || command -v chromium-browser || command -v google-chrome)"
until curl --fail --silent --max-time 2 "$url" >/dev/null; do
  sleep 2
done
exec "$browser" --kiosk --no-first-run --disable-session-crashed-bubble "$url"
EOF
chmod +x ~/.local/bin/autopipette-kiosk-browser
cat > ~/.config/autostart/autopipette-kiosk.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=AutoPipette Kiosk
Exec=/home/OPERATOR/.local/bin/autopipette-kiosk-browser
X-GNOME-Autostart-enabled=true
EOF
```

Install a browser supported by the host's desktop. Replace `/home/OPERATOR` in `Exec=` with the dedicated account's actual home directory. The launcher checks for `chromium`, `chromium-browser`, then `google-chrome`; update its `browser=` line if the installed browser has another command name. Log out and back in once to verify autostart, then reboot to confirm the full boot flow. Configure display sleep/blanking in desktop power settings so the touchscreen remains visible during operation.

The browser and backend must run on the same host. Do not change the kiosk bind address to `0.0.0.0` to view it from another device; see [README.md](README.md) for the trust-boundary rationale.

## Safe commissioning

Before enabling any movement from the touchscreen, a qualified operator should:

1. Confirm the selected local system profile, Moonraker host/port, pipette, gantry, deck layout, syringe calibration, and emergency-stop operation against the physical machine.
2. Verify the browser status and backend logs without executing a protocol or movement command.
3. If motion testing is separately approved, clear the gantry envelope and deck, keep the emergency stop accessible, and begin with a low-risk manually supervised check. Stop if observed motion differs from expected configuration.

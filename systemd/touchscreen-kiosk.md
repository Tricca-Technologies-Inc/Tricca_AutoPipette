# Touchscreen kiosk host

How to set up a Linux host with a local touchscreen so it boots straight into the kiosk, fullscreen, with no desktop. Nothing here is tied to a distro: it needs only systemd, which every mainstream distro uses, plus three packages. The CB1 boards are deployed with Nix through `cb1-autopipette` instead. This guide is for any other host.

The host runs three services:

- `tapd.service` and `autopipette-kiosk.service`, as in [README.md](README.md).
- `autopipette-kiosk-browser.service` (this guide), which runs Chromium fullscreen inside [cage](https://github.com/cage-kiosk/cage), a Wayland compositor that shows a single app and nothing else. With no desktop environment, there's no display manager, autostart file or desktop power setting to configure, and the operator can't leave the kiosk.

## Safety and prerequisites

- Confirm the host detects the touchscreen (for example, `libinput list-devices` lists it).
- Keep the kiosk and `tapd` bound to `127.0.0.1`. Neither has authentication, so never expose either one to the network. The browser runs on the same host, so it doesn't need to.
- Anyone with physical access to the screen can drive the robot. The browser runs as a dedicated account with no administrator rights. Restrict physical access to the robot.
- Don't run motion commands as an installation check. Commissioning motion needs a qualified operator, an empty deck, clear gantry travel and a reachable emergency stop. See [Safe commissioning](#safe-commissioning).

## 1. Install the packages

Install these with your distro's package manager:

- `cage`
- `chromium` (some distros name it `chromium-browser`; Google Chrome works too)
- `curl`

Use the browser your distro packages natively. A sandboxed build (snap or flatpak) may refuse to start from a system service. The browser unit tries `chromium`, `chromium-browser`, `google-chrome-stable` and `google-chrome`, in that order.

## 2. Install the code and the backend

Follow [README.md](README.md). It covers installing a checkout of `main` at `/opt/tricca-autopipette`, creating the locked venv, setting `AUTOPIPETTE_REPO_ROOT` and `AUTOPIPETTE_LOCAL_DIR`, cloning the rig's local config root, and enabling `tapd.service` and `autopipette-kiosk.service`.

Two points matter for a kiosk host:

- The rig's system profile lives in the local config root on the rig's own branch, not in this repo. If the local root holds more than one profile, pin this rig's profile in `tapd.service` (`ExecStart=... tapd --config <name>.json`). A headless service can't answer the interactive profile prompt and fails to start instead.
- Check the backend before adding the browser:

  ```bash
  systemctl is-active tapd.service autopipette-kiosk.service
  curl -fsS -o /dev/null http://127.0.0.1:8000/ && echo kiosk up
  ```

  If either fails, check `journalctl -u tapd.service -u autopipette-kiosk.service -b` before going further.

## 3. Create the kiosk account

```bash
sudo useradd --create-home --shell /usr/sbin/nologin kiosk
```

Don't add it to `wheel`/`sudo` or any admin group. It doesn't need a password or a login shell: the browser unit starts its session directly.

## 4. Install the browser unit

```bash
sudo cp systemd/autopipette-kiosk-browser.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autopipette-kiosk-browser.service
```

The unit takes over `tty1` and waits until the kiosk backend answers, then starts cage and Chromium. If a display manager (GDM, SDDM, LightDM, ...) was installed with the OS, turn it off so it doesn't compete for the screen:

```bash
sudo systemctl disable --now display-manager.service
```

Reboot once to confirm the whole boot flow. Then confirm the screen comes up on the kiosk's Run page.

If the screen stays blank, check:

```bash
journalctl -u autopipette-kiosk-browser.service -b
```

- "no Chromium found" means step 1 is incomplete.
- A seat or DRM permission error usually means a display manager still holds the screen.

cage doesn't blank or lock the screen, so no power settings need changing.

## Safe commissioning

Before enabling any movement from the touchscreen, a qualified operator should:

1. Confirm the system profile `tapd` loaded, the Moonraker host and port, the pipette, gantry, deck layout, syringe calibration and the emergency stop against the physical machine.
2. Check the kiosk's status display and the backend logs without running a protocol or a move.
3. Only if motion testing is approved: clear the deck and the gantry's travel, keep the emergency stop within reach, and start with a low-risk check you supervise by hand. Stop if the motion differs from what the configuration says.

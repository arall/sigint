# Service setup

Both the central server and the remote agent can be run as systemd services that start on boot and restart on failure. Installers live in `scripts/`.

## Prerequisites

- Repo cloned, venv created, dependencies installed per [install.md](install.md).
- For the agent: Meshtastic radio on USB, RTL-SDR connected. GPS optional.
- For the server: HackRF / RTL-SDR / BLE / WiFi per your use case, plus the Meshtastic radio if using C2.

## Central server

```sh
cd ~/code/sigint
sudo ./scripts/install-server.sh
```

The installer:

1. Offers to copy a template from `configs/*.json.example` into `configs/server.json` (skip if you've already written one).
2. Optionally applies a Meshtastic channel URL to the server's radio via `meshtastic --seturl`.
3. Writes `/etc/systemd/system/sigint-server.service` with the current project path substituted for `@PROJECT_DIR@`.
4. `systemctl enable --now sigint-server.service`.

Service details:

- Runs as `root` (needed for BLE / WiFi).
- `ExecStart=.../sdr.py server configs/server.json --web` — web UI always on, port from config (`web_port`) or default 8080.
- `Restart=always, RestartSec=5`.

Useful commands:

```sh
sudo systemctl status sigint-server
sudo systemctl restart sigint-server
journalctl -u sigint-server -f
```

## Remote agent

```sh
cd ~/code/sigint
sudo ./scripts/install-agent.sh
```

The installer prompts for four things:

- **Agent ID** — short identifier, e.g. `N01`.
- **Meshtastic serial port** — full `/dev/serial/by-id/...` path recommended.
- **Meshtastic channel URL** (optional) — applied via `--seturl` if provided. Leave empty if the radio is already on the shared channel.
- **GPS serial port** (optional) — u-blox or similar NMEA source.

Then it writes `configs/agent.json`, installs `sigint-agent.service`, and starts it.

Service details:

- Runs as `root`.
- `ExecStart=.../sdr.py agent --config configs/agent.json`.
- `/var/lib/sigint/` holds `state.json`, `outbox.db`, and `scanner/<type>_*.db`.
- `Restart=always, RestartSec=5`.

Useful commands:

```sh
sudo systemctl status sigint-agent
sudo systemctl restart sigint-agent
journalctl -u sigint-agent -f

# Edit the agent config without reinstalling:
sudo $EDITOR configs/agent.json
sudo systemctl restart sigint-agent
```

## Template substitution (`@PROJECT_DIR@`)

The committed unit files (`scripts/sigint-*.service`) use `@PROJECT_DIR@` as a placeholder for the absolute repo path. Each installer `sed`-substitutes it to the current project directory when copying the unit into `/etc/systemd/system/`. That makes the repo path-portable — clone anywhere, run the installer, done.

## What the installers don't do

None of them install system packages or Python dependencies. Do that first ([install.md](install.md)). The installer assumes:

- `venv/bin/python3` exists in the project dir
- `pip install -r requirements.txt` has been run
- `rtl-sdr`, `readsb`, `rtl_ais`, `multimon-ng`, `rtl-433`, etc. are on PATH as needed

## Provisioning a fresh Meshtastic radio

If the radio is on the factory default channel, the server can't hear it and vice versa. Provision with:

```sh
venv/bin/meshtastic --port /dev/serial/by-id/usb-<your-radio>-if00 --seturl '<URL>'
```

The same URL must be set on every node that should join the C2 mesh. `install-agent.sh` and `install-server.sh` both run `--seturl` for you if you paste the URL at the prompt.

Verify:

```sh
venv/bin/meshtastic --port /dev/serial/by-id/usb-<your-radio>-if00 --info | grep -A1 "Complete URL"
```

## Un-install

```sh
sudo systemctl disable --now sigint-agent     # or sigint-server
sudo rm /etc/systemd/system/sigint-agent.service
sudo systemctl daemon-reload
# Optional: remove the config + state
sudo rm -rf /var/lib/sigint configs/agent.json
```

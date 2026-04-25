# Installation

Covers the central server and remote sensor nodes. Both share the same project layout; the only difference is which services you install and which hardware you plug in.

## Base setup (any node)

```sh
git clone <this-repo> ~/code/sigint
cd ~/code/sigint
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

After the initial setup, always activate the venv before running commands:

```sh
source venv/bin/activate
```

`sudo` runs the system Python and bypasses the venv. For commands that need root (server, BLE, WiFi), use the venv's Python directly:

```sh
sudo venv/bin/python3 src/sdr.py server configs/server.json
```

## System dependencies (Raspberry Pi / Debian / Ubuntu)

```sh
sudo apt-get install -y cmake libusb-1.0-0-dev ffmpeg python3-full python3-venv
```

### librtlsdr (V4-aware fork)

Required for RTL-SDR Blog V4 + `pyrtlsdr`. The Debian `librtlsdr0` package (2.0.x) is missing `rtlsdr_set_dithering` (pyrtlsdr import fails) and `rtlsdr_set_and_get_tuner_bandwidth` (rtl_sdr CLI fails). Build the V4-aware fork that ships those symbols (`librtlsdr.so.0.9git`):

```sh
git clone https://github.com/librtlsdr/librtlsdr.git /tmp/librtlsdr
cd /tmp/librtlsdr && mkdir build && cd build
cmake .. -DINSTALL_UDEV_RULES=ON -DDETACH_KERNEL_DRIVER=ON && make -j4
sudo make install && sudo ldconfig
```

Verify both required symbols are present:

```sh
nm -D /usr/local/lib/librtlsdr.so | grep -E 'set_dithering|set_and_get_tuner_bandwidth'
```

Both must show `T` (defined). If only one is present, the fork is too old — update.

### Blacklist the kernel DVB driver

The kernel auto-claims any RTL2832-based dongle as a DVB-T tuner, blocking userspace SDR access (you'll see `usb_claim_interface error -6` and `Resource busy`). Even the udev rules from the librtlsdr build don't always prevent this on Raspberry Pi OS. Force a blacklist:

```sh
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf
sudo rmmod rtl2832_sdr dvb_usb_rtl28xxu rtl2832 dvb_usb_v2 2>/dev/null
```

The `rmmod` only succeeds while no process is using the SDR. If it errors with "Module ... is in use", reboot or unplug+replug the SDR after writing the blacklist file.

### Configure systemd unit to find the V4 lib

The agent's spawned scanner subprocess (`sdr.py pmr` and friends) opens the RTL-SDR via `pyrtlsdr` → `librtlsdr.so`. The dynamic linker default order (`/lib/aarch64-linux-gnu` first) loads Debian's 2.0.1 lib which is missing V4 symbols. Pin `/usr/local/lib` for the agent:

```ini
# /etc/systemd/system/sigint-agent.service
[Service]
Environment="LD_LIBRARY_PATH=/usr/local/lib"
...
```

`pmr.py` automatically inherits this and forces it for the `rtl_sdr` subprocess too (which itself was built against the V4 fork lib).

### WiFi scanner

```sh
pip install scapy
sudo apt-get install -y iw
```

### BLE scanner

```sh
sudo apt-get install -y bluez bluez-hcidump
```

### ADS-B decoder (`readsb`)

The Debian `readsb` package is compiled without RTL-SDR support. You must build from source:

```sh
sudo apt-get install -y libzstd-dev libncurses-dev
git clone https://github.com/wiedehopf/readsb.git /tmp/readsb-src
cd /tmp/readsb-src && make -j4 RTLSDR=yes
sudo cp readsb /usr/bin/readsb
```

### AIS decoder (`rtl_ais`)

The native Python AIS decoder is educational only. Install `rtl_ais` for real use:

```sh
git clone https://github.com/dgiardini/rtl-ais.git /tmp/rtl-ais
cd /tmp/rtl-ais && make && sudo cp rtl_ais /usr/local/bin/
```

### ISM (`rtl_433`)

```sh
sudo apt-get install -y rtl-433
```

### Pager decoder (`multimon-ng`)

```sh
sudo apt-get install -y multimon-ng
```

### Transcription (optional)

Pick one backend:

- **OpenAI API** (recommended on Pi): set `OPENAI_API_KEY` in `.env`
- **Local Whisper** (~1 GB of PyTorch and model weights):

  ```sh
  pip install openai-whisper
  ```

Optional, for generating test audio:

```sh
pip install gtts
```

## macOS

```sh
brew install librtlsdr
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# optional:
pip install openai-whisper gtts
```

## Environment file

Copy `.env.example` to `.env` and fill in values (`OPENAI_API_KEY`, `WHISPER_LANGUAGES`, `TAK_HOST`/`TAK_PORT`):

```sh
cp .env.example .env
```

## Next steps

- Single-scanner usage → [scanners.md](scanners.md)
- Running a multi-capture server → [configuration.md](configuration.md)
- Installing as a systemd service → [service-setup.md](service-setup.md)
- Connecting remote sensor nodes → [c2.md](c2.md)

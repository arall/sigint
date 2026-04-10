# Installation

## Raspberry Pi 5 (Debian/Ubuntu)

```sh
# System dependencies
sudo apt-get install -y cmake libusb-1.0-0-dev ffmpeg python3-full python3-venv

# Install librtlsdr (keenerd fork — required for RTL-SDR Blog V4 + pyrtlsdr)
# The Debian package (librtlsdr0) is too old and missing rtlsdr_set_dithering.
git clone https://github.com/librtlsdr/librtlsdr.git /tmp/librtlsdr
cd /tmp/librtlsdr && mkdir build && cd build
cmake ..
make -j4
sudo make install
sudo ldconfig

# Create Python virtual environment
cd ~/code/sdr
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# WiFi scanner (probe request sniffing)
pip install scapy
sudo apt-get install -y iw

# BLE scanner (advertisement scanning)
sudo apt-get install -y bluez bluez-hcidump

# ADS-B decoder (must build from source — Debian package lacks RTL-SDR support)
sudo apt-get install -y libzstd-dev libncurses-dev
git clone https://github.com/wiedehopf/readsb.git /tmp/readsb-src
cd /tmp/readsb-src && make -j4 RTLSDR=yes && sudo cp readsb /usr/bin/readsb

# AIS decoder (optional, recommended over native decoder)
git clone https://github.com/dgiardini/rtl-ais.git /tmp/rtl-ais
cd /tmp/rtl-ais && make && sudo cp rtl_ais /usr/local/bin/

# Optional: speech-to-text transcription (OpenAI API recommended for Pi)
# Set OPENAI_API_KEY in .env, or install local whisper (~1GB PyTorch + model):
pip install openai-whisper

# Optional: generate test audio for transcription tests
pip install gtts
```

After setup, always activate the venv before running:
```sh
source venv/bin/activate
```

**Note:** `sudo` bypasses the venv and uses the system Python (which won't have the installed packages). For commands that need root (server, BLE, WiFi), use the venv Python directly:
```sh
sudo /path/to/sigint/venv/bin/python3 src/sdr.py server configs/server.json
```

## macOS

```sh
brew install librtlsdr
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Optional
pip install openai-whisper
pip install gtts
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```sh
cp .env.example .env
```

See `.env.example` for available options (Whisper API key, TAK Server host, etc.).

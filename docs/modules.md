# Modules

| Module | Command | Frequency | Description | Status |
|--------|---------|-----------|-------------|--------|
| **PMR446** | `sdr.py pmr` | 446 MHz | 8 analog channels, FM demod, audio recording, Whisper transcription. `--digital` adds dPMR/DMR energy detection | Tested |
| **FM Scanner** | `sdr.py fm <band>` | Configurable | Generic FM scanner with band profiles, auto window hopping | Tested |
| **FRS/GMRS** | `sdr.py fm frs` | 462-467 MHz | 22 FRS/GMRS channels | New |
| **Marine VHF** | `sdr.py fm marine` | 156-162 MHz | 27 maritime channels incl. CH16 distress | Tested |
| **MURS** | `sdr.py fm murs` | 151-154 MHz | 5 MURS channels | New |
| **2m Amateur** | `sdr.py fm 2m` | 144-148 MHz | VHF amateur FM simplex | New |
| **70cm Amateur** | `sdr.py fm 70cm` | 430-446 MHz | UHF amateur FM simplex | New |
| **CB Radio (EU)** | `sdr.py fm cb` | 26.965-27.405 MHz | EU FM CB, 40 channels | New |
| **Land Mobile** | `sdr.py fm landmobile` | 157-163 MHz | Rail, port ops, utilities, security (22 channels) | New |
| **TETRA** | `sdr.py fm tetra` | 380-400 MHz | EU police/fire/EMS activity detection (energy only) | New |
| **TETRA Private** | `sdr.py fm tetra-priv` | 410-430 MHz | Utilities/private security (energy only) | New |
| **P25** | `sdr.py fm p25` | VHF/UHF | US public safety activity detection (energy only) | New |
| **Keyfob** | `sdr.py keyfob` | 315/433.92 MHz | OOK car keyfob and garage door signal detection | Tested |
| **TPMS** | `sdr.py tpms` | 315/433.92 MHz | Tire pressure sensor decoding (sensor IDs) | Tested |
| **GSM** | `sdr.py gsm` | 935-960 MHz | GSM cell tower scanning, FCCH beacon detection | Tested |
| **LTE** | `sdr.py lte` | 700-2600 MHz | LTE uplink power density measurement | New |
| **ADS-B** | `sdr.py adsb` | 1090 MHz | Aircraft tracking (Mode S, position, altitude, velocity) | Tested |
| **AIS** | `sdr.py ais` | 161.975/162.025 MHz | Vessel tracking (MMSI, position, speed, name) | Tested |
| **POCSAG** | `sdr.py pocsag` | 152-929 MHz | Pager message decoding (numeric and alphanumeric) | Tested |
| **ISM** | `sdr.py ism` | 433/868/915 MHz | rtl_433 wrapper, 200+ protocols (weather, sensors, remotes) | New |
| **LoRa** | `sdr.py lora` | 868/915 MHz | LoRa/Meshtastic chirp detection, bandwidth and duty cycle | New |
| **ELRS/Crossfire** | via `sdr.py server` | 868/915 MHz | FPV drone control link detection (FHSS burst timing) | New |
| **Recorder** | `sdr.py record` | Any | Raw IQ recording to file | Tested |
| **Replay** | `sdr.py replay` | — | IQ file analysis (spectrogram, spectrum, I/Q plots) | Tested |
| **WiFi** | `sdr.py wifi` | 2.4 GHz | Probe request sniffing, persona fingerprinting, drone RemoteID (cross-transport dedup) | Tested |
| **Bluetooth** | `sdr.py bt` | 2.4 GHz | BLE advertisements, Apple Continuity, persona DB, drone RemoteID (cross-transport dedup) | Tested |
| **Wideband Scan** | `sdr.py scan` | Configurable | Energy detection scanner with optional AMC (`--classify`) | Tested |
| **Triangulate** | `sdr.py tri` | — | RSSI multilateration from multi-node .db logs | New |
| **Heatmap** | `sdr.py heatmap` | — | RF activity density heatmap (KML + PNG for ATAK) | New |
| **Correlate** | `sdr.py correlate` | — | Device co-occurrence analysis across signal types | New |
| **FM Voice Parser** | via `sdr.py server` | Configurable | Channelizer FM voice demod — PMR, 70cm, Marine, 2m, FRS from HackRF | Tested |
| **Central Server** | `sdr.py server` | All bands | All captures in parallel from JSON config, channelizer | New |
| **Web Dashboard** | `sdr.py web` | — | Standalone web UI for viewing detections from output directory. Also embeddable in server via `--web` flag | New |

## Server Configs

Two server configs are provided:

- **`configs/server.json`** — Default: keyfob/TPMS (HackRF 433 MHz), LoRa/ELRS (HackRF 868 MHz), ADS-B (RTL-SDR), BLE, WiFi. No voice recording.
- **`configs/server_voice.json`** — Voice-enabled: adds PMR446 and 70cm voice demod via HackRF channelizer, keeps ADS-B on RTL-SDR. PMR transcription enabled.

The FM voice parser runs through the channelizer, so HackRF can simultaneously demodulate voice channels (PMR, 70cm) and detect keyfobs/TPMS from the same 20 MHz capture — no extra RTL-SDR needed. Standalone scanners in server config support `"args"` for extra CLI flags (e.g., `["--transcribe", "--digital"]`).

### Web Dashboard

The web dashboard can run in two modes:

- **Standalone**: `python3 sdr.py web` — reads detection `.db` files from the output directory and serves a web UI on port 8080. Use `-p` for a custom port, `-d` for a custom output directory.
- **Embedded in server**: `sudo python3 sdr.py server --web` or `--web-port 3000` — starts the web UI alongside the server. Also configurable via `"web_port"` in the server JSON config.

Detections are grouped into real-world category tabs rather than a flat signal-type list:

- **Live** — per-category overview grid (total count, unique count, last-seen) + recent events feed
- **Map** — Leaflet canvas showing Aircraft (green) / Vessels (blue) / Drones (red) / Operators (orange) positions over OpenStreetMap. Four layer checkboxes, Fit All button, auto-fit on first load, persistent zoom/pan across tab switches. Leaflet 1.9.4 is vendored into `web/static/` — no CDN, no marker PNGs (uses `L.circleMarker` for pure-SVG markers)
- **Voice** — PMR446 / dPMR / 70cm / MarineVHF / 2m / FRS / FM_voice transmissions with inline transcript + audio playback
- **Drones** — RemoteID, RemoteID-operator, DroneCtrl, DroneVideo grouped by drone serial or frequency with GPS + operator position
- **Aircraft** — ADS-B flights by ICAO with callsign, altitude, speed, heading, position
- **Vessels** — AIS by MMSI with name, nav status, speed, course, position
- **Vehicles** — TPMS by sensor_id (pressure/temperature), keyfob by data_hex
- **Cellular** — GSM / LTE uplink activity per channel (wildcard-matched, so new LTE subtypes appear automatically)
- **Devices** — WiFi APs (physical-AP grouping across 2.4/5 GHz radios + associated clients), WiFi Clients, BLE. Both client tables show an RSSI column (real dBm from HCI / scapy, color-coded by proximity). The BLE persona loader surfaces AirTag and Find My accessory classification (including "AirTag (lost)" for separated mode) via `parsers/ble/apple_continuity.py`'s Continuity 0x12 profiling.
- **Other** — ISM, LoRa, POCSAG, and anything unclassified

Each category tab runs a SQL query against every `.db` file in the output directory with a configurable time window (default 6 h, capped at 7 days via `?window=<hours>`), and auto-refreshes every 3 s while visible. The multi-DB union is important because standalone scanner subprocesses (`sdr.py pmr`, `adsb`, `ais`, etc.) write to their own detection files separate from the main server file. A **Session** dropdown in the header lets you switch category tabs to a single historical `.db` for post-hoc browsing; Live / Log / Timeline / Devices always reflect the active session.

## Test Notes

### Test Setup

**Lab tests:** RTL-SDR Blog V4 (RX) and HackRF One (TX) placed a few centimeters apart, no cable/attenuator. HackRF transmitted at minimum power (VGA 0-20, amp off).

**Field tests:** RTL-SDR Blog V4 on Raspberry Pi 4, telescopic whip antenna on rooftop. AIS, ADS-B, Marine VHF, GSM, and POCSAG tested with real-world signals. TAK integration verified with live vessel and aircraft tracking on ATAK.

### Keyfob

Tested with HackRF TX (OOK bursts at 433.92 MHz) and ambient ISM signals. OOK detection, transmission state tracking, holdover expiry, detection logging, and pattern analysis confirmed working.

**Known limitations:**
- The 433 MHz ISM band is noisy. Ambient signals from nearby devices will trigger detections. Burst count filtering (2-500 valid bursts) helps but some false positives remain.
- Presence-based detection only (OOK burst analysis), not protocol-level decoding. Does not decode rolling codes or device IDs.

### PMR446

Tested with HackRF TX → RTL-SDR RX loopback. FM-modulated voice on CH1, captured via async streaming, FM demodulated, and transcribed with Whisper in English and Spanish.

Quality metrics (synthetic): 0.83 cross-correlation, zero spikes > 0.50, RMS within 3% of original. RF loopback: ~0.25 correlation (limited by consumer SDR phase noise).

**Known limitations:**
- RTL-SDR Blog V4 has ~16 ppm frequency offset, which may assign a transmission to an adjacent channel. Audio is still captured correctly.

### TPMS

Tested with HackRF TX (Manchester-encoded OOK at 433.92 MHz). Scanner detected the signal (31.7 dB SNR), extracted packets, and consistently decoded the same sensor ID across multiple transmissions.

**Known limitations:**
- Sensor ID decoding depends on signal quality. No checksum validation on decoded packets.
- Fixed to 433.92 MHz (EU) or 315 MHz (US). No auto-scanning between bands.

### GSM

Tested with real cell tower signals. Found 13 active GSM-900 channels, identified 4 FCCH beacons (cell towers). Strongest signal: ARFCN 42 at 943.4 MHz with 30+ dB SNR.

**Known limitations:**
- No cell tower ID decoding without gr-gsm. Reports ARFCN and signal strength only.
- Only GSM-900 and GSM-850 bands. Higher bands (DCS-1800, PCS-1900) exceed RTL-SDR reliable range.

### ADS-B

Tested with RTL-SDR Blog V4 + telescopic whip antenna. Using `readsb` (built from source with `RTLSDR=yes`), tracked 10+ aircraft simultaneously with full position, altitude, speed, and callsign decoding. Streamed to ATAK in real-time.

**Important:** The Debian `readsb` package does **not** include RTL-SDR support. You must build from source with `RTLSDR=yes`.

**Known limitations:**
- Native Python decoder requires very strong signals. Installing `readsb` is strongly recommended.

### Marine VHF

Tested with RTL-SDR Blog V4 + telescopic whip antenna near a commercial port. Captured voice transmissions on CH15 (port operations) with Whisper transcription.

**Known limitations:**
- Requires VHF antenna. Cellular/directional antennas (700+ MHz) cannot receive 156 MHz.

### AIS

Tested with RTL-SDR Blog V4 + telescopic whip antenna near a commercial port. Using `rtl_ais`, detected multiple vessels within 30 seconds with full MMSI, position, speed, course, and navigation status.

**Known limitations:**
- Native Python decoder is educational only. Install `rtl_ais` for real-world use.
- Requires line-of-sight to port/sea and a VHF antenna.

### POCSAG

Tested with multimon-ng decoder on EU frequencies (466.075 MHz). Pipeline works, but pager networks are largely decommissioned in most regions.

## Analysis & Intelligence

### Heatmap

Generates RF activity density heatmaps from detection logs. Output is a KML GroundOverlay with a PNG tile, loadable in ATAK or Google Earth.

```sh
python3 sdr.py heatmap output/server_*.db              # All signal types
python3 sdr.py heatmap output/*.db -s PMR446 -s keyfob  # Filter by type
python3 sdr.py heatmap output/*.db -r 0.0005            # Higher resolution grid
```

The central server also generates live heatmaps during capture (configurable via `heatmap_interval_s` in server config JSON, default 60s). Output KML is written to the output directory.

No dependencies beyond numpy — PNG is written with a self-contained encoder (no PIL/matplotlib).

### Device Correlation

Analyzes detection logs to find co-occurring devices across signal types. Uses time-binned co-occurrence with union-find clustering.

```sh
python3 sdr.py correlate output/server_*.db              # Default: 30s window, 50% threshold
python3 sdr.py corr output/*.db -w 60 -t 0.7             # 60s window, 70% threshold
python3 sdr.py corr output/*.db --json correlations.json  # Export to JSON
```

Example output: "WiFi persona X and BLE persona Y co-occur in 90% of time windows" → likely same person. "TPMS sensor A and keyfob B always appear together" → same vehicle.

The server runs correlation in real-time and exports `correlations.json` on shutdown.

### Movement Trails

Tracks device positions over time and sends CoT polyline shapes to ATAK, showing where a mobile emitter has been. Automatic in the central server for all signal types with GPS coordinates.

Requirements for trail generation: 3+ distinct positions with 10+ meters total movement. Per-device ring buffer of 100 positions with 1m dedup.

### Automatic Modulation Classification

Heuristic classifier in `dsp/amc.py` that identifies modulation type from IQ signal statistics. No ML model or GPU required.

```sh
python3 sdr.py scan --classify   # Adds modulation column to wideband scanner display
```

Categories: CW, AM, FM_narrow, FM_wide, OOK/ASK, FSK, PSK, QAM, OFDM, FHSS. Uses envelope statistics, instantaneous frequency variance, phase continuity, spectral occupancy, and constellation estimation.

### Wavelet Burst Detection

CWT-based transient signal detection in `dsp/wavelet.py`. Multi-scale Ricker wavelet analysis detects short bursts (keyfobs, FHSS hops) that FFT energy detection misses due to time-frequency spreading.

Two modes: `detect_bursts_cwt()` (multi-scale, best for unknown durations) and `detect_bursts_stft()` (faster, fixed resolution). Self-contained Ricker wavelet implementation — no pywt dependency.

### RF Fingerprinting

Extracts IQ-level hardware imperfections from burst turn-on transients to identify specific physical transmitters. Integrated into the keyfob parser — `rf_fingerprint` hash appears in detection metadata.

Features extracted: carrier frequency offset (CFO), I/Q amplitude/phase imbalance, carrier phase, rise time, power ramp shape, spectral asymmetry. Hashed for quick cross-session comparison.

**Known limitations:** Consumer SDRs (RTL-SDR, HackRF) have their own hardware imperfections that can mask transmitter signatures. Research-grade, not production reliable.

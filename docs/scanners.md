# Scanners

Every `sdr.py` subcommand, grouped by domain. Run from project root:

```sh
venv/bin/python3 src/sdr.py <subcommand> [options]
```

Add `--gps --gps-port /dev/ttyACM<N>` to any scanner to stamp detections with GPS coordinates. `sudo` is required for BLE and WiFi.

## Voice / FM

| Command | Frequency | Description |
|---|---|---|
| `pmr` | 446 MHz | PMR446 — 8 analog channels, FM demod, audio recording, Whisper transcription. `--digital` adds dPMR/DMR energy detection. |
| `fm <band>` | configurable | Generic FM scanner with band profiles, auto window hopping. `--list` shows all band profiles. |
| `fm frs` | 462–467 MHz | 22 FRS/GMRS channels |
| `fm marine` | 156–162 MHz | 27 maritime channels incl. CH16 distress |
| `fm murs` | 151–154 MHz | 5 MURS channels |
| `fm 2m` | 144–148 MHz | VHF amateur FM simplex |
| `fm 70cm` | 430–446 MHz | UHF amateur FM simplex |
| `fm cb` | 26.965–27.405 MHz | EU FM CB, 40 channels |
| `fm landmobile` | 157–163 MHz | Rail, port ops, utilities, security (22 channels) |
| `fm tetra` | 380–400 MHz | EU police/fire/EMS — energy detection only, no decode |
| `fm tetra-priv` | 410–430 MHz | Utilities/private security — energy detection only |
| `fm p25` | VHF/UHF | US public-safety activity — energy detection only |

Common FM flags:

```sh
sdr.py pmr --transcribe                   # speech-to-text via Whisper / OpenAI
sdr.py pmr --transcribe --language es     # force Spanish transcription
sdr.py pmr --digital                      # analog + dPMR/DMR energy detection
```

## Short-burst / OOK

| Command | Frequency | Description |
|---|---|---|
| `keyfob` | 315/433.92 MHz | OOK car keyfob + garage door signal detection. `-f 315` for US. |
| `tpms` | 315/433.92 MHz | Tire pressure sensor decoding — sensor IDs, Manchester OOK. |
| `ism` | 433/868/915 MHz | `rtl_433` wrapper, 200+ protocols (weather stations, smart home, remotes). `--hop` sweeps ISM bands. |

## Cellular

| Command | Frequency | Description |
|---|---|---|
| `gsm` | 935–960 MHz (+ 850 MHz band) | GSM cell tower scanning, FCCH beacon detection. Reports ARFCN + SNR. |
| `lte` | 700–2600 MHz | LTE uplink power density measurement above baseline. |

## Transport layer

| Command | Frequency | Description |
|---|---|---|
| `adsb` | 1090 MHz | Aircraft tracking (Mode S: ICAO, callsign, altitude, speed). Requires `readsb` built with `RTLSDR=yes`. |
| `ais` | 161.975 / 162.025 MHz | Vessel tracking (MMSI, position, speed, course). Uses `rtl_ais`; native Python decoder is educational only. |

## Paging / mesh

| Command | Frequency | Description |
|---|---|---|
| `pocsag` | 152–929 MHz | Pager messages (numeric + alphanumeric). Uses `multimon-ng`. Most networks decommissioned. |
| `lora` | 868/915 MHz | LoRa / Meshtastic chirp detection, bandwidth and duty cycle. Regional defaults via `--region us|eu|au`. |
| `mesh` | 868 MHz (EU) | Passive decode of Meshtastic mesh traffic (position, telemetry, node info, text). Requires a Meshtastic radio on USB. |

## 2.4 / 5 GHz

| Command | Frequency | Description |
|---|---|---|
| `wifi` | 2.4 + 5 GHz | Probe-request sniffing, beacon capture, drone RemoteID. Monitor-mode adapter + sudo required. `--band 2.4|5|all`. |
| `bt` | 2.4 GHz | BLE advertisements, Apple Continuity, persona DB, drone RemoteID. HCI adapter + sudo. `--adapter hci1`. |
| `dv` | 5.8 / 2.4 GHz | Drone video downlinks (DJI O4, OcuSync). HackRF wideband. |
| `fpv` | 1.2 / 5.8 GHz | FPV analog video frame demodulation (PAL/NTSC). HackRF. |

## Wideband / recording

| Command | Description |
|---|---|
| `scan` | Wideband energy detection. `--classify` adds automatic modulation classification (FM, OOK, FSK, PSK, QAM, OFDM, FHSS, CW). |
| `record` | Capture raw IQ samples to disk. |
| `replay <file>` | Re-run detection pipelines against a recorded IQ file; spectrogram/spectrum/IQ plots. |

## Central server

| Command | Description |
|---|---|
| `server <config.json>` | Multi-capture orchestrator — runs many captures + parsers in parallel from a JSON config. See [configuration.md](configuration.md). Add `--web` for the dashboard. |
| `web` | Standalone dashboard (reads detection DBs from output dir). `-p 3000` for custom port. |
| `agent` | Meshtastic C2 agent runtime. See [c2.md](c2.md). |

## Analysis / post-hoc

| Command | Description |
|---|---|
| `tri a.db b.db c.db` | RSSI multilateration from multi-node session DBs. See [triangulation.md](triangulation.md). |
| `heatmap output/*.db` | RF activity density heatmap (KML + PNG for ATAK). Filter with `-s <signal_type>`. |
| `corr output/*.db` | Cross-signal-type device co-occurrence analysis. Export with `--json`. |

## Known quirks and limitations

- **RTL-SDR Blog V4** has ~16 ppm frequency offset — may assign a transmission to an adjacent channel (audio still correct).
- **HackRF** has ~17 ppm offset and ~10 dB less sensitivity than RTL-SDR; better for wideband, worse for weak narrowband.
- **`readsb` from Debian apt** doesn't include RTL-SDR support. Build from source (see [install.md](install.md)).
- **Keyfob** is presence-based (OOK burst analysis), not protocol-level decoding. 433 MHz ISM is noisy — some false positives remain.
- **TPMS** has no checksum validation on decoded packets. Fixed to 433.92 MHz (EU) or 315 MHz (US), no auto-scan between.
- **GSM** reports ARFCN + signal strength only, no cell ID decoding (no gr-gsm integration). GSM-900 and GSM-850 only.
- **TETRA / P25** are activity-only detectors (no decode).
- **POCSAG** pipeline works, but most pager networks are decommissioned.
- **RF loopback** audio on consumer SDRs hits ~0.25 cross-correlation ceiling because of phase noise.
- **Path-loss triangulation** is uncalibrated by default; expect room-level accuracy at best. See [triangulation.md](triangulation.md) for calibration notes.

## Bench test setup

**Lab:** RTL-SDR Blog V4 (RX) and HackRF One (TX) a few centimetres apart, no cable or attenuator, HackRF at minimum power (VGA 0–20, amp off).

**Field:** RTL-SDR Blog V4 on a Raspberry Pi 4, telescopic whip antenna on a rooftop. AIS, ADS-B, Marine VHF, GSM and POCSAG verified against real-world signals; TAK integration verified with live vessels and aircraft.

## Running the test suite

```sh
bash tests/run_tests.sh               # software-only, ~60 s on a Pi 5
bash tests/run_tests.sh --hw          # include HackRF + RTL-SDR loopback tests
python3 tests/run_tests.py --no-whisper  # skip transcription
```

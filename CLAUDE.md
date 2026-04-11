# SDR Signal Scanner

## Project Overview

SDR-based signal detection and triangulation system for ATAK. Detects radio emissions (PMR, keyfobs, TPMS, GSM, ADS-B, AIS, pagers) from distributed SDR receivers, logs detections with GPS coordinates and signal metadata to a per-session SQLite database, enabling RSSI-based triangulation of emitters.

Target hardware: RTL-SDR Blog V4 (R828D/RTL2832U). WiFi scanner uses an Alfa USB adapter in monitor mode. HackRF One used for TX in hardware tests.

## Project Structure

```
src/
  sdr.py                  # CLI entry point (argparse, dispatches to scanners)
  capture/                # Hardware abstraction — each source owns one device
    base.py               # BaseCaptureSource ABC (add_parser, _emit, start/stop)
    ble.py                # BLE HCI capture (hcitool + hcidump → ad frames)
    wifi.py               # WiFi monitor mode capture (scapy sniff → 802.11 frames)
    rtlsdr_iq.py          # RTL-SDR async IQ capture (reusable at any frequency)
    rtlsdr_sweep.py       # RTL-SDR sweep capture (tunes across a band, for GSM/LTE)
    hackrf_iq.py          # HackRF wideband IQ capture (20 MHz BW via hackrf_transfer)
    channelizer.py        # Extracts narrowband channels from wideband IQ for per-parser delivery
  dsp/                    # Pure signal analysis functions (no hardware, no state)
    ook.py                # OOK/FSK detection, protocol fingerprinting, device classification
    tpms.py               # TPMS OOK/Manchester detection and decoding
    gsm.py                # GSM TDMA uplink burst detection
    lte.py                # LTE uplink power density measurement
    ais.py                # AIS NMEA protocol decoding, Vessel dataclass
    elrs.py               # ELRS/Crossfire FHSS burst timing analysis
    amc.py                # Automatic modulation classification (heuristic, no ML)
    wavelet.py            # CWT/STFT burst detection for low-SNR transients
    rf_fingerprint.py     # IQ-level transmitter hardware fingerprinting
    drone_video.py        # Drone video link OFDM detection and classification
  parsers/                # Signal decoders — consume raw frames, produce SignalDetections
    base.py               # BaseParser ABC (handle_frame, shutdown)
    ble/
      ad_parser.py        # Shared BLE AD structure parser
      apple_continuity.py # All-BLE persona tracking + Apple Continuity decoding
      remote_id.py        # Open Drone ID (ASTM F3411) BLE parser
    wifi/
      probe_request.py    # WiFi probe request parsing + persona fingerprinting
      beacon.py           # WiFi AP beacon parser (BSSID, SSID, crypto, vendor)
      remote_id.py        # Open Drone ID WiFi NaN/beacon parser
    drone/
      video_link.py       # Drone video downlink OFDM detection (DJI O4, OcuSync)
    fm/
      voice.py            # FM voice demod parser for channelizer (multi-band, records audio)
    ook/
      keyfob.py           # OOK/FSK keyfob transmission state machine
      tpms.py             # TPMS OOK/Manchester decoder (auto-decimates for shared capture)
    lora/
      energy.py           # LoRa chirp energy detection per channel
      elrs.py             # ELRS/Crossfire FPV drone control link detection
    cellular/
      gsm.py              # GSM uplink burst parser (per-channel tracking)
      lte.py              # LTE uplink power density parser (baseline + activity)
    marine/
      ais.py              # AIS NMEA sentence parser (vessel database)
  utils/
    loader.py             # macOS RTL-SDR library path patching (must import before rtlsdr)
    db.py                 # SQLite helper: WAL mode, schema, insert/iter helpers
    logger.py             # SignalDetection dataclass + SignalLogger (SQLite writer)
    oui.py                # MAC address OUI manufacturer lookup (IEEE database)
    persona_db.py         # Persistent persona fingerprint database (JSON)
    ap_db.py              # Persistent WiFi AP database keyed by BSSID (JSON)
    transcriber.py        # Whisper speech-to-text for recorded audio
    transcript_store.py   # Atomic JSON sidecar (audio_file -> transcript)
    async_transcriber.py  # Background Whisper worker (non-blocking pipeline)
    triangulate.py        # RSSI multilateration from multi-node .db logs
    heatmap.py            # RF activity density heatmap (KML/PNG for ATAK)
    correlator.py         # Device co-occurrence analysis across signal types
  scanners/               # Thin orchestrators — wire capture source + parsers
    pmr.py                # PMR446 walkie-talkie scanner (446 MHz, FM demod, async streaming)
    fm.py                 # Generic FM scanner with band profiles (FRS, Marine, MURS, 2m, 70cm)
    keyfob.py             # Car keyfob scanner (315/433 MHz) — orchestrator + DSP re-exports
    tpms.py               # Tire pressure sensor scanner (315/433 MHz) — orchestrator + DSP re-exports
    gsm.py                # GSM uplink orchestrator: SweepCapture + GSMBurstParser
    lte.py                # LTE uplink orchestrator: SweepCapture + LTEPowerParser(s)
    adsb.py               # Aircraft ADS-B tracker (1090 MHz, Mode S decoding)
    ais.py                # AIS orchestrator: rtl_ais subprocess + AISParser
    pocsag.py             # Pager message decoder (optional multimon-ng)
    bluetooth.py          # BLE orchestrator: BLECapture + AppleContinuity + RemoteID parsers
    wifi.py               # WiFi orchestrator: WiFiCapture + ProbeRequest + RemoteID parsers
    ism.py                # ISM band scanner (rtl_433 wrapper, 433/868/915 MHz, 200+ protocols)
    lora.py               # LoRa orchestrator: RTLSDRCapture + LoRaEnergyParser
    drone_video.py        # Drone video link scanner: HackRF + DroneVideoLinkParser
    server.py             # Central server: all captures + parsers in parallel from JSON config
    wideband.py           # Wideband energy detection scanner
    recorder.py           # Raw IQ recording and replay
  web/                    # Dashboard UI (consumer layer; reads from .db + JSON sidecars)
    __init__.py           # Public: run_web_server, start_web_server_background
    categories.py         # Signal-type → real-world category map
    loaders.py            # Device + category loaders (pure functions, dict in / list-of-dict out)
    tailer.py             # DBTailer: polls newest .db, builds live dashboard state
    server.py             # WebHandler HTTP routing + whitelisted static file serving
    static/               # Real index.html / style.css / app.js (browser-debuggable)
tests/
  data/                   # Shared test audio (voice WAVs, gTTS MP3s)
  run_tests.sh            # Test runner (--hw for hardware tests)
  sw/                     # Software-only tests (no hardware needed)
    test_pmr_demod.py     # Async streaming pipeline, demod quality, gap detection
    test_pmr_quality.py   # Audio quality regression (correlation, spikes, RMS)
    test_transcribe.py    # Whisper transcription (EN/ES/CA, auto-detect, hallucination filter)
    test_fm_voice_parser.py # FM voice parser (band profiles, detection, demod, recording)
    test_false_detections.py # Zero false detections from noise/leakage/short bursts
    test_voice_detection.py  # Detection accuracy (thresholds, holdover, multi-channel)
    test_multiband_demod.py  # Demod quality per band (PMR, 70cm, Marine, 2m, FRS)
    test_thresholds.py       # Threshold consistency regression across all audio paths
  hw/                     # Hardware tests (require HackRF and/or RTL-SDR)
    test_e2e_voice.py     # Full TX→RX→demod→transcribe on any band (HackRF+RTL-SDR)
    test_scanner_e2e.py   # PMRScanner class E2E with HackRF TX
    test_pmr_audio.py     # Layered pipeline diagnostic (real radio or HackRF TX)
    tx_pmr_loopback.py    # Full HackRF TX → RTL-SDR RX loopback with correlation
    tx_pmr.py             # PMR FM tone transmission
    tx_pmr_voice.py       # PMR voice transmission via TTS
    tx_keyfob.py          # Keyfob OOK transmission
    tx_keyfob_pt2262.py   # PT2262 protocol transmission
    tx_keyfob_keeloq.py   # KeeLoq rolling code transmission
    tx_tpms.py            # TPMS Manchester OOK transmission
configs/
  server_voice.json       # Multi-HackRF + standalone RTL-SDR PMR voice config
tools/
  hackrf_survey.py        # Wideband spectrum survey via hackrf_sweep
  tx_wav_pmr.py           # Transmit a WAV as FM voice on PMR446 (HackRF, for testing)
output/                   # Per-session SQLite detection logs (.db) + audio + JSON sidecars
```

## Commands

Run from `src/` directory:

```sh
# Scanners
python3 sdr.py pmr                           # PMR446 channels (analog)
python3 sdr.py pmr --digital                 # PMR446 analog + dPMR/DMR digital
python3 sdr.py pmr --transcribe              # PMR446 with speech-to-text
python3 sdr.py pmr --transcribe --language es # Force Spanish transcription
python3 sdr.py pmr --transcribe --whisper-model small  # Higher accuracy model
python3 sdr.py fm frs                        # FRS/GMRS channels
python3 sdr.py fm marine                     # Marine VHF channels
python3 sdr.py fm landmobile                 # Land mobile (rail/port/utilities)
python3 sdr.py fm murs                       # MURS channels
python3 sdr.py fm 2m                         # 2m amateur FM
python3 sdr.py fm 70cm                       # 70cm amateur FM
python3 sdr.py fm cb                         # EU FM CB radio (27 MHz)
python3 sdr.py fm tetra                      # TETRA police/EMS energy detection
python3 sdr.py fm tetra-priv                 # TETRA private/utilities energy detection
python3 sdr.py fm p25                        # P25 US public safety energy detection
python3 sdr.py fm --list                     # List all band profiles
python3 sdr.py fm frs --transcribe           # FRS with speech-to-text
python3 sdr.py fm marine --dwell 10          # Marine VHF, 10s dwell per window
python3 sdr.py keyfob                        # Keyfobs at 433.92 MHz
python3 sdr.py keyfob -f 315                 # Keyfobs at 315 MHz (US)
python3 sdr.py tpms                          # Tire pressure sensors
python3 sdr.py gsm                           # Phone activity (GSM uplink)
python3 sdr.py lte                           # Phone presence (LTE uplink power)
python3 sdr.py adsb                          # Aircraft tracking
python3 sdr.py ais                           # Vessel tracking
python3 sdr.py pocsag                        # Pager messages
python3 sdr.py bt                            # BLE advertisement scanning (default: hci1)
python3 sdr.py bt --adapter hci0             # Use different BT adapter
python3 sdr.py bt --min-rssi -70             # Only nearby devices
python3 sdr.py wifi                          # WiFi probe sniffing (2.4+5 GHz, default: wlan1)
python3 sdr.py wifi --band 2.4              # 2.4 GHz only (channels 1,6,11)
python3 sdr.py wifi --band 5                # 5 GHz only (non-DFS channels)
python3 sdr.py wifi --band all              # 2.4+5 GHz including DFS channels
python3 sdr.py wifi --channels 1,6,11,36,149-165  # Custom channel list
python3 sdr.py wifi --min-rssi -70          # Only nearby devices
python3 sdr.py wifi -i wlan2                # Use different interface
python3 sdr.py ism                            # ISM band scanner via rtl_433 (433 MHz)
python3 sdr.py ism -f 868                    # ISM 868 MHz (EU)
python3 sdr.py ism --hop                     # Hop between 433/868/915 MHz
python3 sdr.py lora                          # LoRa/Meshtastic detection (868 MHz EU)
python3 sdr.py lora --region us              # LoRa 915 MHz (US)
python3 sdr.py drone-video                   # Drone video link detection (2.4 GHz, HackRF)
python3 sdr.py dv --band 5.8                 # Drone video on 5.8 GHz band
python3 sdr.py dv --amp                      # With RF amplifier for longer range
python3 sdr.py scan                          # Wideband energy scanner
python3 sdr.py record                        # Record IQ samples
python3 sdr.py replay <file>                 # Analyze recordings
sudo python3 sdr.py server                   # Central server (all captures, needs sudo for BLE/WiFi)
sudo python3 sdr.py server configs/server.json  # Server with custom config
python3 sdr.py triangulate a.db b.db c.db    # Triangulate from multi-node .db logs
python3 sdr.py tri a.db b.db --use-snr       # Use SNR (different gains across nodes)
python3 sdr.py tri a.db b.db -t 10           # 10s correlation window
python3 sdr.py tri a.db b.db --tak           # Send results to ATAK
python3 sdr.py scan --classify               # Wideband scan with modulation classification
python3 sdr.py heatmap output/*.db           # Generate RF heatmap KML from detection logs
python3 sdr.py heatmap output/*.db -s PMR446 # Heatmap for specific signal type
python3 sdr.py correlate output/*.db         # Find co-occurring devices
python3 sdr.py corr output/*.db -w 30 -t 0.5 # Correlate with 30s window, 50% threshold

# Tests (from project root)
./tests/run_tests.sh                         # Full SW test suite (no hardware)
./tests/run_tests.sh --hw                    # Include hardware tests (HackRF + RTL-SDR)
python3 tests/sw/test_pmr_demod.py           # Demod pipeline (no hardware)
python3 tests/sw/test_pmr_quality.py         # Audio quality regression (no hardware)
python3 tests/sw/test_pmr_quality.py --rf    # Include RF loopback (needs HackRF + RTL-SDR)
python3 tests/sw/test_transcribe.py          # Transcription tests (no hardware)
python3 tests/sw/test_fm_voice_parser.py     # FM voice parser tests (no hardware)
python3 tests/sw/test_false_detections.py    # False detection prevention (no hardware)
python3 tests/sw/test_voice_detection.py     # Voice detection accuracy (no hardware)
python3 tests/sw/test_multiband_demod.py     # Multi-band demod quality (no hardware)
python3 tests/sw/test_thresholds.py          # Threshold consistency (no hardware)
python3 tests/hw/test_e2e_voice.py           # E2E voice TX→RX→transcribe (HackRF + RTL-SDR)
python3 tests/hw/test_e2e_voice.py --band 70cm --channels CALL  # Other bands
python3 tests/hw/test_scanner_e2e.py         # Scanner class E2E (HackRF + RTL-SDR)
python3 tests/hw/test_pmr_audio.py           # Layered pipeline diagnostic (real radio)
```

## Dependencies

- Python venv: `python3 -m venv venv && source venv/bin/activate`
- Python packages: numpy, pyrtlsdr, scipy, matplotlib (see requirements.txt; requirements-full.txt includes optional deps)
- System (Raspberry Pi): librtlsdr from [librtlsdr/librtlsdr](https://github.com/librtlsdr/librtlsdr) (keenerd fork, built from source — Debian package is too old for V4), cmake, libusb-1.0-0-dev, ffmpeg
- System (macOS): `brew install librtlsdr`
- BLE scanner: bluez, bluez-hcidump (system packages), Bluetooth adapter with BLE support
- WiFi scanner: scapy (`pip install scapy`), WiFi adapter with monitor mode support (e.g., Alfa), iw
- Optional: openai-whisper (local transcription — requires ffmpeg and ~1GB PyTorch), gTTS (test audio generation)
- Optional external tools: dump1090 (ADS-B), rtl_ais (AIS), multimon-ng (POCSAG), rtl_433 (ISM)
- Configuration: `.env` file for `OPENAI_API_KEY` (OpenAI Whisper API, preferred over local), `WHISPER_LANGUAGES` (e.g. "es,en"), `TAK_HOST`/`TAK_PORT` (see `.env.example`)

## Code Patterns

### Capture / Parser Architecture

The codebase separates hardware capture from signal decoding. This lets one hardware device feed multiple parsers simultaneously (e.g. BLE adapter detects both Apple devices and drones).

- **Capture sources** (`capture/`) own one hardware device and emit raw frames to registered callbacks via `add_parser(callback)`. Subclass `BaseCaptureSource` — implement `start()` (blocking) and `stop()`.
- **Parsers** (`parsers/`) consume raw frames via `handle_frame(frame)` and produce `SignalDetection` objects. Subclass `BaseParser`. Override `shutdown()` to persist state.
- **Scanners** (`scanners/`) are thin orchestrators that wire a capture source to one or more parsers, handle signal setup/teardown, and render the display.
- Frame types vary by capture source: BLE emits `(addr, addr_type, ad_bytes, rssi)` tuples, WiFi emits `(packet, channel)` tuples, RTL-SDR emits numpy IQ arrays.
- To add a new protocol on an existing frequency: write a parser, plug it into the scanner's capture source. No new hardware capture code needed.
- Pure signal analysis functions (OOK/FSK detection, protocol fingerprinting, TPMS decoding) live in `dsp/` — imported by both parsers and scanners. `scanners/keyfob.py` and `scanners/tpms.py` re-export them for backward compatibility.

### General Patterns

- Each scanner has a `scan()` method (PMR and FM use `run()`)
- The generic FM scanner (`scanners/fm.py`) imports DSP functions from `scanners/pmr.py` — do not move or rename `calculate_power_spectrum`, `get_channel_power`, `extract_and_demodulate_buffers`, or `save_audio`
- FM scanner auto-groups channels into 2.0 MHz windows and hops between them when a band is wider than RTL-SDR bandwidth
- Band profiles with `"record_audio": False` (TETRA, P25) run in energy-detection-only mode — RSSI logging works but audio recording is disabled
- `utils/loader.py` must be imported before `from rtlsdr import RtlSdr` on macOS
- Use `SignalDetection.create()` factory (not the raw constructor) to build detections — it handles timestamp and SNR calculation
- Metadata field on SignalDetection must be a JSON string, not a dict
- Scanners that depend on external tools (dump1090, rtl_ais, multimon-ng) have fallback native Python implementations
- Per-transmission state tracking with holdover prevents duplicate detections from signal fluctuations
- SQLite logging includes GPS coords, device ID, SNR — all needed for triangulation

### PMR Scanner Audio Pipeline

The PMR scanner uses a multi-stage audio pipeline for recording voice transmissions:

1. **Async streaming** — `read_samples_async()` in a daemon thread feeds a `queue.Queue`, ensuring 100% IQ capture (no gaps from `sleep()` between reads)
2. **Per-chunk FM demodulation** — each IQ chunk is frequency-shifted, resampled via `scipy.signal.resample_poly` with rational up/down factors (GCD-reduced for exact 16 kHz output at any input sample rate), then FM-demodulated with a polar discriminator
3. **Phase continuity** — the last decimated IQ sample from each chunk is carried to the next for smooth FM demod at boundaries
4. **De-click filter** — median filter + spike interpolation removes crackling from USB buffer boundary artifacts
5. **Async transcription** — Whisper runs in a background worker thread (`utils/async_transcriber.py`). The detection is logged to SQLite *immediately* when TX ends (no waiting on Whisper). When the transcript is ready, it's written to `output/transcripts.json` keyed by audio filename. The web tailer polls that sidecar and back-fills already-displayed rows. Net effect: real-time detection visibility, transcripts arrive 1–10s later. Hallucination filter in `utils/transcriber.py` suppresses common Whisper false outputs on noisy audio (e.g., "Subtítulos realizados por...")
6. **False detection prevention** — `DETECTION_SNR_DB = 15.0` rejects adjacent-channel leakage from strong signals. `MIN_TX_DURATION = 0.5s` (sample-based, not wall-clock) filters sub-second noise spikes that holdover would otherwise let through.
7. **PPM correction** — `--ppm <int>` flag corrects RTL-SDR crystal error so transmissions land in the correct PMR channel (cheap RTL-SDRs run ~30 ppm offset, which equals 12.5 kHz at 446 MHz — exactly one channel of error).

### FM Voice Parser (Channelizer)

The FM voice parser (`parsers/fm/voice.py`) enables voice demodulation and recording through the HackRF channelizer, without needing a dedicated RTL-SDR per band.

- **Band profiles** — predefined channel maps (pmr446, pmr446_digital, 70cm_eu, marine, 2m, frs) with per-band channel_bw and fm_deviation. Add new bands by extending `BAND_PROFILES` dict.
- **Dual power computation** — `_channel_power_linear()` averages FFT power in linear domain for robust detection (especially with small channelizer blocks), while `calculate_power_spectrum` from `scanners/pmr.py` provides dB-scale values for logging, consistent with the standalone PMR and FM scanners.
- **Per-channel state machine** — independent holdover tracking per sub-channel within the band. Multiple simultaneous transmissions on different channels are tracked separately.
- **Buffer coalescing** — `_finalize_tx()` merges adjacent small channelizer blocks into large contiguous chunks before demodulation, producing full-length audio clips instead of sub-second fragments.
- **Reuses PMR pipeline** — `extract_and_demodulate_buffers()` and `save_audio()` from `scanners/pmr.py` for proven FM demodulation with phase continuity and de-clicking.
- **Server config** — registered as `"fm_voice"` in server parser factory. Channel config supports `"band"`, `"transcribe"`, `"whisper_model"`, `"language"` fields.
- **Detection thresholds** — `DETECTION_SNR_DB = 15.0`, `MIN_TX_DURATION = 0.5s` (signal-present samples only, not wall-clock), `MAX_TX_DURATION = 30.0s` force-finalizes runaway recordings. All three audio paths (PMRScanner, FMScanner, FMVoiceParser) track signal-present sample counts separately from holdover buffering for accurate duration filtering. Consistent holdover (2.0s).
- **Shutdown finalization** — PMRScanner finalizes active transmissions (demod + save audio) in its `finally` block, so recordings are preserved regardless of how the scanner is stopped (Ctrl+C, external close, or error). The main loop exits cleanly when the reader thread dies (e.g., SDR closed externally).
- **HackRF sensitivity** — HackRF has lower sensitivity than RTL-SDR for narrowband FM, but the channelizer now coalesces output blocks (~100ms) for stable noise floor estimation and reliable voice detection. Gain is configurable per-capture in server JSON config (lna_gain, vga_gain, amp_enable).

### Server Standalone Subprocess

Standalone scanners in server config (`"type": "standalone"`) run as child `sdr.py` processes. The server passes through `--gps`, `--tak`, `--output` flags automatically. Scanner-specific args go in the `"args"` list:
```json
{"type": "standalone", "scanner_type": "pmr", "args": ["--digital", "--transcribe", "--ppm", "28"]}
{"type": "standalone", "scanner_type": "fm", "args": ["marine", "--transcribe"]}
```

The server **drains the subprocess's stdout/stderr in background threads** and mirrors output to `output/standalone_<name>.log`. Without these drainers the subprocess would block on `print()` once its 64 KB pipe buffer fills (the PMR scanner's dashboard prints frequently), freezing the SDR pipeline.

### Capture Health & Web Dashboard

The server orchestrator (`scanners/server.py`) tracks per-capture status (`pending` / `running` / `degraded` / `failed`) and publishes it to `output/server_info.json` alongside coverage info (frequency range and `continuous` / `hopping` / `passive` mode). Status transitions are printed to the terminal with colored badges and surfaced on the web dashboard's Config tab, which auto-refreshes every 3 seconds.

- **Standalone subprocess failures** (e.g. RTL-SDR claimed by DVB driver) mark the capture `failed` with the last stderr line
- **HackRF queue drops** mark the HackRF capture `degraded` (the channelizer can't keep up with the sample rate)
- **Persona DB** (`personas.json`, `personas_bt.json`), **AP DB** (`aps.json`), and **device correlation** (`correlations.json`) are exported every 30s during runtime, not just at shutdown — configurable via `persona_flush_interval_s` and `correlator_export_interval_s` in the server config
- The Web UI uses `DISPLAY_NAMES` from `scanners/server.py` to render parser/scanner identifiers as friendly labels (`apple_continuity` → "BLE Devices", `pmr` → "PMR446", `beacon` → "WiFi APs", etc.) so the user-facing UI never shows raw Python module names

### SQLite Detection Storage

Detection logging is a per-session SQLite file (`<type>_YYYYMMDD_HHMMSS.db`) in the output directory. `utils/logger.py` owns the single writer connection and serializes inserts under a mutex; `utils/db.py` bootstraps the schema, sets WAL mode and `synchronous=NORMAL`, and exposes `insert_detection` / `iter_detections` / `row_to_dict` / `max_rowid` helpers. Indexes on `(signal_type, ts_epoch)`, `ts_epoch`, `device_id`, and `(signal_type, device_id)` cover the dashboard, triangulation, heatmap, and correlator query patterns.

- **Threading gotcha**: `sqlite3.connect()` must be called with `check_same_thread=False`. The logger is opened on the main thread but parsers call `logger.log()` from many worker threads (scapy sniff, hcidump reader, RTL-SDR async callback, HackRF channelizer). Without this flag every insert raises `ProgrammingError` deep inside the capture loops which silently swallow it — the symptom is detections visible in stdout (`[NEW AP]` prints etc.) but zero rows on disk. The logger's `_lock` already prevents concurrent use of the connection, so the flag is safe.
- **Web tailer**: `web/tailer.py` `DBTailer` polls the newest `.db` file by rowid in read-only URI mode, picking up new inserts via `iter_detections(since_rowid=...)`. Each poll opens a fresh connection to avoid holding a long-lived reader across WAL checkpoints.
- **External consumers**: if something wants CSV, shell out to `sqlite3 out.db -csv -header "SELECT * FROM detections"` — the codebase no longer writes CSV itself.
- **One file per node**: triangulation still composes across nodes by shipping the `.db` file per sensor, exactly as it did with CSVs — no federation / replication.

### Devices Tab (web dashboard)

The former "Personas" tab is now "Devices" with three sub-tabs: **WiFi APs**, **WiFi Clients**, **BLE** (`web/loaders.py` `_load_wifi_aps` / `_load_wifi_clients` / `_load_ble_devices`). Important semantics:

- **WiFi Clients are NOT APs**: the old flat tab labeled client probe personas with the SSIDs they were *probing for*, so a phone searching for "NSA Hotspot #14" looked like an AP broadcasting that SSID. The client rows are now labeled by `manufacturer + fingerprint` with a small `probing: "SSID"` badge.
- **WiFi APs** come from the persisted `aps.json` (`utils/ap_db.py`) keyed by BSSID. The loader groups 2.4/5 GHz radios of the same physical AP using a conservative heuristic — same non-empty SSID AND matching first 5 MAC octets — so the typical vendor pattern of incrementing only the last octet between radios collapses into one row. Over-splitting is harmless; over-grouping is what you should avoid.
- **AP client tracking**: every non-beacon Dot11 frame referencing a known BSSID contributes a client MAC to that AP's `clients` set. The dashboard shows the count with a hover tooltip listing MACs, or an em-dash with a "no clients seen yet" tooltip when the channel hop hasn't dwelled long enough to see data frames.
- **BLE labels**: `_load_ble_devices` prefers the persisted `apple_device` (e.g. "AirPods Pro 2", "Apple Watch", "MacBook") over the generic manufacturer. The Apple Continuity parser (`parsers/ble/apple_continuity.py`) persists this via `PersonaDB.update_persona(apple_device=...)`, and decodes Proximity Pairing model IDs from an `APPLE_PROXIMITY_MODELS` table (AirPods 1–4, AirPods Pro 1/2, AirPods Max, Beats line). Note: Proximity Pairing model IDs are **big-endian**, not little-endian — there was a latent bug in the old decoder that byte-swapped them.
- **Row keys**: row identity uses `persona_key` (`dev_sig:ssid-set`) not `dev_sig`, because the DB can store multiple personas with the same `dev_sig` under different SSID sets. The per-subtab `_devExpanded` is a `Set` so multiple rows can be expanded simultaneously.
- **Tooltips**: badges and capture-status pills use a central `TAG_TIPS` dictionary + `tipFor()` helper so adding a new badge only needs a dictionary entry, not per-call wiring. Tag-prefix matches (e.g. `lna `, `probing: `) handle dynamic values.

### HackRF Queue & Latency

The HackRF capture source (`capture/hackrf_iq.py`) uses a small (4-block) sample queue with **drop-oldest** semantics. When the channelizer can't keep up, the *oldest* queued block is evicted to make room for the newest — this guarantees the parser pipeline always processes fresh samples, preventing the multi-second lag that drop-newest semantics would cause. End-to-end real-time latency is bounded to ~130 ms regardless of channelizer throughput. If drops happen at all, the server marks the capture `degraded` so the operator knows to lower the sample rate.

### BLE Scanner + Drone Detection

The BLE scanner (`sdr.py bt`) runs two parsers on one BLE adapter simultaneously. BLE listening is fully **passive** — it scans all 3 primary advertising channels (37/38/39 = 2402/2426/2480 MHz) via `hcitool lescan` + `hcidump --raw` and decodes every advertisement frame. Every discoverable device in range ends up in the capture stream: phones, watches, fitness trackers, headphones, IoT sensors, etc.

1. **`apple_continuity` parser** — despite the name, this is the **all-BLE persona tracker**. For *every* BLE adv frame it tracks persona fingerprinting via manufacturer ID, AD structure hash, advertised name, MAC rotation, and RSSI. When the manufacturer ID happens to be Apple (76), it *additionally* decodes the Apple Continuity protocol (Nearby Info device type, Handoff hash for MAC de-anonymization). Persistent persona DB (`output/personas_bt.json`). UI displays this as "BLE Devices" via the `DISPLAY_NAMES` map in `scanners/server.py`.
2. **RemoteID parser** — Open Drone ID (ASTM F3411) detection via BLE service UUID `0xFFFA` with application code `0x0D` validation. Decodes drone serial, GPS position, altitude, speed, operator location, and UA type. Logs as `signal_type="RemoteID"`.

The Bluetooth SIG company ID lookup table in `parsers/ble/apple_continuity.py` (`BT_COMPANIES` dict) uses **decimal** values, not hex — easy to confuse since IDs like 0x0087 (Garmin = 135) and 0x0407 (Fitbit = 1031) look like they could be parsed as their hex digits.

No flag needed — drones are detected automatically alongside phones, watches, and IoT devices.

### WiFi Scanner + AP / Drone Detection

The WiFi scanner (`sdr.py wifi`) runs three parsers on one WiFi adapter simultaneously:

1. **Probe request parser** — `Dot11ProbeReq` frames (sent by client devices searching for known networks). Persona fingerprinting via 802.11 IE signature, SSID set, sequence number continuity. Persistent persona DB (`output/personas.json`).
2. **Beacon parser** (`parsers/wifi/beacon.py`) — `Dot11Beacon` frames (broadcast by access points). Extracts BSSID, SSID (or "hidden"), channel, crypto suite (WPA2/WPA3/OWE/WEP/open via RSN IE parsing in `_parse_rsn`), beacon interval, and vendor OUI manufacturer. Logs as `signal_type="WiFi-AP"`. Per-BSSID dedup window (60s) to avoid log flooding. Additionally mines every non-beacon Dot11 frame in `_observe_client()` for (BSSID, client) associations via ToDS/FromDS address inspection, so each AP accumulates its set of associated client MACs. Persists to `output/aps.json` via `ApDB` on the server's 30s flush loop.
3. **RemoteID parser** — Open Drone ID detection from WiFi Beacon/NaN (Neighbor Awareness Networking) frames with ASTM F3411 vendor-specific IE (OUI `FA:0B:BC`, vendor type `0x0D`). Logs as `signal_type="RemoteID"`.

Both parsers share the same ODID message decoders (`parsers/ble/remote_id.py` provides the protocol parsing, reused by the WiFi parser). A shared `DroneRegistry` deduplicates across BLE and WiFi — same drone seen on both transports only logs once per dedup window.

The WiFi ODID format (ASTM F3411-22a) differs from BLE: beacons prepend a message counter byte and include a `msg_size` byte in the message pack header (`[counter] [0xFn] [msg_size=25] [count] [25-byte msgs…]`). The WiFi parser handles both formats, trying WiFi first then falling back to BLE/plain. DJI drones (tested: Matrice 4T) only broadcast WiFi RemoteID when motors are armed — not on power-on alone.

The scanner supports **dual-band hopping** across 2.4 GHz and 5 GHz on a single adapter. Default channels: 1, 6, 11 (2.4 GHz) + 36, 40, 44, 48, 149, 153, 157, 161, 165 (5 GHz non-DFS). Channel hopping uses `iw set freq` with explicit MHz values to disambiguate bands. The `--band` flag provides quick presets (`2.4`, `5`, `all`), or `--channels` accepts custom lists (e.g. `1,6,11,36,149-165`). DFS channels (52–144) are excluded by default but available via `--band all`. 6 GHz channels are supported by the capture layer for adapters that report them.

The scanner requires `sudo` for monitor mode. It handles monitor mode setup/teardown automatically and catches SIGINT/SIGTERM for clean shutdown.

### RemoteID TAK Integration

Both BLE and WiFi RemoteID parsers log two detection types for ATAK map display:

1. **`RemoteID`** — drone position from ODID Location message. CoT type `a-n-A-C-F` (airborne). Callsign shows serial number, UA type, and altitude. Only placed on map when drone has GPS lock.
2. **`RemoteID-operator`** — operator/controller position from ODID System message. CoT type `a-f-G-E-S` (friendly ground). Callsign shows EU operator registration ID. Requires operator GPS in controller.

Both markers use 30-second stale time and update every dedup window (5s). The `channel` field carries the drone serial ID for stable TAK UIDs across sessions.

### Triangulation

Post-hoc RSSI multilateration in `utils/triangulate.py`. No SDR hardware needed — works on `.db` files.

1. **Correlation** — groups detections across nodes by match key (device ID, channel, or frequency) within a time window. Strategy auto-detected from `signal_type`
2. **RSSI → Distance** — log-distance path loss model with per-signal-type defaults for exponent `n` and `rssi_ref`. Use `--use-snr` when nodes have different gain settings
3. **Multilateration** — 2-node: weighted midpoint. 3+ node: `scipy.optimize.minimize` (Nelder-Mead) with grid-search fallback if scipy unavailable
4. **Output** — stdout table, optional CoT to ATAK via `--tak`
- Wired into `sdr.py` as `triangulate`/`tri` subcommand, dispatched after `_start_tak` but before SDR pre-flight (no hardware needed)
- ADS-B/AIS signal types are skipped (they self-report position)
- Node spacing should be at least as far as expected emitter distance; 3 nodes in a triangle recommended

### ATAK Heatmaps

RF activity density heatmap overlay for ATAK maps in `utils/heatmap.py`. Generates KML GroundOverlay with PNG tile from detection logs.

- **CLI**: `python3 sdr.py heatmap output/*.db` — generates `output/heatmap.kml` + PNG
- **Live**: `LiveHeatmap` class in server orchestrator — periodic KML export during capture (default: every 60s, configurable via `heatmap_interval_s` in server config)
- **Filters**: `--signal-type` flag to filter by signal type, `--resolution` for grid cell size (degrees)
- Log-scale color gradient (blue→red), transparent background, pure PNG writer (no PIL/matplotlib dependency)

### Movement Trails

Device movement trail visualization for ATAK in `utils/tak.py` (`TrailTracker` class). Tracks per-device position history and emits CoT polyline shapes.

- Hooked into server `_on_detection` — automatic for all signal types with GPS coordinates
- Minimum 3 positions and 10m total movement before trail is generated
- Per-device ring buffer (100 positions max) with 1m dedup
- Supports: BLE personas, WiFi personas, TPMS sensors, RemoteID drones, ADS-B aircraft

### Device Correlation

Cross-signal-type device co-occurrence analysis in `utils/correlator.py`. Finds devices that consistently appear together.

- **CLI**: `python3 sdr.py correlate output/*.db --window 30 --threshold 0.5`
- **Live**: `DeviceCorrelator` in server orchestrator — accumulates during capture, exports `correlations.json` on shutdown
- Union-find clustering: groups co-occurring devices into clusters (e.g., "WiFi phone + BLE watch + TPMS car")
- Time-binned co-occurrence matrix with configurable window and threshold
- Cross-transport flag identifies correlations across different signal types

### Automatic Modulation Classification (AMC)

Heuristic modulation classifier in `dsp/amc.py`. Classifies unknown signals from IQ statistics — no ML model or GPU needed.

- Categories: CW, AM, FM_narrow, FM_wide, OOK/ASK, FSK, PSK, QAM, OFDM, FHSS
- Feature extraction: envelope statistics (std/mean, kurtosis, bimodality), instantaneous frequency variance, phase continuity, spectral occupancy, constellation estimation
- Integrated into wideband scanner: `python3 sdr.py scan --classify` adds modulation column to display and detection metadata
- Spectral SNR estimation (peak vs median FFT power) — works for both continuous and bursty signals

### Wavelet Burst Detection

CWT-based transient signal detection in `dsp/wavelet.py`. Detects short bursts buried in noise that FFT energy detection misses.

- `detect_bursts_cwt()` — multi-scale Ricker wavelet analysis, best for unknown burst durations
- `detect_bursts_stft()` — Short-Time FFT alternative, faster but fixed resolution
- Self-contained Ricker wavelet + CWT implementation (no pywt/scipy.signal.cwt dependency)
- Returns burst start time, duration, SNR, frequency offset, bandwidth
- Automatic overlap deduplication across scales

### RF Fingerprinting

IQ-level physical transmitter identification in `dsp/rf_fingerprint.py`. Extracts hardware imperfections from burst turn-on transients.

- Features: carrier frequency offset (CFO), I/Q amplitude/phase imbalance, carrier phase, rise time, power ramp shape, spectral asymmetry
- `fingerprint_hash()` — quantized hash for quick comparison across sessions
- `compare_fingerprints()` — weighted similarity score (0-1) with per-feature normalization
- Integrated into keyfob parser: `rf_fingerprint` hash in detection metadata when burst is long enough
- Research-grade: consumer SDR hardware imperfections may mask transmitter signatures

### Drone Video Link Detection

Wideband OFDM video downlink detection in `dsp/drone_video.py`. Uses HackRF 20 MHz capture to detect drone video transmissions (DJI O4, OcuSync, etc.) on 2.4/5.8 GHz ISM bands.

- **CLI**: `python3 sdr.py drone-video` (alias `dv`), `--band 2.4|5.8`, `--amp` for range
- Spectrogram-based OFDM burst detection: spectral flatness, occupied bandwidth, duty cycle
- Distinguishes drone OFDM from WiFi by: non-standard bandwidth, non-WiFi channel centers, high duty cycle (continuous video vs bursty WiFi)
- Classification confidence score (0-1) with multi-feature weighting
- Cannot decrypt or decode video — detection and characterization only
- Requires HackRF One (RTL-SDR cannot tune to 2.4/5.8 GHz)

## Known Limitations

- BLE scanner requires `sudo` and `hcitool`/`hcidump` (bluez); adapter may need reset between runs (`hciconfig hciX down/up`)
- macOS-only library paths in loader.py (Homebrew Intel + Apple Silicon)
- RTL-SDR frequency offset (~16 ppm) may assign transmissions to adjacent PMR channel
- HackRF One has ~17 ppm crystal error and lower sensitivity than RTL-SDR for narrowband FM. The channelizer coalesces output blocks to compensate. For best results, increase lna_gain/vga_gain in server config or enable amp.
- HackRF `hackrf_transfer -C <ppm>` corrects RX frequency but doesn't help sensitivity. Server config supports `"ppm"` field per HackRF.
- RF loopback audio quality limited by consumer SDR phase noise (~0.25 cross-correlation)

# SDR Signal Scanner

## Project Overview

SDR-based signal detection and triangulation system for ATAK. Detects radio emissions (PMR, keyfobs, TPMS, GSM, ADS-B, AIS, pagers, BLE, WiFi, drones, LoRa, ISM) from distributed SDR receivers, logs detections with GPS coordinates and signal metadata to per-session SQLite databases, enabling RSSI-based triangulation of emitters.

Target hardware: RTL-SDR Blog V4 (R828D/RTL2832U), Alfa USB WiFi adapter (monitor mode), HackRF One (TX/wideband).

## Project Structure

```
src/
  sdr.py                  # CLI entry point (argparse, dispatches to scanners)
  capture/                # Hardware abstraction — each source owns one device
  dsp/                    # Pure signal analysis functions (no hardware, no state)
  parsers/                # Signal decoders — consume raw frames, produce SignalDetections
  utils/                  # DB, logging, transcription, triangulation, correlation
  scanners/               # Thin orchestrators — wire capture source + parsers
  web/                    # Dashboard UI (reads from .db + JSON sidecars)
    static/               # index.html / style.css / app.js / leaflet.*
tests/
  sw/                     # Software-only tests (no hardware needed)
  hw/                     # Hardware tests (require HackRF and/or RTL-SDR)
configs/                  # Server JSON configs
output/                   # Per-session SQLite logs (.db) + audio + JSON sidecars
```

## Commands

Run from `src/` directory:

```sh
python3 sdr.py pmr                           # PMR446 (analog)
python3 sdr.py pmr --digital                 # PMR446 analog + dPMR/DMR digital
python3 sdr.py pmr --transcribe              # PMR446 with speech-to-text
python3 sdr.py pmr --transcribe --language es # Force Spanish transcription
python3 sdr.py dmr [-f 145.525] [--transcribe]  # Direct-mode DMR voice (dsd-fme)
python3 sdr.py fm frs|marine|murs|2m|70cm|cb|tetra|p25|landmobile  # FM band profiles
python3 sdr.py fm --list                     # List all band profiles
python3 sdr.py keyfob [-f 315]               # Keyfobs (433.92 MHz default, 315 MHz US)
python3 sdr.py tpms                          # Tire pressure sensors
python3 sdr.py gsm / lte                     # Cellular uplink detection
python3 sdr.py adsb / ais / pocsag           # Aircraft / vessels / pagers
python3 sdr.py bt [--adapter hci0]           # BLE scanning (default: hci1)
python3 sdr.py wifi [--band 2.4|5|all]       # WiFi probe + AP + drone detection
python3 sdr.py ism [-f 868] [--hop]          # ISM band via rtl_433
python3 sdr.py lora [--region us]            # LoRa/Meshtastic detection
python3 sdr.py drone-video [--band 5.8]      # Drone video link (HackRF)
python3 sdr.py scan [--classify]             # Wideband energy scanner
python3 sdr.py record / replay <file>        # IQ recording/replay
sudo python3 sdr.py server [config.json]     # Central server (all captures)
python3 sdr.py triangulate a.db b.db c.db    # RSSI multilateration
python3 sdr.py heatmap output/*.db           # RF heatmap KML for ATAK
python3 sdr.py correlate output/*.db         # Device co-occurrence analysis

# Tests (from project root)
./tests/run_tests.sh                         # Full SW test suite
./tests/run_tests.sh --hw                    # Include hardware tests
```

## Dependencies

- Python venv: `python3 -m venv venv && source venv/bin/activate`
- Python packages: numpy, pyrtlsdr, scipy, matplotlib (see requirements.txt)
- System (Raspberry Pi): librtlsdr from source (keenerd fork), cmake, libusb-1.0-0-dev, ffmpeg
- System (macOS): `brew install librtlsdr`
- BLE: bluez, bluez-hcidump; WiFi: scapy, iw, monitor-mode adapter
- Optional: openai-whisper, gTTS, dump1090, rtl_ais, multimon-ng, rtl_433, dsd-fme (DMR voice — build from lwvmobile/dsd-fme + lwvmobile/mbelib `ambe_tones` branch)
- Config: `.env` for `OPENAI_API_KEY`, `WHISPER_LANGUAGES`, `TAK_HOST`/`TAK_PORT`

## Architecture

### Capture / Parser / Scanner

- **Capture sources** (`capture/`) own one hardware device, emit raw frames via `add_parser(callback)`
- **Parsers** (`parsers/`) consume frames via `handle_frame(frame)`, produce `SignalDetection` objects
- **Scanners** (`scanners/`) are thin orchestrators wiring capture to parsers
- To add a new protocol on an existing frequency: write a parser, plug into existing capture. No new hardware code needed.

### Critical Patterns & Gotchas

- Use `SignalDetection.create()` factory (not raw constructor) — handles timestamp and SNR
- Metadata field on SignalDetection must be a **JSON string**, not a dict
- `utils/loader.py` must be imported before `from rtlsdr import RtlSdr` on macOS
- `scanners/fm.py` imports `calculate_power_spectrum`, `get_channel_power`, `extract_and_demodulate_buffers`, `save_audio` from `scanners/pmr.py` — do not move or rename these
- Each scanner has `scan()` method; PMR and FM use `run()`
- Band profiles with `"record_audio": False` (TETRA, P25) run energy-detection-only mode

### SQLite Storage

Single unified file at `output/detections.db` shared across the server, all scanner subprocesses, and the agent ingest path. WAL mode, `synchronous=NORMAL`, `busy_timeout=10000` so concurrent writers serialise on the file lock instead of erroring out.

- **Schema**: `sessions(id, started_at, ended_at, label, kind, pid)` + `detections(id, session_id, agent_id, ts, signal_type, freq, power, ...)`. Each scanner run / server run / agent ingest opens a `sessions` row at start (via `_db.open_session`) and stamps `ended_at` at stop.
- **Indexes**: `(session_id)`, `(agent_id, ts_epoch)`, `(signal_type, ts_epoch)`, `ts_epoch`, `device_id`, `(signal_type, device_id)`.
- **Forwarded rows** (Meshtastic agent ingest) are tagged with `agent_id = "<aid>"`; server-local rows have `agent_id IS NULL`. Use this column (not `device_id`) to attribute observations to a physical node.
- **Threading**: `sqlite3.connect()` MUST use `check_same_thread=False` — logger opened on main thread, parsers call from worker threads.
- **Root-owned output**: server runs as sudo, web UI as normal user. `db.connect(readonly=True)` falls back to `?mode=ro&immutable=1` on `OperationalError`.
- `calibration.db` and `devices.db` are **separate** files in the same output dir — they aren't session-scoped detection logs and shouldn't be mixed into the unified store.

### SQL-first Dashboard

Every dashboard endpoint runs one query against `output/detections.db` via `web/fetch.py` — no in-memory state, no multi-file fan-out. DBTailer (`web/tailer.py`) is just a watcher + 2s cache refresher for the Live tab.

- `_UNIQUES_SQL` in `fetch.py` must stay in sync with `tailer._extract_uid`.
- Category "Other" uses negation predicate; "Cellular" uses wildcard LIKE for LTE subtypes.
- Session switcher: `?session=<id>` is an integer row id from the `sessions` table (`web/sessions.session_exists` validates).
- Global age filter (`#global-age-limit` in the header): the dashboard sends `&window=<hours>` to category + map endpoints, server clauses `ts_epoch >= now - window`. Suppressed when a historical session is selected (the wall-clock window doesn't make sense against frozen data).

### Web Dashboard

Column sorting: add `class="sortable"` + `data-tbl="<tbody-id>"` + `data-key="<row-field>"` to `<th>` — no renderer changes needed. Devices tab has bespoke sort (`_devSortValue` with `-999` sentinel for null RSSI).

Map: Leaflet 1.9.4 vendored (no CDN). `L.circleMarker` (no PNG images). Lazy-init on first tab activation, `invalidateSize` after 100ms.

`DISPLAY_NAMES` in `scanners/server.py` maps internal names to UI labels.

### FM Voice Pipeline

Three audio paths (PMRScanner, FMScanner, FMVoiceParser) share thresholds: `DETECTION_SNR_DB = 15.0`, `MIN_TX_DURATION = 0.5s` (signal-present samples, not wall-clock), holdover 2.0s. FMVoiceParser adds `MAX_TX_DURATION = 30.0s`.

Async transcription: detection logged to SQLite immediately; transcript arrives 1-10s later in the `transcripts` table of the unified DB (legacy `output/transcripts.json` is still read on startup for backwards compatibility). Hallucination filter in `utils/transcriber.py`.

### DMR Scanner

Direct-mode (simplex) DMR voice via `dsd-fme` subprocess (lwvmobile fork — `dsdccx` chokes on direct-mode FEC even with good sync, see `memory/project_dmr_capture.md`). `scanners/dmr.py` spawns `dsd-fme -fs -P -7 <wav_dir> -i rtl:<dev>:<freq>M:<gain>:<ppm>:<bw>[:<sq>] -o null` (the `-o null` is mandatory — without it dsd-fme tries PulseAudio and fails under sudo). Default freq is 145.525 MHz, gain 25 (sweet spot — g40 saturates the R828D, g10 is dominated by 8-bit ADC quantization noise).

- WAVs are written **directly under `output/audio/`** (not a `dmr/` subdir) so the flat web `/audio/<basename>.wav` handler and the basename-keyed `transcripts` table both work without remapping.
- A poll-based watcher (1s interval) picks up newly-finalised per-call WAVs and ignores `TEMP_*.wav` files (those are still being written). The watcher must require a regex match on the dsd-fme filename pattern — PMR/FM scanners write to the same dir.
- The dsd-fme per-call filename has a variable middle: older docs say `..._{sys}_{gi}_TGT_<tgt>_SRC_<src>.wav`, current builds emit `..._DMR_CC_<n>_GROUP_TGT_<tgt>_SRC_<src>.wav`. The regex (`_FINAL_RE`) only anchors on date/time/random head and TGT/SRC tail; everything between is captured as `info`.
- No SNR gating — dsd-fme only writes a WAV if it actually decoded voice frames, so the existence of the file is the detection. Placeholder `power_db = -30, noise_db = -90` keeps the SignalLogger happy.
- `LD_LIBRARY_PATH=/usr/local/lib` must be set on the **parent Python**, not just the dsd-fme subprocess — `scanners/__init__.py` imports `pmr` which imports `pyrtlsdr` at import time, and pyrtlsdr needs the V4 fork's `librtlsdr`.
- Server config: a `dmr` capture conflicts with `pmr` on the same RTL-SDR. The example `dmr_2m` entry in `configs/server.json` ships with `disabled: true`; toggle the `disabled` flag on `pmr` and `dmr_2m` to swap which one owns device 0 (server.py honours the flag and skips the entry entirely).

### Server

- Standalone scanners run as child `sdr.py` processes; stdout/stderr drained in background threads (else 64KB pipe buffer blocks the SDR pipeline)
- Each subprocess opens its own connection to `output/detections.db` and registers a `sessions` row — multi-writer concurrency is handled by SQLite WAL + busy_timeout, no app-level coordination needed.
- Per-capture status: `pending`/`running`/`degraded`/`failed` in `output/server_info.json`
- HackRF: 4-block queue with drop-oldest (latency ~130ms). Drops mark capture `degraded`.
- Persona/AP DB flushed every 30s. Correlations computed on demand from SQL (no sidecar).
- AgentManager opens an `agent_ingest` session and tags every forwarded detection with `agent_id = <aid>`. `close()` stamps `ended_at` on shutdown.

### Agent GPS

The agent's `configs/agent.json` has `gps_source` (`"meshtastic"` | `"static"` | `null`) which decides where its `gps.json` sidecar values come from. **Two gotchas that have eaten hours:**

1. **`gps_source: "static"` makes Meshtastic invisible.** With `gps_source: "static"`, the agent reads `static_position: {lat, lon}` from the same config and never queries the radio. Debugging meshtastic GPS settings is then a dead end. If `gps.json` shows wrong/coarse positions, **first** check `gps_source` and `static_position` on each node — only then look at the radio.

2. **Channel `module_settings.position_precision` defaults to 18 (~91 m grid) for privacy.** With `gps_source: "meshtastic"`, the agent reads `iface.getMyNodeInfo()['position']`, and that value goes through the **channel-level** position-precision filter. At default 18 bits, lat/lon round to ~4 decimals before reaching us. To get full precision (1e-7 deg, ~1 cm — the protobuf limit), set the primary channel to 32: `meshtastic --port <dev> --ch-set module_settings.position_precision 32 --ch-index 0`. Each node has its own setting; do all of them. Note: this controls precision in mesh broadcasts *and* in local readback through the API — both are clamped by the same setting.

For nodes that don't have a working GPS lock yet, set `position.fixed_position true` plus `--setlat/--setlon` so the radio reports a known fixed coordinate; the agent's meshtastic path will then return that coordinate as if it were a live fix.

### BLE Scanner

`apple_continuity` parser is the **all-BLE persona tracker** (not just Apple). `BT_COMPANIES` dict uses **decimal** values, not hex. RemoteID parser detects drones via service UUID `0xFFFA`. AirTag classification: `{0x12}` only = Find My accessory; Proximity Pairing model IDs are **big-endian**.

### WiFi Scanner

Three parsers: probe requests, beacons, RemoteID. Dual-band hopping (2.4+5 GHz). AP client tracking via ToDS/FromDS inspection. WiFi ODID format differs from BLE (counter byte + msg_size). DJI drones only broadcast RemoteID when motors armed.

### Devices Tab

- WiFi Clients labeled by `manufacturer + fingerprint` with `probing: "SSID"` badge (NOT APs)
- WiFi APs grouped by same SSID + first 5 MAC octets (prefer over-splitting to over-grouping)
- RSSI from `power_db` (not `snr_db`). Colour: >=55 green, >=70 yellow, >=85 orange, else red
- Row key: `persona_key` (`dev_sig:ssid-set`), not `dev_sig`

## Known Limitations

- BLE requires `sudo` + bluez; adapter may need `hciconfig hciX down/up` between runs
- macOS-only library paths in loader.py
- RTL-SDR ~16 ppm offset may shift PMR channel assignment
- HackRF ~17 ppm, lower narrowband FM sensitivity than RTL-SDR
- RF loopback audio quality ~0.25 cross-correlation (SDR phase noise)

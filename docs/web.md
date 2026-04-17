# Web dashboard

Live situational-awareness UI on top of the detection SQLite files. Runs in two modes:

- **Standalone:** `python3 sdr.py web` — serves whatever detection `.db` files are in the output directory. Good for browsing prior sessions without starting capture.
- **Embedded in the server:** `sdr.py server configs/server.json --web` — starts the UI alongside the server. Both modes default to port **8080**.

Flags:

```sh
sdr.py web                              # port 8080, output from DEFAULT_OUTPUT
sdr.py web -p 3000                      # custom port
sdr.py web -d /path/to/output           # custom output directory
sdr.py server cfg.json --web-port 3000  # embedded, custom port
```

You can also set `"web_port": 3000` in the server JSON config.

## Tabs

- **Live** — per-category overview grid (count, unique count, last-seen) plus a recent events feed.
- **Map** — Leaflet 1.9.4 (vendored; no CDN, no PNG markers — uses `L.circleMarker`). Layer toggles for Aircraft (green), Vessels (blue), Drones (red), Operators (orange). Fit All button, auto-fit on first load, zoom/pan persists across tab switches.
- **Voice** — PMR446, dPMR, 70cm, Marine VHF, 2m, FRS, FM_voice. Inline transcript + audio playback.
- **Drones** — RemoteID, RemoteID-operator, DroneCtrl, DroneVideo grouped by drone serial or frequency, with GPS and operator position.
- **Aircraft** — ADS-B flights grouped by ICAO with callsign, altitude, speed, heading, position.
- **Vessels** — AIS by MMSI with name, nav status, speed, course, position.
- **Vehicles** — TPMS (pressure/temperature by sensor_id) + keyfob (by data_hex).
- **Cellular** — GSM and LTE uplink activity per channel. Wildcard-matched — new LTE subtypes appear automatically.
- **Devices** — three sub-tabs:
  - **WiFi APs** — physical-AP grouping across 2.4/5 GHz radios + associated clients.
  - **WiFi Clients** — probe-request personas, color-coded RSSI.
  - **BLE** — persona tracker (not just Apple). Surfaces AirTag / Find My classification, including "AirTag (lost)" for separated-mode trackers (via Continuity 0x12 profiling in `parsers/ble/apple_continuity.py`).
- **Agents** — approved + pending Meshtastic C2 agents. Approve, Start/Stop a scanner, Status, Config. See [c2.md](c2.md).
- **Other** — ISM, LoRa, POCSAG, anything unclassified.

Every category tab accepts an optional `?window=<hours>` (default 6 h, capped at 7 days) and auto-refreshes every 3 s while visible.

## Session dropdown

A header dropdown lets you scope category tabs (Voice / Drones / Aircraft / Vessels / Vehicles / Cellular / Other) to a single historical `.db` for post-hoc browsing. Live / Log / Timeline / Devices always reflect the active session.

## HTTP API

Every endpoint returns JSON except the audio and FPV streams.

| Method / path | Description |
|---|---|
| `GET /` | Dashboard (index.html) |
| `GET /api/state` | Snapshot of current live state (category counts, last-seen) |
| `GET /api/activity` | Per-minute histogram |
| `GET /api/detections` | Windowed recent detection list |
| `GET /api/config` | `server_info.json` passthrough |
| `GET /api/devices` | WiFi APs + clients + BLE, grouped |
| `GET /api/sessions` | Historical `.db` session list |
| `GET /api/correlations` | Multi-device co-occurrence clusters (cached 60 s) |
| `GET /api/cat/<name>` | Category detections (`voice`, `drones`, `aircraft`, `vessels`, `vehicles`, `cellular`, `devices`, `other`) |
| `GET /api/agents` | Agent state (approved / pending / info) |
| `POST /api/agents/approve` | `{"agent_id": "..."}` |
| `POST /api/agents/cmd` | `{"agent_id": "...", "verb": "START|STOP|STATUS|SET", "args": [...]}` |
| `POST /api/agents/cfg` | `{"agent_id": "...", "key": "...", "value": "..."}` |
| `GET /api/fpv/frame` | Latest FPV analog-video JPEG frame |
| `GET /api/fpv/stream` | Live FPV JPEG stream (multipart) |
| `GET /audio/<filename>` | WAV playback for voice transmissions |

## SQL-first design

No in-memory deque, no per-type counter in the read path. Every dashboard endpoint runs direct SQL against every `.db` in the output directory — including standalone scanner subprocesses that write to their own files. The tailer keeps a 2-second cache of Live-tab state so SSE broadcasts don't block on the ~200 ms aggregation query; everything else is computed on demand.

A consequence: to add a new category, add the SQL query in `web/fetch.py` and the tab-renderer in `web/static/app.js`. No in-memory bookkeeping to wire up.

## Column sorting

Add `class="sortable"`, `data-tbl="<tbody-id>"`, and `data-key="<row-field>"` to any `<th>`. No renderer changes needed. The Devices tab has a bespoke sort (`_devSortValue`, with a `-999` sentinel for null RSSI).

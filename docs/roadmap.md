# Roadmap

Living document. Moves faster than the rest of the docs — expect entries to shift category as they land or rot.

## ✅ Done

Core:

- Single-node scanners for PMR446 (+ dPMR/DMR energy), FM bands (FRS/GMRS, Marine VHF, MURS, 2m, 70cm, CB, LandMobile, TETRA, P25), keyfob, TPMS, GSM, LTE, ADS-B, AIS, POCSAG, ISM (rtl_433), LoRa, ELRS/Crossfire, wideband scan with AMC, BLE adv, WiFi probe + beacon + RemoteID, drone video, FPV analog
- Central `sdr.py server` with JSON config, HackRF channelizer, multi-capture orchestration, standalone subprocess adapter
- Per-session SQLite logging (WAL, indexed), SQL-first web dashboard
- `install-nexmon.sh` — build + flash nexmon-patched `brcmfmac` firmware so the Raspberry Pi's built-in WiFi can do monitor mode and frame injection without an external adapter

Analysis:

- RSSI multilateration (`sdr.py tri`, 2+ nodes, log-distance path loss)
- Opportunistic RSSI calibration (`sdr.py calibrate`): per-node, per-band offsets solved from emitters whose position and TX power are known — surveyed WiFi APs, FM stations, cell towers via `configs/calibration_emitters.json`; Huber regression on residuals stored in `output/calibration.db`; applied transparently in `sdr.py tri`. ADS-B RSSI captured from dump1090/readsb `aircraft.json` so the ADS-B extractor activates with free sky-view samples. AIS RSSI captured via a parallel sampler on a second RTL-SDR (`sdr.py ais --rssi-device-index 1`) — rtl_ais holds the primary SDR and has no NMEA RSSI field, so the second dongle runs a background PSD on AIS1/AIS2 and the parser attaches max(AIS1, AIS2) power to each decoded vessel detection. Scanner degrades gracefully to power_db=0 when no secondary SDR is configured.
- Map-tab uncertainty rings use calibrated RSSI when available: `web/fetch.py` applies per-node offsets server-side and ships `power_db_cal` in `/api/map/sources`; `app.js` picks the RSSI-based log-distance model when a calibrated reading exists and falls back to SNR otherwise. Popup shows "calibrated" when applied.
- Real-time multi-node triangulation (`/api/map/triangulations`): `web/triangulate_live.py` pulls the last 5 min of detections from every session `.db`, splits by capturing node (server vs each agent in agents_*.db), applies calibration, and reuses `utils/triangulate.py`'s correlator + multilaterator per signal_type. Map tab renders each fix as a crosshair with a dashed error-radius ring; popup shows contributing nodes, per-observation power, and calibration coverage. Sibling "Triangulations" panel lists recent fixes newest-first with click-to-zoom.
- Cross-node witness correlation (`/api/correlations/witnesses`, Correlations tab): emitters seen by 2+ nodes in the window, same match strategy as `utils.triangulate` (channel / frequency / metadata_id per signal type). Complements the Triangulations panel — no position requirement, ADS-B / AIS included — so coverage gaps ("N02 never hears anything that server + N01 both pick up") are visible at a glance.
- Session replay over C2 (`sdr.py replay-c2 <db>`): reads a recorded detection `.db` and pumps DET messages over the mesh link as if from a named agent. Useful for exercising the server ingest path without live RF, and as a deterministic benchmark for calibration / triangulation accuracy (same input → same server-side artifacts). `--rate` caps DET throughput, `--require-position` / `--require-power` filter for triangulation / calibration benchmarks, `--dry-run` prints wire frames without opening a link.
- Node drag-to-reposition: every source marker on the Map tab is draggable. Drag-end POSTs `/api/map/sources/position`, which persists to `output/position_overrides.json` (atomic write, its own file so the C2 orchestrator's `server_info.json` rewrite can't clobber it) and mirrors the new lat/lon into the calibration DB's `cal_meta` so expected-RSSI math picks it up. `_serve_map_sources` returns `position_source = "manual" | "config" | "detection"` so the UI can show which positions are pinned (black outline + 📌). `DELETE /api/map/sources/position?id=<sid>` clears the override and its cal_meta mirror; the source popup carries an "Unpin" link on manually positioned markers.
- Heatmap KML generation (live + post-hoc via `sdr.py heatmap`)
- Movement trails (CoT polylines to ATAK)
- Device correlation (cross-signal-type co-occurrence + union-find clustering, cached, 6-hour window)
- Automatic modulation classification (`dsp/amc.py`, heuristic FM/OOK/FSK/PSK/QAM/OFDM/FHSS)
- Wavelet burst detection (CWT/STFT low-SNR transients)
- RF fingerprinting (keyfob turn-on transients, CFO/IQ-imbalance hash)

TAK:

- CoT event types, client certificate enrollment, live streaming
- Heatmap GroundOverlay, movement trail polylines

Distributed C2:

- Meshtastic mesh link (`MeshLink`, module-level pubsub listener after the pypubsub 4.x weakref bug)
- Agent runtime with persistent state, outbox retry with exponential backoff, auto-resume of last-tasked scanner after reboot
- Wire protocol: HELLO / APPROVE / CMD / CFG / RES / DET / STAT / LOG / CFGINFO / SCANINFO / ACK; SNR carried on DET
- Outbox prioritises control messages over the DET backlog — a busy BT/WiFi stream no longer starves STAT / RES / CFGINFO / SCANINFO
- CFGINFO + SCANINFO re-fire every 10 STATs so a server restart re-learns agent state without needing the agent to bounce
- Agent STAT heartbeat carries real CPU (1-min loadavg / cpu_count × 100), real uptime, and live GPS (lat/lon + satellite count) — GPS reaches the agent via a `gps.json` sidecar written by the scanner subprocess, avoiding the "scanner owns the serial port" conflict
- Agent `DBTailer` forwarding scanner detections with GPS over the mesh
- Agents web tab with **Manage / Detections / C2 Logs** sub-tabs; pending/approved lists, Approve/Start/Stop/Status controls, paginated detections, click-to-expand row showing per-agent scanner control panel + CFGINFO snapshot; live STAT row shows CPU / uptime / GPS / sat count
- C2 comms log viewer (`/api/agents/comms`) — ring-buffered tx/rx of every mesh frame, filterable by agent
- Map tab "Sources" panel: server + every agent, per-source uncertainty rings sized by calibrated RSSI (with SNR fallback) and per-signal-type path-loss
- Fixed-position `server_position` config + manual drag override (see Analysis)
- systemd service install for server and agent (`scripts/install-*.sh`, `@PROJECT_DIR@` templating)
- JSON config for agent (`configs/agent.json`), matching the server pattern
- Auto-re-approve on HELLO from an already-approved agent — a HELLO from someone in `agents.json` means the agent lost its `state.json` (fresh service install), so the server re-emits APPROVE automatically instead of waiting for an operator to hand-edit `adopted: true`.
- Reliable server→agent CMD / CFG: `ServerOutbox` (`src/server/outbox.py`) allocates a seq per message, retries with exponential backoff (6 s → 120 s, 5 attempts max), stops on `ACK|<agent_id>|<seq>|ok` from the agent. Wire format now carries seq at position 2 for both CMD and CFG (`CMD|N01|<seq>|START|pmr`). Agent auto-ACKs on receipt *before* processing so a slow scanner start can't race a retry into a double-execution.
- DBTailer picks the live scanner DB by parsed filename timestamp (`<type>_YYYYMMDD_HHMMSS.db`) instead of mtime, so a WAL-sidecar touch on a stale file can't redirect the tailer to a dead session and silently stop DET forwarding.

Docs:

- Consolidated wiki under `docs/` with install / architecture / hardware / scanners / configuration / c2 / service-setup / web / triangulation / tak / troubleshooting

## 🚧 In flight

Small known rough edges — fixes are scoped, just not done yet:

- **Category pager is client-side** — loads all rows up to the server's LIMIT, then slices locally so filters keep working across the whole set. For very long sessions the full row list is shipped on every refresh. Server-side offset+limit would scale better at the cost of refactoring the filter code.
- **Agent BT/WiFi outbox saturation** — running the `bt` or `wifi` scanner in a populated area generates detections faster than the mesh can drain (LoRa airtime caps at ~1%, ~6 s per send). Outbox priority now keeps control messages alive, but the DET backlog itself still grows unboundedly. Mitigation today: don't run BT/WiFi continuously over mesh — run it locally on the server, or set a tight `--max-det-rate`. Real fix: agent-side per-persona rate-limit + sub-batch coalescing before enqueue, so we send "30 unique BLE personas in last minute" instead of every advertisement.

## 📋 Planned

Concrete next things, roughly in order. The current Planned list is the remaining "In flight" items promoted — the v1 distributed C2 feature set from docs/roadmap.md:19 is now all shipped.

1. **Server-side category pager** — refactor the big-detection category loaders (`web/fetch.py` + the Signals sub-tabs) to do offset+limit at the SQL layer so long sessions don't ship every row every refresh.
2. **Agent per-persona rate-limit + batch coalescing** — root fix for BT/WiFi outbox saturation: aggregate "30 unique BLE personas in last minute" into a single DET-BATCH frame before enqueueing, instead of one DET per advertisement.

## 💡 Ideas / future

Speculative / research-grade / someday. Kept here so they're not lost.

### Detection
- **TPMS tail detection** — log sensor IDs while driving; recurring IDs across 3+ GPS positions = someone following.
- **Parking lot census** — fingerprint parked vehicles via TPMS sensor IDs over time.
- **IMSI catcher detection** — compare observed cell IDs against OpenCelliD, flag unknown towers.
- **GPS jamming detection** — monitor L1 (1575.42 MHz) for abnormal power levels.
- **RF-based tracker detection** — monitor 800–960 MHz for periodic GSM/LTE bursts from hidden GPS trackers.
- **Anti-stalking AirTag (basic)** — build on existing AirTag / "Find My accessory" / "AirTag (lost)" classification in `parsers/ble/apple_continuity.py`: track any persona that keeps showing up alongside the scanner's GPS fix across multiple locations, alert at 3+ distinct places over 10+ minutes. New `utils/stalker_detector.py` + a dashboard widget.
- **Anti-stalking AirTag (IETF-compliant)** — full implementation of `draft-detecting-unwanted-location-trackers`: rotating-key correlation windows, separated-mode dwell tracking, multi-device owner disambiguation.
- **WiFi deauth / evil-twin detection** — passive parser on the existing monitor-mode adapter. Flag `Dot11Deauth` frames (spike per BSSID = deauth attack). Flag BSSIDs whose SSID matches a registered AP but BSSID prefix doesn't (evil twin). New "rogue" badge on the WiFi APs sub-table.

### DSP / decoding
- **DMR voice decode** — pipe discriminator audio through DSD/dsd-fme for voice or radio-ID extraction. Partially prototyped in `experimental/` (dpmr decoded samples, dsdcc build bits) — not yet integrated into `parsers/`.
- **ML-based AMC** — ONNX Runtime + RadioML pre-trained model for deeper modulation classification on CPU.

### Geolocation
- **TDOA / Doppler** — time-difference-of-arrival for sub-10 m geolocation. Requires a parallel architecture: PPS-capable GPS on every node (u-blox NEO-M8T/F9T), disciplined sample clocks (HackRF external clock input; RTL-SDR lacks one — would need replacement), sample-level timestamps in `capture/`, and an out-of-band IQ snippet transport (LAN/SSH, not Meshtastic — 228 B / 6 s frame limit makes IQ transfer infeasible over the mesh). The opportunistic calibration work preserves hooks (full-precision `ts_epoch`, per-sample `session_db` + `det_rowid` back-references, per-sample node GPS) so this can layer on when the hardware is in place. Evaluate after measuring residual triangulation error post-calibration.

### Platform
- **Uptime-Kuma–style agent health dashboard** — ping history / STAT freshness / outbox depth over time. Groundwork: the C2 comms log already captures every frame.
- **Remote log pull over mesh** — on-demand `LOG` spill of the last N lines of `journalctl -u sigint-agent` from the web UI.
- **Field-replaceable scanner profiles** — YAML-defined profile that pins one SDR to one task (e.g. "drone-watch at this GPS coordinate, alert on any RemoteID"), distributed to agents via CFG. Per-agent scanner control panel is the dashboard-side half; this is the missing declarative half.

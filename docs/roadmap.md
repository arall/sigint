# Roadmap

Living document. Moves faster than the rest of the docs — expect entries to shift category as they land or rot.

## ✅ Done

Core:

- Single-node scanners for PMR446 (+ dPMR/DMR energy), FM bands (FRS/GMRS, Marine VHF, MURS, 2m, 70cm, CB, LandMobile, TETRA, P25), keyfob, TPMS, GSM, LTE, ADS-B, AIS, POCSAG, ISM (rtl_433), LoRa, ELRS/Crossfire, wideband scan with AMC, BLE adv, WiFi probe + beacon + RemoteID, drone video, FPV analog
- Central `sdr.py server` with JSON config, HackRF channelizer, multi-capture orchestration, standalone subprocess adapter
- Per-session SQLite logging (WAL, indexed), SQL-first web dashboard

Analysis:

- RSSI multilateration (`sdr.py tri`, 2+ nodes, log-distance path loss)
- Heatmap KML generation (live + post-hoc via `sdr.py heatmap`)
- Movement trails (CoT polylines to ATAK)
- Device correlation (cross-signal-type co-occurrence + union-find clustering, cached, 6-hour window)
- Automatic modulation classification (`dsp/amc.py`, heuristic FM/OOK/FSK/PSK/QAM/OFDM/FHSS)
- Wavelet burst detection (CWT/STFT low-SNR transients)
- RF fingerprinting (keyfob turn-on transients, CFO/IQ-imbalance hash)

TAK:

- CoT event types, client certificate enrollment, live streaming
- Heatmap GroundOverlay, movement trail polylines

Distributed C2 (this round of work):

- Meshtastic mesh link (`MeshLink`, module-level pubsub listener after the pypubsub 4.x weakref bug)
- Agent runtime with persistent state, outbox retry with exponential backoff, auto-resume of last-tasked scanner after reboot
- Wire protocol (HELLO/APPROVE/CMD/CFG/RES/DET/STAT/LOG/ACK), SNR carried on DET
- Agent `DBTailer` forwarding scanner detections with GPS over the mesh
- Agents web tab: pending/approved lists, Approve/Start/Stop/Status controls, paginated detections table
- Map tab sources panel: server + every agent, per-source uncertainty rings sized by SNR + per-signal-type path-loss
- Fixed-position `server_position` config
- systemd service install for server and agent (`scripts/install-*.sh`, `@PROJECT_DIR@` templating)
- JSON config for agent (`configs/agent.json`), matching the server pattern

Docs:

- Consolidated wiki under `docs/` with install / architecture / hardware / scanners / configuration / c2 / service-setup / web / triangulation / tak / troubleshooting

## 🚧 In flight

Small known rough edges — fixes are scoped, just not done yet:

- **State-sync drift** — server keeps `agents.json` on disk but doesn't re-send `APPROVE` when an already-approved agent HELLOs. If an agent's `state.json` is wiped (fresh service install), it silently ignores every CMD. Workaround: hand-edit `adopted: true`. Real fix: auto-re-approve on HELLO from an approved agent.
- **CMD retries** — server-originated `CMD START` / `CMD STOP` are single-shot broadcasts, lossy over LoRa. Operator clicks Start twice as a workaround. Real fix: mirror the agent's outbox (seq + ACK) on the server→agent direction.
- **DBTailer picks newest by mtime** — fine for a live scanner but SHM touches can bump older DBs' mtimes above the active one, causing detections to stop forwarding after a restart with multiple sessions. Switch to picking by filename timestamp (deterministic from the scanner's `<type>_YYYYMMDD_HHMMSS.db`).
- **Agent STAT carries no GPS** — the scanner subprocess owns the GPS port, agent process can't open it concurrently. Nodes appear on the map only once they forward a geo-tagged DET. A `gps.json` sidecar written by the scanner and polled by the agent would solve it.
- **Category pager is client-side** — loads all rows up to the server's LIMIT, then slices locally so filters keep working across the whole set. For very long sessions the full row list is shipped on every refresh. Server-side offset+limit would scale better at the cost of refactoring the filter code.

## 📋 Planned

Concrete next things, roughly in order:

1. **Real-time multi-node triangulation on the Map tab** — when 3+ agents hear the same signal (type + freq + time window), multilaterate from their positions + RSSI/SNR and draw the estimated emitter point. Relies on the uncertainty-ring work already shipped.
2. **Node drag-to-reposition** — alternative to editing `server_position` in JSON for the server, and to waiting for a DET for agents. Pin-by-hand on the map, persists to disk.
3. **Replay a session over the C2 path** — feed a recorded `.db` through the DBTailer + encoder to exercise the server ingest path without live RF.
4. **Per-node calibration** — measure RSSI/SNR at a known distance, persist into `configs/agent.json`, use in the map ring formula and in `sdr.py tri`.
5. **Correlation on agent data** — `sdr.py correlate` currently unions every `.db`; explicitly surfacing "server + N01 + N02 both saw keyfob X in the same 30 s window" in the dashboard would make multi-node deployments self-documenting.

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
- **DMR voice decode** — pipe discriminator audio through DSD/dsd-fme for voice or radio-ID extraction.
- **ML-based AMC** — ONNX Runtime + RadioML pre-trained model for deeper modulation classification on CPU.

### Geolocation
- **TDOA / Doppler** — time-difference-of-arrival for sub-10 m geolocation. Requires GPS PPS time sync across nodes.

### Platform
- **Uptime-Kuma–style agent health dashboard** — ping history / STAT freshness / outbox depth over time.
- **Remote log pull over mesh** — on-demand `LOG` spill of the last N lines of `journalctl -u sigint-agent` from the web UI.
- **Field-replaceable scanner profiles** — YAML-defined profile that pins one SDR to one task (e.g. "drone-watch at this GPS coordinate, alert on any RemoteID"), distributed to agents via CFG.

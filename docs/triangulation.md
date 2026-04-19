# Triangulation

RSSI multilateration from multi-node detection logs. Two paths:

- **Live** — the Map tab runs the correlator every refresh over the last 5 min of detections from every source (server + every agent). Fixes show as dashed crosshair markers; popup lists contributing nodes, per-observation RSSI, and calibration coverage. Nothing to run — it's always on.
- **Post-hoc** (`sdr.py tri <db>...`) — replays saved sessions end-to-end, configurable path-loss parameters, can push results to ATAK.

## How It Works

1. **Correlation** — matches detections across nodes by device ID (keyfob, TPMS, BLE), channel (PMR, POCSAG), or frequency (GSM, LTE, LoRa) within a configurable time window
2. **RSSI → Distance** — log-distance path loss model: `distance = 10^((RSSI_ref - RSSI) / (10 * n))`
3. **Multilateration** — 2 nodes: weighted midpoint (ambiguous). 3+ nodes: least-squares optimization

## Node Spacing Guidelines

| Scenario | Min spacing | Notes |
|----------|------------|-------|
| Keyfob / TPMS (parking lot) | 30-50 m | Short range, steep power falloff |
| BLE (building) | 10-20 m | Very short range |
| PMR walkie-talkie (outdoor) | 100-300 m | Stronger signal, flatter curve |
| GSM / LTE uplink | 200-500 m | High power, need wider baseline |

Nodes should be spaced at least as far apart as the expected distance to the emitter. 3 nodes in a triangle is much better than 3 in a line.

## Path Loss Parameters

Configurable via `--path-loss-exp` and `--rssi-ref`:

| Signal type | Exponent (n) | RSSI at 1m (dB) | Environment |
|-------------|:------------:|:----------------:|-------------|
| BLE | 2.5 | -40 | Indoor/short range |
| WiFi | 2.7 | -30 | Indoor/outdoor |
| Keyfob / ISM | 2.7 | -30 | Outdoor |
| TPMS | 2.5 | -35 | Outdoor, near ground |
| PMR446 | 2.2 | -20 | Outdoor LOS |
| GSM / LTE | 3.0 | -20 | Urban |
| LoRa | 2.3 | -30 | Outdoor long range |

These are the *model* defaults; per-node hardware bias is handled separately by calibration (below). `--use-snr` remains available as a workaround when calibration isn't set up yet.

## Calibration

`power_db` from an RTL-SDR is dB relative to ADC full-scale, not absolute dBm. Two dongles reading the same signal can disagree by 10–20 dB due to gain variation and temperature drift — bigger than the path-loss model error. Calibration removes this per-node bias.

Calibration is **automatic** — if `output/calibration.db` exists, `sdr.py tri` loads per-(node, band) offsets and subtracts them from every observation before multilateration. Triangulation prints how many observations got a calibrated reading vs. fell back to raw power.

### Building a calibration

Match captured detections against emitters whose position and TX power are known:

```sh
# One-time: tell the calibration DB where this node physically sits.
sudo venv/bin/python3 src/sdr.py calibrate set-position --node-id N01 \
    --lat 42.5098 --lon 1.5361 --alt 1050

# Ingest captured sessions and solve per-band offsets.
sudo venv/bin/python3 src/sdr.py calibrate ingest --node-id N01 \
    --emitters configs/calibration_emitters.json \
    output/wifi_*.db output/fm_*.db output/adsb_*.db

# Inspect solved offsets.
sudo venv/bin/python3 src/sdr.py calibrate show
```

Reference emitters go in `configs/calibration_emitters.json` (see `.example`):

- **WiFi APs** — BSSID, lat/lon, EIRP in dBm (typical home AP ~20 dBm)
- **FM broadcast stations** — frequency, lat/lon, EIRP (public databases)
- **Cell towers** — CGI, frequency, lat/lon, EIRP (forward-compatible; inert until scanners decode serving cell)

Passive sources that don't need a registry:

- **ADS-B** — aircraft self-report position + altitude; TX power inferred from ICAO category table. Dormant until `scanners/adsb.py` captures per-message RSSI (tracked in roadmap).
- **AIS** — vessel class derived from message type; class A ~12.5 W, class B ~2 W. Same RSSI gap as ADS-B today.

Run `sdr.py calibrate ingest` periodically (or `calibrate watch`) as new sessions accumulate; offsets refit from the last 7 days of samples by default. Calibration is node-local in `output/calibration.db` — it stays with the hardware across sessions.

Skip calibration with `sdr.py tri --no-calibration` for before/after comparisons.

## Known Limitations

- RSSI is noisy in practice (multipath, obstructions, antenna orientation). Expect room-level accuracy at best, even after calibration.
- 2-node solutions are inherently ambiguous. 3+ nodes strongly recommended.
- Calibration handles per-node hardware bias. It doesn't solve path-loss model mismatch (log-distance still assumes a simple exponent). For sub-10 m accuracy, TDOA is needed — see the roadmap.
- ADS-B and AIS targets self-report position — triangulation is not needed for them, but they are still useful as passive calibration references.

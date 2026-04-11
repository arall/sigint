# Triangulation

Post-hoc RSSI multilateration from multi-node detection logs. Run 2+ sensor nodes at different GPS positions scanning the same band, then feed their `.db` logs to estimate emitter position.

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

These are uncalibrated defaults. Real-world accuracy (typically 10-50 m outdoors) improves with calibration: measure actual RSSI at a known distance and adjust `n` and `rssi_ref`. Use `--use-snr` when nodes have different gain settings.

## Known Limitations

- RSSI is noisy in practice (multipath, obstructions, antenna orientation). Expect room-level accuracy at best.
- 2-node solutions are inherently ambiguous. 3+ nodes strongly recommended.
- `power_db` is in dBFS (relative to SDR ADC), not dBm. All nodes must use the same gain, or use `--use-snr` to normalize.
- ADS-B and AIS targets self-report position — triangulation is not needed.

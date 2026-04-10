# Architecture

## Hybrid: Autonomous Short-Burst + Central-Orchestrated Long Signals

Nodes default to scanning short-burst frequencies autonomously (since those signals are gone before any central coordination could happen). Central handles wideband monitoring and orchestrates nodes for longer-duration signals.

```
                 ┌──────────────────────────────┐
                 │   CENTRAL SERVER (Pelican)   │
                 │                              │
                 │  HackRF x2 (wideband scan)   │
                 │  RTL-SDR x2 (ADS-B + GSM)    │
                 │                              │
                 │  Detects long signals →      │
                 │  Tasks nodes to measure      │
                 │                              │
                 │  Correlates short-burst      │
                 │  detections from nodes       │
                 └─────────────┬────────────────┘
                               │ Task / Report
                               │ (LoRa / Meshtastic)
                 ┌─────────────┼──────────────┐
                 ▼             ▼              ▼
           ┌──────────┐   ┌──────────┐   ┌──────────┐
           │  NODE A  │   │  NODE B  │   │  NODE C  │
           │ 1x RTL   │   │ 1x RTL   │   │ 1x RTL   │
           │ GPS      │   │ GPS      │   │ GPS      │
           │ LoRa     │   │ LoRa     │   │ LoRa     │
           │          │   │          │   │          │
           │ DEFAULT: │   │ DEFAULT: │   │ DEFAULT: │
           │ Keyfob/  │   │ Keyfob/  │   │ Keyfob/  │
           │ TPMS/    │   │ TPMS/    │   │ TPMS/    │
           │ short-   │   │ short-   │   │ short-   │
           │ burst    │   │ burst    │   │ burst    │
           │          │   │          │   │          │
           │ ON CMD:  │   │ ON CMD:  │   │ ON CMD:  │
           │ Retune → │   │ Retune → │   │ Retune → │
           │ Measure  │   │ Measure  │   │ Measure  │
           │ → Return │   │ → Return │   │ → Return │
           └────┬─────┘   └────┬─────┘   └────┬─────┘
                │              │              │
                └──────────────┼──────────────┘
                               ▼
                    RSSI + GPS → Triangulate
                    → CoT → ATAK map
```

## Task Protocol

Server → Node (retune and measure, then return to default):
```json
{"cmd": "tune", "freq": 446.0625, "bw": 12500, "duration": 10}
```

Node → Server (autonomous short-burst detection):
```json
{"node": "A", "type": "detection", "freq": 433.92, "device_id": "A1B2C3", "rssi": -45.1, "gps": [48.858, 2.294], "ts": 1711900000}
```

Node → Server (commanded RSSI measurement):
```json
{"node": "A", "type": "measure", "freq": 446.0625, "rssi": -62.3, "gps": [48.858, 2.294], "ts": 1711900000}
```

**Short-burst triangulation**: central correlates autonomous detections across nodes by device ID + time window (e.g., same keyfob code seen by 3 nodes within 500ms).

**Long-signal triangulation**: 3+ commanded RSSI reports → multilateration → emitter position → CoT to ATAK.

## Phases

| Phase | Description | Status |
|-------|-------------|--------|
| **1. Single-node PoC** | Scan bands, detect signals, measure RSSI, log to CSV | Done |
| **2. Generic FM scanner** | Configurable band profiles (PMR, FRS, Marine, etc.), reuse demod pipeline | Done |
| **3. Central server** | Wideband detection with HackRF, channelizer, multi-protocol decoding | In progress |
| **4. Node measure mode** | Lightweight tune → RSSI → report daemon for sensor nodes | Planned |
| **5. Comms layer** | LoRa/Meshtastic task protocol between server and nodes | Planned |
| **6. Triangulation** | RSSI multilateration from 2+ node CSV logs (post-hoc) | Done (offline) |
| **7. ATAK integration** | CoT messages, map overlay, real-time tracking | Done |
| **8. Analysis layer** | Heatmaps, movement trails, device correlation, AMC, RF fingerprinting | Done |

## Analysis Layer

The analysis layer operates on detection data (CSV logs or real-time `_on_detection` callbacks) and provides intelligence beyond raw detections:

```
  Detections (CSV / real-time)
         │
         ├── Heatmap Generator ──→ KML GroundOverlay for ATAK
         │     Spatial binning of detections, log-scale color gradient
         │
         ├── Trail Tracker ──→ CoT polylines for ATAK
         │     Per-device position ring buffer, movement detection
         │
         ├── Device Correlator ──→ JSON clusters
         │     Time-binned co-occurrence, union-find clustering
         │
         └── DSP Analysis
               ├── AMC ──→ Modulation classification (FM, OOK, FSK, PSK...)
               ├── Wavelet ──→ Low-SNR burst detection (CWT/STFT)
               └── RF Fingerprint ──→ Transmitter hardware identification
```

In the central server, heatmap/trails/correlator are hooked into the shared logger's `on_detection` callback and run automatically. For post-hoc analysis, `sdr.py heatmap` and `sdr.py correlate` subcommands process CSV files directly.

## Design Principles

- **Hybrid architecture.** Nodes scan short-burst frequencies autonomously (keyfobs, TPMS, pagers). Central orchestrates nodes for longer signals (PMR, GSM). Each signal type gets the approach that fits its duration.
- **Detection + RSSI is the priority.** Knowing "someone is transmitting on PMR CH3 at -35 dB from position X" is the core value. Audio decoding is secondary.
- **Nodes are cheap but not dumb.** One RTL-SDR, GPS, LoRa. ~$80 per unit. They run default scanners autonomously and accept retune commands from central.
- **Each scanner is independent.** Run one module at a time, or run multiple in parallel on different SDRs.
- **Single tuner tradeoff.** When central retunes a node, it loses short-burst coverage. Mitigated by staggering nodes and keeping retune windows short (5-10s).

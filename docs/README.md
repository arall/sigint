# Documentation

Entry points, grouped by what you're trying to do.

## Getting up and running

- **[install.md](install.md)** — System prerequisites, SDR drivers (librtlsdr, readsb, rtl_ais), Python venv, optional extras (Whisper, gTTS, BLE, WiFi).
- **[hardware.md](hardware.md)** — Bill of materials, antenna profiles, sensor node parts list, Meshtastic device matrix.
- **[service-setup.md](service-setup.md)** — Installing the central server and remote agents as systemd services (`scripts/install-*.sh`).

## Running the system

- **[scanners.md](scanners.md)** — Every scanner CLI subcommand (PMR, FM bands, keyfob, TPMS, ADS-B, AIS, WiFi, BLE, LoRa, ISM, etc.) with frequencies, hardware needs, and status.
- **[configuration.md](configuration.md)** — `configs/server.json` and `configs/agent.json` field reference, with annotated examples for HackRF + RTL-SDR + BLE + WiFi + meshlink.
- **[web.md](web.md)** — Web dashboard tabs, HTTP API endpoints, session dropdown, category behavior.

## Distributed operation

- **[c2.md](c2.md)** — Meshtastic C2 layer: adoption flow, wire protocol (HELLO/APPROVE/CMD/CFG/RES/DET/STAT/LOG/ACK), message reference.
- **[triangulation.md](triangulation.md)** — RSSI multilateration across node DBs, path-loss parameters, node-spacing guidance.
- **[tak.md](tak.md)** — TAK Server certificate setup, CoT event types, movement trails, heatmap overlay.

## Under the hood

- **[architecture.md](architecture.md)** — Hybrid autonomous + orchestrated model, capture/parser/scanner pipeline, analysis layer, design principles.
- **[roadmap.md](roadmap.md)** — What's shipped, what's in flight, what's planned, and the speculative ideas list.
- **[troubleshooting.md](troubleshooting.md)** — Common bring-up failures (PSK mismatch, radio stuck in debug mode, state-sync drift), SDR quirks, Pi-specific gotchas.

## Images

- [images/](images/) — Screenshots used in README and docs (currently just `web-ui.png`).

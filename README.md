# SIGINT

ATAK + SDR for signal detection, triangulation, and real-time situational awareness.

![Web Dashboard](docs/images/web-ui.png)

A distributed SIGINT system. A central server scans bands continuously with wideband SDRs and coordinates remote sensor nodes over a Meshtastic mesh. Short-burst signals (keyfobs, TPMS, pagers) are scanned autonomously and triangulated post-hoc; longer transmissions (PMR voice, cellular uplinks) are tasked to nodes on demand. Detections flow into SQLite, surface on a live web dashboard, and stream as CoT events to ATAK for map overlay.

## Quick install

```sh
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd src && python3 sdr.py pmr
```

See **[docs/install.md](docs/install.md)** for system dependencies, SDR drivers, and service-mode setup.

## Documentation

Full documentation lives in **[docs/](docs/)**. Start with the [wiki index](docs/README.md).

## References

- https://github.com/ATAKRR/atakrr
- https://github.com/kamakauzy/ReconRaven

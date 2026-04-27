"""Entry point for `sdr.py agent`."""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

from agent.config import AgentConfig
from agent.agent import Agent
from agent.scanner_mgr import ScannerManager, DBTailer
from comms.meshlink import MeshLink


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sdr.py agent")
    ap.add_argument("--config", default="configs/agent.json",
                    help="Path to agent.json")
    ap.add_argument("--state-dir", default=None,
                    help="Override state dir (defaults from config)")
    ap.add_argument("--meshtastic-port", default=None,
                    help="Override meshtastic serial port")
    ap.add_argument("--agent-id", default=None,
                    help="Override agent id")
    ap.add_argument("--gps-port", default=None,
                    help="Override GPS serial port (NMEA)")
    args = ap.parse_args(argv)

    cfg = AgentConfig.load(args.config)
    agent_id = args.agent_id or cfg.agent_id
    state_dir = args.state_dir or cfg.state_dir
    port = args.meshtastic_port or cfg.meshtastic_port
    gps_port = args.gps_port or cfg.gps_port
    if not port:
        print("ERROR: meshtastic_port not configured", file=sys.stderr)
        return 2

    # GPS is owned by the scanner subprocess (see ScannerManager.start).
    # Only one process can read a given /dev/ttyACM* at a time, so the
    # agent itself does not open the port — detections carry lat/lon
    # stamped by the scanner's logger, and DET messages forward them.

    link = MeshLink.from_serial(port=port, channel_index=cfg.mesh_channel_index)

    # Optional: derive position from the meshtastic radio's own GPS (e.g.
    # T-Echo / Heltec Wireless Tracker), or write a static surveyed
    # position straight to the sidecar (indoor deployments where GPS
    # can't lock). Either way the sidecar at <state>/scanner/gps.json
    # is what _stat_loop and DET tagging consume.
    gps_reader = None
    gps_writer_stop = None
    sidecar_path = os.path.join(state_dir, "scanner", "gps.json")
    if cfg.gps_source == "meshtastic":
        from utils.gps import MeshtasticGpsReader, write_gps_sidecar
        gps_reader = MeshtasticGpsReader(provider=link.get_local_position)
        gps_reader.start()
        gps_writer_stop = threading.Event()
        write_gps_sidecar(gps_reader, sidecar_path, stop_event=gps_writer_stop)
    elif cfg.gps_source == "static" and cfg.static_position:
        # One-shot write — the sidecar reader (_read_sidecar_position
        # below, plus agent.py:_stat_loop) accepts anything <60 s old,
        # so refresh every 30 s to keep it from going stale.
        import json as _json
        os.makedirs(os.path.dirname(sidecar_path), exist_ok=True)
        gps_writer_stop = threading.Event()
        def _static_loop():
            while not gps_writer_stop.is_set():
                payload = {
                    "lat": cfg.static_position["lat"],
                    "lon": cfg.static_position["lon"],
                    "sats": 0,
                    "ts": time.time(),
                }
                tmp = sidecar_path + ".tmp"
                try:
                    with open(tmp, "w") as f:
                        _json.dump(payload, f)
                    os.replace(tmp, sidecar_path)
                except OSError:
                    pass
                gps_writer_stop.wait(30.0)
        threading.Thread(target=_static_loop, daemon=True).start()

    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sdr_py = os.path.join(src_dir, "sdr.py")
    scanner_mgr = ScannerManager(
        python_exe=sys.executable, sdr_py=sdr_py,
        output_dir=os.path.join(state_dir, "scanner"),
        device_id=agent_id, gps_port=gps_port,
    )

    cfg_snapshot = {
        "mesh_channel_index": cfg.mesh_channel_index,
        "meshtastic_port": port,
        "gps_port": gps_port or "",
        "state_dir": state_dir,
        "version": "0.1",
        "hw": "rpi",
    }
    agent = Agent(state_dir=state_dir, agent_id=agent_id,
                  meshlink=link, scanner_mgr=scanner_mgr,
                  cfg_snapshot=cfg_snapshot)
    agent.start()

    # Tail the scanner's per-session DB and forward each new detection
    # as a DET message through the agent's outbox.
    gps_sidecar_path = os.path.join(state_dir, "scanner", "gps.json")

    def _read_sidecar_position():
        # Used when the scanner doesn't itself open a GPS (e.g. BLE on a node
        # whose only GPS is inside the meshtastic radio). The agent writes
        # the sidecar from MeshtasticGpsReader; we inject those coordinates
        # into outgoing DETs so triangulation has positions.
        try:
            import json as _json
            st = os.stat(gps_sidecar_path)
            if time.time() - st.st_mtime > 60:
                return None, None
            with open(gps_sidecar_path) as f:
                d = _json.load(f)
            return d.get("lat"), d.get("lon")
        except Exception:
            return None, None

    def _on_scanner_row(row):
        try:
            freq_mhz = float(row["frequency_hz"]) / 1e6
            rssi = int(float(row["power_db"]))
            ts_unix = int(float(row["ts_epoch"]))
            snr_raw = row.get("snr_db")
            snr = int(round(float(snr_raw))) if snr_raw is not None else None
            lat = row.get("latitude")
            lon = row.get("longitude")
            if lat is None or lon is None:
                lat, lon = _read_sidecar_position()
            dur_s = None
            md = row.get("metadata")
            if md:
                try:
                    import json as _json
                    md_obj = _json.loads(md) if isinstance(md, str) else md
                    raw_dur = md_obj.get("duration_s")
                    if raw_dur is not None:
                        dur_s = float(raw_dur)
                except Exception:
                    pass
            agent.enqueue_det(
                type_=row["signal_type"], freq_mhz=freq_mhz, rssi=rssi,
                lat=lat, lon=lon,
                ts_unix=ts_unix, summary=row.get("channel") or "",
                snr=snr, dur_s=dur_s,
            )
        except Exception:
            pass

    tailer = DBTailer(
        db_dir=os.path.join(state_dir, "scanner"),
        on_row=_on_scanner_row,
    )
    tailer.start()

    done = threading.Event()
    def _sig(_signo, _frame): done.set()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    done.wait()
    tailer.stop()
    if gps_writer_stop is not None:
        gps_writer_stop.set()
    if gps_reader is not None:
        gps_reader.stop()
    agent.stop()
    return 0


if __name__ == "__main__":
    sys.exit(run())

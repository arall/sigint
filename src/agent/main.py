"""Entry point for `sdr.py agent`."""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading

from agent.config import AgentConfig
from agent.agent import Agent
from agent.scanner_mgr import ScannerManager, DBTailer
from comms.meshlink import MeshLink


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sdr.py agent")
    ap.add_argument("--config", default="/etc/sigint/agent.conf",
                    help="Path to agent.conf")
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
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sdr_py = os.path.join(src_dir, "sdr.py")
    scanner_mgr = ScannerManager(
        python_exe=sys.executable, sdr_py=sdr_py,
        output_dir=os.path.join(state_dir, "scanner"),
        device_id=agent_id, gps_port=gps_port,
    )

    agent = Agent(state_dir=state_dir, agent_id=agent_id,
                  meshlink=link, scanner_mgr=scanner_mgr)
    agent.start()

    # Tail the scanner's per-session DB and forward each new detection
    # as a DET message through the agent's outbox.
    def _on_scanner_row(row):
        try:
            freq_mhz = float(row["frequency_hz"]) / 1e6
            rssi = int(float(row["power_db"]))
            ts_unix = int(float(row["ts_epoch"]))
            agent.enqueue_det(
                type_=row["signal_type"], freq_mhz=freq_mhz, rssi=rssi,
                lat=row.get("latitude"), lon=row.get("longitude"),
                ts_unix=ts_unix, summary=row.get("channel") or "",
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
    agent.stop()
    return 0


if __name__ == "__main__":
    sys.exit(run())

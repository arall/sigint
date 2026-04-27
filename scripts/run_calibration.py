#!/usr/bin/env python3
"""Orchestrate a one-shot RSSI calibration cycle.

Spawned by the dashboard's POST /api/calibrate/run as a detached process
(systemd-style: start_new_session). Runs:

  1. Stop sigint-server (frees HackRF)
  2. TX a 45 s FM-modulated tone at 446.05 MHz from HackRF
  3. Start sigint-server (creates a new agents_*.db session)
  4. Wait for mesh-forwarded DETs to land
  5. For each agent: `sdr.py calibrate ingest --device-id-filter NXX`
     against the new session DB, restricted to the surveyed PMR source

Progress is written to STATUS_PATH so the dashboard can poll it.

Run as root (server is root-owned). Detached from caller via setsid so
the systemctl stop/start cycle doesn't kill us.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path("/home/arall/code/sigint")
TONE_PATH = Path("/tmp/calibrate_tone_446.iq")
STATUS_PATH = Path("/tmp/calibrate_status.json")

TX_FREQ_HZ = 446_050_000
TX_SAMPLE_RATE = 2_000_000
TX_DURATION_S = 45
TX_TIMEOUT = TX_DURATION_S + 5  # hackrf_transfer wrapper
TX_GAIN_VGA = 47
# DETs trickle in over mesh after the agent's outbox drains. LoRa duty
# cycle + 5-min STAT cadence means a single DET can take 60-120 s to land
# server-side. Run ingest every INGEST_INTERVAL_S until INGEST_TOTAL_S
# elapses, so late arrivals get captured without a needlessly long fixed
# wait.
INGEST_TOTAL_S = 150
INGEST_INTERVAL_S = 20

AGENT_IDS = ["N01", "N02", "N03"]


def write_status(step: str, message: str, *, done: bool = False, ok: bool = True,
                 extra: dict | None = None) -> None:
    payload = {
        "step": step,
        "message": message,
        "ts": time.time(),
        "done": done,
        "ok": ok,
    }
    if extra:
        payload.update(extra)
    tmp = STATUS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(STATUS_PATH)


def generate_tone_if_missing() -> None:
    """Re-create the IQ tone file if missing or stale."""
    if TONE_PATH.exists() and TONE_PATH.stat().st_size > 100_000_000:
        return
    write_status("generating_tone", "Building IQ tone file")
    import numpy as np  # local import; only needed when missing
    sr = TX_SAMPLE_RATE
    secs = TX_DURATION_S + 5  # cushion
    t = np.arange(sr * secs) / sr
    audio = 0.3 * np.sin(2 * np.pi * 1000 * t)
    df_hz = 5000
    phi = 2 * np.pi * np.cumsum(df_hz * audio) / sr
    iq = np.exp(1j * phi).astype(np.complex64)
    i = (np.real(iq) * 110).astype(np.int8)
    q = (np.imag(iq) * 110).astype(np.int8)
    out = np.empty(len(i) * 2, dtype=np.int8)
    out[0::2] = i
    out[1::2] = q
    out.tofile(TONE_PATH)


def run(cmd: list[str], timeout: float | None = None) -> tuple[int, str]:
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          check=False)
    return res.returncode, (res.stdout + res.stderr)[-2000:]


def latest_agents_db() -> Path | None:
    candidates = sorted(PROJECT.glob("output/agents_*.db"),
                         key=lambda p: p.stat().st_mtime,
                         reverse=True)
    return candidates[0] if candidates else None


def main() -> int:
    try:
        write_status("starting", "Calibration cycle starting")
        generate_tone_if_missing()

        write_status("stopping_server", "Stopping sigint-server to free HackRF")
        run(["systemctl", "stop", "sigint-server"], timeout=15)
        time.sleep(2)  # let HackRF settle

        write_status("transmitting",
                      f"TXing {TX_DURATION_S}s tone at {TX_FREQ_HZ/1e6:.3f} MHz")
        rc, out = run([
            "timeout", str(TX_TIMEOUT),
            "hackrf_transfer",
            "-t", str(TONE_PATH),
            "-f", str(TX_FREQ_HZ),
            "-s", str(TX_SAMPLE_RATE),
            "-a", "1",
            "-x", str(TX_GAIN_VGA),
        ], timeout=TX_TIMEOUT + 10)
        # hackrf_transfer often returns non-zero on SIGTERM after timeout — we don't
        # treat that as failure. We do flag if no power reading was emitted at all.
        if "average power" not in out:
            write_status("tx_failed", f"hackrf_transfer produced no power output. tail:\n{out[-400:]}",
                         done=True, ok=False)
            run(["systemctl", "start", "sigint-server"])
            return 1

        write_status("starting_server", "Restarting sigint-server")
        run(["systemctl", "start", "sigint-server"], timeout=15)

        # Wait for the new session DB to exist (server creates it on start).
        deadline = time.time() + 15
        db = None
        while time.time() < deadline:
            db = latest_agents_db()
            if db is not None and db.stat().st_mtime > time.time() - 30:
                break
            time.sleep(1)
        if db is None:
            write_status("ingest_skipped", "No agents_*.db file found",
                         done=True, ok=False)
            return 1

        # Iteratively ingest while waiting for late mesh arrivals. Each loop
        # reads the freshest db (server may have rotated) and tries each
        # agent. Stops early if all agents got a new sample.
        per_agent = {aid: {"samples": 0, "exit_code": None, "tail": []}
                       for aid in AGENT_IDS}
        deadline = time.time() + INGEST_TOTAL_S
        while time.time() < deadline:
            elapsed = int(INGEST_TOTAL_S - (deadline - time.time()))
            db = latest_agents_db() or db
            write_status("ingesting",
                          f"Ingest pass at +{elapsed}s (mesh DETs trickle in over LoRa)")
            for aid in AGENT_IDS:
                rc, out = run([
                    str(PROJECT / "venv/bin/python3"),
                    str(PROJECT / "src/sdr.py"),
                    "calibrate", "ingest",
                    "--node-id", aid,
                    "--source", "surveyed",
                    "--device-id-filter", aid,
                    str(db),
                ], timeout=60)
                samples_this_pass = 0
                for line in out.splitlines():
                    if "new sample(s)" in line:
                        # "Ingested from N file(s): K new sample(s)"
                        for tok in line.split(":")[-1].split():
                            if tok.isdigit():
                                samples_this_pass = int(tok)
                                break
                        break
                per_agent[aid]["samples"] += samples_this_pass
                per_agent[aid]["exit_code"] = rc
                per_agent[aid]["tail"] = out.splitlines()[-3:]
            if all(v["samples"] > 0 for v in per_agent.values()):
                break
            time.sleep(INGEST_INTERVAL_S)

        # Final stats from cal_samples table
        import sqlite3
        cal_db = PROJECT / "output/calibration.db"
        try:
            c = sqlite3.connect(f"file:{cal_db}?mode=ro", uri=True)
            stats = []
            for r in c.execute(
                "SELECT device_id, COUNT(*), AVG(offset_db), AVG(distance_m) "
                "FROM cal_samples GROUP BY device_id"
            ):
                stats.append({
                    "node": r[0], "n_samples": r[1],
                    "mean_offset_db": round(r[2], 2),
                    "mean_distance_m": round(r[3], 2),
                })
            c.close()
        except Exception as e:
            stats = [{"error": str(e)}]

        write_status("done", "Calibration cycle complete", done=True, ok=True,
                     extra={"per_agent": per_agent, "stats": stats})
        return 0
    except Exception as e:
        write_status("error", f"Unhandled exception: {e}",
                     done=True, ok=False)
        try:
            run(["systemctl", "start", "sigint-server"])
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    sys.exit(main())

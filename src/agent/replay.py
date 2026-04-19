"""
Replay a recorded detection .db over the C2 path as if from a live agent.

Use cases:
  - Exercise the server ingest path without live RF
  - Repeatable triangulation / calibration benchmarks from a known input
  - Stress-test the outbox + mesh link at a known detection rate

The replayer is intentionally thin: it does not run an `Agent` runtime
(no outbox, no scanner manager, no state persistence). It encodes DET
messages directly and pushes them through the provided mesh link. This
keeps the feature scope predictable and the code unit-testable with a
`FakeLink`.

Flow from the replayer's POV:
  1. Send HELLO (unless --skip-handshake). If the agent_id is in the
     server's agents.json, the 6039484 "auto-re-approve on HELLO" path
     will trigger a fresh APPROVE and the replayer can start streaming
     DETs right away. Otherwise the server parks the agent in pending
     and the operator must approve via the dashboard first.
  2. Send DETs at the configured rate. Row-by-row from the source .db
     in `id` order, oldest-first, using each row's ts_unix so arrival-
     sort + detection-time-sort look sensible in the web UI.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Optional

from comms import protocol as P
from utils import db as _db


@dataclass
class ReplayStats:
    sent_hello: bool = False
    sent_dets: int = 0
    skipped_no_position: int = 0
    skipped_no_power: int = 0
    total_rows: int = 0


def iter_det_rows(db_path: str,
                  require_position: bool = False,
                  require_power: bool = False) -> Iterator[dict]:
    """Stream detection rows from a .db as dicts suitable for DET encoding.

    Opens the db read-only; caller doesn't need to manage the connection.
    Rows come back in insertion order (`id ASC`) so replay timing looks
    like the original capture.
    """
    conn = _db.connect(db_path, readonly=True)
    try:
        cur = conn.execute(
            "SELECT id, ts_epoch, signal_type, frequency_hz, power_db, "
            "noise_floor_db, snr_db, channel, latitude, longitude, "
            "device_id, metadata FROM detections ORDER BY id"
        )
        for r in cur:
            if require_position and (r["latitude"] is None or r["longitude"] is None):
                continue
            if require_power and (r["power_db"] is None or float(r["power_db"]) == 0.0):
                continue
            yield {
                "id": int(r["id"]),
                "ts_epoch": float(r["ts_epoch"] or 0.0),
                "signal_type": r["signal_type"] or "",
                "frequency_hz": float(r["frequency_hz"] or 0.0),
                "power_db": float(r["power_db"] or 0.0),
                "snr_db": float(r["snr_db"] or 0.0),
                "channel": r["channel"] or "",
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "device_id": r["device_id"] or "",
                "metadata": r["metadata"] or "",
            }
    finally:
        conn.close()


def _det_for_row(agent_id: str, seq: int, row: dict) -> str:
    """Encode a single DET message from a detection row."""
    freq_mhz = row["frequency_hz"] / 1e6 if row["frequency_hz"] else 0.0
    rssi = int(round(row["power_db"])) if row["power_db"] is not None else 0
    snr = int(round(row["snr_db"])) if row["snr_db"] else None
    # Keep the row's original ts_unix so the web UI's detection-time view
    # tells the truth about when the signal was heard on the capture side.
    ts_unix = int(row["ts_epoch"]) if row["ts_epoch"] else 0
    # `summary` on the wire is the channel label for channelised signals;
    # the server copies it into the detection row's channel column.
    summary = row.get("channel") or ""
    lat = row.get("latitude")
    lon = row.get("longitude")
    try:
        lat = float(lat) if lat not in (None, "") else None
        lon = float(lon) if lon not in (None, "") else None
    except (TypeError, ValueError):
        lat, lon = None, None
    return P.encode_det_truncated(
        agent_id=agent_id, seq=seq, type_=row["signal_type"],
        freq_mhz=freq_mhz, rssi=rssi, lat=lat, lon=lon,
        ts_unix=ts_unix, summary=summary, snr=snr,
    )


def replay_db_to_link(
    link,
    db_path: str,
    agent_id: str,
    rate_per_sec: float = 1.0,
    max_rows: Optional[int] = None,
    skip_handshake: bool = False,
    hello_version: str = "replay",
    hello_hw: str = "replay",
    sleep: Callable[[float], None] = time.sleep,
    stop: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, ReplayStats], None]] = None,
    require_position: bool = False,
    require_power: bool = False,
) -> ReplayStats:
    """Replay a captured .db over `link`, as if from `agent_id`.

    Args:
      link: object with .send(text). Real MeshLink or a mock.
      db_path: path to a detection .db from a previous capture.
      agent_id: identity to claim on the wire. Must already be in
        agents.json on the target server, OR approved after the first
        HELLO.
      rate_per_sec: target DET throughput. Honoured as a best-effort
        sleep between sends; mesh backpressure isn't modelled here.
      max_rows: cap on DETs sent (for benchmarking bounded inputs).
      skip_handshake: don't send HELLO first. Useful when the server
        already has this agent_id approved and recent (avoids noisy
        re-APPROVE churn during short benchmarks).
      sleep: dependency-injected sleep — tests pass a no-op.
      stop: dependency-injected abort predicate — returning True ends
        the loop.
      on_progress: called after each DET with (seq, stats).
      require_position / require_power: skip rows without them. Handy
        when benchmarking triangulation (position required) or
        calibration (power required).
    """
    stats = ReplayStats()
    # HELLO first so the server's auto-re-approve path can trigger a
    # fresh APPROVE if the agent was previously adopted (6039484).
    if not skip_handshake:
        try:
            link.send(P.encode_hello(agent_id, hello_version, hello_hw))
            stats.sent_hello = True
        except Exception:
            # Don't abort — caller may have pre-established state.
            stats.sent_hello = False

    interval = 1.0 / max(rate_per_sec, 0.01)
    seq = 1
    for row in iter_det_rows(db_path,
                              require_position=require_position,
                              require_power=require_power):
        stats.total_rows += 1
        if stop is not None and stop():
            break
        if max_rows is not None and stats.sent_dets >= max_rows:
            break
        # Count the pre-filter skips too so the caller can show "sent
        # 40 of 50 rows; 8 missing position, 2 missing power".
        if row.get("latitude") in (None, "") or row.get("longitude") in (None, ""):
            stats.skipped_no_position += 1
        if not row.get("power_db"):
            stats.skipped_no_power += 1

        wire = _det_for_row(agent_id, seq, row)
        try:
            link.send(wire)
            stats.sent_dets += 1
            if on_progress is not None:
                on_progress(seq, stats)
        except Exception:
            # Mesh link blip — skip this row, don't burn through seq.
            seq -= 1
        seq += 1
        sleep(interval)
    return stats

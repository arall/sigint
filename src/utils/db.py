"""
SQLite backend for signal detection logging.

One file per capture session (or per server run) — triangulation/heatmap
compose across nodes by shipping one artifact. WAL mode lets the logger
write while the web dashboard tails the same file concurrently, and JSON1
keeps the per-signal-type metadata blob queryable without a rigid schema.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from typing import Any, Iterator, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT    NOT NULL,
    ts_epoch       REAL    NOT NULL,
    signal_type    TEXT    NOT NULL,
    frequency_hz   REAL    NOT NULL,
    power_db       REAL    NOT NULL,
    noise_floor_db REAL    NOT NULL,
    snr_db         REAL    NOT NULL,
    channel        TEXT,
    latitude       REAL,
    longitude      REAL,
    device_id      TEXT,
    audio_file     TEXT,
    metadata       TEXT
);
CREATE INDEX IF NOT EXISTS idx_detections_type_ts   ON detections(signal_type, ts_epoch);
CREATE INDEX IF NOT EXISTS idx_detections_ts        ON detections(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_detections_device    ON detections(device_id);
CREATE INDEX IF NOT EXISTS idx_detections_type_dev  ON detections(signal_type, device_id);
"""


def connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and pragmatic tuning.

    Writers get a single connection that the caller serializes with a lock.
    `check_same_thread=False` is required: parsers and captures call the
    logger from many threads (scapy sniff, HCI reader, RTL-SDR async) while
    the connection itself was opened from the server main thread. The logger
    holds a mutex around writes, so the connection is never used concurrently.
    Readers (web tailer, triangulate/heatmap/correlator CLIs) pass
    readonly=True.

    Readonly path has a fallback: `?mode=ro` alone still requires write
    access to the directory containing the .db so SQLite can create the
    `-shm` file for WAL coordination. If the server runs as root but the
    dashboard runs as a normal user, the dir isn't writable and every
    readonly open fails with "attempt to write a readonly database". The
    fallback re-tries with `immutable=1` which tells SQLite "this file
    won't change, skip all WAL coordination". That gives a best-effort
    snapshot of the main DB file (missing any rows still buffered in the
    active WAL) — good enough for historical browsing, and better than
    the zero-rows silent failure we had before.
    """
    if readonly:
        abs_path = os.path.abspath(path)
        try:
            conn = sqlite3.connect(
                f"file:{abs_path}?mode=ro",
                uri=True, timeout=5.0, isolation_level=None,
                check_same_thread=False,
            )
            # Probe the connection — mode=ro errors surface on the first
            # query, not on open(), so we need to actually touch the DB.
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            try:
                conn.close()
            except Exception:
                pass
            conn = sqlite3.connect(
                f"file:{abs_path}?mode=ro&immutable=1",
                uri=True, timeout=5.0, isolation_level=None,
                check_same_thread=False,
            )
    else:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = sqlite3.connect(
            path, timeout=5.0, isolation_level=None,
            check_same_thread=False,
        )
        conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_iso(ts: str) -> float:
    """Parse an ISO 8601 timestamp into a unix epoch float.

    Accepts 'YYYY-MM-DDTHH:MM:SS[.ffffff][+HH:MM|Z]' — the format the
    SignalLogger emits via datetime.now().isoformat().
    """
    if not ts:
        return 0.0
    try:
        from datetime import datetime
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


INSERT_SQL = """
INSERT INTO detections (
    timestamp, ts_epoch, signal_type, frequency_hz,
    power_db, noise_floor_db, snr_db,
    channel, latitude, longitude,
    device_id, audio_file, metadata
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def insert_detection(conn: sqlite3.Connection, detection) -> int:
    """Insert a SignalDetection (or equivalent row dict) and return its rowid."""
    if hasattr(detection, "__dataclass_fields__"):
        d = asdict(detection)
    else:
        d = dict(detection)
    ts = d.get("timestamp") or ""
    row = (
        ts,
        _parse_iso(ts),
        d.get("signal_type") or "",
        float(d.get("frequency_hz") or 0),
        float(d.get("power_db") or 0),
        float(d.get("noise_floor_db") or 0),
        float(d.get("snr_db") or 0),
        d.get("channel"),
        d.get("latitude"),
        d.get("longitude"),
        d.get("device_id"),
        d.get("audio_file"),
        d.get("metadata") or "",
    )
    cur = conn.execute(INSERT_SQL, row)
    return cur.lastrowid


def row_to_dict(row: sqlite3.Row) -> dict:
    """Shape a detections row as a flat dict for the downstream readers."""
    return {
        "timestamp": row["timestamp"],
        "signal_type": row["signal_type"],
        "frequency_hz": row["frequency_hz"],
        "power_db": row["power_db"],
        "noise_floor_db": row["noise_floor_db"],
        "snr_db": row["snr_db"],
        "channel": row["channel"] or "",
        "latitude": row["latitude"] if row["latitude"] is not None else "",
        "longitude": row["longitude"] if row["longitude"] is not None else "",
        "device_id": row["device_id"] or "",
        "audio_file": row["audio_file"] or "",
        "metadata": row["metadata"] or "",
    }


def iter_detections(
    conn: sqlite3.Connection,
    signal_type: Optional[str] = None,
    since_epoch: Optional[float] = None,
    until_epoch: Optional[float] = None,
    since_rowid: Optional[int] = None,
    limit: Optional[int] = None,
) -> Iterator[sqlite3.Row]:
    """Stream detection rows, optionally filtered. Returns sqlite3.Row objects."""
    clauses = []
    params: list[Any] = []
    if signal_type:
        clauses.append("signal_type = ?")
        params.append(signal_type)
    if since_epoch is not None:
        clauses.append("ts_epoch >= ?")
        params.append(since_epoch)
    if until_epoch is not None:
        clauses.append("ts_epoch <= ?")
        params.append(until_epoch)
    if since_rowid is not None:
        clauses.append("id > ?")
        params.append(since_rowid)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM detections {where} ORDER BY id"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    yield from conn.execute(sql, params)


def max_rowid(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM detections").fetchone()
    return int(row[0]) if row else 0

"""
SQLite storage for per-node RSSI calibration.

Separate file from the detection session .db so calibration survives session
rotation and so a node's hardware offsets (which are a property of the node,
not any particular capture) stay available across reboots.

Three tables:
  - cal_samples: one row per (detection matched to a known emitter, computed
    expected RSSI). Keeps source/band/distance/weight for re-fitting later.
  - cal_offsets: solved (device_id, band) -> offset_db, re-written on recompute.
  - cal_meta: scalar settings (schema_version, surveyed node position, mobile
    flag, last ingest epoch).
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Iterable, Iterator, Optional


SCHEMA_VERSION = "1"


SCHEMA = """
CREATE TABLE IF NOT EXISTS cal_samples (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_epoch       REAL    NOT NULL,
    device_id      TEXT    NOT NULL,
    band           TEXT    NOT NULL,
    frequency_hz   REAL    NOT NULL,
    source         TEXT    NOT NULL,
    ref_id         TEXT    NOT NULL,
    power_db       REAL    NOT NULL,
    expected_db    REAL    NOT NULL,
    offset_db      REAL    NOT NULL,
    distance_m     REAL    NOT NULL,
    elevation_deg  REAL,
    weight         REAL    NOT NULL,
    session_db     TEXT,
    det_rowid      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cal_band_ts ON cal_samples(device_id, band, ts_epoch);
CREATE INDEX IF NOT EXISTS idx_cal_source  ON cal_samples(source);

CREATE TABLE IF NOT EXISTS cal_offsets (
    device_id   TEXT    NOT NULL,
    band        TEXT    NOT NULL,
    offset_db   REAL    NOT NULL,
    stderr_db   REAL    NOT NULL,
    n_samples   INTEGER NOT NULL,
    ts_updated  REAL    NOT NULL,
    method      TEXT    NOT NULL,
    PRIMARY KEY (device_id, band)
);

CREATE TABLE IF NOT EXISTS cal_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def default_path(output_dir: str = "output") -> str:
    return os.path.join(output_dir, "calibration.db")


def connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    """Open the calibration DB, creating schema on first write."""
    if readonly:
        abs_path = os.path.abspath(path)
        try:
            conn = sqlite3.connect(
                f"file:{abs_path}?mode=ro", uri=True, timeout=5.0,
                isolation_level=None, check_same_thread=False,
            )
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            try:
                conn.close()
            except Exception:
                pass
            conn = sqlite3.connect(
                f"file:{abs_path}?mode=ro&immutable=1", uri=True, timeout=5.0,
                isolation_level=None, check_same_thread=False,
            )
    else:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = sqlite3.connect(
            path, timeout=5.0, isolation_level=None, check_same_thread=False,
        )
        conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        conn.executescript(SCHEMA)
        _ensure_meta(conn, "schema_version", SCHEMA_VERSION)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    row = conn.execute("SELECT value FROM cal_meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO cal_meta (key, value) VALUES (?, ?)", (key, value))


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO cal_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM cal_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def delete_meta(conn: sqlite3.Connection, *keys: str) -> int:
    """Remove cal_meta rows. Returns how many were actually deleted."""
    if not keys:
        return 0
    placeholders = ",".join("?" * len(keys))
    cur = conn.execute(
        f"DELETE FROM cal_meta WHERE key IN ({placeholders})", keys,
    )
    return cur.rowcount or 0


INSERT_SAMPLE_SQL = """
INSERT INTO cal_samples (
    ts_epoch, device_id, band, frequency_hz, source, ref_id,
    power_db, expected_db, offset_db, distance_m, elevation_deg,
    weight, session_db, det_rowid
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def insert_sample(conn: sqlite3.Connection, sample: dict) -> int:
    row = (
        float(sample["ts_epoch"]),
        str(sample["device_id"]),
        str(sample["band"]),
        float(sample["frequency_hz"]),
        str(sample["source"]),
        str(sample["ref_id"]),
        float(sample["power_db"]),
        float(sample["expected_db"]),
        float(sample["offset_db"]),
        float(sample["distance_m"]),
        sample.get("elevation_deg"),
        float(sample["weight"]),
        sample.get("session_db"),
        sample.get("det_rowid"),
    )
    cur = conn.execute(INSERT_SAMPLE_SQL, row)
    return cur.lastrowid


def insert_samples(conn: sqlite3.Connection, samples: Iterable[dict]) -> int:
    """Bulk insert. Returns count written."""
    n = 0
    for s in samples:
        insert_sample(conn, s)
        n += 1
    return n


def upsert_offset(conn: sqlite3.Connection, device_id: str, band: str,
                  offset_db: float, stderr_db: float, n_samples: int,
                  method: str) -> None:
    conn.execute(
        "INSERT INTO cal_offsets "
        "(device_id, band, offset_db, stderr_db, n_samples, ts_updated, method) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(device_id, band) DO UPDATE SET "
        "offset_db = excluded.offset_db, stderr_db = excluded.stderr_db, "
        "n_samples = excluded.n_samples, ts_updated = excluded.ts_updated, "
        "method = excluded.method",
        (device_id, band, offset_db, stderr_db, n_samples, time.time(), method),
    )


def delete_offsets(conn: sqlite3.Connection, device_id: Optional[str] = None) -> None:
    if device_id:
        conn.execute("DELETE FROM cal_offsets WHERE device_id = ?", (device_id,))
    else:
        conn.execute("DELETE FROM cal_offsets")


def iter_samples(
    conn: sqlite3.Connection,
    device_id: Optional[str] = None,
    band: Optional[str] = None,
    since_epoch: Optional[float] = None,
    min_weight: Optional[float] = None,
) -> Iterator[sqlite3.Row]:
    clauses = []
    params: list = []
    if device_id:
        clauses.append("device_id = ?")
        params.append(device_id)
    if band:
        clauses.append("band = ?")
        params.append(band)
    if since_epoch is not None:
        clauses.append("ts_epoch >= ?")
        params.append(since_epoch)
    if min_weight is not None:
        clauses.append("weight >= ?")
        params.append(min_weight)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM cal_samples {where} ORDER BY ts_epoch"
    yield from conn.execute(sql, params)


def get_offsets(conn: sqlite3.Connection,
                device_id: Optional[str] = None) -> list[sqlite3.Row]:
    if device_id:
        return conn.execute(
            "SELECT * FROM cal_offsets WHERE device_id = ? ORDER BY band",
            (device_id,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM cal_offsets ORDER BY device_id, band"
    ).fetchall()


def distinct_device_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT device_id FROM cal_samples ORDER BY device_id"
    ).fetchall()
    return [r[0] for r in rows]


def seen_detection_ids(conn: sqlite3.Connection, session_db: str) -> set[int]:
    """Rowids from this session_db already ingested — used to make ingest idempotent."""
    rows = conn.execute(
        "SELECT det_rowid FROM cal_samples WHERE session_db = ? AND det_rowid IS NOT NULL",
        (session_db,),
    ).fetchall()
    return {int(r[0]) for r in rows}

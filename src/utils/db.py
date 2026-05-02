"""
SQLite backend for signal detection logging.

Single file at `output/detections.db` shared across server, scanner
subprocesses, and agent ingest. Each scanner run (or server run, or
agent ingest session) inserts a row into `sessions` and tags every
detection it writes with that `session_id`. Forwarded detections from
remote agents also carry an `agent_id` so the dashboard can split by
node without losing the originating session.

WAL mode + per-connection `busy_timeout` lets multiple writers
coexist (single SQLite write lock at a time, sub-ms serialisation
under our detection rates). The web dashboard uses a readonly
connection that won't fight for the write lock.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from typing import Any, Iterator, Optional


# Default location for the unified detection store. Callers that need
# to override (tests, alternate output dirs) pass an explicit path to
# connect().
DEFAULT_DB_FILENAME = "detections.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  REAL    NOT NULL,
    ended_at    REAL,
    label       TEXT,
    kind        TEXT    NOT NULL,
    pid         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

CREATE TABLE IF NOT EXISTS detections (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER REFERENCES sessions(id),
    agent_id       TEXT,
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
CREATE INDEX IF NOT EXISTS idx_detections_session   ON detections(session_id);
CREATE INDEX IF NOT EXISTS idx_detections_agent_ts  ON detections(agent_id, ts_epoch);
CREATE INDEX IF NOT EXISTS idx_detections_type_ts   ON detections(signal_type, ts_epoch);
CREATE INDEX IF NOT EXISTS idx_detections_ts        ON detections(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_detections_device    ON detections(device_id);
CREATE INDEX IF NOT EXISTS idx_detections_type_dev  ON detections(signal_type, device_id);

-- Whisper transcripts are keyed by audio filename (basename of the WAV
-- the FM voice pipeline writes to output/audio/). One row per audio
-- file; INSERT OR REPLACE on re-transcription.
CREATE TABLE IF NOT EXISTS transcripts (
    audio_file TEXT PRIMARY KEY,
    text       TEXT NOT NULL,
    language   TEXT,
    ts_epoch   REAL NOT NULL
);
"""


def default_db_path(output_dir: str = "output") -> str:
    """Canonical path to the unified detection DB."""
    return os.path.join(output_dir, DEFAULT_DB_FILENAME)


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
            path, timeout=10.0, isolation_level=None,
            check_same_thread=False,
        )
        # busy_timeout: under multi-writer load (server + scanner
        # subprocesses + agent ingest all hitting the same file), SQLite
        # serialises on the file write lock. Without a busy_timeout the
        # losing writer immediately raises "database is locked"; with one
        # set, it blocks up to N ms for the lock and almost always gets
        # it. 10 s is well above our typical write spacing.
        conn.executescript(
            "PRAGMA journal_mode=WAL; "
            "PRAGMA synchronous=NORMAL; "
            "PRAGMA busy_timeout=10000;"
        )
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
    session_id, agent_id,
    timestamp, ts_epoch, signal_type, frequency_hz,
    power_db, noise_floor_db, snr_db,
    channel, latitude, longitude,
    device_id, audio_file, metadata
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def insert_detection(
    conn: sqlite3.Connection,
    detection,
    session_id: Optional[int] = None,
    agent_id: Optional[str] = None,
) -> int:
    """Insert a SignalDetection (or equivalent row dict) and return its rowid.

    `session_id` and `agent_id` are tags added by the caller — the logger
    fills `session_id` from its own session row, and the agent ingest
    path fills `agent_id` from the originating node id. Both default to
    NULL when unknown.
    """
    if hasattr(detection, "__dataclass_fields__"):
        d = asdict(detection)
    else:
        d = dict(detection)
    ts = d.get("timestamp") or ""
    row = (
        session_id,
        agent_id,
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


def open_session(
    conn: sqlite3.Connection,
    kind: str,
    label: Optional[str] = None,
    pid: Optional[int] = None,
) -> int:
    """Insert a `sessions` row and return its rowid.

    `kind` examples: "server", "scanner:pmr", "scanner:adsb",
    "agent_ingest". `label` is free-form (a human-friendly name shown in
    the dashboard's session picker). `pid` lets the dashboard tell live
    sessions from orphans after a crash.
    """
    import time as _time
    cur = conn.execute(
        "INSERT INTO sessions (started_at, kind, label, pid) "
        "VALUES (?, ?, ?, ?)",
        (_time.time(), kind, label, pid),
    )
    return cur.lastrowid


def close_session(conn: sqlite3.Connection, session_id: int) -> None:
    """Stamp `ended_at` so the dashboard can mark the session inactive."""
    if session_id is None:
        return
    import time as _time
    try:
        conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (_time.time(), session_id),
        )
    except sqlite3.OperationalError:
        # Best-effort; if the connection is already torn down we don't
        # want shutdown to error out.
        pass


def row_to_dict(row: sqlite3.Row) -> dict:
    """Shape a detections row as a flat dict for the downstream readers."""
    return {
        "session_id": row["session_id"] if "session_id" in row.keys() else None,
        "agent_id": row["agent_id"] if "agent_id" in row.keys() else None,
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
    session_id: Optional[int] = None,
    agent_id: Optional[str] = None,
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
    if session_id is not None:
        clauses.append("session_id = ?")
        params.append(session_id)
    if agent_id is not None:
        clauses.append("agent_id = ?")
        params.append(agent_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM detections {where} ORDER BY id"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    yield from conn.execute(sql, params)


def max_rowid(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM detections").fetchone()
    return int(row[0]) if row else 0


def insert_transcript(conn: sqlite3.Connection, audio_file: str,
                      text: str, language: str = None) -> None:
    """Upsert a Whisper transcript keyed by audio filename (basename).
    Called from the logger's writer thread, serialized under its lock."""
    import os as _os
    import time as _time
    key = _os.path.basename(audio_file or "")
    if not key or not text:
        return
    conn.execute(
        "INSERT OR REPLACE INTO transcripts (audio_file, text, language, ts_epoch) "
        "VALUES (?, ?, ?, ?)",
        (key, text, language, _time.time()),
    )


def get_transcripts(conn: sqlite3.Connection) -> dict:
    """Return {audio_file: text} for every transcript in the DB."""
    try:
        rows = conn.execute(
            "SELECT audio_file, text FROM transcripts"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except sqlite3.OperationalError:
        # Old .db files that predate the transcripts table
        return {}

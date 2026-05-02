"""
Session listing for the web dashboard.

Sessions are rows in the `sessions` table inside the unified
`output/detections.db`. Each scanner run, server run, or agent ingest
session inserts one row at start and stamps `ended_at` at stop.

Public:
  list_sessions(output_dir)        — list every row in the sessions table
  session_exists(output_dir, sid)  — guard for ?session=<id>
"""

import os
import sqlite3
from datetime import datetime

from utils import db as _db


def list_sessions(output_dir):
    """Return all rows from the `sessions` table, newest first.

    Each session dict carries:
      id                 — row id (used as the dropdown value)
      kind               — "server" / "scanner:<type>" / "agent_ingest"
      label              — free-form label set by the producer
      started_at_iso     — ISO 8601 of `started_at`
      ended_at_iso       — ISO 8601 of `ended_at`, or "" while active
      detection_count    — COUNT(*) of detections tagged with this id
      types              — distinct signal_type list (sorted)
      first_ts / last_ts — min/max detection timestamp for this session
      live               — True if `ended_at IS NULL` (active session)
    """
    db_path = _db.default_db_path(output_dir)
    if not os.path.exists(db_path):
        return []
    try:
        conn = _db.connect(db_path, readonly=True)
    except Exception:
        return []
    try:
        try:
            sessions_rows = conn.execute(
                "SELECT id, started_at, ended_at, label, kind, pid "
                "FROM sessions ORDER BY started_at DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        out = []
        for s in sessions_rows:
            sid = int(s["id"])
            try:
                row = conn.execute(
                    "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) "
                    "FROM detections WHERE session_id = ?",
                    (sid,),
                ).fetchone()
                count = int(row[0] or 0)
                first_ts = row[1] or ""
                last_ts = row[2] or ""
                types = [
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT signal_type FROM detections "
                        "WHERE session_id = ? ORDER BY signal_type",
                        (sid,),
                    ).fetchall()
                ]
            except sqlite3.OperationalError:
                count, first_ts, last_ts, types = 0, "", "", []

            started_iso = (
                datetime.fromtimestamp(s["started_at"]).isoformat(timespec="seconds")
                if s["started_at"] else ""
            )
            ended_iso = (
                datetime.fromtimestamp(s["ended_at"]).isoformat(timespec="seconds")
                if s["ended_at"] else ""
            )
            out.append({
                "id": sid,
                "kind": s["kind"] or "",
                "label": s["label"] or "",
                "pid": s["pid"],
                "started_at_iso": started_iso,
                "ended_at_iso": ended_iso,
                "detection_count": count,
                "types": types,
                "first_ts": first_ts,
                "last_ts": last_ts,
                "live": s["ended_at"] is None,
            })
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def session_exists(output_dir, session_id):
    """Return True if `session_id` is a row in the sessions table."""
    if session_id is None:
        return False
    try:
        sid = int(session_id)
    except (TypeError, ValueError):
        return False
    db_path = _db.default_db_path(output_dir)
    if not os.path.exists(db_path):
        return False
    try:
        conn = _db.connect(db_path, readonly=True)
    except Exception:
        return False
    try:
        try:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (sid,)
            ).fetchone()
        except sqlite3.OperationalError:
            return False
        return row is not None
    finally:
        try:
            conn.close()
        except Exception:
            pass

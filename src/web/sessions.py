"""
Session discovery for the web dashboard.

Each per-run detection .db file is a "session". The session switcher
lets the user pick a historical .db from a dropdown and have category
tabs query that file instead of the currently-tailed one. The Live /
Log / Timeline / Devices tabs keep showing the active session for
this iteration.

Public:
  list_sessions(output_dir)            — list all .db files with metadata
  resolve_session_path(output_dir, name) — path-traversal-safe lookup
"""

import os
import sqlite3
from datetime import datetime


# path → (mtime, metadata_dict) cache. Historical sessions don't change,
# so after the first read we can serve their metadata indefinitely. The
# active session's mtime bumps on every detection, so we recompute it.
_metadata_cache = {}


def list_sessions(output_dir):
    """Return a list of detection .db files with metadata, newest first.

    Each session dict carries:
      name              — basename of the .db file (the dropdown value)
      mtime_iso         — last modification time
      size_bytes        — on-disk size including the main file (WAL excluded)
      detection_count   — COUNT(*) from the detections table
      types             — distinct signal_type list (sorted)
      first_ts / last_ts — min/max timestamp in the file
      live              — True for the newest file (the tailer writes here)
    """
    try:
        names = [
            f for f in os.listdir(output_dir)
            if f.endswith('.db')
            and not f.endswith('-wal')
            and not f.endswith('-shm')
        ]
    except OSError:
        return []

    sessions = []
    for name in names:
        path = os.path.join(output_dir, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        meta = _get_metadata(path, st.st_mtime)
        sessions.append({
            "name": name,
            "mtime_iso": datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds'),
            "size_bytes": st.st_size,
            "detection_count": meta.get("detection_count", 0),
            "types": meta.get("types", []),
            "first_ts": meta.get("first_ts", ""),
            "last_ts": meta.get("last_ts", ""),
            "live": False,
        })

    sessions.sort(key=lambda s: s["mtime_iso"], reverse=True)
    if sessions:
        sessions[0]["live"] = True
    return sessions


def _get_metadata(path, mtime):
    cached = _metadata_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    meta = _read_metadata(path)
    _metadata_cache[path] = (mtime, meta)
    return meta


def _read_metadata(path):
    """Read summary stats from a detection .db. Returns empty values if
    the file is unreadable or the schema is missing — never raises."""
    empty = {"detection_count": 0, "types": [], "first_ts": "", "last_ts": ""}
    try:
        uri = f"file:{os.path.abspath(path)}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    except Exception:
        return empty
    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM detections"
        ).fetchone()
        count = row[0] or 0
        first_ts = row[1] or ""
        last_ts = row[2] or ""
        types = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT signal_type FROM detections ORDER BY signal_type"
            ).fetchall()
        ]
        return {
            "detection_count": int(count),
            "types": types,
            "first_ts": first_ts,
            "last_ts": last_ts,
        }
    except sqlite3.Error:
        return empty
    finally:
        try:
            conn.close()
        except Exception:
            pass


def resolve_session_path(output_dir, session_name):
    """Given a user-supplied session name from the dropdown, return the
    absolute .db path if it's a valid session in output_dir, else None.

    Rejects anything that contains a path separator or '..', and
    anything that doesn't end in '.db'. This prevents a client from
    reading arbitrary files on disk via `?session=../../etc/passwd`.
    """
    if not session_name:
        return None
    if "/" in session_name or "\\" in session_name or ".." in session_name:
        return None
    if not session_name.endswith(".db"):
        return None
    path = os.path.join(output_dir, session_name)
    if not os.path.isfile(path):
        return None
    return path

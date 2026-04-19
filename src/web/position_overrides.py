"""
Manual source-position overrides (drag-to-reposition on the Map tab).

Persisted as `output/position_overrides.json`, keyed by source id:
  {"server": {"lat": 42.51, "lon": 1.54, "ts_epoch": 1700000000.0},
   "N01":    {...}}

Kept in its own file rather than piggybacking on `server_info.json`, which
the C2 orchestrator fully rewrites every time a capture's status changes
(see scanners/server.py). That would clobber any web-set override within
seconds. This file is only ever touched by the web handler, so it
survives restarts and scanner ticks without coordination.

Writes go through an atomic rename so a mid-write crash never leaves the
file in a half-parsed state.
"""

from __future__ import annotations

import json
import os
import threading
import tempfile
import time
from typing import Optional


FILENAME = "position_overrides.json"

# Serialise writes across the HTTP handler's worker threads. Reads can
# be lock-free — JSON is small enough that the atomic-rename write is
# effectively instantaneous from the reader's perspective.
_WRITE_LOCK = threading.Lock()


def path_for(output_dir: str) -> str:
    return os.path.join(output_dir, FILENAME)


def load(output_dir: str) -> dict:
    """Return the full overrides dict, or {} if the file is missing/broken.

    Broken = unparseable JSON or wrong top-level type. Callers should
    treat missing entries as "no override" — never as an error.
    """
    path = path_for(output_dir)
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def get(output_dir: str, source_id: str) -> Optional[dict]:
    """Return one source's override entry, or None."""
    data = load(output_dir)
    entry = data.get(source_id)
    if not isinstance(entry, dict):
        return None
    try:
        lat = float(entry.get("lat"))
        lon = float(entry.get("lon"))
    except (TypeError, ValueError):
        return None
    return {
        "lat": lat,
        "lon": lon,
        "ts_epoch": float(entry.get("ts_epoch") or 0.0),
    }


def set(output_dir: str, source_id: str, lat: float, lon: float) -> dict:
    """Upsert a single source's position. Atomic rename write.

    Returns the new override entry {lat, lon, ts_epoch}. Raises ValueError
    on out-of-range lat/lon — the caller should surface that as HTTP 400.
    """
    if not source_id or not isinstance(source_id, str):
        raise ValueError("source_id must be a non-empty string")
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        raise ValueError("lat/lon must be numeric")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise ValueError("lat/lon out of range")

    os.makedirs(output_dir, exist_ok=True)
    path = path_for(output_dir)
    entry = {"lat": round(lat, 7), "lon": round(lon, 7),
             "ts_epoch": time.time()}
    with _WRITE_LOCK:
        data = load(output_dir)
        data[source_id] = entry
        _atomic_write_json(path, data)
    return entry


def delete(output_dir: str, source_id: str) -> bool:
    """Remove an override. Returns True if removed, False if absent."""
    path = path_for(output_dir)
    with _WRITE_LOCK:
        data = load(output_dir)
        if source_id not in data:
            return False
        del data[source_id]
        _atomic_write_json(path, data)
    return True


def _atomic_write_json(path: str, data: dict) -> None:
    """Write JSON via write-then-rename so readers never see a partial file."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    # Named temp in the same dir so os.replace() is atomic (same-filesystem).
    fd, tmp = tempfile.mkstemp(prefix=".overrides_", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync not supported on every fs (e.g. tmpfs); best effort
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

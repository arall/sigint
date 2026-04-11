"""
SQL-backed category fetch.

The tailer keeps a 50k-row in-memory deque that evaporates once a busy
session rolls past the limit. Category tabs need to browse history
beyond that window, so this module reads directly from the current
SQLite detection file using the `(signal_type, ts_epoch)` index.

Each fetch returns rows shaped *exactly* like DBTailer's in-memory
detection dicts — same keys, same types — so the existing pure-function
category loaders in `web/loaders.py` consume them with no changes.
"""

import json
import time

from utils import db as _db

from .categories import CATEGORIES, category_of
from .tailer import _extract_detail


DEFAULT_WINDOW_SECONDS = 6 * 3600   # 6 hours
DEFAULT_LIMIT = 5000


def _category_predicate(category):
    """Build a SQL WHERE clause + params that matches rows belonging
    to the given category. Handles two special cases:

      cellular  — wildcard match on GSM-UPLINK-% / LTE-UPLINK-% so new
                  subtypes (e.g. LTE-UPLINK-BAND7) don't slip through
                  the IN-list.
      other     — everything that's NOT in any other category. Must
                  exclude the cellular wildcard too, otherwise LTE
                  rows would double-count.
    """
    if category == "cellular":
        return (
            "(signal_type LIKE 'GSM-UPLINK-%' OR signal_type LIKE 'LTE-UPLINK-%')",
            [],
        )

    if category == "other":
        # Known signal types that belong to one of the other categories.
        known = set()
        for cat, sigs in CATEGORIES.items():
            if cat != "other":
                known.update(sigs)
        placeholders = ",".join("?" * len(known))
        clause = (
            f"(signal_type NOT IN ({placeholders}) "
            f"AND signal_type NOT LIKE 'GSM-UPLINK-%' "
            f"AND signal_type NOT LIKE 'LTE-UPLINK-%')"
        )
        return clause, sorted(known)

    sigs = CATEGORIES.get(category, [])
    if not sigs:
        return ("1=0", [])
    placeholders = ",".join("?" * len(sigs))
    return (f"signal_type IN ({placeholders})", list(sigs))


def _row_to_detection_dict(row):
    """Shape a sqlite3.Row (from the detections table) into the exact
    dict layout that DBTailer._process_row produces, so category
    loaders don't care where the row came from."""
    try:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}

    sig = row["signal_type"] or ""
    ch = row["channel"] or ""
    freq_hz = row["frequency_hz"] or 0
    snr = row["snr_db"]
    power = row["power_db"]

    return {
        "timestamp": row["timestamp"] or "",
        "signal_type": sig,
        "category": category_of(sig),
        "frequency_mhz": round(freq_hz / 1e6, 4) if freq_hz else 0,
        "channel": ch,
        "snr_db": round(snr, 1) if snr else None,
        "power_db": power if power else None,
        "audio_file": row["audio_file"] or None,
        "detail": _extract_detail(sig, ch, meta),
        "transcript": meta.get("transcript"),
        "dev_sig": meta.get("dev_sig", ""),
        "apple_device": meta.get("apple_device", ""),
        "device_id": row["device_id"] or meta.get("bssid", ""),
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "meta": meta,
    }


def fetch_detections_for_category(
    db_path,
    category,
    window_seconds=DEFAULT_WINDOW_SECONDS,
    limit=DEFAULT_LIMIT,
    now=None,
):
    """Pull recent detections for a category from a SQLite DB and return
    them in the DBTailer deque shape (oldest first, newest last).

    Args:
        db_path: path to a detections .db file.
        category: one of 'voice', 'drones', 'aircraft', 'vessels',
                  'vehicles', 'cellular', 'other'.
        window_seconds: only rows newer than (now - window_seconds).
        limit: hard cap on rows returned (newest rows kept).
        now: override current time (for tests).

    Returns:
        list of dicts shaped like DBTailer._detections entries.
    """
    predicate, params = _category_predicate(category)
    since_epoch = (now if now is not None else time.time()) - window_seconds

    sql = (
        f"SELECT * FROM detections "
        f"WHERE {predicate} AND ts_epoch >= ? "
        f"ORDER BY id DESC LIMIT ?"
    )
    full_params = list(params) + [since_epoch, int(limit)]

    try:
        conn = _db.connect(db_path, readonly=True)
    except Exception:
        return []
    try:
        rows = list(conn.execute(sql, full_params))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    shaped = [_row_to_detection_dict(r) for r in rows]
    # We pulled newest-first; the deque is oldest-first and the loaders
    # that use `reversed(detections)` assume that ordering. Flip.
    shaped.reverse()
    return shaped

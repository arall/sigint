"""
SQL-backed fetchers for the web dashboard.

All readers open one connection to the unified `output/detections.db`
that the SignalLogger writes to. Sessions are rows in the `sessions`
table; the dashboard's session selector passes a session id which
becomes a `WHERE session_id = ?` clause.

Forwarded detections from remote agents live in the same table tagged
with `agent_id = "<aid>"`; server-local rows have `agent_id IS NULL`.
"""

import json
import os
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta

from utils import db as _db
from utils import calibration as _cal
from utils import calibration_db as _cdb

from .categories import CATEGORIES, CATEGORY_LABELS, CATEGORY_ORDER, category_of
from .tailer import _extract_detail


DEFAULT_WINDOW_SECONDS = None   # no time window — rely on DEFAULT_LIMIT
DEFAULT_LIMIT = 5000


# Cached Calibration view. Load on demand and only re-read when the
# cal DB's mtime changes, so the Map tab doesn't pay a SQLite round-trip
# on every request.
_CAL_CACHE = {"path": None, "mtime": None, "cal": _cal.Calibration.empty()}


def _get_calibration(output_dir):
    path = _cdb.default_path(output_dir)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        # No cal DB yet → empty view, but don't churn the cache.
        if _CAL_CACHE["path"] != path:
            _CAL_CACHE["path"] = path
            _CAL_CACHE["mtime"] = None
            _CAL_CACHE["cal"] = _cal.Calibration.empty()
        return _CAL_CACHE["cal"]
    if _CAL_CACHE["path"] == path and _CAL_CACHE["mtime"] == mtime:
        return _CAL_CACHE["cal"]
    _CAL_CACHE["path"] = path
    _CAL_CACHE["mtime"] = mtime
    _CAL_CACHE["cal"] = _cal.load_calibration(path)
    return _CAL_CACHE["cal"]


def _open_ro(output_dir):
    """Open a readonly connection to `output/detections.db`. Returns
    None if the file isn't there yet (no scanner has ever run)."""
    path = _db.default_db_path(output_dir)
    if not os.path.exists(path):
        return None
    try:
        return _db.connect(path, readonly=True)
    except Exception:
        return None


def _close_quiet(conn):
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def _load_transcripts(output_dir):
    """Return {audio_file: text} for every transcript in the unified DB.

    Also reads `transcripts.json` if it still exists — purely for
    backwards compatibility with sessions created before the table
    landed. The async transcriber no longer writes that file.
    """
    merged = {}
    legacy = os.path.join(output_dir, "transcripts.json")
    try:
        with open(legacy, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            merged.update(data)
    except (OSError, json.JSONDecodeError):
        pass

    conn = _open_ro(output_dir)
    if conn is None:
        return merged
    try:
        merged.update(_db.get_transcripts(conn))
    finally:
        _close_quiet(conn)
    return merged


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

    if category == "keyfobs":
        return (
            "(signal_type = 'keyfob'"
            " OR signal_type LIKE 'ISM:Microchip-HCS%'"
            " OR signal_type LIKE 'ISM:Nice-%'"
            " OR signal_type LIKE 'ISM:CAME-%'"
            " OR signal_type LIKE 'ISM:FSK%')",
            [],
        )

    if category == "tpms":
        return (
            "(signal_type = 'tpms'"
            " OR (signal_type LIKE 'ISM:%'"
            "     AND json_extract(metadata, '$.type') = 'TPMS'))",
            [],
        )

    if category == "ism":
        # ISM devices excluding keyfobs and TPMS (those have their own tabs)
        return (
            "(signal_type LIKE 'ISM:%'"
            " AND signal_type NOT LIKE 'ISM:Microchip-HCS%'"
            " AND signal_type NOT LIKE 'ISM:Nice-%'"
            " AND signal_type NOT LIKE 'ISM:CAME-%'"
            " AND signal_type NOT LIKE 'ISM:FSK%'"
            " AND COALESCE(json_extract(metadata, '$.type'), '') != 'TPMS')",
            [],
        )

    sigs = CATEGORIES.get(category, [])
    if not sigs:
        return ("1=0", [])
    placeholders = ",".join("?" * len(sigs))
    return (f"signal_type IN ({placeholders})", list(sigs))


def _row_to_detection_dict(row, transcripts=None):
    """Shape a sqlite3.Row (from the detections table) into the exact
    dict layout that DBTailer._process_row produces, so category
    loaders don't care where the row came from.

    `transcripts` is the parsed transcripts dict; if provided and the
    row has an audio_file, the text overrides whatever was in the
    metadata blob. Matches DBTailer._process_row's overlay behavior so
    the Voice tab shows transcripts no matter which path a row took to
    the renderer.
    """
    try:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}

    sig = row["signal_type"] or ""
    ch = row["channel"] or ""
    freq_hz = row["frequency_hz"] or 0
    snr = row["snr_db"]
    power = row["power_db"]
    audio_file = row["audio_file"] or None
    transcript = meta.get("transcript")
    if audio_file and transcripts:
        sidecar = transcripts.get(audio_file)
        if sidecar:
            transcript = sidecar
            meta["transcript"] = sidecar

    return {
        "timestamp": row["timestamp"] or "",
        "signal_type": sig,
        "category": category_of(sig, meta),
        "frequency_mhz": round(freq_hz / 1e6, 4) if freq_hz else 0,
        "channel": ch,
        "snr_db": round(snr, 1) if snr else None,
        "power_db": power if power else None,
        "audio_file": audio_file,
        "detail": _extract_detail(sig, ch, meta),
        "transcript": transcript,
        "dev_sig": meta.get("dev_sig", ""),
        "apple_device": meta.get("apple_device", ""),
        "device_id": row["device_id"] or meta.get("bssid", ""),
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "meta": meta,
    }


def fetch_detections_for_category(
    output_dir,
    category,
    session_id=None,
    window_seconds=DEFAULT_WINDOW_SECONDS,
    limit=DEFAULT_LIMIT,
    now=None,
    transcripts=None,
):
    """Pull recent detections for a category from the unified DB.

    Args:
        output_dir: the output directory containing detections.db.
        category: one of 'voice', 'drones', 'aircraft', 'vessels',
                  'keyfobs', 'tpms', 'cellular', 'ism', 'lora', 'pagers'.
        session_id: if set, restrict to rows from that session row.
        window_seconds: only rows newer than (now - window_seconds).
        limit: hard cap on rows returned (newest rows kept).
        now: override current time (for tests).

    Returns list of dicts shaped like DBTailer._detections entries
    (oldest first, newest last — matches the deque ordering).
    """
    predicate, params = _category_predicate(category)

    clauses = [predicate]
    if session_id is not None:
        clauses.append("session_id = ?")
        params.append(int(session_id))
    if window_seconds is not None:
        since_epoch = (now if now is not None else time.time()) - window_seconds
        clauses.append("ts_epoch >= ?")
        params.append(since_epoch)

    where = " AND ".join(clauses)
    sql = (
        f"SELECT * FROM detections "
        f"WHERE {where} "
        f"ORDER BY id DESC LIMIT ?"
    )
    full_params = list(params) + [int(limit)]

    conn = _open_ro(output_dir)
    if conn is None:
        return []
    try:
        try:
            rows = list(conn.execute(sql, full_params))
        except sqlite3.OperationalError:
            rows = []
    finally:
        _close_quiet(conn)

    if transcripts is None:
        transcripts = _load_transcripts(output_dir)
    shaped = [_row_to_detection_dict(r, transcripts) for r in rows]
    # We pulled newest-first; the deque is oldest-first and the loaders
    # that use `reversed(detections)` assume that ordering. Flip.
    shaped.reverse()
    return shaped


def _row_for_map(r, cal=None):
    freq_hz = r["frequency_hz"] or 0
    power_db = r["power_db"]
    power_db_cal = None
    cal_applied = False
    if cal is not None and power_db is not None and freq_hz:
        # Calibration is keyed on the *receiving node*. For forwarded
        # rows that's `agent_id`; for server-local rows it's `device_id`
        # (set to the local node id by the calibration ingest CLI).
        # WiFi-AP rows put the emitter BSSID in device_id — calibration
        # silently misses those, which is correct behaviour.
        node_key = r["agent_id"] if "agent_id" in r.keys() and r["agent_id"] \
            else (r["device_id"] or "")
        corrected, applied = _cal.apply_offset(
            float(power_db), node_key, float(freq_hz), cal,
        )
        if applied:
            power_db_cal = round(corrected, 1)
            cal_applied = True
    return {
        "timestamp": r["timestamp"] or "",
        "ts_epoch": r["ts_epoch"] or 0,
        "signal_type": r["signal_type"] or "",
        "freq_mhz": round(freq_hz / 1e6, 4) if freq_hz else 0,
        "power_db": power_db,
        "power_db_cal": power_db_cal,
        "cal_applied": cal_applied,
        "snr_db": round(r["snr_db"], 1) if r["snr_db"] is not None else None,
        "channel": r["channel"] or "",
    }


def fetch_agent_last_positions(output_dir):
    """Return {agent_id: {lat, lon, ts_epoch}} from each agent's most
    recently *inserted* geo-tagged detection.

    Picks rows by `id DESC` so it's deterministic even when multiple
    rows share the same ts_epoch (outbox retries on the same original
    detection).
    """
    conn = _open_ro(output_dir)
    if conn is None:
        return {}
    out = {}
    try:
        cur = conn.execute(
            "SELECT agent_id, ts_epoch, latitude, longitude "
            "FROM detections "
            "WHERE agent_id IS NOT NULL "
            "  AND latitude IS NOT NULL AND longitude IS NOT NULL "
            "ORDER BY id DESC"
        )
        for r in cur:
            aid = r["agent_id"]
            if not aid or aid in out:
                continue
            out[aid] = {
                "lat": r["latitude"],
                "lon": r["longitude"],
                "ts_epoch": r["ts_epoch"] or 0,
            }
    except sqlite3.OperationalError:
        pass
    finally:
        _close_quiet(conn)
    return out


def fetch_detections_by_source(output_dir, limit_per_source=200,
                                window_seconds=None, now=None):
    """Group recent detections by data source.

    A source is either:
      - "server": rows with `agent_id IS NULL` (server-local captures).
      - "<agent_id>": rows forwarded over the Meshtastic C2 mesh from a
        remote agent.

    `window_seconds`, if set, restricts to rows newer than (now - window).
    Uses ts_epoch (the agent's original detection time on forwarded
    rows, the local time on server-local rows).

    Returns {source_id: [rows newest-first]}, capped per source.
    """
    if now is None:
        now = time.time()
    since = (now - window_seconds) if window_seconds else None
    cal = _get_calibration(output_dir)

    conn = _open_ro(output_dir)
    if conn is None:
        return {}
    out = {}
    try:
        if since is not None:
            cur = conn.execute(
                "SELECT timestamp, ts_epoch, signal_type, frequency_hz, "
                "power_db, snr_db, channel, device_id, agent_id "
                "FROM detections "
                "WHERE ts_epoch >= ? "
                "ORDER BY id DESC",
                (since,),
            )
        else:
            cur = conn.execute(
                "SELECT timestamp, ts_epoch, signal_type, frequency_hz, "
                "power_db, snr_db, channel, device_id, agent_id "
                "FROM detections "
                "ORDER BY id DESC LIMIT ?",
                (limit_per_source * 32,),
            )
        for r in cur:
            key = r["agent_id"] or "server"
            lst = out.setdefault(key, [])
            if len(lst) >= limit_per_source:
                continue
            lst.append(_row_for_map(r, cal=cal))
    except sqlite3.OperationalError:
        pass
    finally:
        _close_quiet(conn)
    return out


def fetch_agent_detections(output_dir, limit=50, offset=0):
    """Return a page of detections forwarded from mesh agents.

    Filters on `agent_id IS NOT NULL` so server-local captures don't
    show up. Sorted by `id DESC` (arrival order).

    Returns (rows, total).
    """
    conn = _open_ro(output_dir)
    if conn is None:
        return [], 0
    try:
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM detections WHERE agent_id IS NOT NULL"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return [], 0
        try:
            cur = conn.execute(
                "SELECT timestamp, ts_epoch, signal_type, frequency_hz, "
                "power_db, snr_db, latitude, longitude, channel, agent_id "
                "FROM detections "
                "WHERE agent_id IS NOT NULL "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (int(limit), max(0, int(offset))),
            )
        except sqlite3.OperationalError:
            return [], int(total or 0)
        rows = []
        for r in cur:
            freq_hz = r["frequency_hz"] or 0
            rows.append({
                "timestamp": r["timestamp"] or "",
                "ts_epoch": r["ts_epoch"] or 0,
                "agent_id": r["agent_id"] or "",
                "signal_type": r["signal_type"] or "",
                "freq_mhz": round(freq_hz / 1e6, 4) if freq_hz else 0,
                "power_db": r["power_db"],
                "snr_db": round(r["snr_db"], 1) if r["snr_db"] is not None else None,
                "latitude": r["latitude"],
                "longitude": r["longitude"],
                "channel": r["channel"] or "",
            })
        return rows, int(total or 0)
    finally:
        _close_quiet(conn)


def fetch_recent_detections(
    output_dir,
    limit=50,
    offset=0,
    signal_type=None,
    transcripts=None,
):
    """Newest-first detection rows for the Log tab. Optional type
    filter; overlays the transcripts sidecar on voice rows."""
    if transcripts is None:
        transcripts = _load_transcripts(output_dir)

    conn = _open_ro(output_dir)
    if conn is None:
        return []
    try:
        try:
            if signal_type:
                cur = conn.execute(
                    "SELECT * FROM detections WHERE signal_type = ? "
                    "ORDER BY id DESC LIMIT ? OFFSET ?",
                    (signal_type, int(limit), max(0, int(offset))),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM detections "
                    "ORDER BY id DESC LIMIT ? OFFSET ?",
                    (int(limit), max(0, int(offset))),
                )
            return [_row_to_detection_dict(r, transcripts) for r in cur]
        except sqlite3.OperationalError:
            return []
    finally:
        _close_quiet(conn)


def fetch_activity_histogram(output_dir, minutes=60, now=None):
    """Per-minute detection counts over the last `minutes` wall-clock
    minutes. Returns a list of
      {"minute": "YYYY-MM-DDTHH:MM", "counts": {sig: n, ...}, "total": N}
    with one entry per minute even when empty."""
    now_ts = now if now is not None else time.time()
    since_epoch = now_ts - minutes * 60

    counts = {}   # minute_key → Counter()
    conn = _open_ro(output_dir)
    if conn is not None:
        try:
            for r in conn.execute(
                "SELECT substr(timestamp, 1, 16) AS minute, signal_type, "
                "       COUNT(*) AS n "
                "FROM detections WHERE ts_epoch >= ? "
                "GROUP BY minute, signal_type",
                (since_epoch,),
            ).fetchall():
                m = r["minute"] or ""
                if not m:
                    continue
                counts.setdefault(m, Counter())[r["signal_type"] or ""] += int(r["n"] or 0)
        except sqlite3.OperationalError:
            pass
        finally:
            _close_quiet(conn)

    # Fill zero minutes so the chart is smooth
    result = []
    now_dt = datetime.fromtimestamp(now_ts)
    for i in range(minutes - 1, -1, -1):
        t = now_dt - timedelta(minutes=i)
        key = t.strftime("%Y-%m-%dT%H:%M")
        c = counts.get(key, Counter())
        result.append({
            "minute": key,
            "counts": dict(c),
            "total": sum(c.values()),
        })
    return result


# Per-signal-type unique-id extraction, pushed into SQL via json_extract
# so the Live tab's aggregate query stays fast even with tens of
# thousands of rows. The CASE expression mirrors the _extract_uid
# Python helper in tailer.py — keep them in sync.
_UNIQUES_SQL = """
SELECT DISTINCT signal_type, uid FROM (
    SELECT signal_type,
        CASE signal_type
            WHEN 'BLE-Adv'    THEN COALESCE(json_extract(metadata, '$.persona_id'), channel)
            WHEN 'WiFi-Probe' THEN COALESCE(json_extract(metadata, '$.persona_id'), device_id)
            WHEN 'WiFi-AP'    THEN COALESCE(json_extract(metadata, '$.bssid'), device_id)
            WHEN 'ADS-B'      THEN COALESCE(json_extract(metadata, '$.icao'), channel)
            WHEN 'keyfob'     THEN json_extract(metadata, '$.data_hex')
            WHEN 'tpms'       THEN json_extract(metadata, '$.sensor_id')
            WHEN 'lora'       THEN CAST(frequency_hz AS INTEGER)
            WHEN 'PMR446'     THEN channel
            WHEN 'dPMR'       THEN channel
            WHEN '70cm'       THEN channel
            WHEN 'MarineVHF'  THEN channel
            WHEN '2m'         THEN channel
            WHEN 'FRS'        THEN channel
            ELSE NULL
        END AS uid
    FROM detections
)
WHERE uid IS NOT NULL AND uid != ''
"""


# Signal type display order for the Live tab (matches the old tailer).
_LIVE_TYPE_ORDER = [
    "PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS",
    "RemoteID", "DroneCtrl",
    "keyfob", "tpms", "lora", "ISM",
    "ADS-B",
    "GSM-UPLINK-GSM-900", "GSM-UPLINK-GSM-850",
    "pocsag",
    "BLE-Adv", "WiFi-Probe",
]


def fetch_live_state(output_dir, transcripts=None, recent_events_limit=20):
    """Aggregated Live-tab state: per-type counts / uniques / last-seen /
    last-SNR / last-detail, rolled into categories, plus a recent-events
    feed. Replaces DBTailer.get_state's in-memory counters.

    Computed on demand via SQL on every call. The heavy lifting is:
      - SELECT signal_type, COUNT, MAX(snr), MAX(ts_epoch)  GROUP BY type
      - SELECT signal_type, metadata  FROM latest row per type
      - SELECT last N rows for the Recent feed
    """
    if transcripts is None:
        transcripts = _load_transcripts(output_dir)

    per_type = {}        # sig → {count, last_ts, last_snr, last_detail_row}
    unique_ids = {}      # sig → set of uid strings
    recent_rows = []
    total = 0

    conn = _open_ro(output_dir)
    if conn is None:
        return {
            "detection_count": 0,
            "signals": [],
            "categories": [],
            "recent": [],
        }
    try:
        # Per-type aggregates
        try:
            for r in conn.execute(
                "SELECT signal_type, COUNT(*) AS n, "
                "       MAX(ts_epoch) AS last_epoch, "
                "       MAX(timestamp) AS last_ts "
                "FROM detections GROUP BY signal_type"
            ).fetchall():
                sig = r["signal_type"] or ""
                per_type[sig] = {
                    "count": int(r["n"] or 0),
                    "last_epoch": float(r["last_epoch"] or 0),
                    "last_ts": r["last_ts"] or "",
                    "last_snr": None,
                    "last_detail_row": None,
                }
                total += int(r["n"] or 0)
        except sqlite3.OperationalError:
            pass

        # Newest row per signal_type for last_detail extraction + last_snr
        try:
            for r in conn.execute(
                "SELECT * FROM ("
                "  SELECT *, ROW_NUMBER() OVER ("
                "    PARTITION BY signal_type ORDER BY id DESC"
                "  ) AS rn FROM detections"
                ") WHERE rn = 1"
            ).fetchall():
                sig = r["signal_type"] or ""
                agg = per_type.get(sig)
                if not agg:
                    continue
                agg["last_detail_row"] = r
                if r["snr_db"]:
                    agg["last_snr"] = float(r["snr_db"])
        except sqlite3.OperationalError:
            pass

        # Uniques per type
        try:
            for r in conn.execute(_UNIQUES_SQL).fetchall():
                sig = r["signal_type"] or ""
                uid = r["uid"]
                if uid is None or uid == "":
                    continue
                unique_ids.setdefault(sig, set()).add(str(uid))
        except sqlite3.OperationalError:
            pass

        # Recent events feed
        try:
            for r in conn.execute(
                "SELECT timestamp, signal_type, channel, frequency_hz, snr_db, metadata "
                "FROM detections ORDER BY id DESC LIMIT ?",
                (recent_events_limit,),
            ).fetchall():
                ts = r["timestamp"] or ""
                sig = r["signal_type"] or ""
                ch = r["channel"] or ""
                try:
                    freq = float(r["frequency_hz"] or 0)
                except (ValueError, TypeError):
                    freq = 0
                try:
                    snr = float(r["snr_db"] or 0)
                except (ValueError, TypeError):
                    snr = 0
                try:
                    meta = json.loads(r["metadata"]) if r["metadata"] else {}
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                ts_short = ts.split("T")[1].split(".")[0] if "T" in ts else ""
                detail = _extract_detail(sig, ch, meta)
                line = (f"{ts_short}  {sig:12s} {ch:6s}  "
                        f"{freq/1e6:8.3f} MHz  {snr:5.1f} dB  {detail}")
                recent_rows.append((ts, sig, line))
        except sqlite3.OperationalError:
            pass
    finally:
        _close_quiet(conn)

    # Assemble signals list in canonical display order
    seen = set(per_type.keys())
    ordered_types = [t for t in _LIVE_TYPE_ORDER if t in seen]
    ordered_types += sorted(seen - set(_LIVE_TYPE_ORDER))

    signals = []
    for sig in ordered_types:
        agg = per_type[sig]
        row = agg["last_detail_row"]
        if row is not None:
            try:
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            audio = row["audio_file"]
            if audio and transcripts and transcripts.get(audio):
                meta["transcript"] = transcripts[audio]
            detail = _extract_detail(sig, row["channel"] or "", meta)
        else:
            detail = ""
        last_ts_short = ""
        if "T" in agg["last_ts"]:
            last_ts_short = agg["last_ts"].split("T")[1].split(".")[0]
        signals.append({
            "type": sig,
            "category": category_of(sig),
            "count": agg["count"],
            "uniques": len(unique_ids.get(sig, set())),
            "last_seen": last_ts_short,
            "snr": round(agg["last_snr"], 1) if agg["last_snr"] else None,
            "detail": detail,
        })

    # Roll up into category summary rows
    cat_counts = Counter()
    cat_uniques = {}
    cat_last_seen = {}
    cat_types = {}
    for s in signals:
        c = s["category"]
        cat_counts[c] += s["count"]
        cat_uniques.setdefault(c, 0)
        cat_uniques[c] += s["uniques"]
        prev = cat_last_seen.get(c, "")
        if s["last_seen"] and s["last_seen"] > prev:
            cat_last_seen[c] = s["last_seen"]
        cat_types.setdefault(c, []).append(s["type"])
    categories = [
        {
            "id": c,
            "label": CATEGORY_LABELS[c],
            "count": cat_counts.get(c, 0),
            "uniques": cat_uniques.get(c, 0),
            "last_seen": cat_last_seen.get(c, ""),
            "types": cat_types.get(c, []),
        }
        for c in CATEGORY_ORDER if cat_counts.get(c, 0) > 0
    ]

    # Recent events: newest 20 across all types
    recent_rows.sort(key=lambda x: x[0], reverse=True)
    recent = [
        {"type": sig, "line": line}
        for _, sig, line in recent_rows[:recent_events_limit]
    ]

    return {
        "detection_count": total,
        "signals": signals,
        "categories": categories,
        "recent": recent,
    }


def fetch_active_dev_sigs(output_dir, minutes=5, now=None):
    """Return {dev_sig: {rssi, apple_device}} for BLE / WiFi-probe personas
    detected in the last N minutes. Drives the 'active' flag + last_rssi
    on the Devices tab's BLE + WiFi Clients sub-tables."""
    now_ts = now if now is not None else time.time()
    since_epoch = now_ts - minutes * 60

    active = {}
    conn = _open_ro(output_dir)
    if conn is None:
        return active
    try:
        try:
            rows = conn.execute(
                "SELECT power_db, metadata FROM detections "
                "WHERE ts_epoch >= ? AND signal_type IN ('BLE-Adv', 'WiFi-Probe') "
                "ORDER BY id DESC",
                (since_epoch,),
            ).fetchall()
        except sqlite3.OperationalError:
            return active
    finally:
        _close_quiet(conn)

    for r in rows:
        try:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        dev_sig = meta.get("dev_sig")
        if not dev_sig or dev_sig in active:
            continue
        active[dev_sig] = {
            "rssi": r["power_db"] if r["power_db"] else None,
            "apple_device": meta.get("apple_device", ""),
        }
    return active


def fetch_active_bssids(output_dir, minutes=5, now=None):
    """Return {bssid: {rssi, last_seen}} for WiFi APs seen in the last N
    minutes. Drives the 'active' flag on the Devices tab's WiFi APs
    sub-table."""
    now_ts = now if now is not None else time.time()
    since_epoch = now_ts - minutes * 60

    active = {}
    conn = _open_ro(output_dir)
    if conn is None:
        return active
    try:
        try:
            rows = conn.execute(
                "SELECT power_db, device_id, timestamp, metadata "
                "FROM detections "
                "WHERE ts_epoch >= ? AND signal_type = 'WiFi-AP' "
                "ORDER BY id DESC",
                (since_epoch,),
            ).fetchall()
        except sqlite3.OperationalError:
            return active
    finally:
        _close_quiet(conn)

    for r in rows:
        try:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        bssid = meta.get("bssid") or (r["device_id"] or "")
        if not bssid or bssid in active:
            continue
        active[bssid] = {
            "rssi": r["power_db"] if r["power_db"] else None,
            "last_seen": r["timestamp"] or "",
        }
    return active


_CORR_CACHE = {}
_CORR_CACHE_TTL_S = 60.0
_CORR_LOOKBACK_S = 6 * 3600.0
_CORR_SKIP_SIGNALS = {"ADS-B", "AIS"}
_CORR_MAX_PAIRS = 500


def fetch_correlations(output_dir, window_s=30.0, threshold=0.5):
    """Compute device correlations on demand from the unified DB.

    Returns the same dict shape the legacy DeviceCorrelator export
    produced so the UI renderer doesn't change:
        {timestamp, window_s, threshold, total_devices,
         correlated_pairs, clusters}
    """
    import time as _time
    from utils.correlator import DeviceCorrelator
    from datetime import datetime as _dt

    now = _time.time()
    cache_key = (round(window_s, 3), round(threshold, 3))
    cached = _CORR_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _CORR_CACHE_TTL_S:
        return cached[1]

    since_epoch = now - _CORR_LOOKBACK_S
    c = DeviceCorrelator(window_s=window_s, threshold=threshold)
    db_path = _db.default_db_path(output_dir)
    if os.path.exists(db_path):
        try:
            c.load_db(db_path, since_epoch=since_epoch)
        except Exception:
            pass

    for sig in _CORR_SKIP_SIGNALS:
        prefix = f"{sig}:"
        for uid in [u for u in c._observations if u.startswith(prefix)]:
            del c._observations[uid]

    try:
        pairs = c.correlate()
    except Exception:
        pairs = []
    try:
        clusters = c.find_clusters()
    except Exception:
        clusters = []
    total_pairs = len(pairs)
    if total_pairs > _CORR_MAX_PAIRS:
        pairs = pairs[:_CORR_MAX_PAIRS]

    result = {
        "timestamp": _dt.now().isoformat(),
        "window_s": window_s,
        "threshold": threshold,
        "lookback_s": _CORR_LOOKBACK_S,
        "total_devices": c.device_count,
        "total_pairs": total_pairs,
        "correlated_pairs": pairs,
        "clusters": clusters,
    }
    _CORR_CACHE[cache_key] = (now, result)
    return result

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
import os
import time
from collections import Counter
from datetime import datetime, timedelta

from utils import db as _db

from .categories import CATEGORIES, CATEGORY_LABELS, CATEGORY_ORDER, category_of
from .tailer import _extract_detail, _extract_uid


DEFAULT_WINDOW_SECONDS = None   # no time window — rely on DEFAULT_LIMIT
DEFAULT_LIMIT = 5000


def _load_transcripts_for_db(db_path):
    """Read the `transcripts` table from one detection .db and return
    {audio_file: text}. Empty dict on any read error or missing table
    (old .db files predating the transcripts table schema)."""
    try:
        conn = _db.connect(db_path, readonly=True)
    except Exception:
        return {}
    try:
        return _db.get_transcripts(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _load_transcripts(output_dir):
    """Union transcripts from every .db file in `output_dir`. Used by
    the single-file session fetch path when the caller didn't pre-load;
    the multi-file fetchers call `_load_transcripts_for_db` per file
    to keep each .db's transcripts scoped to its own detections.

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

    from .sessions import is_session_db_name
    try:
        names = [f for f in os.listdir(output_dir) if is_session_db_name(f)]
    except OSError:
        return merged
    for name in names:
        path = os.path.join(output_dir, name)
        merged.update(_load_transcripts_for_db(path))
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

    `transcripts` is the parsed transcripts.json sidecar; if provided
    and the row has an audio_file, the sidecar's text overrides
    whatever was in the metadata blob. Matches DBTailer._process_row's
    overlay behavior so the Voice tab shows transcripts no matter
    which path a row took to the renderer.
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
    db_path,
    category,
    window_seconds=DEFAULT_WINDOW_SECONDS,
    limit=DEFAULT_LIMIT,
    now=None,
    transcripts=None,
):
    """Pull recent detections for a category from a SQLite DB and return
    them in the DBTailer deque shape (oldest first, newest last).

    Args:
        db_path: path to a detections .db file.
        category: one of 'voice', 'drones', 'aircraft', 'vessels',
                  'keyfobs', 'tpms', 'cellular', 'ism', 'lora', 'pagers'.
        window_seconds: only rows newer than (now - window_seconds).
        limit: hard cap on rows returned (newest rows kept).
        now: override current time (for tests).

    Returns:
        list of dicts shaped like DBTailer._detections entries.
    """
    predicate, params = _category_predicate(category)

    if window_seconds is None:
        sql = (
            f"SELECT * FROM detections "
            f"WHERE {predicate} "
            f"ORDER BY id DESC LIMIT ?"
        )
        full_params = list(params) + [int(limit)]
    else:
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

    # If the caller didn't pre-load transcripts, read them from this
    # one .db's `transcripts` table. The union fetcher pre-loads across
    # all .db files and passes the merged dict in so we don't re-query
    # the same table N times.
    if transcripts is None:
        transcripts = _load_transcripts_for_db(db_path)
    shaped = [_row_to_detection_dict(r, transcripts) for r in rows]
    # We pulled newest-first; the deque is oldest-first and the loaders
    # that use `reversed(detections)` assume that ordering. Flip.
    shaped.reverse()
    return shaped


def fetch_detections_for_category_all(
    output_dir,
    category,
    window_seconds=DEFAULT_WINDOW_SECONDS,
    limit=DEFAULT_LIMIT,
    now=None,
):
    # Load transcripts once across all files in this directory so every
    # voice row can overlay its Whisper text without re-reading the sidecar
    # per .db file.
    transcripts = _load_transcripts(output_dir)
    """Union the category fetch across *every* .db file in an output dir.

    The single-file fetcher above is scoped to one session — which breaks
    for standalone scanners that write to their own DB (e.g. `sdr.py pmr`
    as a server subprocess writes to pmr446_*.db, while the main server
    writes server_*.db). In LIVE mode the user expects /api/cat/voice to
    see voice transmissions regardless of which file carried them; this
    helper does the union.

    When the user picks a specific session from the header dropdown we
    stay on the single-file path so the UI respects their scope.
    """
    from .sessions import is_session_db_name
    try:
        names = sorted(f for f in os.listdir(output_dir) if is_session_db_name(f))
    except OSError:
        return []

    merged = []
    for name in names:
        path = os.path.join(output_dir, name)
        rows = fetch_detections_for_category(
            path, category,
            window_seconds=window_seconds,
            limit=limit,
            now=now,
            transcripts=transcripts,
        )
        merged.extend(rows)

    # Sort by timestamp (oldest first, matching single-file output), then
    # keep only the most recent `limit` rows across all files.
    merged.sort(key=lambda r: r.get("timestamp", ""))
    if len(merged) > limit:
        merged = merged[-limit:]
    return merged


# ---------------------------------------------------------------------------
# Generic SQL helpers — back the Log tab, Timeline tab, Live tab, Devices
# tab active flag, and the SSE state stream. They all union across every
# .db file in the output dir so a standalone scanner subprocess writing
# to its own file (pmr446_*.db, adsb_*.db, …) doesn't hide detections
# from the dashboard.
# ---------------------------------------------------------------------------

def _iter_db_paths(output_dir):
    """Yield every session .db file in `output_dir`, sorted alphabetically
    so the order across calls is stable (makes debugging less confusing).
    Excludes support DBs like devices.db (persistent persona/AP store)."""
    from .sessions import is_session_db_name
    try:
        names = sorted(
            f for f in os.listdir(output_dir)
            if is_session_db_name(f)
        )
    except OSError:
        return
    for name in names:
        yield os.path.join(output_dir, name)


def fetch_agent_last_positions(output_dir):
    """Return {agent_id: {lat, lon, ts_epoch}} from each agent's most
    recently *inserted* geo-tagged detection.

    Iterates agents_*.db newest-first and picks the first match per
    agent by rowid DESC — that's deterministic even when multiple rows
    share the same ts_epoch (outbox retries on the same original
    detection) and avoids the SQLite `MAX() + bare-columns` quirk
    where the returned lat/lon can come from a different row than the
    one with the max timestamp.
    """
    try:
        names = sorted(
            (f for f in os.listdir(output_dir)
             if f.startswith("agents_") and f.endswith(".db")),
            reverse=True,
        )
    except OSError:
        return {}
    out: dict = {}
    seen_ids: set = set()
    for name in names:
        path = os.path.join(output_dir, name)
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            # Pull the newest geo-tagged row per agent in this DB.
            cur = conn.execute(
                "SELECT device_id, ts_epoch, latitude, longitude "
                "FROM detections "
                "WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
                "ORDER BY id DESC"
            )
            for r in cur:
                aid = r["device_id"]
                if not aid or aid in seen_ids:
                    continue
                seen_ids.add(aid)
                out[aid] = {
                    "lat": r["latitude"],
                    "lon": r["longitude"],
                    "ts_epoch": r["ts_epoch"] or 0,
                }
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return out


def _row_for_map(r):
    freq_hz = r["frequency_hz"] or 0
    return {
        "timestamp": r["timestamp"] or "",
        "ts_epoch": r["ts_epoch"] or 0,
        "signal_type": r["signal_type"] or "",
        "freq_mhz": round(freq_hz / 1e6, 4) if freq_hz else 0,
        "power_db": r["power_db"],
        "snr_db": round(r["snr_db"], 1) if r["snr_db"] is not None else None,
        "channel": r["channel"] or "",
    }


def fetch_detections_by_source(output_dir, limit_per_source=200,
                                window_seconds=None, now=None):
    """Group recent detections by data source (where the RF was captured).

    Two kinds of source:
      - "server": rows written by server-local captures. Anything in a
        session DB whose filename doesn't start with "agents_".
      - "<agent_id>": rows forwarded over the Meshtastic C2 mesh from a
        remote agent. These live exclusively in agents_*.db, where
        AgentManager sets device_id to the agent_id it received from.

    `window_seconds`, if set, restricts to rows newer than (now - window).
    Uses ts_epoch so it follows the user's notion of "when the emitter
    was heard", which for DET rows is the agent's original detection
    time (outbox retries carry the original ts_unix).

    Returns {source_id: [rows newest-first]}, capped per source.
    """
    from .sessions import is_session_db_name
    try:
        names = sorted(
            (f for f in os.listdir(output_dir) if is_session_db_name(f)),
            reverse=True,
        )
    except OSError:
        return {}
    if now is None:
        import time as _time
        now = _time.time()
    since = (now - window_seconds) if window_seconds else None
    out: dict = {}
    for name in names:
        path = os.path.join(output_dir, name)
        is_agent_db = name.startswith("agents_")
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            if since is not None:
                cur = conn.execute(
                    "SELECT timestamp, ts_epoch, signal_type, frequency_hz, "
                    "power_db, snr_db, channel, device_id FROM detections "
                    "WHERE ts_epoch >= ? ORDER BY id DESC LIMIT ?",
                    (since, limit_per_source * 4),
                )
            else:
                cur = conn.execute(
                    "SELECT timestamp, ts_epoch, signal_type, frequency_hz, "
                    "power_db, snr_db, channel, device_id FROM detections "
                    "ORDER BY id DESC LIMIT ?",
                    (limit_per_source * 4,),
                )
            for r in cur:
                if is_agent_db:
                    key = r["device_id"] or "server"
                else:
                    key = "server"
                lst = out.setdefault(key, [])
                if len(lst) >= limit_per_source:
                    continue
                lst.append(_row_for_map(r))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return out


def fetch_agent_detections(output_dir, limit=50, offset=0):
    """Return a page of detections forwarded from mesh agents.

    Scopes to `agents_*.db` only so server-local captures don't show up.
    Sorted by **arrival** (newest session DB first, newest rowid within),
    not detection timestamp — outbox retries can carry hours-old ts_unix
    values, which would otherwise hide freshly-ingested rows behind
    ancient re-forwarded ones.

    Pagination: skip the first `offset` arrival-ordered rows, then
    return the next `limit`. Also returns the total count across every
    agents_*.db so the UI can render page controls.

    Returns (rows, total).
    """
    try:
        names = sorted(
            (f for f in os.listdir(output_dir)
             if f.startswith("agents_") and f.endswith(".db")),
            reverse=True,
        )
    except OSError:
        return [], 0

    # Pre-count so the UI knows how many pages exist without a second RTT.
    total = 0
    per_db_counts = []
    for name in names:
        path = os.path.join(output_dir, name)
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            per_db_counts.append((path, 0))
            continue
        try:
            n = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
            per_db_counts.append((path, n))
            total += n
        except Exception:
            per_db_counts.append((path, 0))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Walk DBs newest-first, skipping `offset` rows total, then collecting
    # up to `limit`. SQLite OFFSET is cheap enough on the indexed id DESC
    # path; we tell each DB how many to skip and how many to take.
    rows = []
    skip = max(0, offset)
    want = max(0, limit)
    for path, count in per_db_counts:
        if want <= 0:
            break
        if skip >= count:
            skip -= count
            continue
        take = min(want, count - skip)
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            cur = conn.execute(
                "SELECT timestamp, ts_epoch, signal_type, frequency_hz, "
                "power_db, snr_db, latitude, longitude, channel, device_id "
                "FROM detections ORDER BY id DESC LIMIT ? OFFSET ?",
                (take, skip),
            )
            for r in cur:
                freq_hz = r["frequency_hz"] or 0
                rows.append({
                    "timestamp": r["timestamp"] or "",
                    "ts_epoch": r["ts_epoch"] or 0,
                    "agent_id": r["device_id"] or "",
                    "signal_type": r["signal_type"] or "",
                    "freq_mhz": round(freq_hz / 1e6, 4) if freq_hz else 0,
                    "power_db": r["power_db"],
                    "snr_db": round(r["snr_db"], 1) if r["snr_db"] is not None else None,
                    "latitude": r["latitude"],
                    "longitude": r["longitude"],
                    "channel": r["channel"] or "",
                })
            want -= take
            skip = 0
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return rows, total


def fetch_recent_detections(
    output_dir,
    limit=50,
    offset=0,
    signal_type=None,
    transcripts=None,
):
    """Newest-first detection rows for the Log tab. Unions across all .db
    files in the output dir, applies optional type filter, overlays the
    transcripts sidecar on voice rows."""
    if transcripts is None:
        transcripts = _load_transcripts(output_dir)

    per_file_limit = limit + offset
    merged = []
    for path in _iter_db_paths(output_dir):
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            if signal_type:
                sql = ("SELECT * FROM detections WHERE signal_type = ? "
                       "ORDER BY id DESC LIMIT ?")
                params = [signal_type, per_file_limit]
            else:
                sql = "SELECT * FROM detections ORDER BY id DESC LIMIT ?"
                params = [per_file_limit]
            for row in conn.execute(sql, params):
                merged.append(_row_to_detection_dict(row, transcripts))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    merged.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return merged[offset:offset + limit]


def fetch_activity_histogram(output_dir, minutes=60, now=None):
    """Per-minute detection counts over the last `minutes` wall-clock
    minutes. Returns a list of
      {"minute": "YYYY-MM-DDTHH:MM", "counts": {sig: n, ...}, "total": N}
    with one entry per minute even when empty."""
    now_ts = now if now is not None else time.time()
    since_epoch = now_ts - minutes * 60

    counts = {}   # minute_key → Counter()
    for path in _iter_db_paths(output_dir):
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            rows = conn.execute(
                "SELECT substr(timestamp, 1, 16) AS minute, signal_type, "
                "       COUNT(*) AS n "
                "FROM detections WHERE ts_epoch >= ? "
                "GROUP BY minute, signal_type",
                (since_epoch,),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        for r in rows:
            m = r["minute"] or ""
            if not m:
                continue
            counts.setdefault(m, Counter())[r["signal_type"] or ""] += int(r["n"] or 0)

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
# so the Live tab's aggregate query stays fast (~10 ms per DB file) even
# with tens of thousands of rows. The CASE expression mirrors the
# _extract_uid Python helper in tailer.py — keep them in sync.
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
      - SELECT signal_type, metadata  FROM latest row per type  (window fn)
      - SELECT last N rows across all files for the Recent feed

    On a 10k-row DB this is a few ms total — cheap enough to run on
    every SSE tick. The work scales linearly with DB count (multi-session
    dirs). Caller supplies `transcripts` if it already has them loaded.
    """
    if transcripts is None:
        transcripts = _load_transcripts(output_dir)

    per_type = {}        # sig → {count, last_ts, last_snr, last_detail_id, last_row}
    unique_ids = {}      # sig → set of uid strings
    recent_rows = []     # list of (timestamp, signal_type, line) tuples

    total = 0
    for path in _iter_db_paths(output_dir):
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            # Per-type aggregates in one query
            for r in conn.execute(
                "SELECT signal_type, COUNT(*) AS n, "
                "       MAX(ts_epoch) AS last_epoch, "
                "       MAX(timestamp) AS last_ts "
                "FROM detections GROUP BY signal_type"
            ).fetchall():
                sig = r["signal_type"] or ""
                agg = per_type.setdefault(sig, {
                    "count": 0,
                    "last_epoch": 0.0,
                    "last_ts": "",
                    "last_snr": None,
                    "last_detail_row": None,
                })
                agg["count"] += int(r["n"] or 0)
                le = float(r["last_epoch"] or 0)
                if le > agg["last_epoch"]:
                    agg["last_epoch"] = le
                    agg["last_ts"] = r["last_ts"] or ""
                total += int(r["n"] or 0)

            # Fetch the newest row per signal_type for last_detail extraction
            # and last_snr. Uses a window function, available in SQLite ≥3.25.
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
                # Keep the row with the highest ts_epoch across files
                if r["ts_epoch"] and r["ts_epoch"] >= agg["last_epoch"] - 1e-9:
                    agg["last_detail_row"] = r
                    if r["snr_db"]:
                        agg["last_snr"] = float(r["snr_db"])

            # Uniques per type — _extract_uid's logic is per-type and
            # depends on the metadata JSON. Push it into SQL via
            # json_extract so we avoid the per-row Python round-trip.
            # Keeps the query O(unique values) instead of O(total rows).
            for r in conn.execute(_UNIQUES_SQL).fetchall():
                sig = r["signal_type"] or ""
                uid = r["uid"]
                if uid is None or uid == "":
                    continue
                unique_ids.setdefault(sig, set()).add(str(uid))

            # Recent events feed — newest N rows from this file
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
                # Overlay transcript sidecar for voice rows
                if meta.get("audio_file") and transcripts:
                    pass  # audio_file is actually in the row, not meta
                ts_short = ts.split("T")[1].split(".")[0] if "T" in ts else ""
                detail = _extract_detail(sig, ch, meta)
                line = (f"{ts_short}  {sig:12s} {ch:6s}  "
                        f"{freq/1e6:8.3f} MHz  {snr:5.1f} dB  {detail}")
                recent_rows.append((ts, sig, line))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Assemble signals list in the canonical display order
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
            # Overlay transcript sidecar on voice
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

    # Recent events: newest 20 across all files
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
    for path in _iter_db_paths(output_dir):
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            rows = conn.execute(
                "SELECT power_db, metadata FROM detections "
                "WHERE ts_epoch >= ? AND signal_type IN ('BLE-Adv', 'WiFi-Probe') "
                "ORDER BY id DESC",
                (since_epoch,),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            try:
                conn.close()
            except Exception:
                pass

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
    for path in _iter_db_paths(output_dir):
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            rows = conn.execute(
                "SELECT power_db, device_id, timestamp, metadata "
                "FROM detections "
                "WHERE ts_epoch >= ? AND signal_type = 'WiFi-AP' "
                "ORDER BY id DESC",
                (since_epoch,),
            ).fetchall()
        except Exception:
            rows = []
        finally:
            try:
                conn.close()
            except Exception:
                pass

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
    """Compute device correlations on demand from every session .db in
    the output directory.

    Replaces the old `correlations.json` sidecar pattern where the server
    kept a live DeviceCorrelator in memory and wrote a snapshot every
    30s. That had two problems: state was lost on server restart, and
    the web UI saw a snapshot up to 30s stale even on refresh. Reading
    fresh from the detection log gives cross-session correlations for
    free and makes server restarts stateless.

    Returns the same dict shape the old export_json() produced so the
    UI renderer doesn't change:
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
    for db_path in _iter_db_paths(output_dir):
        try:
            if os.path.getmtime(db_path) < since_epoch:
                continue
        except OSError:
            continue
        try:
            c.load_db(db_path, since_epoch=since_epoch)
        except Exception:
            continue

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

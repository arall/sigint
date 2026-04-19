"""
Cross-node witness correlation for the Correlations tab.

Shows emitters that **multiple sources heard within a time window** —
"server + N01 both saw keyfob X in the last 30 s" — whether or not the
observation can be multilaterated into a position fix.

This is deliberately different from:

  * `triangulate_live.fetch_triangulations` — stricter: requires GPS on
    every observation, runs multilateration, skips self-locating types
    (ADS-B / AIS). The Map tab consumes that.
  * `fetch_correlations` — emitter-to-emitter co-occurrence (device A
    and device B often seen together). Does not care which node saw
    them.

Here we keep the *same emitter* but spread across *multiple nodes*.
ADS-B / AIS are included (operationally interesting: "both N01 and N02
heard flight X" is a coverage signal), position is optional, and we
don't multilaterate.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime

from utils import db as _db
from utils.triangulate import MATCH_STRATEGIES, _get_match_key

from .sessions import is_session_db_name


DEFAULT_WINDOW_SECONDS = 30.0
DEFAULT_MAX_RESULTS = 100
_PER_FILE_LIMIT = 10000

# Signal types without a registered match strategy fall back to frequency,
# matching `triangulate.correlate`'s behaviour.
_FALLBACK_STRATEGY = "frequency"


def fetch_cross_node_witnesses(
    output_dir: str,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    now: float | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> list[dict]:
    """Return emitters that 2+ nodes heard within the window, newest-first.

    Each entry reports the witnessing node set, first/last observation
    timestamps, observation count, and per-node observation counts so
    the UI can show "server × 4, N01 × 2".
    """
    if now is None:
        now = time.time()
    since = now - max(1, window_seconds)

    try:
        names = sorted(
            (f for f in os.listdir(output_dir) if is_session_db_name(f)),
            reverse=True,
        )
    except OSError:
        return []

    # { (signal_type, key) -> {nodes: {node_id: count}, first, last, freq, obs} }
    witnesses: dict[tuple[str, str], dict] = {}

    for name in names:
        path = os.path.join(output_dir, name)
        is_agent_db = name.startswith("agents_")
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            cur = conn.execute(
                "SELECT timestamp, ts_epoch, signal_type, frequency_hz, "
                "channel, device_id, metadata FROM detections "
                "WHERE ts_epoch >= ? ORDER BY id",
                (since,),
            )
            for r in cur:
                sig = r["signal_type"] or ""
                if not sig:
                    continue
                # Match strategy mirrors `utils.triangulate`: channel for
                # PMR/keyfob, metadata_id for WiFi/BLE, frequency for
                # everything else (incl. ADS-B / AIS).
                strategy = MATCH_STRATEGIES.get(sig, _FALLBACK_STRATEGY)
                row_dict = _row_to_match_dict(r)
                key = _get_match_key(row_dict, strategy)
                if not key:
                    continue
                node_id = (r["device_id"] or "server") if is_agent_db else "server"

                wid = (sig, key)
                entry = witnesses.setdefault(wid, {
                    "signal_type": sig,
                    "key": key,
                    "freq_mhz": round(float(r["frequency_hz"] or 0) / 1e6, 4),
                    "nodes": defaultdict(int),
                    "first_seen": r["timestamp"] or "",
                    "last_seen": r["timestamp"] or "",
                    "ts_first": float(r["ts_epoch"] or 0.0),
                    "ts_last": float(r["ts_epoch"] or 0.0),
                    "observations": 0,
                })
                entry["nodes"][node_id] += 1
                entry["observations"] += 1
                ts = float(r["ts_epoch"] or 0.0)
                if ts and ts < entry["ts_first"]:
                    entry["ts_first"] = ts
                    entry["first_seen"] = r["timestamp"] or entry["first_seen"]
                if ts and ts > entry["ts_last"]:
                    entry["ts_last"] = ts
                    entry["last_seen"] = r["timestamp"] or entry["last_seen"]
                # Whichever frequency we see last wins — most signals stay
                # on one freq; hopping ones (e.g. RTL-SDR scan) get the
                # latest, which is the most operationally meaningful.
                entry["freq_mhz"] = round(float(r["frequency_hz"] or 0) / 1e6, 4)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Keep only emitters seen by 2+ distinct nodes.
    out: list[dict] = []
    for entry in witnesses.values():
        if len(entry["nodes"]) < 2:
            continue
        out.append({
            "signal_type": entry["signal_type"],
            "key": entry["key"],
            "freq_mhz": entry["freq_mhz"],
            "nodes": sorted(entry["nodes"].keys()),
            "observations_by_node": dict(entry["nodes"]),
            "observations": entry["observations"],
            "first_seen": entry["first_seen"],
            "last_seen": entry["last_seen"],
            "ts_last": entry["ts_last"],
            "window_s": window_seconds,
        })

    out.sort(key=lambda e: e["ts_last"], reverse=True)
    return out[:max_results]


def _row_to_match_dict(row) -> dict:
    """Shape a sqlite3.Row into the dict that `_get_match_key` expects.

    `_get_match_key` was built for `triangulate.load_detections`, which
    eagerly parses metadata into `_meta`. We reproduce the same shape
    so we can reuse the strategy logic verbatim.
    """
    try:
        meta = json.loads(row["metadata"] or "{}") if row["metadata"] else {}
        if not isinstance(meta, dict):
            meta = {}
    except (ValueError, TypeError):
        meta = {}
    return {
        "signal_type": row["signal_type"] or "",
        "channel": row["channel"] or "",
        "frequency_hz": row["frequency_hz"] or 0,
        "device_id": row["device_id"] or "",
        "_meta": meta,
    }

"""
Live multi-node triangulation for the Map tab.

`/api/map/triangulations` calls into here to build a list of recently
triangulated emitters. Reuses `utils/triangulate.py`'s correlation and
position-estimation functions, but sources detections from the live
session `.db` files rather than post-hoc CLI arguments.

Design:
  - Per-node split: non-agent DBs are treated as "server" captures; agent
    DB rows carry `device_id = agent_id` which is our node identity.
  - WiFi-AP beacons set `device_id = BSSID` (the emitter) inside the
    server's own DBs, so we *do not* trust device_id in non-agent DBs as
    a node identifier — everything there is attributed to "server".
  - Self-locating types (ADS-B / AIS) skipped — those report position
    directly, triangulating them is nonsense.
  - Calibration applied via the cached `_get_calibration` view from
    `fetch.py`, so observations feed the RSSI-based log-distance model
    with offset-corrected power when available.
  - Groups produced by `utils.triangulate.correlate`; per-group position
    via `utils.triangulate.estimate_position`. Both are pure functions
    and already unit-tested.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime

from utils import db as _db
from utils import triangulate as _tri

from .sessions import is_session_db_name


DEFAULT_WINDOW_SECONDS = 300    # 5 min — map is "what's live right now"
DEFAULT_MAX_RESULTS = 50
DEFAULT_CORRELATION_WINDOW_S = 5.0

# Per-file load cap: stops a screamingly busy agent DB (WiFi / BLE at a
# festival) from blowing out memory when the map tab refreshes.
_PER_FILE_LIMIT = 5000


def fetch_triangulations(
    output_dir: str,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    now: float | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    correlation_window_s: float = DEFAULT_CORRELATION_WINDOW_S,
) -> list[dict]:
    """Return triangulated emitters seen in the last `window_seconds`.

    Newest-first, capped at `max_results`. Each result carries enough
    detail to render a marker + error circle + popup on the map.
    """
    if now is None:
        now = time.time()
    since = now - max(1, window_seconds)

    # Imported here to avoid a circular import with fetch.py (fetch imports
    # this module via the HTTP handler path in server.py).
    from .fetch import _get_calibration
    cal = _get_calibration(output_dir)

    by_type_node: dict[tuple[str, str], list[dict]] = {}

    try:
        names = sorted(
            (f for f in os.listdir(output_dir) if is_session_db_name(f)),
            reverse=True,
        )
    except OSError:
        return []

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
                "power_db, noise_floor_db, snr_db, channel, latitude, "
                "longitude, device_id, metadata FROM detections "
                "WHERE ts_epoch >= ? ORDER BY id DESC LIMIT ?",
                (since, _PER_FILE_LIMIT),
            )
            for r in cur:
                det = _shape_detection(r, is_agent_db=is_agent_db, cal=cal)
                if det is None:
                    continue
                key = (det["signal_type"], det["_node_id"])
                by_type_node.setdefault(key, []).append(det)
        except Exception:
            # Malformed row / schema mismatch — skip this file, don't kill
            # the request.
            pass
        finally:
            conn.close()

    # `correlate` auto-detects strategy from the first detection's signal
    # type, so call it once per type to keep strategy stable.
    by_type: dict[str, list[tuple[list[dict], str]]] = {}
    for (sig, node_id), dets in by_type_node.items():
        by_type.setdefault(sig, []).append((dets, node_id))

    results: list[dict] = []
    for sig, file_detections in by_type.items():
        if len(file_detections) < 2:
            continue
        try:
            groups = _tri.correlate(
                file_detections,
                time_window_s=correlation_window_s,
                strategy="auto",
            )
        except Exception:
            continue
        for group in groups:
            obs = group.get("observations") or []
            if len({o["node"] for o in obs}) < 2:
                continue
            try:
                pos = _tri.estimate_position(
                    obs, signal_type=group.get("signal_type"),
                )
            except Exception:
                continue
            results.append(_format_result(group, pos))

    # Newest-first, dedup by (signal_type, key) — keeps the latest fix per
    # emitter when multiple correlation clusters land in the same window.
    results.sort(key=lambda x: x["ts_epoch"], reverse=True)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for r in results:
        k = (r["signal_type"], r["key"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)
        if len(deduped) >= max_results:
            break
    return deduped


def _shape_detection(row, *, is_agent_db: bool, cal) -> dict | None:
    """Build a dict that matches what `triangulate.correlate` expects.

    Returns None for rows that can't be triangulated (missing GPS, self-
    locating signal, unparseable timestamp).
    """
    sig = row["signal_type"] or ""
    if sig in _tri.SELF_LOCATING:
        return None
    if row["latitude"] is None or row["longitude"] is None:
        return None
    try:
        ts = datetime.fromisoformat(row["timestamp"])
    except (TypeError, ValueError):
        return None

    # See module docstring for the node-attribution rule.
    node_id = (row["device_id"] or "server") if is_agent_db else "server"

    try:
        meta = json.loads(row["metadata"] or "{}") if row["metadata"] else {}
        if not isinstance(meta, dict):
            meta = {}
    except (ValueError, TypeError):
        meta = {}

    try:
        power = float(row["power_db"] or 0.0)
        noise = float(row["noise_floor_db"] or 0.0)
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        freq_hz = float(row["frequency_hz"] or 0.0)
    except (TypeError, ValueError):
        return None

    # triangulate.correlate pulls observations out of these underscore
    # fields (see utils/triangulate.py load_detections + correlate).
    det = {
        "timestamp": row["timestamp"],
        "ts_epoch": row["ts_epoch"],
        "signal_type": sig,
        "frequency_hz": freq_hz,
        "power_db": row["power_db"],
        "noise_floor_db": row["noise_floor_db"],
        "snr_db": row["snr_db"],
        "channel": row["channel"] or "",
        "device_id": row["device_id"] or "",
        "metadata": row["metadata"] or "",
        "_ts": ts,
        "_lat": lat,
        "_lon": lon,
        "_power": power,
        "_noise": noise,
        "_meta": meta,
        "_node_id": node_id,
    }

    # Calibration uses the *capturing* node, not the detection's device_id
    # column (which is the emitter BSSID for WiFi-AP beacons).
    try:
        from utils import calibration as _cal
        corrected, applied = _cal.apply_offset(power, node_id, freq_hz, cal)
    except Exception:
        corrected, applied = power, False
    det["_power_cal"] = corrected
    det["_cal_applied"] = applied
    return det


def _format_result(group: dict, pos: dict) -> dict:
    obs = group["observations"]
    latest_ts = max((o["timestamp"] for o in obs), default="")
    ts_epoch = 0.0
    try:
        ts_epoch = datetime.fromisoformat(latest_ts).timestamp()
    except (TypeError, ValueError):
        pass
    calibrated_observations = sum(1 for o in obs if o.get("cal_applied"))
    return {
        "signal_type": group.get("signal_type") or "unknown",
        "key": group.get("key") or "",
        "freq_mhz": round((group.get("frequency_hz") or 0) / 1e6, 4),
        "lat": round(pos["lat"], 6),
        "lon": round(pos["lon"], 6),
        "error_m": round(pos["error_radius_m"]),
        "num_nodes": int(pos["num_nodes"]),
        "method": pos.get("method", "unknown"),
        "timestamp": latest_ts,
        "ts_epoch": ts_epoch,
        "nodes": sorted({o["node"] for o in obs}),
        "cal_applied_count": calibrated_observations,
        "observations": [
            {
                "node": o["node"],
                "lat": o["lat"],
                "lon": o["lon"],
                "power_db": round(o["power_db"], 1) if o.get("power_db") is not None else None,
                "cal_applied": bool(o.get("cal_applied")),
                "timestamp": o["timestamp"],
            }
            for o in obs
        ],
    }

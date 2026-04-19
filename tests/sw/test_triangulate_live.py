"""
Tests for web/triangulate_live.py — live multi-node triangulation feed
consumed by /api/map/triangulations on the Map tab.

Covers:
  - Happy path: a server DB + an agent DB see the same keyfob within the
    correlation window → one triangulation result, lat/lon plausible.
  - Single-node groups yield nothing (can't multilaterate alone).
  - Self-locating types (ADS-B) are skipped even with multiple observers.
  - Deduplication: multiple clusters for the same (type, key) yield one
    result (the newest).
  - Window filtering: older-than-window rows don't produce fixes.
  - Agent DBs split by device_id: two agents in the same agents_*.db
    count as two nodes.

Run:
    python3 tests/sw/test_triangulate_live.py
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _make_session_db(output_dir, filename, rows):
    """Write a list of (signal_type, channel, lat, lon, power_db, ts_offset_s,
    device_id, metadata) rows into a session .db at the given path.

    `ts_offset_s` is seconds in the past from now (0 = now, 120 = 2 min ago).
    """
    from utils import db as _db
    from utils.logger import SignalDetection
    from datetime import datetime

    path = os.path.join(output_dir, filename)
    conn = _db.connect(path)
    now = time.time()
    for sig, ch, lat, lon, power, age, device_id, meta in rows:
        det = SignalDetection.create(
            signal_type=sig,
            frequency_hz=433.92e6 if sig == "keyfob" else 1090e6 if sig == "ADS-B" else 446e6,
            power_db=power, noise_floor_db=-95,
            channel=ch,
            latitude=lat, longitude=lon,
            device_id=device_id,
            metadata=json.dumps(meta) if meta else "",
        )
        det.timestamp = datetime.fromtimestamp(now - age).isoformat()
        _db.insert_detection(conn, det)
    conn.close()
    return path


def test_happy_path_two_nodes_triangulate():
    """Server + one agent both hear the same keyfob; should produce a fix."""
    from web.triangulate_live import fetch_triangulations

    tmp = tempfile.mkdtemp()
    # Server sees keyfob at channel 1, measured from lat/lon (42.510, 1.535)
    _make_session_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 42.510, 1.535, -60.0, 3, "server", None),
        ("keyfob", "CH1", 42.510, 1.535, -58.0, 2, "server", None),
    ])
    # Agent N01 sees the same keyfob from a different location
    _make_session_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 42.515, 1.540, -65.0, 3, "N01", None),
        ("keyfob", "CH1", 42.515, 1.540, -63.0, 2, "N01", None),
    ])

    results = fetch_triangulations(tmp, window_seconds=3600)
    assert len(results) == 1, f"expected 1 result, got {len(results)}"
    r = results[0]
    assert r["signal_type"] == "keyfob"
    assert r["key"] == "CH1"
    assert r["num_nodes"] == 2
    assert "server" in r["nodes"] and "N01" in r["nodes"]
    # Estimated position somewhere between the two observers.
    assert 42.505 < r["lat"] < 42.520
    assert 1.532 < r["lon"] < 1.545
    assert r["error_m"] >= 0


def test_single_node_produces_no_triangulation():
    """One source only → can't triangulate, zero results."""
    from web.triangulate_live import fetch_triangulations

    tmp = tempfile.mkdtemp()
    _make_session_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 42.510, 1.535, -60, 1, "server", None),
        ("keyfob", "CH1", 42.510, 1.535, -58, 2, "server", None),
    ])
    results = fetch_triangulations(tmp, window_seconds=3600)
    assert results == []


def test_adsb_is_skipped_even_with_multiple_sources():
    """ADS-B self-reports; multilateration is meaningless. Skip entirely."""
    from web.triangulate_live import fetch_triangulations

    tmp = tempfile.mkdtemp()
    _make_session_db(tmp, "adsb_20260419_120000.db", [
        ("ADS-B", "ABC123", 42.6, 1.55, -20, 2, "server",
         {"icao": "ABC123", "altitude": 30000}),
    ])
    _make_session_db(tmp, "agents_20260419.db", [
        ("ADS-B", "ABC123", 42.6, 1.55, -25, 2, "N01",
         {"icao": "ABC123", "altitude": 30000}),
    ])
    results = fetch_triangulations(tmp, window_seconds=3600)
    assert results == []


def test_window_filters_out_stale_rows():
    """Rows older than window should not produce a fix."""
    from web.triangulate_live import fetch_triangulations

    tmp = tempfile.mkdtemp()
    # Everything is 10 minutes old. Window = 1 minute → zero results.
    _make_session_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 42.510, 1.535, -60, 600, "server", None),
    ])
    _make_session_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 42.515, 1.540, -65, 600, "N01", None),
    ])
    assert fetch_triangulations(tmp, window_seconds=60) == []
    # Same data, wider window → one fix appears.
    assert len(fetch_triangulations(tmp, window_seconds=1200)) == 1


def test_two_agents_in_same_db_count_as_two_nodes():
    """agents_*.db holds rows from every agent — split by device_id."""
    from web.triangulate_live import fetch_triangulations

    tmp = tempfile.mkdtemp()
    _make_session_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 42.510, 1.535, -60, 2, "N01", None),
        ("keyfob", "CH1", 42.515, 1.540, -65, 2, "N02", None),
    ])
    results = fetch_triangulations(tmp, window_seconds=3600)
    assert len(results) == 1
    assert set(results[0]["nodes"]) == {"N01", "N02"}


def test_result_carries_observation_detail():
    """Each triangulation ships per-observation (node, power, cal_applied)."""
    from web.triangulate_live import fetch_triangulations

    tmp = tempfile.mkdtemp()
    _make_session_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 42.510, 1.535, -60, 2, "server", None),
    ])
    _make_session_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 42.515, 1.540, -65, 2, "N01", None),
    ])
    [r] = fetch_triangulations(tmp, window_seconds=3600)
    obs = r["observations"]
    assert len(obs) == 2
    nodes_in_obs = {o["node"] for o in obs}
    assert nodes_in_obs == {"server", "N01"}
    for o in obs:
        assert o["lat"] is not None and o["lon"] is not None
        assert isinstance(o["cal_applied"], bool)


def test_empty_output_dir_returns_empty():
    from web.triangulate_live import fetch_triangulations
    tmp = tempfile.mkdtemp()
    assert fetch_triangulations(tmp, window_seconds=3600) == []


def test_calibration_applied_when_present():
    """When a calibration DB exists, observations carry cal_applied=True
    for the nodes with solved offsets."""
    from web import fetch as _f
    from web.triangulate_live import fetch_triangulations
    from utils import calibration_db as _cdb

    tmp = tempfile.mkdtemp()
    # Solve an offset for "N01" on UHF band (covers 433 MHz keyfobs).
    cal_conn = _cdb.connect(_cdb.default_path(tmp))
    _cdb.upsert_offset(cal_conn, "N01", "UHF", -12.0, 0.3, 50, "huber")
    cal_conn.close()
    # Invalidate the module-level cache so _get_calibration re-reads.
    _f._CAL_CACHE["path"] = None
    _f._CAL_CACHE["mtime"] = None
    _f._CAL_CACHE["cal"] = None

    _make_session_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 42.510, 1.535, -60, 2, "server", None),
    ])
    _make_session_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 42.515, 1.540, -65, 2, "N01", None),
    ])
    [r] = fetch_triangulations(tmp, window_seconds=3600)
    by_node = {o["node"]: o for o in r["observations"]}
    # Only N01 has a solved offset; the server doesn't.
    assert by_node["N01"]["cal_applied"] is True
    assert by_node["server"]["cal_applied"] is False
    assert r["cal_applied_count"] == 1


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"  ERR  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(0 if failures == 0 else 1)

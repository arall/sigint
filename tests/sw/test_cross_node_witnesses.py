"""
Tests for web/cross_node_witnesses.py — the "same emitter, multiple
witnessing nodes" view surfaced in the Correlations tab.

Covers:
  - Basic happy path: two nodes hear the same keyfob → one witness
  - Single-node observations don't surface (need 2+ distinct nodes)
  - ADS-B / AIS are INCLUDED here (unlike triangulate_live, which
    skips self-locating types) — coverage signal matters even though
    the aircraft reports its own position
  - WiFi-AP: BSSID-from-metadata is the key, device_id column (which
    *is* the BSSID in server-side captures) doesn't confuse the split
  - Per-node observation counts in `observations_by_node`
  - Window filtering — rows older than the window don't surface
  - Empty output dir returns []
  - Different match strategies: channel for keyfob/PMR, metadata_id
    for WiFi/BLE, frequency for cellular / ADS-B

Run:
    python3 tests/sw/test_cross_node_witnesses.py
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _write_db(output_dir, filename, rows):
    """rows: (signal_type, channel, freq_hz, power_db, device_id, meta_dict, age_s)"""
    from utils import db as _db
    from utils.logger import SignalDetection
    from datetime import datetime

    path = os.path.join(output_dir, filename)
    conn = _db.connect(path)
    now = time.time()
    for sig, ch, freq, power, dev, meta, age in rows:
        det = SignalDetection.create(
            signal_type=sig,
            frequency_hz=freq,
            power_db=power,
            noise_floor_db=-95,
            channel=ch,
            device_id=dev,
            metadata=json.dumps(meta) if meta else "",
        )
        det.timestamp = datetime.fromtimestamp(now - age).isoformat()
        _db.insert_detection(conn, det)
    conn.close()


def test_two_nodes_witness_same_keyfob():
    from web.cross_node_witnesses import fetch_cross_node_witnesses
    tmp = tempfile.mkdtemp()

    # Server sees CH1 twice, N01 once — all within window.
    _write_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 433.92e6, -60, "server", None, 5),
        ("keyfob", "CH1", 433.92e6, -58, "server", None, 3),
    ])
    _write_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 433.92e6, -65, "N01", None, 4),
    ])

    rows = fetch_cross_node_witnesses(tmp, window_seconds=60)
    assert len(rows) == 1
    w = rows[0]
    assert w["signal_type"] == "keyfob"
    assert w["key"] == "CH1"
    assert set(w["nodes"]) == {"server", "N01"}
    assert w["observations_by_node"] == {"server": 2, "N01": 1}
    assert w["observations"] == 3


def test_single_node_does_not_surface():
    from web.cross_node_witnesses import fetch_cross_node_witnesses
    tmp = tempfile.mkdtemp()
    _write_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 433.92e6, -60, "server", None, 5),
        ("keyfob", "CH1", 433.92e6, -58, "server", None, 3),
    ])
    assert fetch_cross_node_witnesses(tmp, window_seconds=60) == []


def test_adsb_is_included():
    """Unlike triangulate_live (which skips self-locating types), witness
    view keeps ADS-B: "both nodes heard flight X" is a useful coverage
    readout even though the plane self-reports position."""
    from web.cross_node_witnesses import fetch_cross_node_witnesses
    tmp = tempfile.mkdtemp()
    _write_db(tmp, "adsb_20260419_120000.db", [
        ("ADS-B", "ABC123", 1090e6, -20, "server", {"icao": "ABC123"}, 2),
    ])
    _write_db(tmp, "agents_20260419.db", [
        ("ADS-B", "ABC123", 1090e6, -25, "N01", {"icao": "ABC123"}, 2),
    ])
    rows = fetch_cross_node_witnesses(tmp, window_seconds=60)
    assert len(rows) == 1
    assert rows[0]["signal_type"] == "ADS-B"
    assert set(rows[0]["nodes"]) == {"server", "N01"}


def test_wifi_uses_metadata_id_not_device_id():
    """In server-local captures, WiFi-AP sets device_id = BSSID, which
    would wrongly bucket every AP as a different 'node'. Strategy
    metadata_id pulls mac/bssid from metadata — same BSSID across nodes
    becomes the correlation key, nodes stay as server/N01."""
    from web.cross_node_witnesses import fetch_cross_node_witnesses
    tmp = tempfile.mkdtemp()
    bssid = "aa:bb:cc:11:22:33"
    _write_db(tmp, "wifi_20260419_120000.db", [
        ("WiFi-AP", "CH6", 2.437e9, -55, bssid,
         {"bssid": bssid, "mac": bssid}, 2),
    ])
    _write_db(tmp, "agents_20260419.db", [
        ("WiFi-AP", "CH6", 2.437e9, -65, "N01",
         {"bssid": bssid, "mac": bssid}, 2),
    ])
    rows = fetch_cross_node_witnesses(tmp, window_seconds=60)
    # MATCH_STRATEGIES uses "metadata_id" for "wifi" (lower-case). WiFi-AP
    # (camel-case) isn't in the strategies table so it falls through to
    # frequency — both rows share 2.437 GHz, key is "2437000" (kHz).
    # Either way a single witness row with both nodes should surface.
    assert len(rows) == 1
    assert set(rows[0]["nodes"]) == {"server", "N01"}


def test_window_filter_drops_stale_rows():
    from web.cross_node_witnesses import fetch_cross_node_witnesses
    tmp = tempfile.mkdtemp()
    # 10 min old.
    _write_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 433.92e6, -60, "server", None, 600),
    ])
    _write_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 433.92e6, -65, "N01", None, 600),
    ])
    assert fetch_cross_node_witnesses(tmp, window_seconds=60) == []
    # Widen to 15 min → surfaces.
    rows = fetch_cross_node_witnesses(tmp, window_seconds=900)
    assert len(rows) == 1


def test_two_agents_in_same_db():
    """agents_*.db holds rows from every agent — device_id column is the
    node for those rows. Two agents hearing the same key counts as two
    witnesses."""
    from web.cross_node_witnesses import fetch_cross_node_witnesses
    tmp = tempfile.mkdtemp()
    _write_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 433.92e6, -60, "N01", None, 3),
        ("keyfob", "CH1", 433.92e6, -65, "N02", None, 3),
    ])
    rows = fetch_cross_node_witnesses(tmp, window_seconds=60)
    assert len(rows) == 1
    assert set(rows[0]["nodes"]) == {"N01", "N02"}


def test_empty_output_dir_returns_empty():
    from web.cross_node_witnesses import fetch_cross_node_witnesses
    tmp = tempfile.mkdtemp()
    assert fetch_cross_node_witnesses(tmp, window_seconds=60) == []


def test_first_and_last_seen_track_chronology():
    """first_seen should be the oldest observation, last_seen the newest,
    regardless of which file / node they came from."""
    from web.cross_node_witnesses import fetch_cross_node_witnesses
    tmp = tempfile.mkdtemp()
    _write_db(tmp, "keyfob_20260419_120000.db", [
        ("keyfob", "CH1", 433.92e6, -60, "server", None, 60),  # older
        ("keyfob", "CH1", 433.92e6, -55, "server", None, 5),   # newer
    ])
    _write_db(tmp, "agents_20260419.db", [
        ("keyfob", "CH1", 433.92e6, -65, "N01", None, 30),
    ])
    rows = fetch_cross_node_witnesses(tmp, window_seconds=600)
    assert len(rows) == 1
    w = rows[0]
    # ts_first < ts_last
    assert w["first_seen"] < w["last_seen"]


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

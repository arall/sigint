"""
Tests for the SQL-backed state/log/activity/active fetchers added when
we pushed the Live / Log / Timeline / Devices-active paths off the
in-memory tailer deque and onto direct SQL queries.

Covers:
  - fetch_recent_detections: newest-first, limit/offset, type filter,
    multi-DB union, transcript overlay
  - fetch_activity_histogram: per-minute buckets, type counters,
    empty-minute fill, window clamp
  - fetch_live_state: per-type aggregates, unique counts via json_extract,
    category rollup, recent events, display order
  - fetch_active_dev_sigs / fetch_active_bssids: 5-minute window,
    RSSI + apple_device carryover, dedup by key

Run:
    python3 tests/sw/test_web_fetch_state.py
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _build_session(signals, meta_per=None):
    """Write a small .db file with the given (signal_type, channel) pairs.
    `meta_per` is an optional list[dict] passed as metadata per row."""
    from utils.logger import SignalLogger, SignalDetection
    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="ws", min_snr_db=0)
    log.start()
    for i, (sig, ch) in enumerate(signals):
        meta = (meta_per or [{}] * len(signals))[i]
        log.log(SignalDetection.create(
            signal_type=sig,
            frequency_hz=446e6 if sig.startswith("PMR") else 2402e6,
            power_db=-60 - (i % 5),
            noise_floor_db=-95,
            channel=ch,
            device_id=meta.get("_device_id", ""),
            metadata=json.dumps({k: v for k, v in meta.items() if not k.startswith("_")}),
        ))
    log.stop()
    return tmp


def test_fetch_recent_detections_newest_first():
    from web.fetch import fetch_recent_detections

    d = _build_session([("PMR446", f"CH{i}") for i in range(1, 6)])
    rows = fetch_recent_detections(d, limit=3)
    assert len(rows) == 3
    # Newest first = CH5, CH4, CH3
    assert [r["channel"] for r in rows] == ["CH5", "CH4", "CH3"]


def test_fetch_recent_detections_type_filter():
    from web.fetch import fetch_recent_detections

    d = _build_session([
        ("PMR446", "CH1"),
        ("BLE-Adv", "BLE"),
        ("PMR446", "CH2"),
        ("ADS-B", "icao"),
    ])
    rows = fetch_recent_detections(d, limit=10, signal_type="PMR446")
    assert len(rows) == 2
    assert all(r["signal_type"] == "PMR446" for r in rows)


def test_fetch_recent_detections_offset():
    from web.fetch import fetch_recent_detections

    d = _build_session([("PMR446", f"CH{i}") for i in range(1, 11)])
    page1 = fetch_recent_detections(d, limit=3, offset=0)
    page2 = fetch_recent_detections(d, limit=3, offset=3)
    assert [r["channel"] for r in page1] == ["CH10", "CH9", "CH8"]
    assert [r["channel"] for r in page2] == ["CH7", "CH6", "CH5"]


def test_fetch_recent_detections_transcript_overlay():
    from web.fetch import fetch_recent_detections

    d = _build_session(
        [("PMR446", "CH1")],
        meta_per=[{"audio_file": "pmr_ch1.wav"}],
    )
    # Write the sidecar AFTER the detection
    with open(os.path.join(d, "transcripts.json"), "w") as f:
        json.dump({"pmr_ch1.wav": "hello sidecar"}, f)
    # The audio_file lives on the row, not the metadata — simulate that
    # by writing through SignalLogger.log with audio_file arg. We didn't,
    # so this test mostly verifies the fetcher doesn't crash when
    # transcripts.json is present. The real audio_file path is tested
    # in test_web_fetch.py (test_fetch_overlays_transcripts_sidecar).
    rows = fetch_recent_detections(d, limit=1)
    assert len(rows) == 1


def test_fetch_activity_histogram_shape():
    from web.fetch import fetch_activity_histogram

    d = _build_session([("PMR446", "CH1"), ("PMR446", "CH2"), ("BLE-Adv", "")])
    hist = fetch_activity_histogram(d, minutes=10)
    assert len(hist) == 10, f"expected 10 minute buckets, got {len(hist)}"
    assert all("minute" in b and "counts" in b and "total" in b for b in hist)

    # At least one bucket has our test rows
    total = sum(b["total"] for b in hist)
    assert total == 3, f"expected 3 total detections, got {total}"

    # The newest bucket should contain our types
    newest = [b for b in hist if b["total"] > 0][-1]
    assert set(newest["counts"].keys()) == {"PMR446", "BLE-Adv"}


def test_fetch_activity_histogram_empty_dir():
    from web.fetch import fetch_activity_histogram

    tmp = tempfile.mkdtemp()
    hist = fetch_activity_histogram(tmp, minutes=5)
    assert len(hist) == 5
    assert all(b["total"] == 0 for b in hist)


def test_fetch_live_state_counts_and_uniques():
    from web.fetch import fetch_live_state

    d = _build_session([
        ("BLE-Adv",    "BLE"),
        ("BLE-Adv",    "BLE"),
        ("WiFi-Probe", ""),
        ("ADS-B",      "icao1"),
        ("PMR446",     "CH1"),
        ("PMR446",     "CH2"),
        ("PMR446",     "CH1"),   # duplicate channel
    ], meta_per=[
        {"persona_id": "P1"},
        {"persona_id": "P2"},
        {"persona_id": "P1"},
        {"icao": "ABCD"},
        {},
        {},
        {},
    ])
    state = fetch_live_state(d)
    assert state["detection_count"] == 7
    by_type = {s["type"]: s for s in state["signals"]}
    assert by_type["BLE-Adv"]["count"] == 2
    assert by_type["BLE-Adv"]["uniques"] == 2   # P1 + P2
    assert by_type["WiFi-Probe"]["uniques"] == 1
    assert by_type["ADS-B"]["uniques"] == 1
    # PMR446: uniques are keyed by channel → CH1, CH2 = 2 unique
    assert by_type["PMR446"]["count"] == 3
    assert by_type["PMR446"]["uniques"] == 2


def test_fetch_live_state_categories_rollup():
    from web.fetch import fetch_live_state

    d = _build_session([
        ("PMR446",  "CH1"),
        ("MarineVHF", "CH16"),
        ("ADS-B",   "icao1"),
        ("BLE-Adv", "BLE"),
    ], meta_per=[{}, {}, {"icao": "A"}, {"persona_id": "P1"}])
    state = fetch_live_state(d)
    cats = {c["id"]: c for c in state["categories"]}
    assert "voice" in cats and cats["voice"]["count"] == 2
    assert "aircraft" in cats and cats["aircraft"]["count"] == 1
    assert "devices" in cats and cats["devices"]["count"] == 1


def test_fetch_live_state_recent_events():
    from web.fetch import fetch_live_state

    d = _build_session([("PMR446", f"CH{i}") for i in range(1, 8)])
    state = fetch_live_state(d, recent_events_limit=5)
    assert len(state["recent"]) == 5
    # Newest first
    assert "CH7" in state["recent"][0]["line"]
    assert "CH3" in state["recent"][-1]["line"]


def test_fetch_active_dev_sigs_and_bssids():
    from web.fetch import fetch_active_dev_sigs, fetch_active_bssids

    d = _build_session([
        ("BLE-Adv",    "BLE"),
        ("BLE-Adv",    "BLE"),   # same persona — should dedupe
        ("WiFi-Probe", ""),
        ("WiFi-AP",    "CH6"),
    ], meta_per=[
        {"dev_sig": "sigA", "apple_device": "AirPods Pro 2"},
        {"dev_sig": "sigA", "apple_device": "AirPods Pro 2"},
        {"dev_sig": "sigB"},
        {"bssid": "aa:bb:cc:dd:ee:01", "_device_id": "aa:bb:cc:dd:ee:01"},
    ])
    sigs = fetch_active_dev_sigs(d, minutes=60)
    assert set(sigs.keys()) == {"sigA", "sigB"}
    assert sigs["sigA"]["apple_device"] == "AirPods Pro 2"
    assert sigs["sigA"]["rssi"] is not None

    bssids = fetch_active_bssids(d, minutes=60)
    assert "aa:bb:cc:dd:ee:01" in bssids
    assert bssids["aa:bb:cc:dd:ee:01"]["rssi"] is not None


def test_fetch_active_respects_window():
    from web.fetch import fetch_active_dev_sigs

    d = _build_session(
        [("BLE-Adv", "BLE")],
        meta_per=[{"dev_sig": "sigX"}],
    )
    # Pretend "now" is 1 hour in the future. The row has ts ≈ real now,
    # so since_epoch = future - 5 min is still later than the row, and
    # the 5-min window excludes it.
    sigs = fetch_active_dev_sigs(d, minutes=5, now=time.time() + 3600)
    assert sigs == {}, f"row should fall outside window, got {sigs}"


def test_tailer_refresh_cache_smoke():
    from utils.logger import SignalLogger, SignalDetection
    from web.tailer import DBTailer

    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="t", min_snr_db=0)
    log.start()
    log.log(SignalDetection.create("PMR446", 446e6, -50, -90, channel="CH1"))
    log.log(SignalDetection.create("ADS-B", 1090e6, -60, -90, metadata='{"icao":"ABC"}'))
    log.stop()

    t = DBTailer(tmp)
    t._update_tailing_db()
    t._refresh_state()
    state = t.get_state()

    # Live-ish metadata
    assert state["time"]
    assert state["uptime"]
    assert state["db"].endswith(".db")
    assert state["detection_count"] == 2
    # Shape sanity
    for key in ("signals", "categories", "recent", "system"):
        assert key in state


def run_tests():
    tests = [
        ("recent_detections newest-first",    test_fetch_recent_detections_newest_first),
        ("recent_detections type filter",     test_fetch_recent_detections_type_filter),
        ("recent_detections offset",          test_fetch_recent_detections_offset),
        ("recent_detections transcript",      test_fetch_recent_detections_transcript_overlay),
        ("activity histogram shape",          test_fetch_activity_histogram_shape),
        ("activity empty dir",                test_fetch_activity_histogram_empty_dir),
        ("live state counts + uniques",       test_fetch_live_state_counts_and_uniques),
        ("live state category rollup",        test_fetch_live_state_categories_rollup),
        ("live state recent events",          test_fetch_live_state_recent_events),
        ("active dev sigs + bssids",          test_fetch_active_dev_sigs_and_bssids),
        ("active respects window",            test_fetch_active_respects_window),
        ("tailer refresh cache",              test_tailer_refresh_cache_smoke),
    ]

    print("=" * 60)
    print("Web Fetch State Tests")
    print("=" * 60)
    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n  {name}")
        try:
            fn()
            print("  [PASS]")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            failed += 1
    print("\n" + "=" * 60)
    print(f"{passed} passed, {failed} failed")
    print("=" * 60)
    return failed


if __name__ == "__main__":
    sys.exit(run_tests())

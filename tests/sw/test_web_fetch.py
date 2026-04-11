"""
Tests for web/fetch.py — SQL-backed category fetch that replaces the
in-memory deque for category tab queries.

Covers:
  - Category predicate dispatch (voice / drones / cellular wildcard /
    other negation)
  - Window filtering (only rows newer than now - window_seconds)
  - Limit cap
  - Row shape matches DBTailer deque entries (round-trip through
    _load_voice succeeds and produces expected output)
  - 'other' excludes anything in any known category
  - 'cellular' matches GSM-UPLINK-* + LTE-UPLINK-* wildcards
  - Missing / broken .db returns [] instead of raising

Run:
    python3 tests/sw/test_web_fetch.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _make_db_with_signals(signals, ts_offsets=None):
    """Build a detection .db with the given (signal_type, channel) pairs.
    `ts_offsets`, if given, overrides the per-row age in seconds (0 = now,
    3600 = an hour ago, etc)."""
    from utils.logger import SignalLogger, SignalDetection

    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="fetch_test", min_snr_db=0)
    path = log.start()

    now = time.time()
    for i, (sig, ch) in enumerate(signals):
        det = SignalDetection.create(
            signal_type=sig,
            frequency_hz=446e6 if sig.startswith("PMR") else 1090e6 if sig == "ADS-B" else 2437e6,
            power_db=-50,
            noise_floor_db=-90,
            channel=ch,
            metadata='{"icao":"ABC"}' if sig == "ADS-B" else "",
        )
        # Override timestamp for age filtering tests
        if ts_offsets is not None:
            from datetime import datetime
            offset = ts_offsets[i]
            det.timestamp = datetime.fromtimestamp(now - offset).isoformat()
        log.log(det)

    log.stop()
    return path, now


def test_voice_predicate_matches_only_voice_types():
    from web.fetch import fetch_detections_for_category

    path, now = _make_db_with_signals([
        ("PMR446", "CH1"),
        ("MarineVHF", "CH16"),
        ("ADS-B", "ICAO"),
        ("BLE-Adv", ""),
        ("FM_voice", "CH2"),
    ])
    rows = fetch_detections_for_category(path, "voice", now=now + 1)
    types = {r["signal_type"] for r in rows}
    assert types == {"PMR446", "MarineVHF", "FM_voice"}, \
        f"expected voice types, got {types}"


def test_cellular_wildcard_matching():
    from web.fetch import fetch_detections_for_category

    path, now = _make_db_with_signals([
        ("GSM-UPLINK-GSM-900", "ARFCN42"),
        ("GSM-UPLINK-GSM-850", "ARFCN5"),
        ("LTE-UPLINK-BAND1", "EARFCN0"),
        ("LTE-UPLINK-BAND20", "EARFCN1"),  # subtype not in CATEGORIES
        ("PMR446", "CH1"),
        ("ADS-B", "ICAO"),
    ])
    rows = fetch_detections_for_category(path, "cellular", now=now + 1)
    types = {r["signal_type"] for r in rows}
    assert "LTE-UPLINK-BAND20" in types, \
        "cellular wildcard must match new LTE subtypes"
    assert len(types) == 4
    assert "PMR446" not in types


def test_other_category_excludes_known():
    """'other' must catch ISM / LoRa / POCSAG AND unknown types, but
    NOT collapse with anything in another category — including cellular."""
    from web.fetch import fetch_detections_for_category

    path, now = _make_db_with_signals([
        ("ISM", "433"),
        ("lora", "868"),
        ("pocsag", "466"),
        ("weird-new-signal", ""),           # unknown → other
        ("PMR446", "CH1"),                  # voice, should NOT match
        ("ADS-B", "ICAO"),                  # aircraft, should NOT match
        ("LTE-UPLINK-BAND7", "EARFCN0"),    # cellular, should NOT match
        ("BLE-Adv", ""),                    # devices, should NOT match
    ])
    rows = fetch_detections_for_category(path, "other", now=now + 1)
    types = {r["signal_type"] for r in rows}
    assert types == {"ISM", "lora", "pocsag", "weird-new-signal"}, \
        f"other predicate leaked known types: {types}"


def test_window_filtering():
    """Rows older than window_seconds must be excluded."""
    from web.fetch import fetch_detections_for_category

    # Build 3 rows at 0, 7200 (2h ago), and 14400 (4h ago) seconds offset
    path, now = _make_db_with_signals(
        [("PMR446", "CH1"), ("PMR446", "CH2"), ("PMR446", "CH3")],
        ts_offsets=[0, 7200, 14400],
    )
    # 1 hour window: only the 0-offset row
    rows = fetch_detections_for_category(path, "voice", window_seconds=3600, now=now + 1)
    assert len(rows) == 1
    assert rows[0]["channel"] == "CH1"

    # 3 hour window: the 0 and 2h rows
    rows = fetch_detections_for_category(path, "voice", window_seconds=3 * 3600, now=now + 1)
    channels = {r["channel"] for r in rows}
    assert channels == {"CH1", "CH2"}

    # 5 hour window: all three
    rows = fetch_detections_for_category(path, "voice", window_seconds=5 * 3600, now=now + 1)
    assert len(rows) == 3


def test_limit_cap():
    from web.fetch import fetch_detections_for_category

    path, now = _make_db_with_signals([("PMR446", f"CH{i}") for i in range(1, 11)])
    rows = fetch_detections_for_category(path, "voice", limit=3, now=now + 1)
    assert len(rows) == 3, f"limit should cap at 3, got {len(rows)}"


def test_shape_compat_with_loaders():
    """Fetched rows must flow through the pure loaders unchanged."""
    from web.fetch import fetch_detections_for_category
    from web.loaders import _load_voice, _load_aircraft, _load_other

    path, now = _make_db_with_signals([
        ("PMR446", "CH1"),
        ("ADS-B", "icao"),
        ("ISM", "433"),
    ])

    voice = _load_voice(fetch_detections_for_category(path, "voice", now=now + 1))
    assert len(voice) == 1
    assert voice[0]["signal_type"] == "PMR446"

    ac = _load_aircraft(fetch_detections_for_category(path, "aircraft", now=now + 1))
    assert len(ac) == 1
    assert ac[0]["icao"] == "ABC"

    other = _load_other(fetch_detections_for_category(path, "other", now=now + 1))
    assert len(other) == 1
    assert other[0]["signal_type"] == "ISM"


def test_unknown_category_returns_empty():
    from web.fetch import fetch_detections_for_category

    path, now = _make_db_with_signals([("PMR446", "CH1")])
    rows = fetch_detections_for_category(path, "bogus", now=now + 1)
    assert rows == []


def test_missing_db_returns_empty():
    from web.fetch import fetch_detections_for_category

    rows = fetch_detections_for_category("/nonexistent/path.db", "voice")
    assert rows == []


def test_fetch_all_unions_across_db_files():
    """Regression for the 'standalone subprocess writes to its own .db'
    case: sdr.py pmr writes pmr446_*.db while the main server writes
    server_*.db. The live category tab must see both."""
    from web.fetch import fetch_detections_for_category_all
    from web.loaders import CATEGORY_LOADERS
    from utils.logger import SignalLogger

    tmp = tempfile.mkdtemp()

    # File 1: the "server" DB — no voice
    log1 = SignalLogger(output_dir=tmp, signal_type="server", min_snr_db=0)
    log1.start()
    log1.log_signal("WiFi-AP", 2437e6, -70, -95, channel="CH6")
    log1.log_signal("BLE-Adv", 2402e6, -65, -95)
    log1.stop()

    # File 2: the "pmr" standalone subprocess DB — voice only
    log2 = SignalLogger(output_dir=tmp, signal_type="pmr446", min_snr_db=0)
    log2.start()
    log2.log_signal("PMR446", 446e6, -50, -90, channel="CH1",
                    metadata='{"duration_s":2.5}')
    log2.log_signal("PMR446", 446e6, -50, -90, channel="CH2",
                    metadata='{"duration_s":1.8}')
    log2.stop()

    # Single-file fetch on the server DB sees nothing voice
    from web.fetch import fetch_detections_for_category
    import glob, os
    server_path = [p for p in glob.glob(os.path.join(tmp, "*.db"))
                   if "server" in os.path.basename(p)][0]
    single = fetch_detections_for_category(server_path, "voice")
    assert single == [], \
        "server DB alone should have no voice; got " + str(single)

    # Union across both .db files sees the PMR detections
    merged = fetch_detections_for_category_all(tmp, "voice")
    assert len(merged) == 2, f"union should see 2 voice dets, got {len(merged)}"
    types = {d["signal_type"] for d in merged}
    assert types == {"PMR446"}

    # And the loader renders them
    rows = CATEGORY_LOADERS["voice"](merged)
    assert len(rows) == 2
    assert {r["channel"] for r in rows} == {"CH1", "CH2"}


def test_fetch_all_empty_dir():
    from web.fetch import fetch_detections_for_category_all
    tmp = tempfile.mkdtemp()
    assert fetch_detections_for_category_all(tmp, "voice") == []


def test_fetch_overlays_transcripts_table():
    """Regression: the SQL fetch must overlay the `transcripts` table
    onto voice rows. Without this, transcripts sit in their own table
    but never reach the Voice tab — the race window between logging a
    voice detection and the async transcriber writing its result."""
    from web.fetch import fetch_detections_for_category, fetch_detections_for_category_all
    from utils.logger import SignalLogger

    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="sv", min_snr_db=0)
    p = log.start()
    # Voice detection logged BEFORE the transcriber writes the table —
    # this is the real-world timing of the async transcription pipeline.
    log.log_signal(
        "PMR446", 446e6, -50, -90, channel="CH7",
        audio_file="pmr_ch7_20260411_150308.wav",
        metadata='{}',
    )
    # Transcriber now writes its output into the transcripts table via
    # the logger's shared writer connection.
    log.log_transcript("pmr_ch7_20260411_150308.wav", "hola mundo", language="es")
    log.stop()

    # Single-file path should pick up the table transcript
    rows = fetch_detections_for_category(p, "voice")
    assert len(rows) == 1
    assert rows[0]["transcript"] == "hola mundo"

    # Union path should pick it up too
    rows_all = fetch_detections_for_category_all(tmp, "voice")
    assert len(rows_all) == 1
    assert rows_all[0]["transcript"] == "hola mundo"


def test_ordering_is_oldest_first():
    """Deque ordering is oldest first, newest last. _load_voice iterates
    reversed(detections) to get newest-first rows. Make sure the SQL
    fetch preserves that contract."""
    from web.fetch import fetch_detections_for_category
    from web.loaders import _load_voice

    path, now = _make_db_with_signals(
        [("PMR446", "CH1"), ("PMR446", "CH2"), ("PMR446", "CH3")],
        ts_offsets=[300, 200, 100],  # CH1 oldest, CH3 newest
    )
    fetched = fetch_detections_for_category(path, "voice", now=now + 1)
    # Fetched should be oldest first
    assert fetched[0]["channel"] == "CH1"
    assert fetched[-1]["channel"] == "CH3"

    # And the voice loader (which reverses) should yield newest first
    rows = _load_voice(fetched)
    assert rows[0]["channel"] == "CH3"
    assert rows[-1]["channel"] == "CH1"


def run_tests():
    tests = [
        ("Voice predicate",             test_voice_predicate_matches_only_voice_types),
        ("Cellular wildcard",           test_cellular_wildcard_matching),
        ("Other excludes known",        test_other_category_excludes_known),
        ("Window filtering",            test_window_filtering),
        ("Limit cap",                   test_limit_cap),
        ("Loader shape compat",         test_shape_compat_with_loaders),
        ("Unknown category",            test_unknown_category_returns_empty),
        ("Missing db",                  test_missing_db_returns_empty),
        ("Oldest-first ordering",       test_ordering_is_oldest_first),
        ("Union across .db files",      test_fetch_all_unions_across_db_files),
        ("Union empty dir",             test_fetch_all_empty_dir),
        ("Transcript table overlay",    test_fetch_overlays_transcripts_table),
    ]

    print("=" * 60)
    print("Web Fetch (SQL-backed category) Tests")
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

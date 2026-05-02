"""
Tests for web/fetch.py — SQL-backed category fetch over the unified
`output/detections.db`.

Covers:
  - Category predicate dispatch (voice / aircraft / cellular wildcard)
  - Window filtering (only rows newer than now - window_seconds)
  - Limit cap
  - Row shape feeds the pure category loaders unchanged
  - 'cellular' matches GSM-UPLINK-* + LTE-UPLINK-* wildcards
  - Missing detections.db returns [] instead of raising
  - Sessions co-existing in one DB don't leak into each other
  - Transcripts table overlays voice rows even when written after the
    detection (async transcriber timing)
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _seed(output_dir, signals, ts_offsets=None, signal_type_label="seed"):
    """Open one logger, write the rows, return (output_dir, now)."""
    from utils.logger import SignalLogger, SignalDetection
    from datetime import datetime

    log = SignalLogger(output_dir=output_dir, signal_type=signal_type_label,
                       min_snr_db=0)
    log.start()
    now = time.time()
    for i, (sig, ch) in enumerate(signals):
        det = SignalDetection.create(
            signal_type=sig,
            frequency_hz=(446e6 if sig.startswith("PMR")
                          else 1090e6 if sig == "ADS-B"
                          else 2437e6),
            power_db=-50,
            noise_floor_db=-90,
            channel=ch,
            metadata='{"icao":"ABC"}' if sig == "ADS-B" else "{}",
        )
        if ts_offsets is not None:
            offset = ts_offsets[i]
            det.timestamp = datetime.fromtimestamp(now - offset).isoformat()
        log.log(det)
    log.stop()
    return output_dir, now


def test_voice_predicate_matches_only_voice_types():
    from web.fetch import fetch_detections_for_category

    tmp = tempfile.mkdtemp()
    _seed(tmp, [
        ("PMR446", "CH1"),
        ("MarineVHF", "CH16"),
        ("ADS-B", "ICAO"),
        ("BLE-Adv", ""),
        ("FM_voice", "CH2"),
    ])
    rows = fetch_detections_for_category(tmp, "voice")
    types = {r["signal_type"] for r in rows}
    assert types == {"PMR446", "MarineVHF", "FM_voice"}, \
        f"expected voice types, got {types}"


def test_cellular_wildcard_matching():
    from web.fetch import fetch_detections_for_category

    tmp = tempfile.mkdtemp()
    _seed(tmp, [
        ("GSM-UPLINK-GSM-900", "ARFCN42"),
        ("GSM-UPLINK-GSM-850", "ARFCN5"),
        ("LTE-UPLINK-BAND1", "EARFCN0"),
        ("LTE-UPLINK-BAND20", "EARFCN1"),  # subtype not in CATEGORIES
        ("PMR446", "CH1"),
        ("ADS-B", "ICAO"),
    ])
    rows = fetch_detections_for_category(tmp, "cellular")
    types = {r["signal_type"] for r in rows}
    assert "LTE-UPLINK-BAND20" in types, \
        "cellular wildcard must match new LTE subtypes"
    assert len(types) == 4
    assert "PMR446" not in types


def test_window_filtering():
    """Rows older than window_seconds must be excluded."""
    from web.fetch import fetch_detections_for_category

    tmp = tempfile.mkdtemp()
    _, now = _seed(
        tmp,
        [("PMR446", "CH1"), ("PMR446", "CH2"), ("PMR446", "CH3")],
        ts_offsets=[0, 7200, 14400],
    )
    # 1 hour window: only the 0-offset row
    rows = fetch_detections_for_category(tmp, "voice",
                                         window_seconds=3600, now=now + 1)
    assert len(rows) == 1
    assert rows[0]["channel"] == "CH1"

    # 3 hour window: the 0 and 2h rows
    rows = fetch_detections_for_category(tmp, "voice",
                                         window_seconds=3 * 3600, now=now + 1)
    channels = {r["channel"] for r in rows}
    assert channels == {"CH1", "CH2"}

    # 5 hour window: all three
    rows = fetch_detections_for_category(tmp, "voice",
                                         window_seconds=5 * 3600, now=now + 1)
    assert len(rows) == 3


def test_limit_cap():
    from web.fetch import fetch_detections_for_category

    tmp = tempfile.mkdtemp()
    _seed(tmp, [("PMR446", f"CH{i}") for i in range(1, 11)])
    rows = fetch_detections_for_category(tmp, "voice", limit=3)
    assert len(rows) == 3, f"limit should cap at 3, got {len(rows)}"


def test_shape_compat_with_loaders():
    from web.fetch import fetch_detections_for_category
    from web.loaders import _load_voice, _load_aircraft, _load_ism

    tmp = tempfile.mkdtemp()
    _seed(tmp, [
        ("PMR446", "CH1"),
        ("ADS-B", "icao"),
        ("ISM:Bresser", "433"),
    ])

    voice = _load_voice(fetch_detections_for_category(tmp, "voice"))
    assert len(voice) == 1
    assert voice[0]["signal_type"] == "PMR446"

    ac = _load_aircraft(fetch_detections_for_category(tmp, "aircraft"))
    assert len(ac) == 1
    assert ac[0]["icao"] == "ABC"

    ism = _load_ism(fetch_detections_for_category(tmp, "ism"))
    assert len(ism) == 1
    assert ism[0]["signal_type"] == "ISM:Bresser"


def test_unknown_category_returns_empty():
    from web.fetch import fetch_detections_for_category

    tmp = tempfile.mkdtemp()
    _seed(tmp, [("PMR446", "CH1")])
    rows = fetch_detections_for_category(tmp, "bogus")
    assert rows == []


def test_missing_db_returns_empty():
    from web.fetch import fetch_detections_for_category

    rows = fetch_detections_for_category("/nonexistent/path", "voice")
    assert rows == []


def test_two_sessions_in_one_db():
    """Detections from two scanner sessions land in one DB; the unfiltered
    fetch sees both, the session-id filter narrows to one."""
    from utils import db as _db
    from utils.logger import SignalLogger
    from web.fetch import fetch_detections_for_category

    tmp = tempfile.mkdtemp()
    a = SignalLogger(output_dir=tmp, signal_type="server", min_snr_db=0)
    a.start()
    a.log_signal("WiFi-AP", 2437e6, -70, -95, channel="CH6")
    a.log_signal("BLE-Adv", 2402e6, -65, -95)
    a.stop()
    sid_a = a.session_id

    b = SignalLogger(output_dir=tmp, signal_type="pmr446", min_snr_db=0)
    b.start()
    b.log_signal("PMR446", 446e6, -50, -90, channel="CH1",
                  metadata='{"duration_s":2.5}')
    b.log_signal("PMR446", 446e6, -50, -90, channel="CH2",
                  metadata='{"duration_s":1.8}')
    b.stop()
    sid_b = b.session_id

    # Unfiltered: both sessions visible
    voice = fetch_detections_for_category(tmp, "voice")
    assert len(voice) == 2
    assert {d["channel"] for d in voice} == {"CH1", "CH2"}

    # Filtered to session A: no voice
    assert fetch_detections_for_category(tmp, "voice", session_id=sid_a) == []

    # Filtered to session B: both PMR rows
    voice_b = fetch_detections_for_category(tmp, "voice", session_id=sid_b)
    assert len(voice_b) == 2


def test_fetch_overlays_transcripts_table():
    """The SQL fetch must overlay the `transcripts` table onto voice
    rows. Without this, transcripts written by the async transcriber
    after the detection insert would never reach the Voice tab."""
    from web.fetch import fetch_detections_for_category
    from utils.logger import SignalLogger

    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="sv", min_snr_db=0)
    log.start()
    log.log_signal(
        "PMR446", 446e6, -50, -90, channel="CH7",
        audio_file="pmr_ch7_20260411_150308.wav",
        metadata='{}',
    )
    log.log_transcript("pmr_ch7_20260411_150308.wav",
                       "hola mundo", language="es")
    log.stop()

    rows = fetch_detections_for_category(tmp, "voice")
    assert len(rows) == 1
    assert rows[0]["transcript"] == "hola mundo"


def test_ordering_is_oldest_first():
    """Deque ordering is oldest first, newest last. _load_voice iterates
    reversed(detections) to get newest-first rows."""
    from web.fetch import fetch_detections_for_category
    from web.loaders import _load_voice

    tmp = tempfile.mkdtemp()
    _, now = _seed(
        tmp,
        [("PMR446", "CH1"), ("PMR446", "CH2"), ("PMR446", "CH3")],
        ts_offsets=[300, 200, 100],  # CH1 oldest, CH3 newest
    )
    fetched = fetch_detections_for_category(tmp, "voice")
    assert fetched[0]["channel"] == "CH1"
    assert fetched[-1]["channel"] == "CH3"

    rows = _load_voice(fetched)
    assert rows[0]["channel"] == "CH3"
    assert rows[-1]["channel"] == "CH1"


def run_tests():
    tests = [
        ("Voice predicate",             test_voice_predicate_matches_only_voice_types),
        ("Cellular wildcard",           test_cellular_wildcard_matching),
        ("Window filtering",            test_window_filtering),
        ("Limit cap",                   test_limit_cap),
        ("Loader shape compat",         test_shape_compat_with_loaders),
        ("Unknown category",            test_unknown_category_returns_empty),
        ("Missing db",                  test_missing_db_returns_empty),
        ("Oldest-first ordering",       test_ordering_is_oldest_first),
        ("Two sessions in one DB",      test_two_sessions_in_one_db),
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

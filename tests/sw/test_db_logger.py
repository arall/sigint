"""
Data-layer regression tests for utils/db.py and utils/logger.py.

Covers the path that caused the "check_same_thread" incident:
  server main thread opens SignalLogger → parser threads call log() →
  every insert raises ProgrammingError deep in the capture loop and the
  DB stays empty. This test spawns worker threads and asserts the rows
  actually land.

Run:
    python3 tests/sw/test_db_logger.py
"""

import os
import sqlite3
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def test_connect_creates_schema():
    from utils import db as _db
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "schema.db")
    conn = _db.connect(path)

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [t[0] for t in tables]
    assert "detections" in names, f"detections table missing: {names}"

    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    idx = {i[0] for i in indexes}
    required = {
        "idx_detections_type_ts",
        "idx_detections_ts",
        "idx_detections_device",
        "idx_detections_type_dev",
    }
    missing = required - idx
    assert not missing, f"missing indexes: {missing}"

    # WAL mode must be on
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"expected WAL journal mode, got {mode}"

    conn.close()


def test_insert_and_iter_roundtrip():
    from utils import db as _db
    from utils.logger import SignalDetection

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "round.db")
    conn = _db.connect(path)

    detections = [
        SignalDetection.create(
            signal_type="PMR446", frequency_hz=446_006_250, power_db=-50,
            noise_floor_db=-90, channel="CH1", metadata='{"duration_s":2.5}',
        ),
        SignalDetection.create(
            signal_type="WiFi-AP", frequency_hz=2_437_000_000, power_db=-72,
            noise_floor_db=-95, channel="CH6", device_id="aa:bb:cc:dd:ee:ff",
            metadata='{"ssid":"TestAP"}',
        ),
        SignalDetection.create(
            signal_type="ADS-B", frequency_hz=1_090_000_000, power_db=-60,
            noise_floor_db=-90, channel="ICAO123",
        ),
    ]
    for d in detections:
        _db.insert_detection(conn, d)

    rows = list(_db.iter_detections(conn))
    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"
    assert _db.max_rowid(conn) == 3

    # Row mapping
    shaped = _db.row_to_dict(rows[0])
    assert shaped["signal_type"] == "PMR446"
    assert shaped["channel"] == "CH1"
    assert shaped["metadata"] == '{"duration_s":2.5}'

    # Filtering by type
    wifi = list(_db.iter_detections(conn, signal_type="WiFi-AP"))
    assert len(wifi) == 1
    assert wifi[0]["device_id"] == "aa:bb:cc:dd:ee:ff"

    # Filtering by since_rowid (what the tailer uses for incremental poll)
    tail = list(_db.iter_detections(conn, since_rowid=2))
    assert len(tail) == 1
    assert tail[0]["signal_type"] == "ADS-B"

    conn.close()


def test_multi_thread_insert_no_programming_error():
    """Regression for the check_same_thread footgun. Parsers run on worker
    threads but the logger is opened on the main thread; every insert
    must land without raising sqlite3.ProgrammingError."""
    from utils.logger import SignalLogger

    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="threaded", min_snr_db=0)
    db_path = log.start()

    errors = []
    N_THREADS = 8
    N_PER_THREAD = 50

    def worker(idx):
        try:
            for i in range(N_PER_THREAD):
                log.log_signal(
                    signal_type="WiFi-AP",
                    frequency_hz=2_437_000_000,
                    power_db=-60 - (idx % 10),
                    noise_floor_db=-95,
                    channel=f"CH{(idx % 3) + 1}",
                )
        except Exception as e:
            errors.append((idx, repr(e)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"threaded inserts raised: {errors}"

    log.stop()

    # Reader in a separate connection sees all N_THREADS * N_PER_THREAD rows.
    reader = sqlite3.connect(db_path)
    count = reader.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    reader.close()
    expected = N_THREADS * N_PER_THREAD
    assert count == expected, f"expected {expected} rows on disk, got {count}"


def test_logger_respects_min_snr():
    from utils.logger import SignalLogger

    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="snr", min_snr_db=10)
    db_path = log.start()

    # SNR = power - noise = 5 (below threshold, should drop)
    ok = log.log_signal("PMR446", 446e6, -85, -90, channel="CH1")
    assert ok is False, "min_snr should have dropped this detection"

    # SNR = 20 (above threshold, keeps)
    ok = log.log_signal("PMR446", 446e6, -70, -90, channel="CH1")
    assert ok is True

    log.stop()
    reader = sqlite3.connect(db_path)
    n = reader.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    reader.close()
    assert n == 1, f"expected 1 row (above SNR), got {n}"


def test_logger_autofill_device_id_and_gps():
    from utils.logger import SignalLogger, SignalDetection

    class FakeGPS:
        position = (41.4, 2.1)

    tmp = tempfile.mkdtemp()
    log = SignalLogger(
        output_dir=tmp, signal_type="gps",
        device_id="node-A", min_snr_db=0, gps=FakeGPS(),
    )
    db_path = log.start()

    det = SignalDetection.create("PMR446", 446e6, -50, -90, channel="CH1")
    log.log(det)
    log.stop()

    reader = sqlite3.connect(db_path)
    row = reader.execute(
        "SELECT device_id, latitude, longitude FROM detections"
    ).fetchone()
    reader.close()
    assert row == ("node-A", 41.4, 2.1), f"autofill mismatch: {row}"


def test_concurrent_reader_while_writer():
    """WAL mode lets a reader open the DB while the writer still holds it."""
    from utils.logger import SignalLogger
    from utils import db as _db

    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="wal", min_snr_db=0)
    path = log.start()

    log.log_signal("PMR446", 446e6, -50, -90, channel="CH1")
    log.log_signal("PMR446", 446e6, -50, -90, channel="CH2")

    # Open a second connection while the writer is still alive
    reader = _db.connect(path, readonly=True)
    rows = list(_db.iter_detections(reader))
    assert len(rows) >= 2, f"reader saw {len(rows)} rows while writer open"
    reader.close()

    # Writer keeps writing after the reader closes
    log.log_signal("PMR446", 446e6, -50, -90, channel="CH3")

    reader2 = _db.connect(path, readonly=True)
    rows2 = list(_db.iter_detections(reader2))
    assert len(rows2) == 3, f"reader2 saw {len(rows2)} rows after new write"
    reader2.close()

    log.stop()


def run_tests():
    tests = [
        ("Schema + indexes + WAL",       test_connect_creates_schema),
        ("Insert + iter roundtrip",      test_insert_and_iter_roundtrip),
        ("Multi-thread insert safety",   test_multi_thread_insert_no_programming_error),
        ("Logger respects min_snr_db",   test_logger_respects_min_snr),
        ("Autofill device_id + GPS",     test_logger_autofill_device_id_and_gps),
        ("WAL reader while writer",      test_concurrent_reader_while_writer),
    ]

    print("=" * 60)
    print("DB + Logger Tests")
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

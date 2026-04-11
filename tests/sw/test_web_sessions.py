"""
Tests for web/sessions.py — session discovery + path-traversal guard.

Covers:
  - list_sessions on empty dir
  - list_sessions returns one row per .db, sorted newest-first
  - Oldest files ignored, WAL/SHM sidecars skipped
  - Metadata: detection_count, types, first_ts, last_ts
  - `live` flag marks the newest session only
  - Metadata cache: same mtime → cached; different mtime → refreshed
  - resolve_session_path accepts valid names
  - resolve_session_path rejects path traversal / absolute / wrong ext

Run:
    python3 tests/sw/test_web_sessions.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _make_session_db(output_dir, name, signals):
    """Write a .db file directly so we control the filename."""
    from utils import db as _db
    from utils.logger import SignalDetection
    path = os.path.join(output_dir, name)
    conn = _db.connect(path)
    for sig, ch in signals:
        det = SignalDetection.create(
            signal_type=sig, frequency_hz=446e6,
            power_db=-50, noise_floor_db=-90, channel=ch,
        )
        _db.insert_detection(conn, det)
    conn.close()
    return path


def test_list_sessions_empty_dir():
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    assert list_sessions(tmp) == []


def test_list_sessions_missing_dir():
    from web.sessions import list_sessions
    assert list_sessions("/nonexistent/path") == []


def test_list_sessions_skips_wal_and_shm():
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    _make_session_db(tmp, "session1.db", [("PMR446", "CH1")])
    # Fake WAL/SHM sidecars
    open(os.path.join(tmp, "session1.db-wal"), "w").close()
    open(os.path.join(tmp, "session1.db-shm"), "w").close()
    sessions = list_sessions(tmp)
    assert len(sessions) == 1
    assert sessions[0]["name"] == "session1.db"


def test_list_sessions_newest_first_and_live_flag():
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    p1 = _make_session_db(tmp, "older.db", [("PMR446", "CH1")])
    time.sleep(0.05)
    p2 = _make_session_db(tmp, "middle.db", [("PMR446", "CH2")])
    time.sleep(0.05)
    p3 = _make_session_db(tmp, "newest.db", [("PMR446", "CH3")])

    sessions = list_sessions(tmp)
    names = [s["name"] for s in sessions]
    assert names == ["newest.db", "middle.db", "older.db"], \
        f"expected newest first, got {names}"
    assert sessions[0]["live"] is True
    assert sessions[1]["live"] is False
    assert sessions[2]["live"] is False


def test_session_metadata_counts_and_types():
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    _make_session_db(tmp, "mixed.db", [
        ("PMR446", "CH1"),
        ("PMR446", "CH2"),
        ("ADS-B", "icao1"),
        ("BLE-Adv", ""),
    ])
    sessions = list_sessions(tmp)
    assert len(sessions) == 1
    s = sessions[0]
    assert s["detection_count"] == 4
    assert set(s["types"]) == {"PMR446", "ADS-B", "BLE-Adv"}
    assert s["first_ts"] != ""
    assert s["last_ts"] != ""
    assert s["size_bytes"] > 0


def test_metadata_cache_by_mtime():
    """Same file, same mtime → cached. Bumping mtime → refreshed."""
    from web import sessions as sess_mod

    tmp = tempfile.mkdtemp()
    path = _make_session_db(tmp, "cache.db", [("PMR446", "CH1")])

    # First call populates cache
    sess_mod._metadata_cache.clear()
    m1 = sess_mod._get_metadata(path, os.stat(path).st_mtime)
    assert m1["detection_count"] == 1

    # Second call with same mtime → no recompute. Patch _read_metadata
    # so we can detect a stray call.
    orig = sess_mod._read_metadata
    calls = []
    def spy(p):
        calls.append(p)
        return orig(p)
    sess_mod._read_metadata = spy
    try:
        m2 = sess_mod._get_metadata(path, os.stat(path).st_mtime)
        assert calls == [], "cache hit should not recompute"

        # New mtime → recompute
        fake_mtime = os.stat(path).st_mtime + 1
        m3 = sess_mod._get_metadata(path, fake_mtime)
        assert len(calls) == 1, "stale cache should recompute"
    finally:
        sess_mod._read_metadata = orig


def test_metadata_of_broken_db_returns_empty():
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    # Empty file ending in .db — should not crash
    with open(os.path.join(tmp, "broken.db"), "w") as f:
        f.write("not a sqlite db")
    sessions = list_sessions(tmp)
    assert len(sessions) == 1
    assert sessions[0]["detection_count"] == 0
    assert sessions[0]["types"] == []


def test_resolve_session_path_happy():
    from web.sessions import resolve_session_path
    tmp = tempfile.mkdtemp()
    _make_session_db(tmp, "ok.db", [("PMR446", "CH1")])
    assert resolve_session_path(tmp, "ok.db") == os.path.join(tmp, "ok.db")


def test_resolve_session_path_rejects_traversal():
    from web.sessions import resolve_session_path
    tmp = tempfile.mkdtemp()
    assert resolve_session_path(tmp, "../../etc/passwd") is None
    assert resolve_session_path(tmp, "../secret.db") is None
    assert resolve_session_path(tmp, "/etc/passwd") is None
    assert resolve_session_path(tmp, "subdir/file.db") is None
    assert resolve_session_path(tmp, "..") is None


def test_resolve_session_path_wrong_extension():
    from web.sessions import resolve_session_path
    tmp = tempfile.mkdtemp()
    # Create a real file that isn't a .db
    with open(os.path.join(tmp, "data.csv"), "w") as f:
        f.write("foo,bar\n")
    assert resolve_session_path(tmp, "data.csv") is None


def test_resolve_session_path_missing_file():
    from web.sessions import resolve_session_path
    tmp = tempfile.mkdtemp()
    assert resolve_session_path(tmp, "nope.db") is None


def test_resolve_session_path_empty_or_none():
    from web.sessions import resolve_session_path
    assert resolve_session_path("/tmp", None) is None
    assert resolve_session_path("/tmp", "") is None


def run_tests():
    tests = [
        ("list_sessions empty dir",        test_list_sessions_empty_dir),
        ("list_sessions missing dir",      test_list_sessions_missing_dir),
        ("list_sessions skips WAL/SHM",    test_list_sessions_skips_wal_and_shm),
        ("Newest first + live flag",       test_list_sessions_newest_first_and_live_flag),
        ("Metadata counts + types",        test_session_metadata_counts_and_types),
        ("Metadata cache by mtime",        test_metadata_cache_by_mtime),
        ("Broken .db doesn't crash",       test_metadata_of_broken_db_returns_empty),
        ("resolve_session_path happy",     test_resolve_session_path_happy),
        ("resolve rejects traversal",      test_resolve_session_path_rejects_traversal),
        ("resolve rejects wrong ext",      test_resolve_session_path_wrong_extension),
        ("resolve rejects missing file",   test_resolve_session_path_missing_file),
        ("resolve rejects empty",          test_resolve_session_path_empty_or_none),
    ]

    print("=" * 60)
    print("Web Sessions Tests")
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

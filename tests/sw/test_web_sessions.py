"""
Tests for web/sessions.py — sessions-table listing.

Sessions are rows in the unified `output/detections.db`'s `sessions`
table. The dashboard's session selector references them by integer id;
the `?session=<id>` query param maps to a `WHERE session_id = ?` clause.

Covers:
  - list_sessions on empty / missing dir
  - list_sessions returns one row per `sessions` table entry, newest first
  - Active sessions (NULL ended_at) get `live = True`
  - detection_count + types match what's in the DB for that session
  - session_exists guards integer ids
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _open_session_with_dets(output_dir, kind, label, signals,
                             close=True, agent_id=None):
    from utils import db as _db
    from utils.logger import SignalDetection
    path = _db.default_db_path(output_dir)
    conn = _db.connect(path)
    sid = _db.open_session(conn, kind=kind, label=label, pid=os.getpid())
    for sig, ch in signals:
        det = SignalDetection.create(
            signal_type=sig, frequency_hz=446e6,
            power_db=-50, noise_floor_db=-90, channel=ch,
        )
        _db.insert_detection(conn, det, session_id=sid, agent_id=agent_id)
    if close:
        _db.close_session(conn, sid)
    conn.close()
    return sid


def test_list_sessions_empty_dir():
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    assert list_sessions(tmp) == []


def test_list_sessions_missing_dir():
    from web.sessions import list_sessions
    assert list_sessions("/nonexistent/path") == []


def test_list_sessions_newest_first_and_live_flag():
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    _open_session_with_dets(tmp, "scanner:pmr", "older",
                             [("PMR446", "CH1")])
    time.sleep(0.05)
    _open_session_with_dets(tmp, "scanner:pmr", "middle",
                             [("PMR446", "CH2")])
    time.sleep(0.05)
    _open_session_with_dets(tmp, "scanner:pmr", "newest",
                             [("PMR446", "CH3")], close=False)

    sessions = list_sessions(tmp)
    labels = [s["label"] for s in sessions]
    assert labels == ["newest", "middle", "older"], \
        f"expected newest first, got {labels}"
    # The active (non-closed) one is `live`.
    assert sessions[0]["live"] is True
    assert sessions[1]["live"] is False
    assert sessions[2]["live"] is False


def test_session_metadata_counts_and_types():
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    _open_session_with_dets(tmp, "scanner:mixed", "mixed", [
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


def test_session_metadata_scoped_per_session():
    """Two sessions in the same DB should report disjoint counts."""
    from web.sessions import list_sessions
    tmp = tempfile.mkdtemp()
    _open_session_with_dets(tmp, "scanner:a", "a", [("PMR446", "CH1")])
    _open_session_with_dets(tmp, "scanner:b", "b",
                             [("ADS-B", ""), ("ADS-B", "")])
    sessions = {s["label"]: s for s in list_sessions(tmp)}
    assert sessions["a"]["detection_count"] == 1
    assert sessions["b"]["detection_count"] == 2
    assert sessions["a"]["types"] == ["PMR446"]
    assert sessions["b"]["types"] == ["ADS-B"]


def test_session_exists_happy_and_invalid():
    from web.sessions import session_exists
    tmp = tempfile.mkdtemp()
    sid = _open_session_with_dets(tmp, "scanner:test", "t",
                                   [("PMR446", "CH1")])
    assert session_exists(tmp, sid)
    assert session_exists(tmp, str(sid))   # str ids accepted
    assert not session_exists(tmp, sid + 999)
    assert not session_exists(tmp, "not-an-int")
    assert not session_exists(tmp, None)


def test_session_exists_missing_db():
    from web.sessions import session_exists
    tmp = tempfile.mkdtemp()
    # No detections.db yet
    assert not session_exists(tmp, 1)


def run_tests():
    tests = [
        ("list_sessions empty dir",        test_list_sessions_empty_dir),
        ("list_sessions missing dir",      test_list_sessions_missing_dir),
        ("Newest first + live flag",       test_list_sessions_newest_first_and_live_flag),
        ("Metadata counts + types",        test_session_metadata_counts_and_types),
        ("Per-session metadata is scoped", test_session_metadata_scoped_per_session),
        ("session_exists happy + invalid", test_session_exists_happy_and_invalid),
        ("session_exists missing db",      test_session_exists_missing_db),
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

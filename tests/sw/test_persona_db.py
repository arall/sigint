"""
Tests for utils/persona_db.py merge semantics.

Covers:
  - Exact-match update (same dev_sig + same SSID set)
  - SSID overlap match (same dev_sig, partially overlapping SSIDs)
  - Broadcast-only (empty SSIDs) persona
  - apple_device persistence across flushes (BLE AirPods / Watch labels
    must survive save/load/merge; this is the regression for the Apple
    Watch collapsing to generic "Apple" after restart)
  - session counter increments exactly once per find+update cycle
  - save/load roundtrip

Run:
    python3 tests/sw/test_persona_db.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def test_exact_match_update():
    from utils.persona_db import PersonaDB

    db = PersonaDB(os.path.join(tempfile.mkdtemp(), "p.json"))
    db.update_persona(
        dev_sig="abc123", ssids={"HomeWiFi"}, macs={"aa:11:22:33:44:55"},
        manufacturer="Apple", randomized=True, probe_count=10,
    )
    db.update_persona(
        dev_sig="abc123", ssids={"HomeWiFi"}, macs={"bb:11:22:33:44:55"},
        manufacturer="Apple", randomized=True, probe_count=5,
    )
    personas = db._data["personas"]
    assert len(personas) == 1, f"expected 1 merged persona, got {len(personas)}"
    p = list(personas.values())[0]
    assert p["sessions"] == 2
    assert p["total_probes"] == 15
    assert set(p["macs_seen"]) == {"aa:11:22:33:44:55", "bb:11:22:33:44:55"}


def test_ssid_overlap_match():
    """Same dev_sig + overlapping (not identical) SSIDs → one persona."""
    from utils.persona_db import PersonaDB

    db = PersonaDB(os.path.join(tempfile.mkdtemp(), "p.json"))
    db.update_persona(
        dev_sig="abc123", ssids={"HomeWiFi", "Gym"},
        macs={"aa:bb:cc:dd:ee:01"},
        manufacturer="Apple", randomized=True, probe_count=10,
    )
    # Session 2: same device, probes for HomeWiFi + a new SSID
    db.update_persona(
        dev_sig="abc123", ssids={"HomeWiFi", "Cafe"},
        macs={"aa:bb:cc:dd:ee:02"},
        manufacturer="Apple", randomized=True, probe_count=3,
    )
    personas = db._data["personas"]
    assert len(personas) == 1, f"overlap should merge into 1, got {len(personas)}"
    p = list(personas.values())[0]
    assert set(p["ssids"]) == {"HomeWiFi", "Gym", "Cafe"}
    assert p["sessions"] == 2
    assert p["total_probes"] == 13


def test_broadcast_only_persona():
    """Device with no advertised SSIDs is keyed by dev_sig alone."""
    from utils.persona_db import PersonaDB

    db = PersonaDB(os.path.join(tempfile.mkdtemp(), "p.json"))
    db.update_persona(
        dev_sig="ble001", ssids=set(), macs={"aa:bb:cc:dd:ee:ff"},
        manufacturer="Apple", randomized=True, probe_count=1,
    )
    db.update_persona(
        dev_sig="ble001", ssids=set(), macs={"11:22:33:44:55:66"},
        manufacturer="Apple", randomized=True, probe_count=1,
    )
    personas = db._data["personas"]
    assert len(personas) == 1
    p = list(personas.values())[0]
    assert p["sessions"] == 2
    assert len(p["macs_seen"]) == 2


def test_apple_device_persists():
    """AirPods / Apple Watch / MacBook specific labels must survive
    save + reload + merge. This is the regression for the Apple devices
    collapsing to generic 'Apple' after server restart."""
    from utils.persona_db import PersonaDB

    path = os.path.join(tempfile.mkdtemp(), "p.json")
    db = PersonaDB(path)
    db.update_persona(
        dev_sig="apple-watch-1", ssids=set(), macs={"aa:11:22:33:44:55"},
        manufacturer="Apple", randomized=True, probe_count=1,
        apple_device="Apple Watch",
    )
    db.save()

    # Reload from disk
    db2 = PersonaDB(path)
    p = list(db2._data["personas"].values())[0]
    assert p.get("apple_device") == "Apple Watch", \
        f"apple_device lost: {p.get('apple_device')}"

    # Merge with another observation that doesn't supply apple_device
    db2.update_persona(
        dev_sig="apple-watch-1", ssids=set(), macs={"bb:22:33:44:55:66"},
        manufacturer="Apple", randomized=True, probe_count=2,
    )
    p = list(db2._data["personas"].values())[0]
    assert p.get("apple_device") == "Apple Watch", \
        "existing apple_device must not be clobbered by a merge"


def test_apple_device_can_be_added_later():
    """If the first observation of a device doesn't include apple_device
    yet, a subsequent merge that DOES supply it should populate it."""
    from utils.persona_db import PersonaDB

    db = PersonaDB(os.path.join(tempfile.mkdtemp(), "p.json"))
    db.update_persona(
        dev_sig="ipad-1", ssids=set(), macs={"aa:11:22:33:44:55"},
        manufacturer="Apple", randomized=True, probe_count=1,
    )
    db.update_persona(
        dev_sig="ipad-1", ssids=set(), macs={"bb:22:33:44:55:66"},
        manufacturer="Apple", randomized=True, probe_count=1,
        apple_device="iPad",
    )
    p = list(db._data["personas"].values())[0]
    assert p.get("apple_device") == "iPad"


def test_save_load_roundtrip():
    from utils.persona_db import PersonaDB

    path = os.path.join(tempfile.mkdtemp(), "p.json")
    db = PersonaDB(path)
    db.update_persona(
        dev_sig="d1", ssids={"Net1"}, macs={"aa:bb:cc:dd:ee:ff"},
        manufacturer="Samsung", randomized=False, probe_count=7,
    )
    db.update_persona(
        dev_sig="d2", ssids={"Net2"}, macs={"11:22:33:44:55:66"},
        manufacturer="Google", randomized=False, probe_count=3,
    )
    db.save()

    db2 = PersonaDB(path)
    assert db2.total_personas == 2
    summary = db2.summary()
    assert summary["total"] == 2
    assert summary["updated"] is not None


def test_get_session_count():
    from utils.persona_db import PersonaDB

    db = PersonaDB(os.path.join(tempfile.mkdtemp(), "p.json"))
    # No prior sessions for an unknown persona
    assert db.get_session_count("unknown", {"SomeSSID"}) == 0

    db.update_persona(
        dev_sig="d1", ssids={"N1"}, macs={"aa:bb:cc:dd:ee:01"},
        manufacturer="", randomized=False, probe_count=1,
    )
    assert db.get_session_count("d1", {"N1"}) == 1

    db.update_persona(
        dev_sig="d1", ssids={"N1"}, macs={"aa:bb:cc:dd:ee:02"},
        manufacturer="", randomized=False, probe_count=1,
    )
    assert db.get_session_count("d1", {"N1"}) == 2


def run_tests():
    tests = [
        ("Exact-match update",           test_exact_match_update),
        ("SSID overlap match",           test_ssid_overlap_match),
        ("Broadcast-only persona",       test_broadcast_only_persona),
        ("apple_device persists",        test_apple_device_persists),
        ("apple_device backfilled",      test_apple_device_can_be_added_later),
        ("save + load roundtrip",        test_save_load_roundtrip),
        ("get_session_count",            test_get_session_count),
    ]

    print("=" * 60)
    print("PersonaDB Tests")
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

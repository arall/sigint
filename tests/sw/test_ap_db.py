"""
Tests for utils/ap_db.py merge semantics.

Covers:
  - First observation creates a record keyed by BSSID
  - SSIDs / channels accumulate over observations (no dup entries)
  - Associated clients are union-merged across observations
  - client_count stays consistent with the clients list length
  - hidden flag flips off once a real SSID shows up
  - sessions counter increments once per process (not per flush)
  - save/load roundtrip

Run:
    python3 tests/sw/test_ap_db.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _make_db():
    from utils.ap_db import ApDB
    return ApDB(os.path.join(tempfile.mkdtemp(), "aps.json"))


def test_first_observation_creates_record():
    db = _make_db()
    db.update_ap(
        bssid="aa:bb:cc:dd:ee:ff",
        ssid="Home",
        channel=6,
        crypto="WPA2-PSK",
        manufacturer="Ubiquiti",
        rssi=-60,
        hidden=False,
        beacon_interval=100,
        total_beacons=5,
        first_seen="2026-04-11T10:00:00",
        last_seen="2026-04-11T10:05:00",
        clients=["11:22:33:44:55:66"],
    )
    rec = db.all_aps()["aa:bb:cc:dd:ee:ff"]
    assert rec["ssids"] == ["Home"]
    assert rec["channels"] == [6]
    assert rec["crypto"] == "WPA2-PSK"
    assert rec["client_count"] == 1
    assert rec["sessions"] == 1
    assert rec["total_beacons"] == 5


def test_ssids_and_channels_accumulate():
    db = _make_db()
    bssid = "aa:bb:cc:dd:ee:ff"
    db.update_ap(
        bssid=bssid, ssid="Home", channel=6, crypto="WPA2-PSK",
        manufacturer="", rssi=-60, hidden=False, beacon_interval=100,
        total_beacons=1, first_seen="2026-04-11T10:00:00",
        last_seen="2026-04-11T10:00:00",
    )
    # Same AP re-observed on a different channel + with an extra SSID
    db.update_ap(
        bssid=bssid, ssid="HomeGuest", channel=36, crypto="WPA2-PSK",
        manufacturer="", rssi=-58, hidden=False, beacon_interval=100,
        total_beacons=10, first_seen="2026-04-11T10:00:00",
        last_seen="2026-04-11T10:10:00",
    )
    # Duplicate — neither should add again
    db.update_ap(
        bssid=bssid, ssid="Home", channel=6, crypto="WPA2-PSK",
        manufacturer="", rssi=-60, hidden=False, beacon_interval=100,
        total_beacons=12, first_seen="2026-04-11T10:00:00",
        last_seen="2026-04-11T10:11:00",
    )

    rec = db.all_aps()[bssid]
    assert set(rec["ssids"]) == {"Home", "HomeGuest"}
    assert set(rec["channels"]) == {6, 36}
    assert rec["total_beacons"] == 12
    assert rec["last_seen"] == "2026-04-11T10:11:00"


def test_clients_accumulate_across_flushes():
    db = _make_db()
    bssid = "aa:bb:cc:dd:ee:ff"

    db.update_ap(
        bssid=bssid, ssid="Home", channel=6, crypto="WPA2-PSK",
        manufacturer="", rssi=-60, hidden=False, beacon_interval=100,
        total_beacons=1, first_seen="t0", last_seen="t0",
        clients=["c1:01", "c1:02"],
    )
    db.update_ap(
        bssid=bssid, ssid="Home", channel=6, crypto="WPA2-PSK",
        manufacturer="", rssi=-60, hidden=False, beacon_interval=100,
        total_beacons=2, first_seen="t0", last_seen="t1",
        clients=["c1:02", "c1:03"],  # one dup + one new
    )
    rec = db.all_aps()[bssid]
    assert set(rec["clients"]) == {"c1:01", "c1:02", "c1:03"}
    assert rec["client_count"] == 3


def test_hidden_cleared_when_ssid_appears():
    db = _make_db()
    bssid = "aa:bb:cc:dd:ee:ff"

    # First observation: hidden SSID (empty)
    db.update_ap(
        bssid=bssid, ssid="", channel=1, crypto="WPA2-PSK",
        manufacturer="", rssi=-70, hidden=True, beacon_interval=100,
        total_beacons=1, first_seen="t0", last_seen="t0",
    )
    assert db.all_aps()[bssid]["hidden"] is True

    # Later the AP broadcasts its real SSID
    db.update_ap(
        bssid=bssid, ssid="HomeNet", channel=1, crypto="WPA2-PSK",
        manufacturer="", rssi=-70, hidden=False, beacon_interval=100,
        total_beacons=2, first_seen="t0", last_seen="t1",
    )
    rec = db.all_aps()[bssid]
    assert rec["hidden"] is False
    assert "HomeNet" in rec["ssids"]


def test_sessions_increments_once_per_process():
    db = _make_db()
    bssid = "aa:bb:cc:dd:ee:ff"

    for i in range(5):
        db.update_ap(
            bssid=bssid, ssid="Home", channel=6, crypto="WPA2-PSK",
            manufacturer="", rssi=-60, hidden=False, beacon_interval=100,
            total_beacons=i + 1, first_seen="t0", last_seen=f"t{i}",
        )
    rec = db.all_aps()[bssid]
    # 5 flushes in the same process should still equal 1 session
    assert rec["sessions"] == 1, f"expected 1 session, got {rec['sessions']}"


def test_sessions_increments_across_processes():
    """Second instantiation (new process) pointing at the same file
    increments sessions on first observation of each BSSID."""
    from utils.ap_db import ApDB

    path = os.path.join(tempfile.mkdtemp(), "aps.json")
    db1 = ApDB(path)
    db1.update_ap(
        bssid="aa:bb:cc:dd:ee:ff", ssid="Home", channel=6, crypto="WPA2-PSK",
        manufacturer="", rssi=-60, hidden=False, beacon_interval=100,
        total_beacons=5, first_seen="t0", last_seen="t0",
    )
    db1.save()

    db2 = ApDB(path)  # "new process"
    db2.update_ap(
        bssid="aa:bb:cc:dd:ee:ff", ssid="Home", channel=6, crypto="WPA2-PSK",
        manufacturer="", rssi=-60, hidden=False, beacon_interval=100,
        total_beacons=10, first_seen="t0", last_seen="t1",
    )
    rec = db2.all_aps()["aa:bb:cc:dd:ee:ff"]
    assert rec["sessions"] == 2


def test_save_load_roundtrip():
    from utils.ap_db import ApDB

    path = os.path.join(tempfile.mkdtemp(), "aps.json")
    db = ApDB(path)
    db.update_ap(
        bssid="aa:bb:cc:dd:ee:ff", ssid="Home", channel=6, crypto="WPA2-PSK",
        manufacturer="Vendor", rssi=-60, hidden=False, beacon_interval=100,
        total_beacons=42, first_seen="t0", last_seen="t1",
        clients=["c1", "c2"],
    )
    db.save()

    db2 = ApDB(path)
    assert db2.total_aps == 1
    rec = list(db2.all_aps().values())[0]
    assert rec["ssids"] == ["Home"]
    assert rec["client_count"] == 2
    assert rec["total_beacons"] == 42


def run_tests():
    tests = [
        ("First observation",           test_first_observation_creates_record),
        ("SSIDs + channels accumulate", test_ssids_and_channels_accumulate),
        ("Clients accumulate",          test_clients_accumulate_across_flushes),
        ("Hidden flag flips",           test_hidden_cleared_when_ssid_appears),
        ("Sessions per process",        test_sessions_increments_once_per_process),
        ("Sessions across processes",   test_sessions_increments_across_processes),
        ("save + load roundtrip",       test_save_load_roundtrip),
    ]

    print("=" * 60)
    print("ApDB Tests")
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

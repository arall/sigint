"""
Tests for web/loaders.py + web/categories.py.

These are pure functions that take either an output directory (device
loaders) or a list of in-memory detection dicts (category loaders) and
return shaped row lists the dashboard renders. Lightweight, no HTTP.

Covers:
  - category_of: direct match + GSM-UPLINK / LTE-UPLINK wildcard + "other" fallback
  - All 7 category loaders on empty input (no crash, empty list)
  - Voice: per-transmission rows with transcript / duration / audio
  - Drones: grouped by RemoteID serial, latest GPS + operator GPS merged
  - Aircraft: grouped by ICAO, latest callsign + altitude + speed
  - Vessels: grouped by MMSI with name / speed / position
  - Vehicles: TPMS by sensor_id, keyfob by data_hex
  - Cellular: wildcard signal_type → grouped by frequency
  - Other: ISM / LoRa / POCSAG catch-all
  - Device loaders: WiFi clients don't get SSIDs as their label (NSA
    Hotspot regression), BLE uses apple_device when present
  - WiFi AP grouping: same SSID + first-5-octet prefix → one row

Run:
    python3 tests/sw/test_web_loaders.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _det(signal_type, **kw):
    """Build a detection dict matching DBTailer's _detections shape."""
    defaults = {
        "timestamp": "2026-04-11T12:00:00",
        "signal_type": signal_type,
        "frequency_mhz": 0.0,
        "channel": "",
        "snr_db": 20.0,
        "power_db": -60.0,
        "audio_file": None,
        "detail": "",
        "transcript": None,
        "dev_sig": "",
        "apple_device": "",
        "device_id": "",
        "latitude": None,
        "longitude": None,
        "meta": {},
    }
    defaults.update(kw)
    from web.categories import category_of
    defaults["category"] = category_of(signal_type)
    return defaults


def test_category_of_direct_match():
    from web.categories import category_of

    assert category_of("PMR446") == "voice"
    assert category_of("dPMR") == "voice"
    assert category_of("FM_voice") == "voice"
    assert category_of("RemoteID") == "drones"
    assert category_of("DroneCtrl") == "drones"
    assert category_of("DroneVideo") == "drones"
    assert category_of("ADS-B") == "aircraft"
    assert category_of("AIS") == "vessels"
    assert category_of("tpms") == "vehicles"
    assert category_of("keyfob") == "vehicles"
    assert category_of("BLE-Adv") == "devices"
    assert category_of("WiFi-Probe") == "devices"
    assert category_of("WiFi-AP") == "devices"
    assert category_of("ISM") == "other"


def test_category_of_wildcards():
    from web.categories import category_of

    assert category_of("GSM-UPLINK-GSM-900") == "cellular"
    assert category_of("GSM-UPLINK-GSM-850") == "cellular"
    assert category_of("LTE-UPLINK-BAND1") == "cellular"
    assert category_of("LTE-UPLINK-BAND20") == "cellular"
    assert category_of("unknown_thing") == "other"
    assert category_of("") == "other"


def test_all_category_loaders_handle_empty():
    from web.loaders import CATEGORY_LOADERS

    for name, fn in CATEGORY_LOADERS.items():
        out = fn([])
        assert out == [], f"{name} loader should return [] on empty, got {out}"


def test_load_voice():
    from web.loaders import _load_voice

    dets = [
        _det("PMR446", channel="CH1", frequency_mhz=446.006, snr_db=25.0,
             audio_file="a.wav", transcript="hello",
             meta={"duration_s": 2.5, "language": "en"}),
        _det("ADS-B", channel="icao"),  # should be filtered out
        _det("MarineVHF", channel="CH16", frequency_mhz=156.800, snr_db=18.0,
             meta={"duration_s": 5.0}),
    ]
    rows = _load_voice(dets)
    assert len(rows) == 2
    # Newest-first via reversed()
    assert rows[0]["signal_type"] == "MarineVHF"
    assert rows[0]["duration_s"] == 5.0
    assert rows[1]["signal_type"] == "PMR446"
    assert rows[1]["transcript"] == "hello"
    assert rows[1]["language"] == "en"


def test_load_drones_by_serial():
    from web.loaders import _load_drones

    dets = [
        _det("RemoteID", timestamp="2026-04-11T12:00:00",
             meta={"serial_number": "ABC123", "latitude": 41.4, "longitude": 2.1,
                   "altitude": 50.0, "speed": 10.0, "ua_type": "Quadcopter"}),
        _det("RemoteID", timestamp="2026-04-11T12:00:10",
             meta={"serial_number": "ABC123", "latitude": 41.41, "longitude": 2.11,
                   "altitude": 60.0, "speed": 12.0, "ua_type": "Quadcopter"}),
        _det("RemoteID-operator", timestamp="2026-04-11T12:00:05",
             meta={"serial_number": "ABC123", "latitude": 41.399, "longitude": 2.099}),
        _det("DroneCtrl", frequency_mhz=868.3,
             meta={"protocol": "ELRS"}),
    ]
    rows = _load_drones(dets)

    # Find the RemoteID row for ABC123
    serials = {r.get("serial"): r for r in rows if r["signal_type"] == "RemoteID"}
    assert "ABC123" in serials, f"missing drone ABC123, got {serials.keys()}"
    rec = serials["ABC123"]
    assert rec["count"] == 2  # two RemoteID obs
    assert rec["last_lat"] == 41.41  # latest wins
    assert rec["last_lon"] == 2.11
    assert rec["altitude_m"] == 60.0
    assert rec["speed_ms"] == 12.0

    # Operator gets its own row (keyed with :op suffix)
    op_rows = [r for r in rows if r["signal_type"] == "RemoteID-operator"]
    assert len(op_rows) == 1
    assert op_rows[0]["op_lat"] == 41.399

    # DroneCtrl gets its own row
    ctrl_rows = [r for r in rows if r["signal_type"] == "DroneCtrl"]
    assert len(ctrl_rows) == 1
    assert ctrl_rows[0]["protocol"] == "ELRS"


def test_load_aircraft_by_icao():
    from web.loaders import _load_aircraft

    dets = [
        _det("ADS-B", timestamp="2026-04-11T12:00:00",
             latitude=41.4, longitude=2.1,
             meta={"icao": "4CA123", "callsign": "IBE123",
                   "altitude": 35000, "speed": 450, "heading": 90}),
        _det("ADS-B", timestamp="2026-04-11T12:00:10",
             latitude=41.42, longitude=2.12,
             meta={"icao": "4CA123", "altitude": 36000, "speed": 460, "heading": 92}),
        _det("ADS-B", timestamp="2026-04-11T12:00:05",
             meta={"icao": "A11111", "callsign": "UAL99",
                   "altitude": 10000}),
        _det("PMR446", channel="CH1"),  # filtered
    ]
    rows = _load_aircraft(dets)
    by_icao = {r["icao"]: r for r in rows}
    assert set(by_icao) == {"4CA123", "A11111"}
    ib = by_icao["4CA123"]
    assert ib["callsign"] == "IBE123"      # preserved across later obs
    assert ib["altitude_ft"] == 36000       # latest wins
    assert ib["speed_kt"] == 460
    assert ib["heading"] == 92
    assert ib["latitude"] == 41.42          # latest position
    assert ib["count"] == 2


def test_load_vessels_by_mmsi():
    from web.loaders import _load_vessels

    dets = [
        _det("AIS", timestamp="2026-04-11T12:00:00",
             latitude=41.4, longitude=2.1,
             meta={"mmsi": "224123456", "name": "CARGO SHIP",
                   "ship_type": "Cargo", "nav_status": "Under way",
                   "speed": 12.5, "course": 270.0}),
        _det("AIS", timestamp="2026-04-11T12:00:30",
             latitude=41.41, longitude=2.11,
             meta={"mmsi": "224123456", "speed": 13.0}),
    ]
    rows = _load_vessels(dets)
    assert len(rows) == 1
    v = rows[0]
    assert v["mmsi"] == "224123456"
    assert v["name"] == "CARGO SHIP"
    assert v["ship_type"] == "Cargo"
    assert v["speed_kn"] == 13.0
    assert v["count"] == 2


def test_load_vehicles_tpms_and_keyfob():
    from web.loaders import _load_vehicles

    dets = [
        _det("tpms", frequency_mhz=433.92,
             meta={"sensor_id": "ABCD1234", "protocol": "Ford",
                   "pressure_kpa": 220.0, "temperature_c": 25.0}),
        _det("tpms", frequency_mhz=433.92,
             meta={"sensor_id": "ABCD1234", "protocol": "Ford",
                   "pressure_kpa": 221.0, "temperature_c": 26.0}),
        _det("keyfob", frequency_mhz=433.92,
             meta={"data_hex": "abcdef01", "protocol": "PT2262"}),
        _det("keyfob", frequency_mhz=315.0,
             meta={"data_hex": "abcdef01", "protocol": "PT2262"}),
    ]
    rows = _load_vehicles(dets)
    kinds = [r["kind"] for r in rows]
    assert "TPMS" in kinds and "Keyfob" in kinds

    tpms = next(r for r in rows if r["kind"] == "TPMS")
    assert tpms["id"] == "ABCD1234"
    assert tpms["count"] == 2
    assert tpms["pressure_kpa"] == 221.0
    assert tpms["temperature_c"] == 26.0

    # Same data_hex on different frequencies → same burst fingerprint, one row
    kf = [r for r in rows if r["kind"] == "Keyfob"]
    assert len(kf) == 1
    assert kf[0]["count"] == 2


def test_load_cellular_wildcard_grouping():
    from web.loaders import _load_cellular

    dets = [
        _det("GSM-UPLINK-GSM-900", frequency_mhz=902.5, channel="ARFCN42"),
        _det("GSM-UPLINK-GSM-900", frequency_mhz=902.5, channel="ARFCN42"),
        _det("LTE-UPLINK-BAND1",   frequency_mhz=1920.0, channel="EARFCN0"),
        _det("PMR446", channel="CH1"),  # filtered
    ]
    rows = _load_cellular(dets)
    assert len(rows) == 2
    techs = {r["technology"] for r in rows}
    assert techs == {"GSM", "LTE"}
    gsm = next(r for r in rows if r["technology"] == "GSM")
    assert gsm["count"] == 2


def test_load_other_catchall():
    from web.loaders import _load_other

    dets = [
        _det("ISM", frequency_mhz=433.92,
             meta={"model": "WeatherStation", "protocol": "Bresser"}),
        _det("lora", frequency_mhz=868.1),
        _det("PMR446", channel="CH1"),  # voice — filtered out
    ]
    rows = _load_other(dets)
    types = {r["signal_type"] for r in rows}
    assert types == {"ISM", "lora"}
    ism = next(r for r in rows if r["signal_type"] == "ISM")
    assert ism["model"] == "WeatherStation"


# ---- Device loaders ----

def _seed_persona(output_dir, table, persona_key, **fields):
    """Write one persona row directly into the devices.db's persona table
    via PersonaDB so the loaders have something to read. Uses the same
    schema the real parsers write through."""
    from utils.persona_db import PersonaDB
    db_path = os.path.join(output_dir, "devices.db")
    db = PersonaDB(db_path, table=table)
    # PersonaDB.update_persona merges by dev_sig+ssids; easier to poke
    # straight into _data for deterministic test fixtures.
    db._data["personas"][persona_key] = fields
    db.save()


def _seed_ap(output_dir, **fields):
    from utils.ap_db import ApDB
    db_path = os.path.join(output_dir, "devices.db")
    db = ApDB(db_path)
    db._data["aps"][fields["bssid"]] = fields
    db.save()


def test_load_wifi_clients_label_is_not_ssid():
    """Regression: NSA Hotspot #14 was rendering as if it were an AP.
    WiFi client label must never be an SSID — it has to be
    manufacturer/fingerprint with the SSID as a separate field."""
    from web.loaders import _load_wifi_clients

    tmp = tempfile.mkdtemp()
    _seed_persona(
        tmp, "personas_wifi", "dead:NSA Hotspot #14",
        dev_sig="dead",
        ssids=["NSA Hotspot #14"],
        macs_seen=["aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"],
        manufacturer=None,
        randomized=True,
        sessions=42,
        total_probes=123,
        first_session="2026-04-01",
        last_session="2026-04-11",
    )
    rows = _load_wifi_clients(tmp)
    assert len(rows) == 1
    r = rows[0]
    assert r["label"] != "NSA Hotspot #14", \
        "WiFi client label must NOT be the probed SSID"
    assert "NSA Hotspot #14" in r["ssids"]
    assert r["mac_count"] == 2
    assert r["randomized"] is True


def test_load_ble_devices_prefers_apple_device():
    from web.loaders import _load_ble_devices

    tmp = tempfile.mkdtemp()
    _seed_persona(
        tmp, "personas_bt", "aw1",
        dev_sig="aw1",
        ssids=[],
        macs_seen=["aa:aa:aa:aa:aa:aa"],
        manufacturer="Apple",
        apple_device="Apple Watch",
        randomized=True,
        sessions=10,
        total_probes=100,
        first_session="2026-04-01",
        last_session="2026-04-11",
    )
    rows = _load_ble_devices(tmp)
    assert len(rows) == 1
    assert rows[0]["label"] == "Apple Watch", \
        f"apple_device should win over manufacturer, got {rows[0]['label']}"
    assert rows[0]["apple_device"] == "Apple Watch"


def test_load_wifi_aps_physical_ap_grouping():
    """2.4 GHz + 5 GHz radios of the same physical AP should collapse
    into one row when they share an SSID and have matching first-5 MAC
    octets."""
    from web.loaders import _load_wifi_aps

    tmp = tempfile.mkdtemp()
    for bssid, extra in [
        ("aa:bb:cc:dd:ee:00", {"channels": [6],  "last_rssi": -60, "clients": ["c1"], "total_beacons": 10}),
        ("aa:bb:cc:dd:ee:01", {"channels": [36], "last_rssi": -65, "clients": ["c2"], "total_beacons": 12}),
        # Different physical AP — same SSID but different 5-octet prefix
        ("ff:ee:dd:cc:bb:aa", {"channels": [11], "last_rssi": -70, "clients": [],     "total_beacons": 5}),
    ]:
        _seed_ap(
            tmp,
            bssid=bssid,
            ssids=["Home"],
            crypto="WPA2-PSK",
            manufacturer="Ubiquiti" if bssid.startswith("aa") else "TP-Link",
            hidden=False,
            first_seen="t0",
            last_seen="t2" if "ee:01" in bssid else "t1",
            sessions=1,
            **extra,
        )
    groups = _load_wifi_aps(tmp)
    # Ubiquiti pair → 1 grouped row; TP-Link → 1 ungrouped
    counts = {g["bssid_count"] for g in groups}
    assert 2 in counts, f"expected at least one 2-radio group, got counts {counts}"

    # Find the 2-member group and verify it aggregates properly
    big = [g for g in groups if g["bssid_count"] == 2][0]
    assert set(big["bands"]) == {"2.4", "5"}
    assert big["total_beacons"] == 22
    assert set(big["clients"]) == {"c1", "c2"}
    assert big["client_count"] == 2


def run_tests():
    tests = [
        ("category_of direct match",        test_category_of_direct_match),
        ("category_of wildcards",           test_category_of_wildcards),
        ("All category loaders empty",      test_all_category_loaders_handle_empty),
        ("Voice loader",                    test_load_voice),
        ("Drones grouped by serial",        test_load_drones_by_serial),
        ("Aircraft grouped by ICAO",        test_load_aircraft_by_icao),
        ("Vessels grouped by MMSI",         test_load_vessels_by_mmsi),
        ("Vehicles TPMS + keyfob",          test_load_vehicles_tpms_and_keyfob),
        ("Cellular wildcard grouping",      test_load_cellular_wildcard_grouping),
        ("Other catch-all",                 test_load_other_catchall),
        ("WiFi client label not SSID",      test_load_wifi_clients_label_is_not_ssid),
        ("BLE prefers apple_device",        test_load_ble_devices_prefers_apple_device),
        ("WiFi AP physical grouping",       test_load_wifi_aps_physical_ap_grouping),
    ]

    print("=" * 60)
    print("Web Loaders Tests")
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

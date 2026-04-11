"""
Tests for parsers/ble/apple_continuity.py

Two layers:

1. parse_apple_continuity — the pure stateless decoder that takes raw
   manufacturer-specific AD bytes and returns a dict. Tests cover:
   - Nearby Info (0x10) device_type extraction
   - Proximity Pairing (0x07) model_id → AirPods product name
   - Find My (0x12) nearby vs separated mode
   - _classify_findmy priority rules

2. AppleContinuityParser.handle_frame — the stateful persona tracker
   that takes full BLE frames and maintains an in-memory persona map.
   Tests cover:
   - AirTag in separated mode gets labeled "AirTag (lost)" immediately
   - Find My accessory in nearby mode gets labeled "Find My accessory",
     then upgraded to "AirTag (lost)" when a separated frame arrives
   - An iPhone broadcasting both Find My and Nearby Info is labeled
     by Nearby Info, not Find My (Nearby Info wins)
   - An AirPods Pro 2 via Proximity Pairing gets its big-endian
     model ID decoded correctly (regression for the old LE bug)

Run:
    python3 tests/sw/test_apple_continuity.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _ble_frame(mac, mfr_data, rssi=-60):
    """Build a minimal BLE advertisement frame (as the BLE capture source
    would emit it) with an Apple manufacturer-specific AD structure."""
    mfr = bytes([0x4C, 0x00]) + mfr_data   # Apple company ID (76) LE
    ad = bytes([len(mfr) + 1, 0xFF]) + mfr
    return (mac, 1, ad, rssi)


def _make_parser():
    """Fresh AppleContinuityParser wired to a throwaway SignalLogger."""
    from parsers.ble.apple_continuity import AppleContinuityParser
    from utils.logger import SignalLogger
    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="bt_test", min_snr_db=0)
    log.start()
    return AppleContinuityParser(logger=log, min_rssi=-100), log


def test_parse_nearby_info_device_types():
    from parsers.ble.apple_continuity import parse_apple_continuity

    # Upper nibble of payload[0] = device code
    cases = {
        0x10: "iPhone",       # 0001_xxxx
        0x20: "iPad",         # 0010_xxxx
        0x30: "MacBook",      # 0011_xxxx
        0x40: "Apple Watch",  # 0100_xxxx
        0x60: "HomePod",      # 0110_xxxx
        0xE0: "AirPods Pro",  # 1110_xxxx
        0xF0: "AirPods Max",  # 1111_xxxx
    }
    for payload0, expected in cases.items():
        r = parse_apple_continuity(bytes([0x10, 0x02, payload0, 0x00]))
        assert r.get("device_type") == expected, \
            f"expected {expected}, got {r.get('device_type')} for payload0={payload0:#04x}"


def test_parse_proximity_pairing_airpods_big_endian():
    """Proximity Pairing model IDs are big-endian; AirPods Pro 2 = 0x1620."""
    from parsers.ble.apple_continuity import parse_apple_continuity

    # msg_type 0x07, len, model high byte, model low byte, ...
    data = bytes([0x07, 0x19, 0x16, 0x20, 0x01, 0x85, 0x55, 0x04]) + bytes(15)
    r = parse_apple_continuity(data)
    assert r["model_id"] == "0x1620", f"bad model_id: {r.get('model_id')}"
    assert r["device_type"] == "AirPods Pro 2"
    assert r["battery_right"] == 50
    assert r["battery_left"] == 50


def test_parse_findmy_nearby_and_separated():
    from parsers.ble.apple_continuity import parse_apple_continuity

    # Nearby: short payload
    r = parse_apple_continuity(bytes([0x12, 0x02, 0x00, 0x00]))
    assert r["findmy"] is True
    assert r["findmy_mode"] == "nearby"
    assert r["findmy_maintained"] is False

    # Separated: long payload (status byte 0x04 = maintained bit set)
    r = parse_apple_continuity(bytes([0x12, 0x19, 0x04]) + bytes(24))
    assert r["findmy_mode"] == "separated"
    assert r["findmy_maintained"] is True
    assert r["findmy_status"] == 0x04


def test_classify_findmy_priority():
    from parsers.ble.apple_continuity import _classify_findmy

    # Only Find My, nearby → accessory
    assert _classify_findmy({0x12}, "nearby") == "Find My accessory"
    # Only Find My, separated → AirTag (lost)
    assert _classify_findmy({0x12}, "separated") == "AirTag (lost)"
    # Any other Continuity type present → not classifiable as AirTag
    assert _classify_findmy({0x10, 0x12}, "separated") is None
    assert _classify_findmy({0x07, 0x12}, "nearby") is None
    # Empty set → None
    assert _classify_findmy(set(), None) is None


def test_integration_airtag_separated():
    """Single frame in separated mode → AirTag (lost) immediately."""
    p, log = _make_parser()
    frame = _ble_frame(
        "aa:bb:cc:dd:ee:01",
        bytes([0x12, 0x19, 0x04]) + bytes(24),   # len=0x19 (25), separated
    )
    p.handle_frame(frame)
    persona = list(p._personas.values())[0]
    assert persona["apple_device"] == "AirTag (lost)"
    assert 0x12 in persona["continuity_types"]
    log.stop()


def test_integration_findmy_accessory_upgrades_to_airtag():
    """Nearby mode frame first → Find My accessory. Then a separated
    frame arrives → label upgrades to AirTag (lost)."""
    p, log = _make_parser()
    mac = "bb:bb:cc:dd:ee:02"

    p.handle_frame(_ble_frame(mac, bytes([0x12, 0x02, 0x00, 0x00])))
    persona = list(p._personas.values())[0]
    assert persona["apple_device"] == "Find My accessory"

    p.handle_frame(_ble_frame(mac, bytes([0x12, 0x19, 0x04]) + bytes(24)))
    persona = list(p._personas.values())[0]
    assert persona["apple_device"] == "AirTag (lost)", \
        f"should have upgraded, got {persona['apple_device']}"
    log.stop()


def test_integration_iphone_wins_over_findmy():
    """An iPhone that broadcasts both Find My AND Nearby Info must be
    labeled by Nearby Info (iPhone), never by Find My."""
    p, log = _make_parser()
    mac = "cc:bb:cc:dd:ee:03"

    # First a Find My frame (would tentatively classify as Find My accessory)
    p.handle_frame(_ble_frame(mac, bytes([0x12, 0x02, 0x00, 0x00])))
    # Then a Nearby Info frame with device_code 0x01 (iPhone)
    p.handle_frame(_ble_frame(mac, bytes([0x10, 0x02, 0x10, 0x20])))
    persona = list(p._personas.values())[0]
    assert persona["apple_device"] == "iPhone", \
        f"Nearby Info should override Find My, got {persona['apple_device']}"
    assert persona["continuity_types"] == {0x10, 0x12}
    log.stop()


def test_integration_proximity_pairing_wins_over_findmy():
    """AirPods Pro 2 broadcasts Proximity Pairing — must override any
    earlier tentative Find My label."""
    p, log = _make_parser()
    mac = "dd:bb:cc:dd:ee:04"

    # Find My nearby first
    p.handle_frame(_ble_frame(mac, bytes([0x12, 0x02, 0x00, 0x00])))
    # Proximity Pairing for AirPods Pro 2 (0x1620)
    pp_data = bytes([0x07, 0x19, 0x16, 0x20, 0x01, 0x85, 0x55, 0x04]) + bytes(15)
    p.handle_frame(_ble_frame(mac, pp_data))
    persona = list(p._personas.values())[0]
    assert persona["apple_device"] == "AirPods Pro 2"
    log.stop()


def run_tests():
    tests = [
        ("parse Nearby Info device_type",       test_parse_nearby_info_device_types),
        ("parse Proximity Pairing (AirPods)",   test_parse_proximity_pairing_airpods_big_endian),
        ("parse Find My nearby + separated",    test_parse_findmy_nearby_and_separated),
        ("_classify_findmy priority",           test_classify_findmy_priority),
        ("integration: AirTag separated",       test_integration_airtag_separated),
        ("integration: nearby upgrades",        test_integration_findmy_accessory_upgrades_to_airtag),
        ("integration: iPhone wins",            test_integration_iphone_wins_over_findmy),
        ("integration: AirPods Pro 2 wins",     test_integration_proximity_pairing_wins_over_findmy),
    ]

    print("=" * 60)
    print("Apple Continuity + AirTag Tests")
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

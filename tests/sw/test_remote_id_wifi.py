"""
Tests for parsers/wifi/remote_id.py with frames from the Open Drone ID
sample captures (https://github.com/opendroneid/wireshark-dissector,
Apache-2.0): one beacon and one WiFi NaN Service Discovery Frame from the
same transmitter (84:cc:a8:60:43:24).

Run:
    python3 tests/sw/test_remote_id_wifi.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

BEACON = bytes.fromhex(
    "00b511002e18000000028509a000df010480000000ffffffffffff84cca860432484cca8604324000d00000000000000"
    "00b80b2104030106000e4742522d4f502d31323341424344dd85fa0bbc0dd0f0190500004d46473141303132333435"
    "3637383900000000000050f610005c527ebcba251ba88cb4b60000aa099808394100000a00300052656372656174696f"
    "6e616c00000000000000000000004004a485251b6edbb3b601003200000000150000000000000050004742522d4f502d"
    "31323341424344000000000000000000"
)

NAN_SDF = bytes.fromhex(
    "00ff11002e18000000028509a000dd0102d0000000516f9a01000084cca8604324506f9a01017980060409506f9a1303"
    "27008869199d92090100101d23f0190110026c527e979f251be6eab3b60000aa099808394100000a000e040001000223"
)

SENDER = "84:cc:a8:60:43:24"


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, detection):
        self.rows.append(detection)


def _parser():
    from parsers.ble.remote_id import DroneRegistry
    from parsers.wifi.remote_id import WiFiRemoteIDParser
    log = _Log()
    return WiFiRemoteIDParser(log, min_rssi=-100, drone_registry=DroneRegistry()), log


def _frame(data):
    from scapy.layers.dot11 import RadioTap
    return (RadioTap(data), 6)


def test_beacon_is_decoded():
    parser, _ = _parser()
    payload, mac, _ = parser._extract_odid(_frame(BEACON)[0])
    assert mac == SENDER
    messages = parser._parse_odid_payload(payload)
    assert len(messages) == 5


def test_nan_frame_is_decoded():
    parser, _ = _parser()
    payload, mac, _ = parser._extract_odid(_frame(NAN_SDF)[0])
    assert payload is not None, "NaN Service Discovery Frame not recognised"
    assert mac == SENDER
    messages = parser._parse_odid_payload(payload)
    assert len(messages) == 1
    location = messages[0]
    assert abs(location["latitude"] - 45.5450519) < 1e-7
    assert abs(location["longitude"] - -122.9722906) < 1e-7


def test_nan_frame_reaches_the_logger():
    parser, log = _parser()
    parser.handle_frame(_frame(NAN_SDF))
    assert len(log.rows) == 1
    meta = json.loads(log.rows[0].metadata)
    assert meta["mac"] == SENDER
    assert abs(log.rows[0].latitude - 45.5450519) < 1e-7


def test_nan_frame_for_another_service_is_ignored():
    parser, _ = _parser()
    other = NAN_SDF.replace(bytes.fromhex("8869199d9209"), bytes.fromhex("010203040506"))
    payload, _, _ = parser._extract_odid(_frame(other)[0])
    assert payload is None


def test_truncated_nan_frame_is_ignored():
    parser, _ = _parser()
    payload, _, _ = parser._extract_odid(_frame(NAN_SDF[:-20])[0])
    assert payload is None


# --- runner ---------------------------------------------------------------

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in globals().items()
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)

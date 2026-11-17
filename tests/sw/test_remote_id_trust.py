"""
Tests for the optional spoofing checks in parsers/wifi/remote_id.py
(remoteid package). Skipped when remoteid is not installed.

Frames:
  - a beacon from the Open Drone ID sample captures
    (https://github.com/opendroneid/wireshark-dissector, Apache-2.0)
  - a beacon as sent by https://github.com/jjshoots/RemoteIDSpoofer
    (ESP8266 sketch), built from its source without transmitting

Run:
    python3 tests/sw/test_remote_id_trust.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

ODID_BEACON = bytes.fromhex(
    "00b511002e18000000028509a000df010480000000ffffffffffff84cca860432484cca8604324000d00000000000000"
    "00b80b2104030106000e4742522d4f502d31323341424344dd85fa0bbc0dd0f0190500004d46473141303132333435"
    "3637383900000000000050f610005c527ebcba251ba88cb4b60000aa099808394100000a00300052656372656174696f"
    "6e616c00000000000000000000004004a485251b6edbb3b601003200000000150000000000000050004742522d4f502d"
    "31323341424344000000000000000000"
)

SPOOFER_BEACON = bytes.fromhex(
    "80000000ffffffffffff0067c66973510067c6697351200040b55e08efef05000a0011000010375532306f304a3930"
    "7841304757584901088b9682840c18306003010605040002000007065a5a20010b1432046c122448dd0918fe340301"
    "00000000dd21fa0bbc0d01f21901320052656372656174696f6e616c0000000000000000000000"
)


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


def _odid_beacon():
    from scapy.layers.dot11 import RadioTap
    packet = RadioTap(ODID_BEACON)
    packet.time = 1621633931.162
    return packet


def _spoofer_beacon():
    from scapy.layers.dot11 import Dot11, RadioTap
    # Add a RadioTap header with a signal level, then dissect the bytes as
    # a capture would deliver them
    built = RadioTap(present="dBm_AntSignal", dBm_AntSignal=-50) / Dot11(SPOOFER_BEACON)
    packet = RadioTap(bytes(built))
    packet.time = 1794916800.2
    return packet


def test_reference_transmitter_is_plausible():
    parser, log = _parser()
    parser.handle_frame((_odid_beacon(), 6))
    drone_rows = [r for r in log.rows if r.signal_type == "RemoteID"]
    assert len(drone_rows) == 1
    meta = json.loads(drone_rows[0].metadata)
    assert meta["trust"] == "plausible"
    assert meta["trust_reasons"] == []
    assert "spoofer" not in meta


def test_spoofer_is_flagged():
    parser, log = _parser()
    parser.handle_frame((_spoofer_beacon(), 1))
    assert len(log.rows) == 1
    meta = json.loads(log.rows[0].metadata)
    assert meta["trust"] == "spoofed"
    assert "known_spoofer" in meta["trust_reasons"]
    assert meta["spoofer"] == "jjshoots/RemoteIDSpoofer"


def test_without_remoteid_nothing_is_added():
    parser, log = _parser()
    parser._trust = None
    parser.handle_frame((_spoofer_beacon(), 1))
    meta = json.loads(log.rows[0].metadata)
    assert "trust" not in meta


# --- runner ---------------------------------------------------------------

if __name__ == "__main__":
    import traceback
    try:
        import remoteid  # noqa: F401
    except ImportError:
        print("  SKIP  remoteid not installed (pip install remoteid)")
        sys.exit(0)
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

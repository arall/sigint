"""Unit tests for the Ubertooth text-stream adapter."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from capture.ubertooth import UbertoothCaptureSource


def test_advertisement_frame():
    source = UbertoothCaptureSource(channel=37)
    got = []
    source.add_parser(got.append)
    source._consume_line("systime=1 freq=2402 addr=8e89bed6 delta_t=1 ms rssi=-61")
    source._consume_line("    Type:  ADV_IND")
    source._consume_line("    AdvA:  fb:06:5d:28:e6:d9 (random)")
    source._consume_line("    AdvData: 02 01 06 03 03 aa fe")
    assert got == [("FB:06:5D:28:E6:D9", 1, bytes.fromhex("0201060303aafe"), -61)], got


def test_non_advertisement_is_ignored():
    source = UbertoothCaptureSource(channel=37)
    got = []
    source.add_parser(got.append)
    source._consume_line("systime=1 freq=2402 addr=8e89bed6 delta_t=1 ms rssi=-70")
    source._consume_line("    Type:  SCAN_RSP")
    source._consume_line("    AdvA:  fb:06:5d:28:e6:d9 (random)")
    source._consume_line("    AdvData: 02 01 06")
    assert got == []


def test_channel_validation():
    try:
        UbertoothCaptureSource(channel=36)
    except ValueError:
        return
    raise AssertionError("invalid advertising channel accepted")


def run_tests():
    tests = [
        ("advertisement frame", test_advertisement_frame),
        ("non-advertisement ignored", test_non_advertisement_is_ignored),
        ("channel validation", test_channel_validation),
    ]
    failures = 0
    for name, test in tests:
        try:
            test()
            print(f"[PASS] {name}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {name}: {exc}")
    return failures == 0


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)

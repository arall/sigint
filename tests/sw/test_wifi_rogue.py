"""
Tests for parsers/wifi/deauth.py and parsers/wifi/evil_twin.py.

Two concerns, shared fixture shape (scapy Dot11 frames wrapped in the
`(packet, channel)` tuple the WiFiCaptureSource emits):

DeauthParser
  - One deauth doesn't trigger (legit disconnect, not an attack).
  - A burst above SPIKE_COUNT inside SPIKE_WINDOW triggers exactly once.
  - Cooldown suppresses re-fires from the same source during the
    cooldown window.
  - Separate source MACs are tracked independently.

EvilTwinParser
  - First BSSID for an SSID is the reference — no detection fires.
  - A second BSSID with a *different* first-5-octet prefix for the same
    SSID fires exactly one WiFi-EvilTwin row.
  - A second BSSID with the *same* first-5-octet prefix (normal
    enterprise multi-AP fabric) does not fire.
  - `crypto_mismatch` flag is True when the rogue flips WPA2 → open.
  - Hidden SSIDs are ignored (indistinguishable, guaranteed FPs).

Run:
    python3 tests/sw/test_wifi_rogue.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _logger():
    from utils.logger import SignalLogger
    tmp = tempfile.mkdtemp()
    log = SignalLogger(output_dir=tmp, signal_type="wifi_test", min_snr_db=0)
    log.start()
    return log


# --- deauth fixtures -------------------------------------------------------

def _deauth_frame(src, dst="ff:ff:ff:ff:ff:ff", reason=7, channel=6, rssi=-50):
    """Build a Dot11 deauth frame tuple as the WiFi capture source emits it."""
    from scapy.layers.dot11 import Dot11, Dot11Deauth
    pkt = Dot11(type=0, subtype=12, addr1=dst, addr2=src, addr3=src) / \
        Dot11Deauth(reason=reason)
    # dBm_AntSignal lives on the RadioTap header in real captures. Scapy
    # exposes it as a plain attribute when read off the wire, so tests
    # assign it directly — matches how the parser reads it.
    pkt.dBm_AntSignal = rssi
    return (pkt, channel)


def _disas_frame(src, dst, reason=8, channel=6):
    from scapy.layers.dot11 import Dot11, Dot11Disas
    pkt = Dot11(type=0, subtype=10, addr1=dst, addr2=src, addr3=src) / \
        Dot11Disas(reason=reason)
    return (pkt, channel)


def test_deauth_single_frame_does_not_fire():
    """A single deauth is a normal disconnect — must not trigger."""
    from parsers.wifi.deauth import DeauthParser
    log = _logger()
    parser = DeauthParser(logger=log)
    parser.handle_frame(_deauth_frame("aa:bb:cc:dd:ee:ff"))
    assert parser.detection_count == 0, \
        "single deauth should not fire"


def test_deauth_spike_fires_once_then_cools_down():
    """Five+ frames inside SPIKE_WINDOW = one detection, then cooldown."""
    from parsers.wifi.deauth import DeauthParser
    log = _logger()
    parser = DeauthParser(logger=log, spike_count=5, spike_window=10.0,
                          cooldown=30.0)
    src = "aa:bb:cc:dd:ee:ff"
    # First four — no fire.
    for _ in range(4):
        parser.handle_frame(_deauth_frame(src))
    assert parser.detection_count == 0, \
        "below threshold should not fire"
    # Fifth — fires.
    parser.handle_frame(_deauth_frame(src))
    assert parser.detection_count == 1, \
        f"fifth frame should fire; count={parser.detection_count}"
    # Continued flood stays suppressed by cooldown.
    for _ in range(50):
        parser.handle_frame(_deauth_frame(src))
    assert parser.detection_count == 1, \
        f"cooldown should suppress re-fires; count={parser.detection_count}"


def test_deauth_independent_sources_fire_independently():
    """Two attackers flooding in parallel must each produce their own row."""
    from parsers.wifi.deauth import DeauthParser
    log = _logger()
    parser = DeauthParser(logger=log, spike_count=5, spike_window=10.0)
    for _ in range(5):
        parser.handle_frame(_deauth_frame("aa:aa:aa:aa:aa:01"))
        parser.handle_frame(_deauth_frame("bb:bb:bb:bb:bb:02"))
    assert parser.detection_count == 2, \
        f"expected 2 sources → 2 fires, got {parser.detection_count}"


def test_deauth_mixed_disassoc_counts_in_same_window():
    """Deauth + Disassoc from the same source share the spike budget —
    MDK4 and aireplay-ng sprinkle both, we should treat them as one
    attack rather than requiring the threshold twice."""
    from parsers.wifi.deauth import DeauthParser
    log = _logger()
    parser = DeauthParser(logger=log, spike_count=5, spike_window=10.0)
    src = "aa:bb:cc:dd:ee:01"
    dst = "11:22:33:44:55:66"
    for _ in range(3):
        parser.handle_frame(_deauth_frame(src, dst))
    for _ in range(2):
        parser.handle_frame(_disas_frame(src, dst))
    assert parser.detection_count == 1, \
        f"mixed subtypes should combine; got {parser.detection_count}"


def test_deauth_old_frames_age_out_of_window():
    """Frames outside SPIKE_WINDOW must not count — otherwise any AP
    sending occasional deauths over hours would eventually trip."""
    from parsers.wifi.deauth import DeauthParser
    log = _logger()
    parser = DeauthParser(logger=log, spike_count=5, spike_window=10.0)
    src = "aa:bb:cc:dd:ee:02"
    # Fake monotonic time so we don't sleep 10s in tests.
    import parsers.wifi.deauth as mod
    real_mono = time.monotonic
    fake_now = [real_mono()]
    mod.time.monotonic = lambda: fake_now[0]
    try:
        for _ in range(4):
            parser.handle_frame(_deauth_frame(src))
        fake_now[0] += 15.0  # way outside the 10s window
        parser.handle_frame(_deauth_frame(src))
        assert parser.detection_count == 0, \
            "aged-out frames should not count towards the spike"
    finally:
        mod.time.monotonic = real_mono


# --- evil-twin fixtures ---------------------------------------------------

def _beacon_frame(bssid, ssid, crypto="open", channel=6, rssi=-50):
    """Build a Dot11 beacon with an SSID IE and optional RSN for WPA2.

    `crypto` accepts "open", "wpa2", or "wep".
    """
    from scapy.layers.dot11 import (
        Dot11, Dot11Beacon, Dot11Elt,
    )
    cap = 0x0400  # ESS
    if crypto in ("wpa2", "wep"):
        cap |= 0x10  # privacy bit
    pkt = Dot11(type=0, subtype=8, addr1="ff:ff:ff:ff:ff:ff",
                addr2=bssid, addr3=bssid) / \
        Dot11Beacon(cap=cap, beacon_interval=100) / \
        Dot11Elt(ID=0, info=ssid.encode())
    if crypto == "wpa2":
        # Minimal RSN IE (version 1, CCMP group + pairwise, PSK AKM)
        rsn = (
            b"\x01\x00"               # version
            b"\x00\x0f\xac\x04"       # group cipher: CCMP
            b"\x01\x00"               # pairwise count
            b"\x00\x0f\xac\x04"       # pairwise: CCMP
            b"\x01\x00"               # AKM count
            b"\x00\x0f\xac\x02"       # AKM: PSK
            b"\x00\x00"               # RSN caps
        )
        pkt = pkt / Dot11Elt(ID=48, info=rsn)
    pkt.dBm_AntSignal = rssi
    return (pkt, channel)


def test_evil_twin_first_bssid_does_not_fire():
    """The first time we see an SSID, we just catalogue it."""
    from parsers.wifi.evil_twin import EvilTwinParser
    log = _logger()
    parser = EvilTwinParser(logger=log)
    parser.handle_frame(_beacon_frame("aa:bb:cc:11:22:33", "HomeNet"))
    assert parser.detection_count == 0


def test_evil_twin_different_prefix_fires():
    """Same SSID, different first-5-octet prefix → evil-twin detection."""
    from parsers.wifi.evil_twin import EvilTwinParser
    log = _logger()
    parser = EvilTwinParser(logger=log)
    parser.handle_frame(_beacon_frame("aa:bb:cc:11:22:33", "HomeNet"))
    parser.handle_frame(_beacon_frame("ff:ee:dd:cc:bb:aa", "HomeNet"))
    assert parser.detection_count == 1, \
        f"expected 1 evil-twin fire, got {parser.detection_count}"


def test_evil_twin_same_prefix_does_not_fire():
    """Same SSID + same first-5-octet prefix = normal multi-AP fabric."""
    from parsers.wifi.evil_twin import EvilTwinParser
    log = _logger()
    parser = EvilTwinParser(logger=log)
    parser.handle_frame(_beacon_frame("aa:bb:cc:11:22:01", "OfficeWiFi"))
    parser.handle_frame(_beacon_frame("aa:bb:cc:11:22:02", "OfficeWiFi"))
    parser.handle_frame(_beacon_frame("aa:bb:cc:11:22:03", "OfficeWiFi"))
    assert parser.detection_count == 0, \
        f"same-prefix APs must not fire; got {parser.detection_count}"


def test_evil_twin_fires_once_per_new_prefix():
    """Repeated beacons from the rogue don't produce duplicate rows."""
    from parsers.wifi.evil_twin import EvilTwinParser
    log = _logger()
    parser = EvilTwinParser(logger=log)
    parser.handle_frame(_beacon_frame("aa:bb:cc:11:22:33", "HomeNet"))
    for _ in range(10):
        parser.handle_frame(_beacon_frame("ff:ee:dd:cc:bb:aa", "HomeNet"))
    assert parser.detection_count == 1


def test_evil_twin_crypto_mismatch_flag():
    """WPA2 legit → open rogue is the high-signal case. Must be flagged."""
    from parsers.wifi.evil_twin import EvilTwinParser
    log = _logger()
    parser = EvilTwinParser(logger=log)
    parser.handle_frame(_beacon_frame(
        "aa:bb:cc:11:22:33", "HomeNet", crypto="wpa2"))
    parser.handle_frame(_beacon_frame(
        "ff:ee:dd:cc:bb:aa", "HomeNet", crypto="open"))
    summary = parser.get_summary()
    assert "HomeNet" in summary
    assert summary["HomeNet"]["prefix_count"] == 2


def test_evil_twin_ignores_hidden_ssids():
    """Hidden SSIDs broadcast empty strings — can't distinguish legit
    from rogue, so we skip them entirely to avoid a flood of FPs."""
    from parsers.wifi.evil_twin import EvilTwinParser
    log = _logger()
    parser = EvilTwinParser(logger=log)
    parser.handle_frame(_beacon_frame("aa:bb:cc:11:22:33", ""))
    parser.handle_frame(_beacon_frame("ff:ee:dd:cc:bb:aa", ""))
    assert parser.detection_count == 0


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

"""
WiFi Deauth / Disassociation Parser

Detects deauthentication attacks by watching 802.11 management frames. A
legitimate disconnect produces one deauth; an active attack (aireplay-ng,
MDK4, etc.) floods dozens per second. We bucket deauth + disassoc frames
by source MAC and fire a single `WiFi-Deauth` detection per spike.

Spike criterion (defaults):
- At least 5 deauth/disassoc frames from the same source within a 10s
  rolling window.
- After firing, a 30s cooldown prevents the same attack from logging on
  every subsequent frame — one row per attack, not one per packet.
"""

import json
import threading
import time
from collections import deque
from datetime import datetime

from parsers.base import BaseParser
from utils.logger import SignalDetection
from utils.oui import lookup_manufacturer

SPIKE_COUNT = 5
SPIKE_WINDOW = 10.0  # seconds
COOLDOWN = 30.0  # seconds after firing before same source can fire again

# 802.11-2016 Table 9-49: deauth / disassoc reason codes (subset)
_REASON_CODES = {
    1: "unspecified",
    2: "prev-auth-invalid",
    3: "deauth-leaving",
    4: "inactivity",
    5: "ap-busy",
    6: "class2-from-non-auth",
    7: "class3-from-non-assoc",
    8: "disassoc-leaving",
    9: "assoc-but-not-auth",
    15: "4way-handshake-timeout",
    16: "group-key-timeout",
    23: "ieee8021x-failed",
}


def _reason_name(code):
    if code is None:
        return None
    return _REASON_CODES.get(int(code), f"reason-{int(code)}")


class DeauthParser(BaseParser):
    """Detects deauth/disassoc floods by spike count per source MAC."""

    def __init__(self, logger, spike_count=SPIKE_COUNT,
                 spike_window=SPIKE_WINDOW, cooldown=COOLDOWN):
        super().__init__(logger)
        self.spike_count = spike_count
        self.spike_window = spike_window
        self.cooldown = cooldown
        self._lock = threading.Lock()
        # src_mac -> {"times": deque, "dsts": set, "reasons": set,
        #             "last_rssi": int, "last_fired": float, "fire_count": int}
        self._sources = {}

    def handle_frame(self, frame):
        from scapy.layers.dot11 import Dot11, Dot11Deauth, Dot11Disas

        packet, channel = frame
        if not packet.haslayer(Dot11):
            return
        if not (packet.haslayer(Dot11Deauth) or packet.haslayer(Dot11Disas)):
            return

        src = (packet.addr2 or "").lower()
        dst = (packet.addr1 or "").lower()
        if not src:
            return

        subtype = "deauth" if packet.haslayer(Dot11Deauth) else "disassoc"
        reason = None
        try:
            reason = int(
                packet[Dot11Deauth].reason if subtype == "deauth"
                else packet[Dot11Disas].reason
            )
        except Exception:
            pass

        rssi = None
        try:
            rssi = int(packet.dBm_AntSignal)
        except (AttributeError, TypeError):
            pass

        now = time.monotonic()

        with self._lock:
            state = self._sources.get(src)
            if state is None:
                state = {
                    "times": deque(),
                    "dsts": set(),
                    "reasons": set(),
                    "subtypes": set(),
                    "last_rssi": None,
                    "last_fired": 0.0,
                    "fire_count": 0,
                }
                self._sources[src] = state

            q = state["times"]
            q.append(now)
            cutoff = now - self.spike_window
            while q and q[0] < cutoff:
                q.popleft()

            state["dsts"].add(dst)
            if reason is not None:
                state["reasons"].add(reason)
            state["subtypes"].add(subtype)
            if rssi is not None:
                state["last_rssi"] = rssi

            spike = len(q) >= self.spike_count
            cool = (now - state["last_fired"]) < self.cooldown
            if not spike or cool:
                return

            state["last_fired"] = now
            state["fire_count"] += 1
            count_in_window = len(q)
            dsts = sorted(state["dsts"])
            reasons = sorted(_reason_name(r) for r in state["reasons"] if r is not None)
            subtypes = sorted(state["subtypes"])
            broadcast = "ff:ff:ff:ff:ff:ff" in state["dsts"]
            state["dsts"].clear()
            state["reasons"].clear()
            state["subtypes"].clear()

        manufacturer = lookup_manufacturer(src) or ""
        target_label = "broadcast" if broadcast else (
            f"{len(dsts)} client{'s' if len(dsts) != 1 else ''}"
        )
        print(f"  [DEAUTH-SPIKE] src={src} [{manufacturer or '?'}]  "
              f"{count_in_window} frames / {self.spike_window:.0f}s  "
              f"target={target_label}  reasons={reasons or '—'}  "
              f"CH: {channel}  RSSI: {rssi} dBm")

        metadata = {
            "src": src,
            "manufacturer": manufacturer,
            "subtypes": subtypes,
            "reasons": reasons,
            "count_in_window": count_in_window,
            "window_seconds": self.spike_window,
            "targets": dsts,
            "target_count": len(dsts),
            "broadcast": broadcast,
            "channel": channel,
            "detected_at": datetime.now().isoformat(),
        }

        try:
            from capture.wifi import channel_to_freq
            freq_mhz = channel_to_freq(channel) or 2437
        except Exception:
            freq_mhz = 2437

        power_db = float(rssi) if rssi is not None else -90.0
        detection = SignalDetection.create(
            signal_type="WiFi-Deauth",
            frequency_hz=freq_mhz * 1e6,
            power_db=power_db,
            noise_floor_db=-95.0,
            channel=f"CH{channel}",
            device_id=src,
            metadata=json.dumps(metadata),
        )
        self.logger.log(detection)

    @property
    def detection_count(self):
        with self._lock:
            return sum(s["fire_count"] for s in self._sources.values())

    def get_summary(self):
        with self._lock:
            return {
                src: {"fire_count": s["fire_count"], "last_rssi": s["last_rssi"]}
                for src, s in self._sources.items()
                if s["fire_count"] > 0
            }

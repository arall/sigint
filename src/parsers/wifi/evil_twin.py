"""
WiFi Evil-Twin Parser

Flags beacons whose SSID matches one we've already catalogued this session
but whose BSSID belongs to a different MAC prefix — the classic evil-twin
signature: attacker broadcasts "HomeNet" with their own radio alongside the
legitimate AP.

Matches the BSSID grouping rule used by the dashboard (same SSID + first 5
MAC octets counts as the "same" AP family) so multi-AP enterprise networks
with sequential BSSIDs don't trip the alarm. Distinct OUI for the same SSID
does trip it — chain-hotel false positives can be suppressed by an
allowlist later.

Emits `WiFi-EvilTwin` once per `(ssid, new-prefix)` pair. Crypto mismatch
(e.g. legit WPA2 → rogue open) is a stronger signal and is surfaced in the
metadata so the UI can sort on it.
"""

import json
import threading
import time
from datetime import datetime

from parsers.base import BaseParser
from parsers.wifi.beacon import _extract_crypto
from utils.logger import SignalDetection
from utils.oui import lookup_manufacturer


def _bssid_prefix(bssid):
    """First 5 MAC octets — the dashboard's grouping key for same-family APs."""
    if not bssid:
        return ""
    return bssid.lower().rsplit(":", 1)[0]


class EvilTwinParser(BaseParser):
    """Detects SSID collisions across different BSSID prefixes."""

    def __init__(self, logger, min_rssi=-90):
        super().__init__(logger)
        self.min_rssi = min_rssi
        self._lock = threading.Lock()
        # ssid -> {"prefixes": {prefix: {bssid, crypto, manufacturer, first_seen}},
        #          "fired": set of prefixes already logged as evil-twin}
        self._ssids = {}

    def handle_frame(self, frame):
        from scapy.layers.dot11 import Dot11, Dot11Beacon, Dot11Elt

        packet, channel = frame
        if not packet.haslayer(Dot11Beacon):
            return

        bssid = (packet.addr3 or packet.addr2 or "").lower()
        if not bssid:
            return

        rssi = None
        try:
            rssi = int(packet.dBm_AntSignal)
        except (AttributeError, TypeError):
            pass
        if rssi is not None and rssi < self.min_rssi:
            return

        ssid = ""
        elt = packet.getlayer(Dot11Elt)
        while elt is not None:
            if elt.ID == 0:
                if elt.info:
                    try:
                        ssid = elt.info.decode("utf-8", errors="replace")
                    except Exception:
                        ssid = ""
                break
            elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None

        # Hidden SSIDs are indistinguishable between APs — skip.
        if not ssid or all(c in ("\x00", " ") for c in ssid):
            return

        try:
            crypto = _extract_crypto(packet)
        except Exception:
            crypto = "?"

        prefix = _bssid_prefix(bssid)
        manufacturer = lookup_manufacturer(bssid) or ""
        now = time.time()

        fired_payload = None

        with self._lock:
            entry = self._ssids.get(ssid)
            if entry is None:
                entry = {"prefixes": {}, "fired": set()}
                self._ssids[ssid] = entry

            if prefix not in entry["prefixes"]:
                entry["prefixes"][prefix] = {
                    "bssid": bssid,
                    "crypto": crypto,
                    "manufacturer": manufacturer,
                    "first_seen": datetime.now().isoformat(),
                    "first_seen_mono": now,
                }

                # The first prefix is the reference — no twin yet.
                if len(entry["prefixes"]) > 1 and prefix not in entry["fired"]:
                    entry["fired"].add(prefix)
                    ref_prefix = next(iter(entry["prefixes"]))
                    ref = entry["prefixes"][ref_prefix]
                    fired_payload = {
                        "ssid": ssid,
                        "new_bssid": bssid,
                        "new_prefix": prefix,
                        "new_crypto": crypto,
                        "new_manufacturer": manufacturer,
                        "ref_bssid": ref["bssid"],
                        "ref_prefix": ref_prefix,
                        "ref_crypto": ref["crypto"],
                        "ref_manufacturer": ref["manufacturer"],
                        "ref_first_seen": ref["first_seen"],
                        "crypto_mismatch": crypto != ref["crypto"],
                        "manufacturer_mismatch": (
                            bool(manufacturer) and bool(ref["manufacturer"])
                            and manufacturer != ref["manufacturer"]
                        ),
                        "all_prefixes": sorted(entry["prefixes"]),
                        "channel": channel,
                        "detected_at": datetime.now().isoformat(),
                    }

        if fired_payload is None:
            return

        severity_bits = []
        if fired_payload["crypto_mismatch"]:
            severity_bits.append(
                f"crypto {fired_payload['ref_crypto']}→{fired_payload['new_crypto']}"
            )
        if fired_payload["manufacturer_mismatch"]:
            severity_bits.append(
                f"vendor {fired_payload['ref_manufacturer']}→"
                f"{fired_payload['new_manufacturer']}"
            )
        sev = "  ".join(severity_bits) or "prefix mismatch"
        print(f"  [EVIL-TWIN] SSID={ssid!r}  new={bssid} [{manufacturer or '?'}]  "
              f"ref={fired_payload['ref_bssid']} [{fired_payload['ref_manufacturer'] or '?'}]  "
              f"{sev}  CH: {channel}  RSSI: {rssi} dBm")

        try:
            from capture.wifi import channel_to_freq
            freq_mhz = channel_to_freq(channel) or 2437
        except Exception:
            freq_mhz = 2437

        power_db = float(rssi) if rssi is not None else -90.0
        detection = SignalDetection.create(
            signal_type="WiFi-EvilTwin",
            frequency_hz=freq_mhz * 1e6,
            power_db=power_db,
            noise_floor_db=-95.0,
            channel=f"CH{channel}",
            device_id=bssid,
            metadata=json.dumps(fired_payload),
        )
        self.logger.log(detection)

    @property
    def detection_count(self):
        with self._lock:
            return sum(len(e["fired"]) for e in self._ssids.values())

    def get_summary(self):
        with self._lock:
            return {
                ssid: {
                    "prefix_count": len(e["prefixes"]),
                    "fired": sorted(e["fired"]),
                }
                for ssid, e in self._ssids.items()
                if len(e["prefixes"]) > 1
            }

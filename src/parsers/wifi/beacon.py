"""
WiFi Beacon Parser

Logs nearby WiFi access points from 802.11 Beacon frames. Extracts BSSID,
SSID, channel, crypto suite (WPA2/WPA3/OWE/open), and vendor OUI. Tracks
each BSSID across repeated beacons with a dedup window so the CSV isn't
flooded — one log line per AP every N seconds while it's seen.
"""

import json
import threading
import time
from datetime import datetime

from parsers.base import BaseParser
from utils.logger import SignalDetection
from utils.oui import lookup_manufacturer

# Re-log each BSSID at most this often (seconds)
DEDUP_WINDOW = 60

# 802.11 RSN (Robust Security Network) AKM suite selectors (OUI 00:0f:ac)
_AKM_NAMES = {
    1: "802.1X",
    2: "PSK",
    3: "FT-802.1X",
    4: "FT-PSK",
    5: "802.1X-SHA256",
    6: "PSK-SHA256",
    8: "SAE",
    9: "FT-SAE",
    11: "Suite-B",
    18: "OWE",
}


def _parse_rsn(rsn_bytes):
    """
    Parse an RSN (WPA2/WPA3) information element body.
    Returns a short string like 'WPA2-PSK', 'WPA3-SAE', 'OWE', or 'RSN'.
    """
    if len(rsn_bytes) < 10:
        return "RSN"
    try:
        # Skip version (2) + group cipher suite (4) + pairwise count (2) + pairwise suites
        idx = 2 + 4
        pc = int.from_bytes(rsn_bytes[idx:idx + 2], "little")
        idx += 2 + 4 * pc
        if idx + 2 > len(rsn_bytes):
            return "RSN"
        akm_count = int.from_bytes(rsn_bytes[idx:idx + 2], "little")
        idx += 2
        akms = []
        for _ in range(akm_count):
            if idx + 4 > len(rsn_bytes):
                break
            suite = rsn_bytes[idx:idx + 4]
            idx += 4
            if suite[:3] == b"\x00\x0f\xac":
                akms.append(_AKM_NAMES.get(suite[3], f"AKM{suite[3]}"))
        if not akms:
            return "RSN"
        if "SAE" in akms or "FT-SAE" in akms:
            return "WPA3-SAE"
        if "OWE" in akms:
            return "OWE"
        if "PSK" in akms or "FT-PSK" in akms or "PSK-SHA256" in akms:
            return "WPA2-PSK"
        if "802.1X" in akms or "FT-802.1X" in akms or "802.1X-SHA256" in akms:
            return "WPA2-EAP"
        return "RSN-" + "/".join(akms)
    except Exception:
        return "RSN"


def _extract_crypto(packet):
    """
    Walk the Dot11Elt chain and derive a crypto label from RSN (IE 48)
    and WPA vendor IE (OUI 00:50:f2, type 1). Falls back to 'WEP' if the
    privacy bit is set with no RSN/WPA, else 'open'.
    """
    from scapy.layers.dot11 import Dot11Beacon, Dot11Elt

    has_rsn = None
    has_wpa = False
    privacy = False

    # Privacy bit lives in the beacon capability field
    if packet.haslayer(Dot11Beacon):
        privacy = bool(packet[Dot11Beacon].cap & 0x10)

    elt = packet.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 48 and elt.info:  # RSN
            has_rsn = _parse_rsn(bytes(elt.info))
        elif elt.ID == 221 and elt.info and len(elt.info) >= 4:
            # Vendor-specific: check for Microsoft WPA IE (00:50:f2, type 1)
            if bytes(elt.info[:4]) == b"\x00\x50\xf2\x01":
                has_wpa = True
        elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None

    if has_rsn:
        return has_rsn
    if has_wpa:
        return "WPA"
    if privacy:
        return "WEP"
    return "open"


class BeaconParser(BaseParser):
    """Parses 802.11 Beacon frames to catalog nearby WiFi APs."""

    def __init__(self, logger, min_rssi=-90):
        super().__init__(logger)
        self.min_rssi = min_rssi
        self._lock = threading.Lock()
        # bssid -> {ssid, channel, crypto, manufacturer, rssi, first_seen,
        #          last_seen, last_logged, count}
        self._aps = {}

    def handle_frame(self, frame):
        """Process a WiFi frame: (packet, channel). Only acts on beacons."""
        from scapy.layers.dot11 import Dot11, Dot11Beacon, Dot11Elt

        packet, channel = frame
        if not packet.haslayer(Dot11Beacon):
            return

        bssid = packet.addr3 or packet.addr2
        if not bssid:
            return

        # RSSI
        rssi = None
        try:
            rssi = packet.dBm_AntSignal
        except AttributeError:
            pass
        if rssi is not None and rssi < self.min_rssi:
            return

        # SSID — walk the Dot11Elt chain looking for ID 0 (SSID IE).
        # Usually first, but be defensive.
        ssid = ""
        hidden = False
        elt = packet.getlayer(Dot11Elt)
        while elt is not None:
            if elt.ID == 0:
                if elt.info:
                    try:
                        ssid = elt.info.decode("utf-8", errors="replace")
                    except Exception:
                        ssid = ""
                if not ssid or all(c in ("\x00", " ") for c in ssid):
                    hidden = True
                    ssid = ""
                break
            elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None

        # Crypto
        try:
            crypto = _extract_crypto(packet)
        except Exception:
            crypto = "?"

        # Beacon interval (units of TU = 1.024 ms)
        beacon_interval = None
        if packet.haslayer(Dot11Beacon):
            try:
                beacon_interval = int(packet[Dot11Beacon].beacon_interval)
            except Exception:
                pass

        now = time.time()
        should_log = False

        with self._lock:
            ap = self._aps.get(bssid)
            if ap is None:
                manufacturer = lookup_manufacturer(bssid) or ""
                ap = {
                    "bssid": bssid,
                    "ssid": ssid,
                    "channel": channel,
                    "crypto": crypto,
                    "manufacturer": manufacturer,
                    "hidden": hidden,
                    "beacon_interval": beacon_interval,
                    "rssi": rssi,
                    "first_seen": datetime.now().isoformat(),
                    "last_seen": datetime.now().isoformat(),
                    "last_logged": 0,
                    "count": 0,
                }
                self._aps[bssid] = ap
                should_log = True
                n_aps = len(self._aps)
                print(f"  [NEW AP] {bssid}  "
                      f"[{ap['manufacturer'] or '?'}]  "
                      f"SSID: {ssid or '(hidden)'}  "
                      f"CH: {channel}  {crypto}  "
                      f"RSSI: {rssi} dBm  "
                      f"[{n_aps} APs]")
            else:
                ap["count"] += 1
                ap["last_seen"] = datetime.now().isoformat()
                ap["rssi"] = rssi
                # SSID may become visible on a later beacon if we missed the first
                if not ap["ssid"] and ssid:
                    ap["ssid"] = ssid
                    ap["hidden"] = False
                if (now - ap["last_logged"]) >= DEDUP_WINDOW:
                    should_log = True

            if should_log:
                ap["last_logged"] = now
                snapshot = dict(ap)
                snapshot.pop("last_logged", None)

        if should_log and rssi is not None:
            try:
                from capture.wifi import channel_to_freq
                freq_mhz = channel_to_freq(channel) or 2437
            except Exception:
                freq_mhz = 2437
            detection = SignalDetection.create(
                signal_type="WiFi-AP",
                frequency_hz=freq_mhz * 1e6,
                power_db=float(rssi),
                noise_floor_db=-95.0,
                channel=f"CH{channel}",
                device_id=bssid,
                metadata=json.dumps(snapshot),
            )
            self.logger.log(detection)

    def shutdown(self):
        """Nothing to persist — BSSIDs are in the CSV log."""
        pass

    @property
    def detection_count(self):
        with self._lock:
            return len(self._aps)

    def get_summary(self):
        """Return (n_aps, aps_dict) for display on shutdown."""
        with self._lock:
            return len(self._aps), {b: dict(a) for b, a in self._aps.items()}

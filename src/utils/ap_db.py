"""
Persistent WiFi AP Database
Stores nearby WiFi access points (beacon-derived) across scanning sessions.

Each AP is keyed by BSSID. Multiple SSIDs / channels are accumulated over time
(an AP can rebroadcast, or the same BSSID can appear on different channels).
The database is flushed periodically by the server's persona-flush loop and
at parser shutdown.

Schema:
{
    "aps": {
        "<bssid>": {
            "bssid": "aa:bb:cc:dd:ee:ff",
            "ssids": ["HomeWiFi"],
            "channels": [6, 36],
            "crypto": "WPA2-PSK",
            "manufacturer": "Ubiquiti Inc.",
            "hidden": false,
            "beacon_interval": 100,
            "last_rssi": -64,
            "first_seen": "2026-04-11T10:00:00",
            "last_seen":  "2026-04-11T10:30:00",
            "sessions": 2,
            "total_beacons": 1423
        }
    },
    "updated": "2026-04-11T10:30:00"
}
"""

import json
import os
from datetime import datetime


class ApDB:
    """Persistent store for WiFi AP records across sessions."""

    def __init__(self, path):
        self.path = path
        self._data = {"aps": {}, "updated": None}
        self._session_recorded = set()
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    self._data = json.load(f)
                    if "aps" not in self._data:
                        self._data["aps"] = {}
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        self._data["updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self.path)

    def update_ap(self, bssid, ssid, channel, crypto, manufacturer,
                  rssi, hidden, beacon_interval, total_beacons,
                  first_seen, last_seen, clients=None):
        """Merge an AP observation into the database."""
        aps = self._data["aps"]
        rec = aps.get(bssid)
        clients = list(clients or [])

        if rec is None:
            rec = {
                "bssid": bssid,
                "ssids": [ssid] if ssid else [],
                "channels": [channel] if channel is not None else [],
                "crypto": crypto or "",
                "manufacturer": manufacturer or "",
                "hidden": bool(hidden),
                "beacon_interval": beacon_interval,
                "last_rssi": rssi,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "sessions": 1,
                "total_beacons": int(total_beacons or 0),
                "clients": sorted(set(clients)),
                "client_count": len(set(clients)),
            }
            aps[bssid] = rec
            self._session_recorded.add(bssid)
            return

        if ssid and ssid not in rec["ssids"]:
            rec["ssids"].append(ssid)
        if channel is not None and channel not in rec["channels"]:
            rec["channels"].append(channel)
        if crypto and crypto != rec.get("crypto"):
            rec["crypto"] = crypto
        if manufacturer and not rec.get("manufacturer"):
            rec["manufacturer"] = manufacturer
        if beacon_interval is not None:
            rec["beacon_interval"] = beacon_interval
        if rssi is not None:
            rec["last_rssi"] = rssi
        rec["hidden"] = bool(hidden) and not rec["ssids"]
        rec["last_seen"] = last_seen
        rec["total_beacons"] = int(total_beacons or rec.get("total_beacons", 0))

        if clients:
            merged = sorted(set(rec.get("clients", []) or []) | set(clients))
            rec["clients"] = merged
            rec["client_count"] = len(merged)
        elif "client_count" not in rec:
            rec["client_count"] = len(rec.get("clients", []) or [])

        if bssid not in self._session_recorded:
            rec["sessions"] = int(rec.get("sessions", 0)) + 1
            self._session_recorded.add(bssid)

    @property
    def total_aps(self):
        return len(self._data["aps"])

    def all_aps(self):
        return dict(self._data["aps"])

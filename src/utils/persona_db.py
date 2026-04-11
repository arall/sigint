"""
Persistent Persona Database
Stores and retrieves device persona fingerprints across scanning sessions.

Each persona is identified by its device signature (from 802.11 IEs) combined
with its accumulated SSID set. The database is stored as a JSON file and
updated at the end of each scanning session.

Schema:
{
    "personas": {
        "<persona_key>": {
            "dev_sig": "abc123",
            "ssids": ["HomeWiFi", "GymFree"],
            "macs_seen": ["aa:bb:cc:dd:ee:ff", ...],
            "manufacturer": "Apple, Inc.",
            "randomized": true,
            "sessions": 3,
            "first_session": "2026-04-03T21:00:00",
            "last_session": "2026-04-05T14:30:00",
            "total_probes": 142
        }
    },
    "updated": "2026-04-05T14:30:00"
}
"""

import json
import os
from datetime import datetime


class PersonaDB:
    """Persistent store for persona fingerprints across sessions."""

    def __init__(self, path):
        self.path = path
        self._data = {"personas": {}, "updated": None}
        self._load()

    def _load(self):
        """Load existing database from disk."""
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        """Write database to disk."""
        self._data["updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)

    @staticmethod
    def _make_key(dev_sig, ssids):
        """
        Build a persona lookup key from device signature and SSID set.

        For devices with SSIDs: key = dev_sig + sorted SSIDs hash.
        For broadcast-only devices: key = dev_sig (model-level grouping).
        """
        if ssids:
            ssid_part = "|".join(sorted(ssids))
            return f"{dev_sig}:{ssid_part}"
        return dev_sig

    def find(self, dev_sig, ssids):
        """
        Find a persona matching the given signature and SSIDs.

        Matching strategy:
        1. Exact key match (same sig + same SSIDs)
        2. SSID subset/superset match (same sig, overlapping SSIDs — the persona
           may have accumulated more SSIDs over prior sessions)

        Returns (persona_key, persona_dict) or (None, None).
        """
        personas = self._data["personas"]

        # Exact match
        key = self._make_key(dev_sig, ssids)
        if key in personas:
            return key, personas[key]

        # SSID overlap match (same device signature)
        if ssids:
            for pkey, persona in personas.items():
                if persona["dev_sig"] == dev_sig:
                    stored_ssids = set(persona["ssids"])
                    if stored_ssids & set(ssids):  # any overlap
                        return pkey, persona

        return None, None

    def update_persona(self, dev_sig, ssids, macs, manufacturer, randomized,
                       probe_count, apple_device=None):
        """
        Update or create a persona in the database.

        Args:
            dev_sig: Device signature hash
            ssids: Set of SSIDs probed this session
            macs: Set of MAC addresses seen this session
            manufacturer: Manufacturer name or None
            randomized: Whether the MAC(s) are randomized
            probe_count: Number of probes this session
            apple_device: Decoded Apple device type (e.g. "Apple Watch",
                          "AirPods Pro") — persisted so the Devices tab
                          keeps the label after a server restart.
        """
        key, existing = self.find(dev_sig, ssids)

        if existing:
            # Merge into existing persona
            existing["ssids"] = sorted(set(existing["ssids"]) | set(ssids))
            existing["macs_seen"] = sorted(set(existing["macs_seen"]) | set(macs))
            existing["sessions"] += 1
            existing["last_session"] = datetime.now().isoformat()
            existing["total_probes"] += probe_count
            if manufacturer and not existing.get("manufacturer"):
                existing["manufacturer"] = manufacturer
            if apple_device and not existing.get("apple_device"):
                existing["apple_device"] = apple_device

            # Re-key if SSIDs expanded
            new_key = self._make_key(dev_sig, existing["ssids"])
            if new_key != key:
                self._data["personas"][new_key] = existing
                del self._data["personas"][key]
        else:
            # New persona
            key = self._make_key(dev_sig, ssids)
            self._data["personas"][key] = {
                "dev_sig": dev_sig,
                "ssids": sorted(ssids),
                "macs_seen": sorted(macs),
                "manufacturer": manufacturer,
                "apple_device": apple_device,
                "randomized": randomized,
                "sessions": 1,
                "first_session": datetime.now().isoformat(),
                "last_session": datetime.now().isoformat(),
                "total_probes": probe_count,
            }

    def get_session_count(self, dev_sig, ssids):
        """Get how many prior sessions this persona has been seen in."""
        _, existing = self.find(dev_sig, ssids)
        return existing["sessions"] if existing else 0

    @property
    def total_personas(self):
        return len(self._data["personas"])

    def summary(self):
        """Return a summary of the database for display."""
        personas = self._data["personas"]
        returning = sum(1 for p in personas.values() if p["sessions"] > 1)
        return {
            "total": len(personas),
            "returning": returning,
            "updated": self._data.get("updated"),
        }

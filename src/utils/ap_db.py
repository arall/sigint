"""
Persistent WiFi AP Database
Stores nearby WiFi access points (beacon-derived) across scanning sessions.

Each AP is keyed by BSSID. Multiple SSIDs / channels / clients are
accumulated over time. Stored as a `wifi_aps` table in a shared
devices.db SQLite file that lives alongside the per-session detection
.db files but is not itself treated as a session.

Public API matches the old JSON version — `ApDB(path)`,
`update_ap(...)`, `save()`, `.total_aps`, `.all_aps()`. If the
constructor is given a legacy aps.json path, it migrates into the
sibling devices.db once and keeps going.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime


def _derive_db_path(path):
    if path.endswith(".db"):
        return path, None
    directory = os.path.dirname(path) or "."
    return os.path.join(directory, "devices.db"), path


class ApDB:
    """Persistent store for WiFi AP records across sessions."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS wifi_aps (
        bssid           TEXT PRIMARY KEY,
        ssids           TEXT,
        channels        TEXT,
        crypto          TEXT,
        manufacturer    TEXT,
        hidden          INTEGER,
        beacon_interval INTEGER,
        last_rssi       REAL,
        first_seen      TEXT,
        last_seen       TEXT,
        sessions        INTEGER,
        total_beacons   INTEGER,
        clients         TEXT,
        client_count    INTEGER
    );
    """

    def __init__(self, path):
        db_path, legacy_json = _derive_db_path(path)
        self.path = db_path
        self._data = {"aps": {}, "updated": None}
        self._session_recorded = set()
        self._lock = threading.Lock()
        self._conn = None
        self._open()
        self._maybe_import_json(legacy_json)
        self._load()

    def _open(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(
            self.path, timeout=5.0, isolation_level=None,
            check_same_thread=False,
        )
        self._conn.executescript(
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"
        )
        self._conn.executescript(self._SCHEMA)

    def _maybe_import_json(self, legacy_json):
        if not legacy_json or not os.path.exists(legacy_json):
            return
        try:
            row = self._conn.execute("SELECT COUNT(*) FROM wifi_aps").fetchone()
            if row and row[0] > 0:
                return
        except sqlite3.OperationalError:
            return
        try:
            with open(legacy_json, "r") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        aps = data.get("aps") if isinstance(data, dict) else None
        if not aps:
            return
        print(f"[ap-db] importing {len(aps)} rows "
              f"from {os.path.basename(legacy_json)}")
        with self._conn:
            for bssid, rec in aps.items():
                self._conn.execute(
                    "INSERT OR REPLACE INTO wifi_aps VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        bssid,
                        json.dumps(rec.get("ssids", []) or []),
                        json.dumps(rec.get("channels", []) or []),
                        rec.get("crypto", ""),
                        rec.get("manufacturer", ""),
                        int(bool(rec.get("hidden"))),
                        rec.get("beacon_interval"),
                        rec.get("last_rssi"),
                        rec.get("first_seen", ""),
                        rec.get("last_seen", ""),
                        int(rec.get("sessions", 0)),
                        int(rec.get("total_beacons", 0)),
                        json.dumps(sorted(rec.get("clients", []) or [])),
                        int(rec.get("client_count", len(rec.get("clients", []) or []))),
                    ),
                )

    def _load(self):
        self._data = {"aps": {}, "updated": None}
        try:
            rows = self._conn.execute(
                "SELECT bssid, ssids, channels, crypto, manufacturer, "
                "hidden, beacon_interval, last_rssi, first_seen, "
                "last_seen, sessions, total_beacons, clients, client_count "
                "FROM wifi_aps"
            ).fetchall()
        except sqlite3.OperationalError:
            return
        latest = ""
        for r in rows:
            clients = json.loads(r[12] or "[]")
            self._data["aps"][r[0]] = {
                "bssid": r[0],
                "ssids": json.loads(r[1] or "[]"),
                "channels": json.loads(r[2] or "[]"),
                "crypto": r[3] or "",
                "manufacturer": r[4] or "",
                "hidden": bool(r[5]),
                "beacon_interval": r[6],
                "last_rssi": r[7],
                "first_seen": r[8] or "",
                "last_seen": r[9] or "",
                "sessions": int(r[10] or 0),
                "total_beacons": int(r[11] or 0),
                "clients": clients,
                "client_count": int(r[13] or len(clients)),
            }
            if r[9] and r[9] > latest:
                latest = r[9]
        if latest:
            self._data["updated"] = latest

    def save(self):
        self._data["updated"] = datetime.now().isoformat()
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute("DELETE FROM wifi_aps")
                    for bssid, rec in self._data["aps"].items():
                        clients = sorted(set(rec.get("clients", []) or []))
                        self._conn.execute(
                            "INSERT INTO wifi_aps VALUES "
                            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                bssid,
                                json.dumps(rec.get("ssids", []) or []),
                                json.dumps(rec.get("channels", []) or []),
                                rec.get("crypto", ""),
                                rec.get("manufacturer", ""),
                                int(bool(rec.get("hidden"))),
                                rec.get("beacon_interval"),
                                rec.get("last_rssi"),
                                rec.get("first_seen", ""),
                                rec.get("last_seen", ""),
                                int(rec.get("sessions", 0)),
                                int(rec.get("total_beacons", 0)),
                                json.dumps(clients),
                                len(clients),
                            ),
                        )
            except sqlite3.OperationalError as e:
                print(f"[ap-db] save failed: {e}")

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

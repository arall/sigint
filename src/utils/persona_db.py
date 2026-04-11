"""
Persistent Persona Database
Stores and retrieves device persona fingerprints across scanning sessions.

Each persona is identified by its device signature (from 802.11 IEs) combined
with its accumulated SSID set. Stored as a table in a SQLite devices.db
that lives alongside the per-session detection .db files but is not
itself treated as a session (see web/sessions.py is_session_db_name).

Public API is unchanged from the old JSON-backed version — callers still
do `PersonaDB(path, table=...)`, `update_persona(...)`, `find(...)`,
`get_session_count(...)`, `save()`, `.total_personas`. The `path` used
to be a personas.json file; now it's a devices.db file, and an optional
`table` argument picks the table name (default "personas"; WiFi uses
"personas_wifi" and BLE uses "personas_bt" so the two kinds share one
.db without colliding). If the constructor is given a legacy .json path,
it auto-migrates into the sibling devices.db and keeps going.
"""

import json
import os
import re
import sqlite3
import threading
from datetime import datetime


def _derive_db_path_and_table(path):
    """Accept either a legacy .json path or a .db path. Return
    (db_path, table, legacy_json_path_or_None)."""
    if path.endswith(".db"):
        return path, None, None
    # Legacy migration: personas.json → devices.db, table from basename
    directory = os.path.dirname(path) or "."
    base = os.path.basename(path)
    if base == "personas.json":
        table = "personas_wifi"
    elif base == "personas_bt.json":
        table = "personas_bt"
    else:
        table = re.sub(r"\W+", "_", os.path.splitext(base)[0]) or "personas"
    return os.path.join(directory, "devices.db"), table, path


class PersonaDB:
    """Persistent store for persona fingerprints across sessions."""

    _CREATE_TEMPLATE = """
    CREATE TABLE IF NOT EXISTS {table} (
        persona_key   TEXT PRIMARY KEY,
        dev_sig       TEXT,
        ssids         TEXT,
        macs_seen     TEXT,
        manufacturer  TEXT,
        apple_device  TEXT,
        randomized    INTEGER,
        sessions      INTEGER,
        first_session TEXT,
        last_session  TEXT,
        total_probes  INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_{table}_devsig ON {table}(dev_sig);
    """

    def __init__(self, path, table=None):
        db_path, derived_table, legacy_json = _derive_db_path_and_table(path)
        self.path = db_path
        self.table = table or derived_table or "personas"
        # Validate the table name so the f-string SQL is safe
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.table):
            raise ValueError(f"invalid table name: {self.table!r}")
        self._data = {"personas": {}, "updated": None}
        self._conn = None
        self._lock = threading.Lock()
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
        self._conn.executescript(self._CREATE_TEMPLATE.format(table=self.table))

    def _maybe_import_json(self, legacy_json):
        """One-shot migration: if a pre-migration .json file exists AND
        this table is still empty, pull its personas into the table so
        the user doesn't lose their accumulated identity data."""
        if not legacy_json or not os.path.exists(legacy_json):
            return
        try:
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM {self.table}"
            ).fetchone()
            if row and row[0] > 0:
                return  # already migrated or populated
        except sqlite3.OperationalError:
            return
        try:
            with open(legacy_json, "r") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        personas = data.get("personas") if isinstance(data, dict) else None
        if not personas:
            return
        print(f"[persona-db] importing {len(personas)} rows "
              f"from {os.path.basename(legacy_json)} → {self.table}")
        with self._conn:
            for key, p in personas.items():
                self._conn.execute(
                    f"INSERT OR REPLACE INTO {self.table} VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key,
                        p.get("dev_sig", ""),
                        json.dumps(p.get("ssids", []) or []),
                        json.dumps(p.get("macs_seen", []) or []),
                        p.get("manufacturer"),
                        p.get("apple_device"),
                        int(bool(p.get("randomized"))),
                        int(p.get("sessions", 0)),
                        p.get("first_session", ""),
                        p.get("last_session", ""),
                        int(p.get("total_probes", 0)),
                    ),
                )

    def _load(self):
        """Pull every row from the SQL table into the in-memory dict."""
        self._data = {"personas": {}, "updated": None}
        try:
            rows = self._conn.execute(
                f"SELECT persona_key, dev_sig, ssids, macs_seen, manufacturer, "
                f"apple_device, randomized, sessions, first_session, "
                f"last_session, total_probes FROM {self.table}"
            ).fetchall()
        except sqlite3.OperationalError:
            return
        latest = ""
        for r in rows:
            self._data["personas"][r[0]] = {
                "dev_sig": r[1] or "",
                "ssids": json.loads(r[2] or "[]"),
                "macs_seen": json.loads(r[3] or "[]"),
                "manufacturer": r[4],
                "apple_device": r[5],
                "randomized": bool(r[6]),
                "sessions": int(r[7] or 0),
                "first_session": r[8] or "",
                "last_session": r[9] or "",
                "total_probes": int(r[10] or 0),
            }
            if r[9] and r[9] > latest:
                latest = r[9]
        # Derive "updated" from the most-recent last_session so the
        # summary() contract matches the old JSON-backed behavior.
        if latest:
            self._data["updated"] = latest

    def save(self):
        """Write the in-memory dict back to the SQL table. Called on the
        server's 30s flush loop and at parser shutdown."""
        self._data["updated"] = datetime.now().isoformat()
        with self._lock:
            try:
                with self._conn:  # BEGIN/COMMIT
                    self._conn.execute(f"DELETE FROM {self.table}")
                    for key, p in self._data["personas"].items():
                        self._conn.execute(
                            f"INSERT INTO {self.table} VALUES "
                            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                key,
                                p.get("dev_sig", ""),
                                json.dumps(p.get("ssids", []) or []),
                                json.dumps(p.get("macs_seen", []) or []),
                                p.get("manufacturer"),
                                p.get("apple_device"),
                                int(bool(p.get("randomized"))),
                                int(p.get("sessions", 0)),
                                p.get("first_session", ""),
                                p.get("last_session", ""),
                                int(p.get("total_probes", 0)),
                            ),
                        )
            except sqlite3.OperationalError as e:
                print(f"[persona-db] save failed: {e}")

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

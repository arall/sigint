"""
Apple Continuity BLE Parser

Parses Apple-specific BLE advertisements: Nearby Info, Handoff, Proximity
Pairing, Find My. Used for device fingerprinting and persona tracking.
"""

import hashlib
import json
import struct
import threading
import time
from collections import defaultdict
from datetime import datetime

from parsers.base import BaseParser
from parsers.ble.ad_parser import parse_ad_structures
from utils.logger import SignalDetection
from utils.oui import is_randomized_mac
from utils.persona_db import PersonaDB

# BLE approximate center frequency for logging
BLE_ADV_FREQ = 2440e6

# BT SIG assigned company identifiers (decimal values).
# Reference: https://bitbucket.org/bluetooth-SIG/public/raw/main/assigned_numbers/company_identifiers/company_identifiers.yaml
BT_COMPANIES = {
    2:    "Intel",                  # 0x0002
    6:    "Microsoft",              # 0x0006
    13:   "Texas Instruments",      # 0x000D
    48:   "Logitech",               # 0x0030
    76:   "Apple",                  # 0x004C
    89:   "Nordic Semi",            # 0x0059
    117:  "Samsung",                # 0x0075
    135:  "Garmin",                 # 0x0087
    224:  "Google",                 # 0x00E0
    301:  "Bose",                   # 0x012D
    305:  "Cypress",                # 0x0131
    343:  "Xiaomi",                 # 0x0157
    741:  "Sonos",                  # 0x02E5
    957:  "GoPro",                  # 0x03BD
    1031: "Fitbit",                 # 0x0407
    1177: "Tile",                   # 0x0499
    1452: "Polar Electro",          # 0x05AC
    1530: "JBL",                    # 0x05FA
    1957: "Sennheiser",             # 0x07A5
    2257: "Bang & Olufsen",         # 0x08D1
    2614: "Anker",                  # 0x0A36
}

# Apple Continuity message types
APPLE_CONTINUITY_TYPES = {
    0x01: "AirPrint",
    0x03: "AirPlay",
    0x05: "AirDrop",
    0x06: "HomeKit",
    0x07: "Proximity Pairing",
    0x08: "Hey Siri",
    0x09: "AirPlay Target",
    0x0A: "AirPlay Source",
    0x0C: "Handoff",
    0x0D: "Tethering Target",
    0x0E: "Tethering Source",
    0x0F: "Nearby Action",
    0x10: "Nearby Info",
    0x12: "Find My",
}

# Apple Nearby Info device types (upper nibble of first data byte)
APPLE_DEVICE_TYPES = {
    0x01: "iPhone",
    0x02: "iPad",
    0x03: "MacBook",
    0x04: "Apple Watch",
    0x05: "AirPods",
    0x06: "HomePod",
    0x07: "Mac Pro",
    0x09: "MacBook",
    0x0A: "Apple Watch",
    0x0B: "MacBook",
    0x0C: "iPhone",
    0x0E: "AirPods Pro",
    0x0F: "AirPods Max",
    0x10: "AirPods Pro",
    0x14: "Apple Vision Pro",
}

# Apple Proximity Pairing model IDs (msg type 0x07). AirPods and Beats
# headphones advertise these when out of the case / in pairing mode. The
# upper byte distinguishes product families; we only need a coarse label.
APPLE_PROXIMITY_MODELS = {
    0x0220: "AirPods",
    0x0320: "PowerBeats3",
    0x0520: "BeatsX",
    0x0620: "Beats Solo3",
    0x0720: "Beats Studio3",
    0x0920: "Beats Studio3",
    0x0A20: "AirPods",                 # 1st gen (alt)
    0x0B20: "Powerbeats Pro",
    0x0C20: "Beats Solo Pro",
    0x0D20: "Powerbeats Pro",
    0x0E20: "AirPods Pro",
    0x0F20: "AirPods 2",
    0x1020: "AirPods Pro",
    0x1120: "AirPods 3",
    0x1220: "AirPods Max",
    0x1320: "Beats Flex",
    0x1420: "Beats Studio Buds",
    0x1520: "Beats Fit Pro",
    0x1620: "AirPods Pro 2",
    0x1720: "Beats Studio Pro",
    0x1820: "Beats Solo 4",
    0x1920: "Beats Studio Buds+",
    0x1A20: "AirPods Pro 2 (USB-C)",
    0x1B20: "AirPods 4",
    0x1C20: "AirPods 4 (ANC)",
    0x1D20: "AirPods Max (USB-C)",
}

# Detection parameters
DEDUP_WINDOW = 30  # seconds before re-logging same persona


def parse_apple_continuity(data):
    """Parse Apple Continuity protocol data from manufacturer-specific AD."""
    if len(data) < 2:
        return None

    msg_type = data[0]
    msg_len = data[1]
    payload = data[2:]

    result = {
        "type": msg_type,
        "type_name": APPLE_CONTINUITY_TYPES.get(msg_type, f"0x{msg_type:02x}"),
    }

    if msg_type == 0x10 and len(payload) >= 1:
        device_code = (payload[0] >> 4) & 0x0F
        activity = payload[0] & 0x0F
        result["device_type"] = APPLE_DEVICE_TYPES.get(device_code, f"0x{device_code:x}")
        result["activity"] = activity
        if len(payload) >= 2:
            result["wifi_on"] = bool(payload[1] & 0x20)

    elif msg_type == 0x0C and len(payload) >= 2:
        result["handoff_hash"] = payload[:14].hex()

    elif msg_type == 0x07 and len(payload) >= 3:
        # Proximity Pairing — payload is big-endian, not little-endian.
        # First 2 bytes = product model (e.g. 0x0E20 = AirPods Pro).
        device_model = (payload[0] << 8) | payload[1]
        result["model_id"] = f"0x{device_model:04x}"
        name = APPLE_PROXIMITY_MODELS.get(device_model)
        if name:
            result["device_type"] = name
        if len(payload) >= 6:
            result["battery_right"] = (payload[4] >> 4) * 10
            result["battery_left"] = (payload[4] & 0x0F) * 10
            result["battery_case"] = (payload[5] >> 4) * 10

    elif msg_type == 0x12:
        result["findmy"] = True

    return result


def build_device_signature(ad_info, apple_info):
    """
    Build a device fingerprint from advertisement data.

    Combines manufacturer ID, AD type structure, service UUIDs,
    and Apple device type into a stable hash that persists across
    MAC rotations.
    """
    apple_device_type = None
    if apple_info and "device_type" in apple_info:
        apple_device_type = apple_info["device_type"]

    sig_data = (
        ad_info["mfr_id"],
        tuple(ad_info["ad_types"]),
        tuple(sorted(f"0x{u:04x}" if isinstance(u, int) else str(u)
                     for u in ad_info["service_uuids"])),
        ad_info["tx_power"],
        apple_device_type,
    )
    return hashlib.sha256(repr(sig_data).encode()).hexdigest()[:12]


class AppleContinuityParser(BaseParser):
    """
    Parses BLE advertisements for device fingerprinting and persona tracking.

    Handles all BLE devices (not just Apple), with enhanced parsing for
    Apple Continuity protocol (Nearby Info, Handoff, Proximity Pairing, etc.)
    """

    def __init__(self, logger, min_rssi=-90, persona_db_path=None):
        super().__init__(logger)
        self.min_rssi = min_rssi
        self._lock = threading.Lock()

        # MAC tracking: mac -> per-MAC state
        self._macs = {}
        # Persona tracking: persona_id -> persona state
        self._personas = {}
        self._sig_to_personas = defaultdict(list)
        self._next_persona_id = 1

        # Persistent persona database
        self._persona_db = None
        if persona_db_path:
            self._persona_db = PersonaDB(persona_db_path)
            db_summary = self._persona_db.summary()
            if db_summary["total"] > 0:
                print(f"[*] Loaded BLE persona DB: {db_summary['total']} known, "
                      f"{db_summary['returning']} returning")

    def handle_frame(self, frame):
        """Process a BLE advertisement frame: (addr, addr_type, ad_bytes, rssi)."""
        addr, addr_type, ad_bytes, rssi = frame

        if rssi is not None and rssi < self.min_rssi:
            return

        ad_info = parse_ad_structures(ad_bytes)

        # Parse Apple Continuity if manufacturer is Apple
        apple = None
        if ad_info["mfr_id"] == 76 and len(ad_info["mfr_data"]) >= 2:
            apple = parse_apple_continuity(ad_info["mfr_data"])

        dev_sig = build_device_signature(ad_info, apple)
        name = ad_info["name"]

        now = time.time()
        should_log = False

        with self._lock:
            pid = self._find_persona(addr, dev_sig, name, apple)
            persona = self._personas[pid]
            persona["count"] += 1
            persona["last_rssi"] = rssi
            persona["last_seen"] = datetime.now().isoformat()
            is_new = persona["count"] == 1

            if name:
                persona["names"].add(name)
            if ad_info["mfr_id"] is not None and persona["mfr_id"] is None:
                persona["mfr_id"] = ad_info["mfr_id"]
                persona["mfr_name"] = BT_COMPANIES.get(ad_info["mfr_id"])
            if ad_info["tx_power"] is not None and persona["tx_power"] is None:
                persona["tx_power"] = ad_info["tx_power"]

            if apple:
                if "handoff_hash" in apple and not persona.get("handoff_hash"):
                    persona["handoff_hash"] = apple["handoff_hash"]
                if "device_type" in apple and not persona.get("apple_device"):
                    persona["apple_device"] = apple["device_type"]

            self._macs[addr]["last_seen"] = now

            if is_new:
                should_log = True
                n_personas = len(self._personas)
                mfr = persona["mfr_name"] or (
                    f"CID:{persona['mfr_id']}" if persona["mfr_id"] is not None else ""
                )
                device = persona.get("apple_device")
                if device:
                    label = f"{device}"
                elif name:
                    label = name
                elif mfr:
                    label = mfr
                else:
                    label = "?"
                rnd = "rand" if persona["randomized"] else "pub"
                returning = ""
                if persona["prior_sessions"] > 0:
                    returning = f"  **RETURNING (seen {persona['prior_sessions']}x)**"
                print(f"  [NEW] P{pid:03d}  {addr}  [{rnd}]  RSSI: {rssi} dBm  "
                      f"{label}  [{n_personas} personas]{returning}")
            elif (now - persona["last_logged"]) >= DEDUP_WINDOW:
                should_log = True

            if should_log:
                persona["last_logged"] = now

            persona_snapshot = {
                "persona_id": f"P{pid:03d}",
                "mac": addr,
                "macs": sorted(persona["macs"]),
                "dev_sig": dev_sig,
                "name": name,
                "names": sorted(persona["names"]),
                "manufacturer": persona["mfr_name"],
                "manufacturer_id": persona["mfr_id"],
                "tx_power": persona["tx_power"],
                "randomized": persona["randomized"],
                "apple_device": persona.get("apple_device"),
                "probe_count": persona["count"],
                "first_seen": persona["first_seen"],
                "prior_sessions": persona["prior_sessions"],
            }

        if should_log and rssi is not None:
            noise_floor = -100.0
            detection = SignalDetection.create(
                signal_type="BLE-Adv",
                frequency_hz=BLE_ADV_FREQ,
                power_db=float(rssi),
                noise_floor_db=noise_floor,
                channel="BLE",
                metadata=json.dumps(persona_snapshot),
            )
            self.logger.log(detection)

    def _find_persona(self, mac, dev_sig, name, apple_info):
        """Find or create persona for this MAC. Caller must hold self._lock."""
        if mac in self._macs:
            return self._macs[mac]["persona_id"]

        # Apple Handoff hash merge
        handoff_hash = None
        if apple_info and "handoff_hash" in apple_info:
            handoff_hash = apple_info["handoff_hash"]
            for pid, persona in self._personas.items():
                if persona.get("handoff_hash") == handoff_hash:
                    self._macs[mac] = {"persona_id": pid, "last_seen": time.time()}
                    persona["macs"].add(mac)
                    print(f"  [MERGE] {mac} -> P{pid:03d} (Handoff hash)")
                    return pid

        # Match by device signature + name
        if dev_sig in self._sig_to_personas:
            for pid in self._sig_to_personas[dev_sig]:
                persona = self._personas[pid]
                if name and name in persona["names"]:
                    self._macs[mac] = {"persona_id": pid, "last_seen": time.time()}
                    persona["macs"].add(mac)
                    print(f"  [MERGE] {mac} -> P{pid:03d} (name match: {name})")
                    return pid

        # Check persistent DB
        prior_sessions = 0
        if self._persona_db:
            prior_sessions = self._persona_db.get_session_count(
                dev_sig, {name} if name else set()
            )

        pid = self._next_persona_id
        self._next_persona_id += 1

        randomized = is_randomized_mac(mac)
        apple_device = None
        if apple_info:
            apple_device = apple_info.get("device_type")

        self._personas[pid] = {
            "macs": {mac},
            "dev_sig": dev_sig,
            "names": set(),
            "first_seen": datetime.now().isoformat(),
            "last_seen": None,
            "last_logged": 0,
            "count": 0,
            "last_rssi": None,
            "mfr_id": None,
            "mfr_name": None,
            "tx_power": None,
            "randomized": randomized,
            "prior_sessions": prior_sessions,
            "handoff_hash": handoff_hash,
            "apple_device": apple_device,
        }
        self._sig_to_personas[dev_sig].append(pid)
        self._macs[mac] = {"persona_id": pid, "last_seen": time.time()}
        return pid

    def flush(self):
        """Persist in-memory personas to the sidecar DB (safe to call
        repeatedly while running)."""
        if not self._persona_db:
            return
        with self._lock:
            for pid, p in self._personas.items():
                self._persona_db.update_persona(
                    dev_sig=p["dev_sig"],
                    ssids=p["names"],
                    macs=p["macs"],
                    manufacturer=p["mfr_name"],
                    randomized=p["randomized"],
                    probe_count=p["count"],
                    apple_device=p.get("apple_device"),
                )
        self._persona_db.save()

    def shutdown(self):
        """Persist personas to database."""
        self.flush()

    @property
    def detection_count(self):
        with self._lock:
            return len(self._personas)

    def get_summary(self):
        """Return session summary for display on shutdown."""
        with self._lock:
            n_personas = len(self._personas)
            n_macs = len(self._macs)
            personas_copy = {pid: dict(p) for pid, p in self._personas.items()}
        db_summary = self._persona_db.summary() if self._persona_db else None
        return n_personas, n_macs, personas_copy, db_summary

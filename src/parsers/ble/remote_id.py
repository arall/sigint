"""
Open Drone ID (RemoteID) BLE Parser

Parses ASTM F3411 / ASD-STAN prEN 4709-002 Remote ID messages from BLE
advertisements. Mandated by FAA (US) and EASA (EU) since 2024 — most
consumer drones broadcast this.

Open Drone ID uses BLE service UUID 0xFFFA. Each advertisement carries one
or more message types in a message pack:

- 0x0: Basic ID — drone serial number or session ID
- 0x1: Location/Vector — lat, lon, altitude, speed, heading
- 0x2: Authentication — authentication data (optional)
- 0x3: Self-ID — operator-defined text description
- 0x4: System — operator location, area count, classification
- 0x5: Operator ID — operator registration ID
- 0xF: Message Pack — container for multiple messages
"""

import json
import struct
import threading
import time
from datetime import datetime

from parsers.base import BaseParser
from parsers.ble.ad_parser import parse_ad_structures
from utils.logger import SignalDetection

# Open Drone ID BLE service UUID (16-bit)
ODID_SERVICE_UUID = 0xFFFA

# ODID application code (vendor type byte) per ASTM F3411
ODID_APP_CODE = 0x0D

# BLE approximate center frequency
BLE_ADV_FREQ = 2440e6

# Message types
MSG_BASIC_ID = 0x0
MSG_LOCATION = 0x1
MSG_AUTH = 0x2
MSG_SELF_ID = 0x3
MSG_SYSTEM = 0x4
MSG_OPERATOR_ID = 0x5
MSG_PACK = 0xF

# ID types for Basic ID
ID_TYPES = {
    0: "None",
    1: "Serial (ANSI/CTA-2063-A)",
    2: "CAA Registration",
    3: "UTM (UUID)",
    4: "Specific Session ID",
}

# UA (drone) types
UA_TYPES = {
    0: "None",
    1: "Aeroplane",
    2: "Helicopter/Multirotor",
    3: "Gyroplane",
    4: "Hybrid Lift (VTOL)",
    5: "Ornithopter",
    6: "Glider",
    7: "Kite",
    8: "Free Balloon",
    9: "Captive Balloon",
    10: "Airship",
    11: "Parachute",
    12: "Rocket",
    13: "Tethered Aircraft",
    14: "Ground Obstacle",
    15: "Other",
}

# Operator classification
OPERATOR_CLASSIFICATIONS = {
    0: "Undeclared",
    1: "EU Open",
    2: "EU Specific",
    3: "EU Certified",
}

# Dedup window — don't log same drone more than once per N seconds
DEDUP_WINDOW = 5


def _decode_lat_lon(raw):
    """Decode ODID lat/lon from int32 (1e-7 degrees)."""
    if raw == 0 or raw == 0x7FFFFFFF:
        return None
    return raw / 1e7


def _decode_altitude(raw):
    """Decode ODID altitude from uint16 (0.5m resolution, -1000m offset)."""
    if raw == 0xFFFF:
        return None
    return (raw / 2.0) - 1000.0


def _decode_speed(raw):
    """Decode ODID speed from uint8 (0.25 m/s resolution) or uint16."""
    if raw == 0xFF or raw == 0xFFFF:
        return None
    return raw * 0.25


def _parse_basic_id(payload):
    """Parse Basic ID message (type 0x0)."""
    if len(payload) < 20:
        return None
    id_type = (payload[0] >> 4) & 0x0F
    ua_type = payload[0] & 0x0F
    # ID is 20 bytes, null-terminated ASCII
    id_bytes = payload[1:21]
    drone_id = id_bytes.split(b"\x00")[0].decode("ascii", errors="replace").strip()
    return {
        "id_type": ID_TYPES.get(id_type, f"0x{id_type:x}"),
        "ua_type": UA_TYPES.get(ua_type, f"0x{ua_type:x}"),
        "drone_id": drone_id,
    }


def _parse_location(payload):
    """Parse Location/Vector message (type 0x1)."""
    if len(payload) < 22:
        return None
    status = (payload[0] >> 4) & 0x0F
    height_type = (payload[0] >> 2) & 0x01  # 0=above takeoff, 1=AGL
    ew_direction = (payload[0] >> 1) & 0x01
    speed_mult = payload[0] & 0x01  # 0 = 0.25 m/s, 1 = 0.75 m/s

    direction = struct.unpack("B", payload[1:2])[0]  # 0-360 degrees
    speed_raw = struct.unpack("B", payload[2:3])[0]
    vert_speed_raw = struct.unpack("b", payload[3:4])[0]  # signed

    lat = struct.unpack("<i", payload[4:8])[0]
    lon = struct.unpack("<i", payload[8:12])[0]

    pressure_alt = struct.unpack("<H", payload[12:14])[0]
    geodetic_alt = struct.unpack("<H", payload[14:16])[0]
    height = struct.unpack("<H", payload[16:18])[0]

    h_accuracy = (payload[18] >> 4) & 0x0F
    v_accuracy = payload[18] & 0x0F
    baro_accuracy = (payload[19] >> 4) & 0x0F
    speed_accuracy = payload[19] & 0x0F
    timestamp_raw = struct.unpack("<H", payload[20:22])[0]

    speed_factor = 0.75 if speed_mult else 0.25
    speed = speed_raw * speed_factor if speed_raw != 0xFF else None
    vert_speed = vert_speed_raw * 0.5 if vert_speed_raw != 0x7F else None

    result = {
        "latitude": _decode_lat_lon(lat),
        "longitude": _decode_lat_lon(lon),
        "pressure_alt_m": _decode_altitude(pressure_alt),
        "geodetic_alt_m": _decode_altitude(geodetic_alt),
        "height_m": _decode_altitude(height),
        "height_type": "AGL" if height_type else "above_takeoff",
        "speed_ms": speed,
        "vert_speed_ms": vert_speed,
        "direction_deg": direction if direction != 0xFF else None,
    }
    # Remove None values for cleaner output
    return {k: v for k, v in result.items() if v is not None}


def _parse_self_id(payload):
    """Parse Self-ID message (type 0x3)."""
    if len(payload) < 1:
        return None
    desc_type = payload[0]
    text = payload[1:24].split(b"\x00")[0].decode("ascii", errors="replace").strip()
    return {"description_type": desc_type, "text": text}


def _parse_system(payload):
    """Parse System message (type 0x4)."""
    if len(payload) < 18:
        return None
    classification = (payload[0] >> 4) & 0x0F
    operator_lat = struct.unpack("<i", payload[1:5])[0]
    operator_lon = struct.unpack("<i", payload[5:9])[0]
    area_count = struct.unpack("<H", payload[9:11])[0]
    area_radius = struct.unpack("B", payload[11:12])[0]
    area_ceiling = struct.unpack("<H", payload[12:14])[0]
    area_floor = struct.unpack("<H", payload[14:16])[0]

    result = {
        "classification": OPERATOR_CLASSIFICATIONS.get(classification,
                                                       f"0x{classification:x}"),
        "operator_latitude": _decode_lat_lon(operator_lat),
        "operator_longitude": _decode_lat_lon(operator_lon),
        "area_count": area_count,
        "area_radius_m": area_radius * 10,
        "area_ceiling_m": _decode_altitude(area_ceiling),
        "area_floor_m": _decode_altitude(area_floor),
    }
    return {k: v for k, v in result.items() if v is not None}


def _parse_operator_id(payload):
    """Parse Operator ID message (type 0x5)."""
    if len(payload) < 1:
        return None
    op_id_type = payload[0]
    op_id = payload[1:21].split(b"\x00")[0].decode("ascii", errors="replace").strip()
    return {"operator_id_type": op_id_type, "operator_id": op_id}


def _parse_message(msg_type, payload):
    """Parse a single ODID message by type."""
    parsers = {
        MSG_BASIC_ID: _parse_basic_id,
        MSG_LOCATION: _parse_location,
        MSG_SELF_ID: _parse_self_id,
        MSG_SYSTEM: _parse_system,
        MSG_OPERATOR_ID: _parse_operator_id,
    }
    parser = parsers.get(msg_type)
    if parser:
        return parser(payload)
    return None


class DroneRegistry:
    """Shared cross-transport drone state for dedup across BLE and WiFi."""

    def __init__(self):
        self._lock = threading.Lock()
        self._drones = {}  # drone_id -> state

    def update(self, drone_id, rssi, transport):
        """Update drone state. Returns (is_new, should_log)."""
        now = time.time()
        with self._lock:
            is_new = drone_id not in self._drones
            state = self._drones.setdefault(drone_id, {
                "first_seen": datetime.now().isoformat(),
                "last_logged": 0,
                "count": 0,
                "transports": set(),
            })
            state["count"] += 1
            state["last_seen"] = datetime.now().isoformat()
            state["last_rssi"] = rssi
            state["transports"].add(transport)

            should_log = is_new or (now - state["last_logged"]) >= DEDUP_WINDOW
            if should_log:
                state["last_logged"] = now

        return is_new, should_log

    @property
    def drone_count(self):
        with self._lock:
            return len(self._drones)

    def get_summary(self):
        with self._lock:
            # Convert sets to lists for JSON serialization
            result = {}
            for k, v in self._drones.items():
                entry = dict(v)
                entry["transports"] = list(entry.get("transports", set()))
                result[k] = entry
            return result


# Module-level shared registry — used by both BLE and WiFi parsers
_shared_registry = None


def get_drone_registry():
    """Get or create the shared drone registry."""
    global _shared_registry
    if _shared_registry is None:
        _shared_registry = DroneRegistry()
    return _shared_registry


class RemoteIDParser(BaseParser):
    """
    Parses Open Drone ID (ASTM F3411) messages from BLE advertisements.

    Detects drones broadcasting RemoteID via service UUID 0xFFFA with
    application code 0x0D, decodes drone ID, position, operator location,
    and logs as signal_type="RemoteID".
    """

    def __init__(self, logger, min_rssi=-90, drone_registry=None):
        super().__init__(logger)
        self.min_rssi = min_rssi
        self._registry = drone_registry or get_drone_registry()

    def handle_frame(self, frame):
        """Process a BLE advertisement frame: (addr, addr_type, ad_bytes, rssi)."""
        addr, addr_type, ad_bytes, rssi = frame

        if rssi is not None and rssi < self.min_rssi:
            return

        ad_info = parse_ad_structures(ad_bytes)

        # Check for Open Drone ID service data keyed by UUID 0xFFFA
        odid_data = ad_info["service_data"].get(ODID_SERVICE_UUID)

        if odid_data is None:
            # No service data for 0xFFFA — not an ODID frame
            if ODID_SERVICE_UUID not in ad_info["service_uuids"]:
                return
            # Has the UUID but no service data — try manufacturer data
            odid_data = ad_info["mfr_data"]

        if not odid_data or len(odid_data) < 1:
            return

        # Validate ODID application code (0x0D) — first byte of service data
        # per ASTM F3411. Prevents false positives from other 0xFFFA services.
        if odid_data[0] != ODID_APP_CODE:
            return

        # Skip the app code byte — rest is the ODID message
        payload = odid_data[1:]
        if len(payload) < 1:
            return

        # Parse ODID message(s)
        messages = self._parse_odid_payload(payload)
        if not messages:
            return

        # Build detection metadata
        drone_info = self._merge_messages(messages, addr, rssi)
        drone_info["transport"] = "BLE"

        # Dedup via shared registry (cross-transport)
        drone_id = drone_info.get("drone_id", addr)
        is_new, should_log = self._registry.update(drone_id, rssi, "BLE")

        if is_new:
            ua_type = drone_info.get("ua_type", "Drone")
            lat = drone_info.get("latitude")
            lon = drone_info.get("longitude")
            alt = drone_info.get("geodetic_alt_m")
            pos_str = ""
            if lat is not None and lon is not None:
                pos_str = f"  ({lat:.5f}, {lon:.5f}"
                if alt is not None:
                    pos_str += f", {alt:.0f}m"
                pos_str += ")"
            print(f"  [DRONE] {drone_id}  {ua_type}  RSSI: {rssi} dBm"
                  f"  MAC: {addr}{pos_str}")

        if should_log and rssi is not None:
            noise_floor = -100.0

            # Drone position from Location message
            drone_lat = drone_info.get("latitude")
            drone_lon = drone_info.get("longitude")
            detection = SignalDetection.create(
                signal_type="RemoteID",
                frequency_hz=BLE_ADV_FREQ,
                power_db=float(rssi),
                noise_floor_db=noise_floor,
                channel=drone_id,
                latitude=drone_lat,
                longitude=drone_lon,
                metadata=json.dumps(drone_info),
            )
            self.logger.log(detection)

            # Operator/controller position from System message
            sys_info = drone_info.get("system", {})
            op_lat = sys_info.get("operator_latitude")
            op_lon = sys_info.get("operator_longitude")
            if op_lat is not None and op_lon is not None:
                op_meta = {
                    "drone_id": drone_id,
                    "operator_id": drone_info.get("operator_id", ""),
                    "classification": sys_info.get("classification", ""),
                    "transport": "BLE",
                }
                op_detection = SignalDetection.create(
                    signal_type="RemoteID-operator",
                    frequency_hz=BLE_ADV_FREQ,
                    power_db=float(rssi),
                    noise_floor_db=noise_floor,
                    channel=f"{drone_id}-op",
                    latitude=op_lat,
                    longitude=op_lon,
                    metadata=json.dumps(op_meta),
                )
                self.logger.log(op_detection)

    def _parse_odid_payload(self, payload):
        """Parse ODID payload, handling both single messages and message packs."""
        messages = []

        if len(payload) < 1:
            return messages

        # First byte: message type (upper 4 bits) + protocol version (lower 4 bits)
        msg_type = (payload[0] >> 4) & 0x0F
        # proto_version = payload[0] & 0x0F

        if msg_type == MSG_PACK:
            # Message Pack — contains multiple messages
            if len(payload) < 2:
                return messages
            msg_count = payload[1]
            offset = 2
            for _ in range(msg_count):
                if offset + 25 > len(payload):
                    break
                sub_type = (payload[offset] >> 4) & 0x0F
                parsed = _parse_message(sub_type, payload[offset + 1:offset + 25])
                if parsed:
                    parsed["_msg_type"] = sub_type
                    messages.append(parsed)
                offset += 25
        else:
            # Single message
            parsed = _parse_message(msg_type, payload[1:])
            if parsed:
                parsed["_msg_type"] = msg_type
                messages.append(parsed)

        return messages

    def _merge_messages(self, messages, addr, rssi):
        """Merge multiple ODID messages into a single drone info dict."""
        info = {"mac": addr, "rssi": rssi}

        for msg in messages:
            msg_type = msg.pop("_msg_type", None)
            if msg_type == MSG_BASIC_ID:
                info.update(msg)
            elif msg_type == MSG_LOCATION:
                info.update(msg)
            elif msg_type == MSG_SELF_ID:
                info["self_id"] = msg
            elif msg_type == MSG_SYSTEM:
                info["system"] = msg
            elif msg_type == MSG_OPERATOR_ID:
                info.update(msg)

        return info

    @property
    def detection_count(self):
        return self._registry.drone_count

    def get_summary(self):
        """Return summary of detected drones."""
        return self._registry.get_summary()

"""
AIS Protocol Decoding Functions

Pure functions for decoding AIS NMEA sentences into vessel data.
No hardware access, no state — takes NMEA strings in, returns decoded
vessel information out.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict


# AIS Message Types
AIS_MESSAGE_TYPES = {
    1: "Position Report (Class A scheduled)",
    2: "Position Report (Class A assigned)",
    3: "Position Report (Class A interrogated)",
    4: "Base Station Report",
    5: "Static and Voyage Data",
    6: "Binary Addressed Message",
    7: "Binary Acknowledge",
    8: "Binary Broadcast Message",
    9: "SAR Aircraft Position Report",
    10: "UTC/Date Inquiry",
    11: "UTC/Date Response",
    12: "Addressed Safety Message",
    13: "Safety Acknowledge",
    14: "Safety Broadcast Message",
    15: "Interrogation",
    16: "Assignment Mode Command",
    17: "DGNSS Broadcast",
    18: "Position Report (Class B)",
    19: "Extended Position Report (Class B)",
    20: "Data Link Management",
    21: "Aid-to-Navigation Report",
    22: "Channel Management",
    23: "Group Assignment Command",
    24: "Static Data Report",
    25: "Single Slot Binary Message",
    26: "Multiple Slot Binary Message",
    27: "Position Report (Long Range)",
}

SHIP_TYPES = {
    0: "Not available", 20: "Wing in ground", 30: "Fishing", 31: "Towing",
    32: "Towing (large)", 33: "Dredging", 34: "Diving ops", 35: "Military ops",
    36: "Sailing", 37: "Pleasure craft", 40: "High speed craft", 50: "Pilot vessel",
    51: "Search and rescue", 52: "Tug", 53: "Port tender", 54: "Anti-pollution",
    55: "Law enforcement", 58: "Medical transport", 59: "Noncombatant",
    60: "Passenger", 70: "Cargo", 80: "Tanker", 90: "Other",
}

NAV_STATUS = {
    0: "Under way using engine", 1: "At anchor", 2: "Not under command",
    3: "Restricted manoeuvrability", 4: "Constrained by draught", 5: "Moored",
    6: "Aground", 7: "Engaged in fishing", 8: "Under way sailing",
    9: "Reserved (HSC)", 10: "Reserved (WIG)", 11: "Power-driven towing astern",
    12: "Power-driven pushing/towing", 13: "Reserved", 14: "AIS-SART active",
    15: "Not defined",
}


@dataclass
class Vessel:
    """Tracked vessel information."""
    mmsi: str
    name: Optional[str] = None
    callsign: Optional[str] = None
    ship_type: Optional[int] = None
    imo: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    sog: Optional[float] = None
    cog: Optional[float] = None
    heading: Optional[int] = None
    rot: Optional[float] = None
    nav_status: Optional[int] = None
    destination: Optional[str] = None
    eta: Optional[str] = None
    draught: Optional[float] = None
    last_seen: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    last_message_type: Optional[int] = None

    @property
    def ship_type_name(self) -> str:
        if self.ship_type is None:
            return "Unknown"
        if 20 <= self.ship_type < 30:
            return SHIP_TYPES.get(20, "WIG")
        elif 30 <= self.ship_type < 40:
            return SHIP_TYPES.get(self.ship_type, "Special")
        elif 40 <= self.ship_type < 50:
            return SHIP_TYPES.get(40, "HSC")
        elif 50 <= self.ship_type < 60:
            return SHIP_TYPES.get(self.ship_type, "Special")
        elif 60 <= self.ship_type < 70:
            return "Passenger"
        elif 70 <= self.ship_type < 80:
            return "Cargo"
        elif 80 <= self.ship_type < 90:
            return "Tanker"
        else:
            return SHIP_TYPES.get(self.ship_type, "Other")

    @property
    def nav_status_name(self) -> str:
        if self.nav_status is None:
            return "Unknown"
        return NAV_STATUS.get(self.nav_status, "Unknown")


def decode_ais_string(bits, start, length):
    """Decode 6-bit ASCII string from AIS message."""
    chars = []
    for i in range(length):
        pos = start + i * 6
        if pos + 6 > len(bits):
            break
        val = int(bits[pos:pos + 6], 2)
        if val < 32:
            val += 64
        chars.append(chr(val))
    return ''.join(chars).strip('@').strip()


def decode_ais_signed(bits, start, length):
    """Decode signed integer from AIS message."""
    val = int(bits[start:start + length], 2)
    if val >= (1 << (length - 1)):
        val -= (1 << length)
    return val


def decode_ais_unsigned(bits, start, length):
    """Decode unsigned integer from AIS message."""
    return int(bits[start:start + length], 2)


def nmea_to_bits(payload):
    """Convert NMEA AIS payload to binary string."""
    bits = ""
    for char in payload:
        val = ord(char) - 48
        if val > 40:
            val -= 8
        bits += format(val, '06b')
    return bits


def decode_ais_message(nmea_sentence, vessel_db):
    """Decode an AIS NMEA sentence and update vessel database."""
    try:
        if not nmea_sentence.startswith(('!AIVDM', '!AIVDO')):
            return None

        if '*' in nmea_sentence:
            msg_body, checksum_str = nmea_sentence.rsplit('*', 1)
            msg_body = msg_body[1:]
            try:
                expected = int(checksum_str[:2], 16)
                computed = 0
                for ch in msg_body:
                    computed ^= ord(ch)
                if computed != expected:
                    return None
            except ValueError:
                return None

        parts = nmea_sentence.split(',')
        if len(parts) < 7:
            return None

        total_sentences = int(parts[1])
        if total_sentences > 1:
            return None

        payload = parts[5]
        if not payload:
            return None

        bits = nmea_to_bits(payload)
        if len(bits) < 38:
            return None

        msg_type = decode_ais_unsigned(bits, 0, 6)
        mmsi = str(decode_ais_unsigned(bits, 8, 30)).zfill(9)

        if mmsi not in vessel_db:
            vessel_db[mmsi] = Vessel(mmsi=mmsi)

        vessel = vessel_db[mmsi]
        vessel.last_seen = datetime.now()
        vessel.message_count += 1
        vessel.last_message_type = msg_type

        if msg_type in (1, 2, 3):
            _decode_position_report_a(bits, vessel)
        elif msg_type == 4:
            _decode_base_station(bits, vessel)
        elif msg_type == 5:
            _decode_static_voyage(bits, vessel)
        elif msg_type == 18:
            _decode_position_report_b(bits, vessel)
        elif msg_type == 19:
            _decode_extended_position_b(bits, vessel)
        elif msg_type == 24:
            _decode_static_data(bits, vessel)
        elif msg_type == 21:
            _decode_aton(bits, vessel)

        return vessel
    except Exception:
        return None


def _decode_position_report_a(bits, vessel):
    if len(bits) < 168:
        return
    vessel.nav_status = decode_ais_unsigned(bits, 38, 4)
    rot_raw = decode_ais_signed(bits, 42, 8)
    if rot_raw == -128:
        vessel.rot = None
    elif rot_raw == 0:
        vessel.rot = 0.0
    elif rot_raw == 127 or rot_raw == -127:
        vessel.rot = float(rot_raw)
    else:
        import math
        sign = 1 if rot_raw > 0 else -1
        vessel.rot = sign * (rot_raw / 4.733) ** 2
    vessel.sog = decode_ais_unsigned(bits, 50, 10) / 10.0
    lon = decode_ais_signed(bits, 61, 28) / 600000.0
    lat = decode_ais_signed(bits, 89, 27) / 600000.0
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        vessel.longitude = lon
        vessel.latitude = lat
    vessel.cog = decode_ais_unsigned(bits, 116, 12) / 10.0
    vessel.heading = decode_ais_unsigned(bits, 128, 9)


def _decode_position_report_b(bits, vessel):
    if len(bits) < 168:
        return
    vessel.sog = decode_ais_unsigned(bits, 46, 10) / 10.0
    lon = decode_ais_signed(bits, 57, 28) / 600000.0
    lat = decode_ais_signed(bits, 85, 27) / 600000.0
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        vessel.longitude = lon
        vessel.latitude = lat
    vessel.cog = decode_ais_unsigned(bits, 112, 12) / 10.0
    vessel.heading = decode_ais_unsigned(bits, 124, 9)


def _decode_extended_position_b(bits, vessel):
    if len(bits) < 312:
        return
    _decode_position_report_b(bits, vessel)
    vessel.name = decode_ais_string(bits, 143, 20)
    vessel.ship_type = decode_ais_unsigned(bits, 263, 8)


def _decode_static_voyage(bits, vessel):
    if len(bits) < 424:
        return
    vessel.imo = str(decode_ais_unsigned(bits, 40, 30))
    vessel.callsign = decode_ais_string(bits, 70, 7)
    vessel.name = decode_ais_string(bits, 112, 20)
    vessel.ship_type = decode_ais_unsigned(bits, 232, 8)
    # ETA: month (4 bits @ 274), day (5 @ 278), hour (5 @ 283), minute (6 @ 288)
    eta_month = decode_ais_unsigned(bits, 274, 4)
    eta_day = decode_ais_unsigned(bits, 278, 5)
    eta_hour = decode_ais_unsigned(bits, 283, 5)
    eta_minute = decode_ais_unsigned(bits, 288, 6)
    if eta_month > 0 and eta_day > 0:
        vessel.eta = f"{eta_month:02d}-{eta_day:02d} {eta_hour:02d}:{eta_minute:02d}"
    vessel.draught = decode_ais_unsigned(bits, 294, 8) / 10.0
    vessel.destination = decode_ais_string(bits, 302, 20)


def _decode_static_data(bits, vessel):
    if len(bits) < 160:
        return
    part_num = decode_ais_unsigned(bits, 38, 2)
    if part_num == 0:
        vessel.name = decode_ais_string(bits, 40, 20)
    elif part_num == 1:
        vessel.ship_type = decode_ais_unsigned(bits, 40, 8)
        vessel.callsign = decode_ais_string(bits, 90, 7)


def _decode_base_station(bits, vessel):
    if len(bits) < 168:
        return
    lon = decode_ais_signed(bits, 79, 28) / 600000.0
    lat = decode_ais_signed(bits, 107, 27) / 600000.0
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        vessel.longitude = lon
        vessel.latitude = lat
    vessel.name = "Base Station"


def _decode_aton(bits, vessel):
    if len(bits) < 272:
        return
    vessel.name = decode_ais_string(bits, 43, 20)
    lon = decode_ais_signed(bits, 164, 28) / 600000.0
    lat = decode_ais_signed(bits, 192, 27) / 600000.0
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        vessel.longitude = lon
        vessel.latitude = lat

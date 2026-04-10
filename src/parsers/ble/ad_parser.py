"""
BLE Advertisement Data (AD) structure parser.

Shared utility used by all BLE parsers to extract typed fields from
raw advertisement bytes per Bluetooth Core Spec Vol 3, Part C, Section 11.
"""

import struct


def parse_ad_structures(ad_bytes):
    """
    Parse BLE advertisement data (AD structures).

    Returns dict with: name, tx_power, manufacturer_id, manufacturer_data,
    service_uuids, service_data, ad_types (for fingerprinting).
    """
    result = {
        "name": None,
        "tx_power": None,
        "mfr_id": None,
        "mfr_data": b"",
        "service_uuids": [],
        "service_data": {},  # uuid -> bytes
        "ad_types": [],
    }

    i = 0
    while i < len(ad_bytes) - 1:
        length = ad_bytes[i]
        if length == 0 or i + length >= len(ad_bytes):
            break
        ad_type = ad_bytes[i + 1]
        ad_value = ad_bytes[i + 2:i + 1 + length]
        result["ad_types"].append(ad_type)

        if ad_type in (0x08, 0x09) and ad_value:  # Local Name
            try:
                result["name"] = ad_value.decode("utf-8", errors="replace")
            except Exception:
                pass
        elif ad_type == 0x0A and ad_value:  # TX Power Level
            result["tx_power"] = struct.unpack("b", bytes([ad_value[0]]))[0]
        elif ad_type == 0xFF and len(ad_value) >= 2:  # Manufacturer Specific
            result["mfr_id"] = struct.unpack("<H", ad_value[:2])[0]
            result["mfr_data"] = ad_value[2:]
        elif ad_type in (0x02, 0x03):  # 16-bit Service UUIDs (incomplete/complete)
            for j in range(0, len(ad_value) - 1, 2):
                uuid = struct.unpack("<H", ad_value[j:j + 2])[0]
                result["service_uuids"].append(uuid)
        elif ad_type == 0x16 and len(ad_value) >= 2:  # Service Data - 16-bit UUID
            uuid = struct.unpack("<H", ad_value[:2])[0]
            result["service_data"][uuid] = ad_value[2:]
        elif ad_type in (0x04, 0x05):  # 32-bit Service UUIDs
            for j in range(0, len(ad_value) - 3, 4):
                uuid = struct.unpack("<I", ad_value[j:j + 4])[0]
                result["service_uuids"].append(uuid)
        elif ad_type in (0x06, 0x07):  # 128-bit Service UUIDs
            for j in range(0, len(ad_value) - 15, 16):
                result["service_uuids"].append(ad_value[j:j + 16])

        i += 1 + length

    return result

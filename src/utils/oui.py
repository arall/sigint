"""
OUI (Organizationally Unique Identifier) lookup for MAC addresses.

Uses the IEEE OUI database (data/oui.csv) to resolve the first 3 bytes of a
MAC address to a manufacturer name. Also detects randomized MACs by checking
the "locally administered" bit.

The OUI database can be updated by downloading from:
  https://standards-oui.ieee.org/oui/oui.csv
"""

import csv
import os

# Path to IEEE OUI database
_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
OUI_CSV_PATH = os.path.join(_DATA_DIR, "oui.csv")

# Cached lookup table: "AABBCC" -> "Apple, Inc."
_oui_db = None


def _load_oui_db():
    """Load the OUI database from CSV into memory."""
    global _oui_db
    if _oui_db is not None:
        return

    _oui_db = {}
    if not os.path.exists(OUI_CSV_PATH):
        return

    with open(OUI_CSV_PATH, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 3:
                # Assignment is the OUI hex string (e.g., "AABBCC")
                oui_hex = row[1].strip().upper()
                org_name = row[2].strip().strip('"')
                _oui_db[oui_hex] = org_name


def is_randomized_mac(mac):
    """
    Check if a MAC address is locally administered (randomized).

    The second bit of the first octet being 1 indicates a locally administered
    address, which is used by MAC randomization on iOS/Android.
    """
    first_byte = int(mac.replace(":", "").replace("-", "")[:2], 16)
    return bool(first_byte & 0x02)


def lookup_manufacturer(mac):
    """
    Look up the manufacturer for a MAC address.

    Args:
        mac: MAC address string (e.g., "AA:BB:CC:DD:EE:FF")

    Returns:
        Manufacturer name string, or None if not found.
        Returns None for randomized MACs (no valid OUI).
    """
    _load_oui_db()

    if is_randomized_mac(mac):
        return None

    # Extract first 3 bytes as uppercase hex without separators
    oui = mac.replace(":", "").replace("-", "")[:6].upper()
    return _oui_db.get(oui)


def get_device_description(mac):
    """
    Get a human-readable device description from a MAC address.

    Returns a string like "Apple (randomized)", "Samsung", or "Unknown (randomized)".
    """
    randomized = is_randomized_mac(mac)
    manufacturer = lookup_manufacturer(mac)

    if manufacturer:
        return manufacturer
    elif randomized:
        return "randomized"
    else:
        return "unknown"

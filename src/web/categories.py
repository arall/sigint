"""
Category map — groups signal types into real-world domains so the
dashboard can show dedicated tabs (Voice / Drones / Aircraft / Vessels /
Vehicles / Cellular / Devices / Other) instead of one flat firehose.
Anything not listed falls into "other"; GSM-UPLINK-* / LTE-UPLINK-* is
handled by prefix so new subtypes don't fall through.
"""

CATEGORIES = {
    "voice": [
        "PMR446", "dPMR", "dPMR446", "70cm", "MarineVHF", "2m", "FRS", "FM_voice",
        "TETRA",
    ],
    "drones": [
        "RemoteID", "RemoteID-operator", "DroneCtrl", "DroneVideo",
    ],
    "aircraft": ["ADS-B"],
    "vessels":  ["AIS"],
    "keyfobs":  ["keyfob"],
    "tpms":     ["tpms"],
    "cellular": [
        "GSM-UPLINK-GSM-900", "GSM-UPLINK-GSM-850", "LTE-UPLINK",
    ],
    "devices": [
        "BLE-Adv", "WiFi-Probe", "WiFi-AP",
    ],
    "ism":      ["ISM"],
    "lora":     ["lora"],
    "pagers":   ["pocsag"],
}

CATEGORY_LABELS = {
    "voice":    "Voice",
    "drones":   "Drones",
    "aircraft": "Aircraft",
    "vessels":  "Vessels",
    "keyfobs":  "Keyfobs",
    "tpms":     "TPMS",
    "cellular": "Cellular",
    "devices":  "Devices",
    "ism":      "ISM",
    "lora":     "LoRa",
    "pagers":   "Pagers",
}

CATEGORY_ORDER = [
    "voice", "drones", "aircraft", "vessels",
    "keyfobs", "tpms", "cellular", "devices",
    "ism", "lora", "pagers",
]

TYPE_TO_CATEGORY = {sig: cat for cat, sigs in CATEGORIES.items() for sig in sigs}


# ISM signal types that are keyfobs (rolling code chips, FSK car remotes)
_ISM_KEYFOB_PREFIXES = (
    "ISM:Microchip-HCS",   # HCS200, HCS300, HCS301 rolling code
    "ISM:Nice-",           # Nice FLO / FLOR gate remotes
    "ISM:CAME-",           # CAME gate remotes
    "ISM:FSK",             # Native FSK car keyfob detection
)


def category_of(signal_type, metadata=None):
    """Map a raw signal_type string to a category id. Handles wildcards
    (GSM-UPLINK-* / LTE-UPLINK-* → cellular, ISM keyfobs/TPMS → their tabs)."""
    if signal_type in TYPE_TO_CATEGORY:
        return TYPE_TO_CATEGORY[signal_type]
    if signal_type.startswith("GSM-UPLINK") or signal_type.startswith("LTE-UPLINK"):
        return "cellular"
    if signal_type.startswith("ISM:"):
        # Check if it's a known keyfob chip
        for prefix in _ISM_KEYFOB_PREFIXES:
            if signal_type.startswith(prefix):
                return "keyfobs"
        # Check metadata for TPMS
        if metadata and isinstance(metadata, dict) and metadata.get("type") == "TPMS":
            return "tpms"
        return "ism"
    return "other"

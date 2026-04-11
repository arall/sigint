"""
Category map — groups signal types into real-world domains so the
dashboard can show dedicated tabs (Voice / Drones / Aircraft / Vessels /
Vehicles / Cellular / Devices / Other) instead of one flat firehose.
Anything not listed falls into "other"; GSM-UPLINK-* / LTE-UPLINK-* is
handled by prefix so new subtypes don't fall through.
"""

CATEGORIES = {
    "voice": [
        "PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS", "FM_voice",
    ],
    "drones": [
        "RemoteID", "RemoteID-operator", "DroneCtrl", "DroneVideo",
    ],
    "aircraft": ["ADS-B"],
    "vessels":  ["AIS"],
    "vehicles": ["tpms", "keyfob"],
    "cellular": [
        "GSM-UPLINK-GSM-900", "GSM-UPLINK-GSM-850", "LTE-UPLINK",
    ],
    "devices": [
        "BLE-Adv", "WiFi-Probe", "WiFi-AP",
    ],
    "other": [
        "ISM", "lora", "pocsag",
    ],
}

CATEGORY_LABELS = {
    "voice":    "Voice",
    "drones":   "Drones",
    "aircraft": "Aircraft",
    "vessels":  "Vessels",
    "vehicles": "Vehicles",
    "cellular": "Cellular",
    "devices":  "Devices",
    "other":    "Other",
}

CATEGORY_ORDER = [
    "voice", "drones", "aircraft", "vessels",
    "vehicles", "cellular", "devices", "other",
]

TYPE_TO_CATEGORY = {sig: cat for cat, sigs in CATEGORIES.items() for sig in sigs}


def category_of(signal_type):
    """Map a raw signal_type string to a category id. Handles wildcards
    (GSM-UPLINK-* / LTE-UPLINK-* → cellular)."""
    if signal_type in TYPE_TO_CATEGORY:
        return TYPE_TO_CATEGORY[signal_type]
    if signal_type.startswith("GSM-UPLINK") or signal_type.startswith("LTE-UPLINK"):
        return "cellular"
    return "other"

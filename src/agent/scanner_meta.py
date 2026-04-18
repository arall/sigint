"""Per-scanner static metadata used by the agent to populate SCANINFO.

Kept simple — center frequency, bandwidth, channel count, hopping flag,
and a short parser hint per scanner type. The dashboard renders this in
the agent's expandable Agents-tab row so an operator can see at a glance
what a node is actually capturing.

Adding a new scanner type to the table is the only thing required for
it to show up in the dashboard. Runtime values (drop counts, current
center freq after retune, ...) are out of scope here — the scanner
subprocess would need to expose those as a sidecar.
"""
from __future__ import annotations

from typing import Dict, TypedDict


class ScannerMeta(TypedDict):
    center_mhz: float
    bw_mhz: float
    channels: int
    hopping: bool
    parsers: str


SCANNER_META: Dict[str, ScannerMeta] = {
    "pmr": {
        "center_mhz": 446.05, "bw_mhz": 2.4, "channels": 8,
        "hopping": False, "parsers": "fm_voice (+ dPMR with --digital)",
    },
    "fm": {
        # Generic FM scanner — covers whatever band profile is selected.
        "center_mhz": 0.0, "bw_mhz": 2.4, "channels": 0,
        "hopping": True, "parsers": "fm_voice",
    },
    "keyfob": {
        "center_mhz": 433.92, "bw_mhz": 2.0, "channels": 1,
        "hopping": False, "parsers": "keyfob (OOK)",
    },
    "tpms": {
        "center_mhz": 433.92, "bw_mhz": 2.0, "channels": 1,
        "hopping": False, "parsers": "tpms (Manchester OOK)",
    },
    "gsm": {
        "center_mhz": 947.5, "bw_mhz": 2.0, "channels": 124,
        "hopping": True, "parsers": "gsm (FCCH burst detect)",
    },
    "lte": {
        "center_mhz": 1842.5, "bw_mhz": 2.0, "channels": 0,
        "hopping": True, "parsers": "lte (uplink power)",
    },
    "adsb": {
        "center_mhz": 1090.0, "bw_mhz": 2.4, "channels": 1,
        "hopping": False, "parsers": "readsb (Mode S)",
    },
    "ais": {
        "center_mhz": 162.0, "bw_mhz": 2.4, "channels": 2,
        "hopping": False, "parsers": "rtl_ais",
    },
    "pocsag": {
        "center_mhz": 466.075, "bw_mhz": 2.4, "channels": 1,
        "hopping": False, "parsers": "multimon-ng",
    },
    "ism": {
        "center_mhz": 0.0, "bw_mhz": 2.4, "channels": 0,
        "hopping": True, "parsers": "rtl_433 (200+ protocols)",
    },
    "lora": {
        "center_mhz": 868.3, "bw_mhz": 2.4, "channels": 1,
        "hopping": False, "parsers": "lora chirp",
    },
    "wifi": {
        "center_mhz": 0.0, "bw_mhz": 0.0, "channels": 14,
        "hopping": True, "parsers": "probe_request, beacon, remoteid_wifi",
    },
    "bt": {
        "center_mhz": 2402.0, "bw_mhz": 80.0, "channels": 3,
        "hopping": False, "parsers": "apple_continuity, remoteid_ble",
    },
    "mesh": {
        "center_mhz": 868.3, "bw_mhz": 0.0, "channels": 1,
        "hopping": False, "parsers": "Meshtastic serial decoder",
    },
    "scan": {
        "center_mhz": 0.0, "bw_mhz": 2.4, "channels": 0,
        "hopping": True, "parsers": "wideband energy + AMC",
    },
}


def for_scanner(scanner_type: str) -> ScannerMeta:
    """Return metadata for `scanner_type`, or a benign fallback."""
    return SCANNER_META.get(scanner_type, {
        "center_mhz": 0.0, "bw_mhz": 0.0, "channels": 0,
        "hopping": False, "parsers": scanner_type,
    })

"""
WiFi Probe Request Parser

Extracts device fingerprints from 802.11 probe request frames using
Information Element signatures, SSID sets, and sequence number continuity
to track devices across MAC address rotations.
"""

import hashlib
import json
import threading
import time
from collections import defaultdict
from datetime import datetime

from parsers.base import BaseParser
from utils.logger import SignalDetection
from utils.oui import get_device_description, is_randomized_mac, lookup_manufacturer
from utils.persona_db import PersonaDB

# 2.4 GHz WiFi channels (center frequencies)
WIFI_CHANNELS = {
    1: 2412e6,
    2: 2417e6,
    3: 2422e6,
    4: 2427e6,
    5: 2432e6,
    6: 2437e6,
    7: 2442e6,
    8: 2447e6,
    9: 2452e6,
    10: 2457e6,
    11: 2462e6,
}

# Detection parameters
DEDUP_WINDOW = 30  # seconds before re-logging same persona
SEQ_CONTINUITY_WINDOW = 50  # max seq gap to consider same device


def extract_device_signature(packet):
    """
    Build a device signature from 802.11 Information Elements.

    Returns a hex string hash of (IE ID list, supported rates, HT capabilities,
    vendor OUIs). This fingerprints the device model/chipset — identical across
    MAC rotations.
    """
    from scapy.layers.dot11 import Dot11Elt, Dot11EltRates, Dot11EltHTCapabilities

    ie_ids = []
    rates = []
    ht_bytes = b""
    vendor_ouis = []

    elt = packet.getlayer(Dot11Elt)
    while elt:
        ie_ids.append(elt.ID)
        if elt.ID == 221 and elt.info and len(elt.info) >= 3:
            vendor_ouis.append(elt.info[:3])
        elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None

    if packet.haslayer(Dot11EltRates):
        rates = list(packet[Dot11EltRates].rates)

    if packet.haslayer(Dot11EltHTCapabilities):
        ht_bytes = bytes(packet[Dot11EltHTCapabilities])[:6]

    sig_data = (
        tuple(ie_ids),
        tuple(rates),
        ht_bytes,
        tuple(vendor_ouis),
    )
    return hashlib.sha256(repr(sig_data).encode()).hexdigest()[:12]


class ProbeRequestParser(BaseParser):
    """
    Parses WiFi probe request frames for device fingerprinting and
    persona tracking across MAC rotations.
    """

    def __init__(self, logger, min_rssi=-85, persona_db_path=None):
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
                print(f"[*] Loaded persona DB: {db_summary['total']} known personas "
                      f"({db_summary['returning']} returning)")

    def handle_frame(self, frame):
        """Process a WiFi frame: (packet, channel). Only acts on probe requests."""
        from scapy.layers.dot11 import Dot11, Dot11ProbeReq, Dot11Elt

        packet, channel = frame

        if not packet.haslayer(Dot11ProbeReq):
            return

        mac = packet.addr2
        if not mac:
            return

        # RSSI
        rssi = None
        try:
            rssi = packet.dBm_AntSignal
        except AttributeError:
            pass
        if rssi is not None and rssi < self.min_rssi:
            return

        # Sequence number
        seq_num = None
        if packet.haslayer(Dot11):
            seq_num = packet[Dot11].SC >> 4

        # SSID
        ssid = ""
        elt = packet.getlayer(Dot11Elt)
        if elt and elt.ID == 0 and elt.info:
            try:
                ssid = elt.info.decode("utf-8", errors="replace")
            except Exception:
                pass

        # Device signature from IEs
        dev_sig = extract_device_signature(packet)

        now = time.time()
        should_log = False

        with self._lock:
            pid = self._find_persona(mac, dev_sig, ssid, seq_num)
            persona = self._personas[pid]
            persona["count"] += 1
            persona["last_rssi"] = rssi
            persona["last_seen"] = datetime.now().isoformat()
            is_new = persona["count"] == 1

            if ssid:
                persona["ssids"].add(ssid)
                if len(persona["ssids"]) == 1 and persona["prior_sessions"] == 0:
                    if self._persona_db:
                        prior = self._persona_db.get_session_count(dev_sig, persona["ssids"])
                        persona["prior_sessions"] = prior

            if not persona["manufacturer"]:
                mfr = lookup_manufacturer(mac)
                if mfr:
                    persona["manufacturer"] = mfr
                    persona["device_desc"] = mfr

            self._macs[mac]["last_seq"] = seq_num
            self._macs[mac]["last_seen"] = now

            if is_new:
                should_log = True
                n_personas = len(self._personas)
                n_macs = len(persona["macs"])
                mac_info = f" ({n_macs} MACs)" if n_macs > 1 else ""
                returning = ""
                if persona["prior_sessions"] > 0:
                    returning = f"  **RETURNING (seen {persona['prior_sessions']}x)**"
                print(f"  [NEW] P{pid:03d}  {mac}{mac_info}  "
                      f"[{persona['device_desc']}]  "
                      f"RSSI: {rssi} dBm  CH: {channel}  "
                      f"SSID: {ssid or '(broadcast)'}  "
                      f"[{n_personas} personas]{returning}")
            elif (now - persona["last_logged"]) >= DEDUP_WINDOW:
                should_log = True

            if should_log:
                persona["last_logged"] = now

            persona_snapshot = {
                "persona_id": f"P{pid:03d}",
                "mac": mac,
                "macs": sorted(persona["macs"]),
                "dev_sig": dev_sig,
                "device": persona["device_desc"],
                "manufacturer": persona["manufacturer"],
                "randomized": persona["randomized"],
                "ssid": ssid or None,
                "ssids": sorted(persona["ssids"]),
                "probe_count": persona["count"],
                "first_seen": persona["first_seen"],
                "prior_sessions": persona["prior_sessions"],
            }

        if should_log and rssi is not None:
            freq = WIFI_CHANNELS.get(channel, 2437e6)
            noise_floor = -95.0
            detection = SignalDetection.create(
                signal_type="WiFi-Probe",
                frequency_hz=freq,
                power_db=float(rssi),
                noise_floor_db=noise_floor,
                channel=f"CH{channel}",
                metadata=json.dumps(persona_snapshot),
            )
            self.logger.log(detection)

    def _find_persona(self, mac, dev_sig, ssid, seq_num):
        """Find or create persona. Caller must hold self._lock."""
        if mac in self._macs:
            return self._macs[mac]["persona_id"]

        # Search by device signature + SSID overlap
        if dev_sig in self._sig_to_personas:
            for pid in self._sig_to_personas[dev_sig]:
                persona = self._personas[pid]
                if ssid and ssid in persona["ssids"]:
                    self._macs[mac] = {
                        "persona_id": pid,
                        "last_seq": seq_num,
                        "last_seen": time.time(),
                    }
                    persona["macs"].add(mac)
                    print(f"  [MERGE] {mac} -> P{pid:03d} (SSID match: {ssid})")
                    return pid

                # Sequence number continuity
                if seq_num is not None:
                    for other_mac, mstate in self._macs.items():
                        if (mstate["persona_id"] == pid
                                and mstate["last_seq"] is not None):
                            seq_diff = (seq_num - mstate["last_seq"]) % 4096
                            if 0 < seq_diff <= SEQ_CONTINUITY_WINDOW:
                                self._macs[mac] = {
                                    "persona_id": pid,
                                    "last_seq": seq_num,
                                    "last_seen": time.time(),
                                }
                                persona["macs"].add(mac)
                                print(f"  [MERGE] {mac} -> P{pid:03d} "
                                      f"(seq continuity: {mstate['last_seq']}->{seq_num})")
                                return pid

        # Check persistent DB
        prior_sessions = 0
        if self._persona_db:
            prior_sessions = self._persona_db.get_session_count(
                dev_sig, {ssid} if ssid else set()
            )

        pid = self._next_persona_id
        self._next_persona_id += 1

        manufacturer = lookup_manufacturer(mac)
        randomized = is_randomized_mac(mac)
        device_desc = get_device_description(mac)

        self._personas[pid] = {
            "macs": {mac},
            "dev_sig": dev_sig,
            "ssids": set(),
            "first_seen": datetime.now().isoformat(),
            "last_seen": None,
            "last_logged": 0,
            "count": 0,
            "last_rssi": None,
            "manufacturer": manufacturer,
            "randomized": randomized,
            "device_desc": device_desc,
            "prior_sessions": prior_sessions,
        }
        self._sig_to_personas[dev_sig].append(pid)
        self._macs[mac] = {
            "persona_id": pid,
            "last_seq": seq_num,
            "last_seen": time.time(),
        }
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
                    ssids=p["ssids"],
                    macs=p["macs"],
                    manufacturer=p["manufacturer"],
                    randomized=p["randomized"],
                    probe_count=p["count"],
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

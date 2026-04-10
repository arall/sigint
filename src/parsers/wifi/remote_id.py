"""
Open Drone ID (RemoteID) WiFi Parser

Parses ASTM F3411 Remote ID messages from WiFi frames:
- WiFi NaN (Neighbor Awareness Networking) action frames
- WiFi Beacon frames with vendor-specific IEs

Drones broadcast RemoteID over WiFi using NaN Service Discovery Frames
or legacy beacon frames with the ASTM F3411 OUI and payload.

Uses the same ODID message parsing as the BLE RemoteID parser.
"""

import json
import time
from datetime import datetime

from parsers.base import BaseParser
from parsers.ble.remote_id import (
    _parse_message,
    get_drone_registry,
    MSG_BASIC_ID,
    MSG_LOCATION,
    MSG_SELF_ID,
    MSG_SYSTEM,
    MSG_OPERATOR_ID,
    MSG_PACK,
    ODID_APP_CODE,
)
from utils.logger import SignalDetection

# ASTM F3411 / Open Drone ID WiFi OUI
# FA:0B:BC is the ASTM International CID used for RemoteID
ODID_OUI = b"\xfa\x0b\xbc"

# WiFi channels (center frequencies)
WIFI_CHANNELS = {
    1: 2412e6, 2: 2417e6, 3: 2422e6, 4: 2427e6, 5: 2432e6,
    6: 2437e6, 7: 2442e6, 8: 2447e6, 9: 2452e6, 10: 2457e6, 11: 2462e6,
}

# Dedup window
DEDUP_WINDOW = 5


class WiFiRemoteIDParser(BaseParser):
    """
    Parses Open Drone ID (ASTM F3411) messages from WiFi frames.

    Detects drones broadcasting RemoteID via:
    1. WiFi NaN (Neighbor Awareness Networking) action frames with ODID payload
    2. WiFi Beacon/Probe Response with vendor-specific IE containing ODID OUI
    """

    def __init__(self, logger, min_rssi=-85, drone_registry=None):
        super().__init__(logger)
        self.min_rssi = min_rssi
        self._registry = drone_registry or get_drone_registry()

    def handle_frame(self, frame):
        """Process a WiFi frame: (packet, channel)."""
        packet, channel = frame

        # Try to extract ODID payload from various frame types
        odid_payload, mac, rssi = self._extract_odid(packet)
        if odid_payload is None:
            return

        if rssi is not None and rssi < self.min_rssi:
            return

        # Parse ODID messages
        messages = self._parse_odid_payload(odid_payload)
        if not messages:
            return

        # Build detection
        drone_info = self._merge_messages(messages, mac, rssi, channel)
        drone_id = drone_info.get("drone_id", mac or "unknown")

        # Dedup via shared registry (cross-transport)
        is_new, should_log = self._registry.update(drone_id, rssi, "WiFi")

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
            print(f"  [DRONE-WiFi] {drone_id}  {ua_type}  RSSI: {rssi} dBm"
                  f"  CH: {channel}  MAC: {mac}{pos_str}")

        if should_log and rssi is not None:
            freq = WIFI_CHANNELS.get(channel, 2437e6)
            noise_floor = -95.0

            # Drone position from Location message
            drone_lat = drone_info.get("latitude")
            drone_lon = drone_info.get("longitude")
            detection = SignalDetection.create(
                signal_type="RemoteID",
                frequency_hz=freq,
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
                    "transport": "WiFi",
                }
                op_detection = SignalDetection.create(
                    signal_type="RemoteID-operator",
                    frequency_hz=freq,
                    power_db=float(rssi),
                    noise_floor_db=noise_floor,
                    channel=f"{drone_id}-op",
                    latitude=op_lat,
                    longitude=op_lon,
                    metadata=json.dumps(op_meta),
                )
                self.logger.log(op_detection)

    def _extract_odid(self, packet):
        """
        Try to extract ODID payload from a WiFi frame.

        Returns (odid_payload_bytes, mac, rssi) or (None, None, None).
        """
        from scapy.layers.dot11 import Dot11, Dot11Beacon, Dot11ProbeResp, Dot11Elt

        mac = None
        rssi = None

        if packet.haslayer(Dot11):
            mac = packet[Dot11].addr2
            try:
                rssi = packet.dBm_AntSignal
            except AttributeError:
                pass

        # Check vendor-specific IEs in Beacon/ProbeResp frames
        if packet.haslayer(Dot11Beacon) or packet.haslayer(Dot11ProbeResp):
            payload = self._find_odid_vendor_ie(packet)
            if payload:
                return payload, mac, rssi

        # Check for WiFi NaN action frames
        # NaN uses Action frames (type=0, subtype=13) with specific OUI
        if packet.haslayer(Dot11):
            dot11 = packet[Dot11]
            # Action frame: type=0 (Management), subtype=13 (Action)
            if dot11.type == 0 and dot11.subtype == 13:
                payload = self._find_odid_in_action(packet)
                if payload:
                    return payload, mac, rssi

        return None, None, None

    def _find_odid_vendor_ie(self, packet):
        """Search Dot11Elt chain for vendor-specific IE with ODID OUI + app code."""
        from scapy.layers.dot11 import Dot11Elt

        elt = packet.getlayer(Dot11Elt)
        while elt:
            # Vendor-specific IE (ID=221): OUI (3) + type (1) + payload
            if elt.ID == 221 and elt.info and len(elt.info) >= 5:
                oui = elt.info[:3]
                vendor_type = elt.info[3]
                if oui == ODID_OUI and vendor_type == ODID_APP_CODE:
                    # Skip OUI (3 bytes) + vendor type (1 byte)
                    return elt.info[4:]
            elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None
        return None

    def _find_odid_in_action(self, packet):
        """Extract ODID payload from a WiFi NaN action frame."""
        # NaN action frames carry ODID data in vendor-specific attributes
        # The raw payload after the Dot11 header contains:
        # - Category (1 byte): 0x04 (Public Action) or 0x7F (Vendor-specific)
        # - Action (1 byte)
        # - OUI (3 bytes)
        # - Vendor type (1 byte): 0x0D for ODID
        # - ... ODID message payload
        raw = bytes(packet.payload) if hasattr(packet, 'payload') else b""

        # Search for ODID OUI in the raw action frame payload
        idx = raw.find(ODID_OUI)
        if idx >= 0 and idx + 4 < len(raw):
            # Validate vendor type byte (0x0D)
            if raw[idx + 3] != ODID_APP_CODE:
                return None
            # Payload follows after OUI (3 bytes) + type byte (1 byte)
            return raw[idx + 4:]

        return None

    def _parse_odid_payload(self, payload):
        """Parse ODID payload, handling both single messages and message packs.

        WiFi ODID (ASTM F3411-22a) beacons prepend a message counter byte
        before the standard message pack.  The WiFi message pack also carries
        an extra ``msg_size`` byte (always 25) between the type/version byte
        and the message count.  Layout::

            [counter] [0xFn = Pack|ver] [msg_size=25] [count] [25-byte msgs …]

        BLE ODID omits the counter and msg_size bytes, so the parser tries the
        WiFi format first, then falls back to the BLE/plain format.
        """
        messages = []

        if len(payload) < 1:
            return messages

        # --- WiFi format: counter byte + message pack with msg_size field ---
        # Check if byte 1 looks like a message pack header (upper nibble 0xF)
        if len(payload) >= 4:
            maybe_pack = (payload[1] >> 4) & 0x0F
            if maybe_pack == MSG_PACK:
                # payload[0] = counter (skip)
                # payload[1] = 0xFn  (MSG_PACK | proto_version)
                # payload[2] = msg_size (25)
                # payload[3] = msg_count
                msg_size = payload[2]
                msg_count = payload[3]
                if msg_size == 25 and 1 <= msg_count <= 10:
                    offset = 4
                    for _ in range(msg_count):
                        if offset + msg_size > len(payload):
                            break
                        sub_type = (payload[offset] >> 4) & 0x0F
                        parsed = _parse_message(sub_type,
                                                payload[offset + 1:offset + msg_size])
                        if parsed:
                            parsed["_msg_type"] = sub_type
                            messages.append(parsed)
                        offset += msg_size
                    if messages:
                        return messages

        # --- BLE / plain format (no counter byte) ---
        msg_type = (payload[0] >> 4) & 0x0F

        if msg_type == MSG_PACK:
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
            parsed = _parse_message(msg_type, payload[1:])
            if parsed:
                parsed["_msg_type"] = msg_type
                messages.append(parsed)

        return messages

    def _merge_messages(self, messages, mac, rssi, channel):
        """Merge ODID messages into a single drone info dict."""
        info = {"mac": mac, "rssi": rssi, "channel": channel, "transport": "WiFi"}

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

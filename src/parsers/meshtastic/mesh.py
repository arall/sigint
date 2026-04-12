"""
Meshtastic Mesh Parser

Consumes decoded packet dicts from MeshtasticCaptureSource, produces
SignalDetections with signal types:
  - Meshtastic-Position  (node GPS, goes on map)
  - Meshtastic-Telemetry (battery, environment)
  - Meshtastic-Node      (node info / identity)

device_id = node hex ID (e.g. "!760a1abc")
channel   = mesh channel number or portnum for routing
"""

import json
import time
from datetime import datetime

from parsers.base import BaseParser
from utils.logger import SignalDetection

# EU LoRa frequency (used as nominal for logging — no actual SDR tuning)
MESH_FREQ_HZ = 869.525e6


class MeshtasticParser(BaseParser):
    """Parses Meshtastic packets into SignalDetections."""

    def __init__(self, logger, capture_source=None, region="eu"):
        super().__init__(logger)
        self._capture = capture_source  # for node name resolution
        self._region = region.upper()
        self._total = 0
        # Dedup: (from_id, portnum) -> last_logged_time
        self._last_logged = {}
        self._dedup_window = 5.0  # seconds

    @property
    def total_detections(self):
        return self._total

    def _node_name(self, node_id):
        """Resolve node number to short name."""
        if self._capture:
            nodes = self._capture.node_db
            node = nodes.get(node_id) or nodes.get(
                f"!{node_id:08x}" if isinstance(node_id, int) else node_id)
            if node:
                user = node.get("user", {})
                return user.get("shortName") or user.get("longName") or str(node_id)
        if isinstance(node_id, int):
            return f"!{node_id:08x}"
        return str(node_id)

    def _node_hex(self, node_id):
        """Normalize node ID to hex string."""
        if isinstance(node_id, int):
            return f"!{node_id:08x}"
        return str(node_id)

    def _freq(self):
        """Nominal frequency for region."""
        return 906.875e6 if self._region == "US" else MESH_FREQ_HZ

    def _should_log(self, from_id, portnum):
        """Simple dedup: don't log same (node, portnum) faster than dedup window."""
        key = (from_id, portnum)
        now = time.time()
        last = self._last_logged.get(key, 0)
        if now - last < self._dedup_window:
            return False
        self._last_logged[key] = now
        return True

    def handle_frame(self, packet):
        """Process one Meshtastic packet dict."""
        from_raw = packet.get("from")
        from_id = self._node_hex(from_raw) if from_raw else packet.get("fromId", "?")
        from_name = self._node_name(from_raw) if from_raw else str(from_id)
        to_raw = packet.get("to")
        to_name = self._node_name(to_raw) if to_raw else str(packet.get("toId", "?"))

        rssi = packet.get("rxRssi")
        snr = packet.get("rxSnr")
        hop_limit = packet.get("hopLimit")
        hop_start = packet.get("hopStart")
        hops = (hop_start - hop_limit) if hop_start and hop_limit else None
        channel = packet.get("channel", 0)

        power_db = float(rssi) if rssi is not None else 0.0
        noise_floor = power_db - float(snr) if snr is not None and rssi is not None else -120.0

        decoded = packet.get("decoded")
        if not decoded:
            # Encrypted packet we can't decrypt — still log the node activity
            if packet.get("encrypted") and from_id != "?":
                self._handle_encrypted(from_id, from_name, to_name,
                                       channel, hops, snr, power_db, noise_floor)
            return

        portnum = decoded.get("portnum", "UNKNOWN_APP")

        if portnum == "POSITION_APP":
            self._handle_position(decoded, from_id, from_name, to_name,
                                  channel, hops, snr, power_db, noise_floor)
        elif portnum == "TELEMETRY_APP":
            self._handle_telemetry(decoded, from_id, from_name,
                                   channel, hops, snr, power_db, noise_floor)
        elif portnum == "NODEINFO_APP":
            self._handle_nodeinfo(decoded, from_id, from_name,
                                  channel, hops, snr, power_db, noise_floor)
        elif portnum == "TRACEROUTE_APP":
            self._handle_traceroute(decoded, from_id, from_name, to_name,
                                    channel, hops, snr, power_db, noise_floor)
        elif portnum == "NEIGHBORINFO_APP":
            self._handle_neighborinfo(decoded, from_id, from_name,
                                      channel, hops, snr, power_db, noise_floor)

    def _handle_position(self, decoded, from_id, from_name, to_name,
                         channel, hops, snr, power_db, noise_floor):
        pos = decoded.get("position", {})
        lat = pos.get("latitude") or (pos.get("latitudeI", 0) / 1e7)
        lon = pos.get("longitude") or (pos.get("longitudeI", 0) / 1e7)
        if lat == 0 and lon == 0:
            return
        if not self._should_log(from_id, "POSITION_APP"):
            return

        alt = pos.get("altitude")
        sats = pos.get("satsInView")

        meta = {
            "node_id": from_id,
            "node_name": from_name,
            "altitude_m": alt,
            "sats": sats,
            "hops": hops,
            "snr": snr,
        }

        detection = SignalDetection.create(
            signal_type="Meshtastic-Position",
            frequency_hz=self._freq(),
            power_db=power_db,
            noise_floor_db=noise_floor,
            channel=str(channel),
            device_id=from_id,
            latitude=lat,
            longitude=lon,
            metadata=json.dumps(meta),
        )
        self.logger.log(detection)
        self._total += 1

    def _handle_telemetry(self, decoded, from_id, from_name,
                          channel, hops, snr, power_db, noise_floor):
        telem = decoded.get("telemetry", {})
        device = telem.get("deviceMetrics", {})
        env = telem.get("environmentMetrics", {})
        if not device and not env:
            return
        if not self._should_log(from_id, "TELEMETRY_APP"):
            return

        meta = {
            "node_id": from_id,
            "node_name": from_name,
            "hops": hops,
            "snr": snr,
        }
        if device:
            meta["battery"] = device.get("batteryLevel")
            meta["voltage"] = device.get("voltage")
            meta["channel_util"] = device.get("channelUtilization")
            meta["air_util_tx"] = device.get("airUtilTx")
            meta["uptime_s"] = device.get("uptimeSeconds")
        if env:
            meta["temperature"] = env.get("temperature")
            meta["humidity"] = env.get("relativeHumidity")
            meta["pressure"] = env.get("barometricPressure")

        detection = SignalDetection.create(
            signal_type="Meshtastic-Telemetry",
            frequency_hz=self._freq(),
            power_db=power_db,
            noise_floor_db=noise_floor,
            channel=str(channel),
            device_id=from_id,
            metadata=json.dumps(meta),
        )
        self.logger.log(detection)
        self._total += 1

    def _handle_nodeinfo(self, decoded, from_id, from_name,
                         channel, hops, snr, power_db, noise_floor):
        user = decoded.get("user", {})
        if not user:
            return
        if not self._should_log(from_id, "NODEINFO_APP"):
            return

        meta = {
            "node_id": from_id,
            "long_name": user.get("longName", ""),
            "short_name": user.get("shortName", ""),
            "hw_model": user.get("hwModel", ""),
            "role": user.get("role", ""),
            "mac": user.get("macaddr", ""),
            "hops": hops,
            "snr": snr,
        }

        detection = SignalDetection.create(
            signal_type="Meshtastic-Node",
            frequency_hz=self._freq(),
            power_db=power_db,
            noise_floor_db=noise_floor,
            channel=str(channel),
            device_id=from_id,
            metadata=json.dumps(meta),
        )
        self.logger.log(detection)
        self._total += 1

    def _handle_traceroute(self, decoded, from_id, from_name, to_name,
                           channel, hops, snr, power_db, noise_floor):
        route = decoded.get("traceroute", {})
        route_list = route.get("route", [])
        if not self._should_log(from_id, "TRACEROUTE_APP"):
            return

        names = [self._node_name(r) for r in route_list]
        meta = {
            "node_id": from_id,
            "node_name": from_name,
            "to": to_name,
            "route": names,
            "hops": hops,
            "snr": snr,
        }

        detection = SignalDetection.create(
            signal_type="Meshtastic-Node",
            frequency_hz=self._freq(),
            power_db=power_db,
            noise_floor_db=noise_floor,
            channel=str(channel),
            device_id=from_id,
            metadata=json.dumps(meta),
        )
        self.logger.log(detection)
        self._total += 1

    def _handle_neighborinfo(self, decoded, from_id, from_name,
                             channel, hops, snr, power_db, noise_floor):
        neighbors = decoded.get("neighborinfo", {}).get("neighbors", [])
        if not self._should_log(from_id, "NEIGHBORINFO_APP"):
            return

        nb_list = []
        for nb in neighbors:
            nb_name = self._node_name(nb.get("nodeId"))
            nb_snr = nb.get("snr")
            nb_list.append({"name": nb_name, "snr": nb_snr})

        meta = {
            "node_id": from_id,
            "node_name": from_name,
            "neighbors": nb_list,
            "hops": hops,
            "snr": snr,
        }

        detection = SignalDetection.create(
            signal_type="Meshtastic-Node",
            frequency_hz=self._freq(),
            power_db=power_db,
            noise_floor_db=noise_floor,
            channel=str(channel),
            device_id=from_id,
            metadata=json.dumps(meta),
        )
        self.logger.log(detection)
        self._total += 1

    def _handle_encrypted(self, from_id, from_name, to_name,
                          channel, hops, snr, power_db, noise_floor):
        """Log encrypted packet as node activity (can't decrypt, but know who transmitted)."""
        if not self._should_log(from_id, "ENCRYPTED"):
            return

        meta = {
            "node_id": from_id,
            "node_name": from_name,
            "to": to_name,
            "encrypted": True,
            "hops": hops,
            "snr": snr,
        }

        detection = SignalDetection.create(
            signal_type="Meshtastic-Node",
            frequency_hz=self._freq(),
            power_db=power_db,
            noise_floor_db=noise_floor,
            channel=str(channel),
            device_id=from_id,
            metadata=json.dumps(meta),
        )
        self.logger.log(detection)
        self._total += 1

    def shutdown(self):
        pass

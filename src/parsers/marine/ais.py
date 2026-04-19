"""
AIS NMEA Parser

Processes NMEA sentences (from rtl_ais or other sources) to decode vessel
information. Maintains a vessel database and logs position updates.
"""

import json
import time
from datetime import datetime
from typing import Dict

from parsers.base import BaseParser
from dsp.ais import Vessel, decode_ais_message, AIS_MESSAGE_TYPES
from utils.logger import SignalDetection

AIS_CENTER_FREQ = 162.0e6


class AISParser(BaseParser):
    """
    Parses AIS NMEA sentences and maintains a vessel database.

    Receives NMEA strings (not IQ samples) and decodes vessel position,
    identity, and voyage data. Logs updates as SignalDetections.
    """

    def __init__(self, logger, holdover_seconds=5.0, rssi_monitor=None):
        """
        rssi_monitor: optional AISChannelRSSI (requires a secondary
            RTL-SDR). When provided, each decoded vessel detection is
            logged with `power_db` pulled from the monitor's most
            recent in-window sample. When omitted, power_db stays 0
            and calibration stays dormant for AIS — matching
            pre-monitor behaviour exactly.
        """
        super().__init__(logger)
        self.holdover_seconds = holdover_seconds
        self.vessel_db: Dict[str, Vessel] = {}
        self._last_logged: Dict[str, int] = {}  # mmsi -> last logged message_count
        self._total_detections = 0
        self.rssi_monitor = rssi_monitor

    @property
    def total_detections(self):
        return self._total_detections

    def handle_frame(self, nmea_sentence):
        """Process an NMEA sentence string."""
        vessel = decode_ais_message(nmea_sentence, self.vessel_db)
        if vessel is None:
            return

        if vessel.latitude is None or vessel.longitude is None:
            return

        last_count = self._last_logged.get(vessel.mmsi, 0)
        if vessel.message_count > last_count:
            self._last_logged[vessel.mmsi] = vessel.message_count
            self._total_detections += 1

            # AIS "not available" sentinels: heading=511, cog=360.0, sog=102.3
            hdg = vessel.heading if vessel.heading is not None and vessel.heading < 511 else None
            cog = vessel.cog if vessel.cog is not None and vessel.cog < 360.0 else None
            sog = vessel.sog if vessel.sog is not None and vessel.sog < 102.3 else None
            meta = {
                "mmsi": vessel.mmsi,
                "name": vessel.name or "",
                "callsign": vessel.callsign or "",
                "imo": vessel.imo or "",
                "ship_type": vessel.ship_type_name,
                "nav_status": vessel.nav_status_name,
                "speed_kn": sog,
                "course": cog,
                "heading": hdg,
                "rot": vessel.rot,
                "destination": vessel.destination or "",
                "eta": vessel.eta or "",
                "draught": vessel.draught if vessel.draught and vessel.draught > 0 else None,
            }

            # Attach RSSI from the parallel sampler if one's running.
            # rtl_ais doesn't tell us which channel decoded this MMSI,
            # so the monitor returns max(AIS1, AIS2) — a close enough
            # proxy for calibration purposes.
            power_db = 0.0
            noise_db = 0.0
            if self.rssi_monitor is not None:
                p = self.rssi_monitor.recent_power()
                if p is not None:
                    power_db = float(p)
                    # Nominal noise floor for the band; calibration
                    # consumes power_db directly, SNR just needs to be
                    # positive enough to pass the logger's min_snr_db
                    # filter (which is 0 for this scanner anyway).
                    noise_db = -60.0
                    meta["rssi_dbfs"] = power_db

            detection = SignalDetection.create(
                signal_type="AIS",
                frequency_hz=AIS_CENTER_FREQ,
                power_db=power_db,
                noise_floor_db=noise_db,
                channel=vessel.mmsi,
                latitude=vessel.latitude,
                longitude=vessel.longitude,
                metadata=json.dumps(meta),
            )
            self.logger.log(detection)

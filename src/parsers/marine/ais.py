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

    def __init__(self, logger, holdover_seconds=5.0):
        super().__init__(logger)
        self.holdover_seconds = holdover_seconds
        self.vessel_db: Dict[str, Vessel] = {}
        self._last_logged: Dict[str, int] = {}  # mmsi -> last logged message_count
        self._total_detections = 0

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

            detection = SignalDetection.create(
                signal_type="AIS",
                frequency_hz=AIS_CENTER_FREQ,
                power_db=0,
                noise_floor_db=0,
                channel=vessel.mmsi,
                latitude=vessel.latitude,
                longitude=vessel.longitude,
                metadata=json.dumps(meta),
            )
            self.logger.log(detection)

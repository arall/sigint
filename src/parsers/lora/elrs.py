"""
ELRS / Crossfire Drone Control Link Parser

Detects FPV drone control transmissions at 868/915 MHz by analyzing
burst timing patterns for FHSS periodicity. Catches drones that don't
broadcast RemoteID.

Plugs into the same capture source as the LoRa energy parser — both
analyze the same IQ stream from the 868 MHz band.
"""

import json
import time
from datetime import datetime

from parsers.base import BaseParser
from dsp.elrs import detect_fhss_bursts, analyze_hop_periodicity
from utils.logger import SignalDetection

# Dedup: don't log same drone control link more than once per N seconds
DEDUP_WINDOW = 10


class ELRSParser(BaseParser):
    """
    Detects ELRS and Crossfire drone control links from IQ samples.

    Analyzes burst timing for periodic FHSS hopping patterns that
    distinguish drone control from regular LoRa traffic.
    """

    def __init__(self, logger, sample_rate, center_freq, min_snr_db=6.0):
        super().__init__(logger)
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.min_snr_db = min_snr_db

        self._last_logged = 0
        self._detection_count = 0
        self._last_result = None

    @property
    def detection_count(self):
        return self._detection_count

    @property
    def last_detection_result(self):
        return self._last_result

    def handle_frame(self, samples):
        """Process IQ samples for drone control link detection."""
        burst_times, noise_db, peak_power_db = detect_fhss_bursts(
            samples, self.sample_rate, self.min_snr_db)

        self._last_result = {
            'num_bursts': len(burst_times),
            'noise_db': noise_db,
            'peak_power_db': peak_power_db,
        }

        if len(burst_times) < 10:
            return

        analysis = analyze_hop_periodicity(burst_times)
        self._last_result.update(analysis)

        if not analysis['detected']:
            return

        now = time.time()
        if (now - self._last_logged) < DEDUP_WINDOW:
            return

        self._last_logged = now
        self._detection_count += 1

        snr = peak_power_db - noise_db

        print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
              f"DRONE CTRL: {analysis['protocol']} | "
              f"{analysis['hop_rate_hz']} Hz | "
              f"SNR: {snr:.1f} dB | "
              f"Confidence: {analysis['confidence']:.0%}")

        detection = SignalDetection.create(
            signal_type="DroneCtrl",
            frequency_hz=self.center_freq,
            power_db=peak_power_db,
            noise_floor_db=noise_db,
            channel=f"{self.center_freq/1e6:.1f}MHz",
            metadata=json.dumps({
                "protocol": analysis['protocol'],
                "hop_rate_hz": analysis['hop_rate_hz'],
                "confidence": round(analysis['confidence'], 2),
                "num_bursts": analysis['num_bursts'],
                "details": analysis['details'],
            }),
        )
        self.logger.log(detection)

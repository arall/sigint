"""
Drone Video Link Parser — detects wideband OFDM video downlinks.

Consumes IQ samples from HackRF capture and detects drone video
transmissions (DJI O4, OcuSync, etc.) by their OFDM spectral
signature, bandwidth, and duty cycle.

Distinguishes drone video links from standard WiFi traffic.
"""

import json
import time
from datetime import datetime

from parsers.base import BaseParser
from dsp.drone_video import detect_ofdm_bursts, classify_bursts
from utils.logger import SignalDetection

# Dedup: one detection per window
DEDUP_WINDOW = 5


class DroneVideoLinkParser(BaseParser):
    """Detects drone video downlink OFDM signals from IQ samples."""

    def __init__(self, logger, sample_rate, center_freq,
                 min_snr_db=8.0, min_bw_hz=5e6):
        super().__init__(logger)
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.min_snr_db = min_snr_db
        self.min_bw_hz = min_bw_hz

        self._last_logged = 0
        self._detection_count = 0
        self._frame_count = 0
        self._last_result = None

    @property
    def detection_count(self):
        return self._detection_count

    @property
    def last_result(self):
        return self._last_result

    def handle_frame(self, samples):
        """Process IQ samples for drone video link detection."""
        self._frame_count += 1

        bursts, noise_db = detect_ofdm_bursts(
            samples, self.sample_rate,
            min_bw_hz=self.min_bw_hz,
            min_snr_db=self.min_snr_db,
        )

        result = classify_bursts(bursts, self.center_freq, self.sample_rate)
        self._last_result = result

        if not result["detected"]:
            return

        now = time.time()
        if (now - self._last_logged) < DEDUP_WINDOW:
            return

        self._last_logged = now
        self._detection_count += 1

        bw_mhz = result["bandwidth_hz"] / 1e6
        freq_mhz = result["center_freq_hz"] / 1e6
        wifi_tag = " [WiFi?]" if result["is_wifi"] else ""

        print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
              f"DRONE VIDEO: {freq_mhz:.1f} MHz | "
              f"BW: {bw_mhz:.1f} MHz | "
              f"SNR: {result['snr_db']:.1f} dB | "
              f"Duty: {result['duty_cycle']:.0%} | "
              f"Conf: {result['confidence']:.0%}{wifi_tag}")

        detection = SignalDetection.create(
            signal_type="DroneVideo",
            frequency_hz=result["center_freq_hz"],
            power_db=result["power_db"],
            noise_floor_db=result["noise_db"],
            channel=f"{freq_mhz:.1f}MHz",
            metadata=json.dumps({
                "bandwidth_mhz": round(bw_mhz, 1),
                "duty_cycle": result["duty_cycle"],
                "confidence": result["confidence"],
                "flatness": result["flatness"],
                "is_wifi": result["is_wifi"],
                "n_bursts": result["n_bursts"],
            }),
        )
        self.logger.log(detection)

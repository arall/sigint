"""
LTE Uplink Power Density Parser

Processes IQ sample blocks to measure LTE uplink band power density.
Detects aggregate phone activity as power rises above a calibrated baseline.
"""

import json
import time
from collections import defaultdict

import numpy as np

from parsers.base import BaseParser
from dsp.lte import measure_power_spectrum, compute_band_summary
from utils.logger import SignalDetection


class LTEPowerParser(BaseParser):
    """
    Measures LTE uplink power density and detects activity above baseline.

    Unlike GSM (distinct bursts per device), LTE uses OFDMA where devices
    share bandwidth. Individual devices can't be isolated — we detect
    aggregate activity as elevated power density.
    """

    def __init__(self, logger, sample_rate, band_name="Band-8",
                 activity_threshold_db=3.0, holdover_seconds=3.0,
                 center_freq=0):
        super().__init__(logger)
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.band_name = band_name
        self.activity_threshold_db = activity_threshold_db
        self.holdover_seconds = holdover_seconds

        self._baseline = None  # Calibrated baseline power
        self._calibration_samples = []
        self._calibration_count = 5
        self._last_logged = 0
        self._total_detections = 0
        self._history = []
        self._last_result = None

    @property
    def last_detection_result(self):
        return self._last_result

    @property
    def baseline(self):
        return self._baseline

    @property
    def total_detections(self):
        return self._total_detections

    @property
    def history(self):
        return list(self._history)

    def calibrate(self, samples):
        """Feed calibration samples to establish baseline. Returns True when done."""
        result = measure_power_spectrum(samples, self.sample_rate)
        self._calibration_samples.append(result['overall_power_db'])

        if len(self._calibration_samples) >= self._calibration_count:
            self._baseline = round(np.mean(self._calibration_samples), 2)
            return True
        return False

    def handle_frame(self, samples, center_freq=None):
        """Process IQ samples for LTE power density measurement."""
        if center_freq is not None:
            self.center_freq = center_freq
        result = measure_power_spectrum(samples, self.sample_rate)
        self._last_result = result

        if self._baseline is None:
            return  # Not calibrated yet

        delta = result['overall_power_db'] - self._baseline
        is_active = delta >= self.activity_threshold_db

        self._history.append({
            'time': time.time(),
            'power_db': result['overall_power_db'],
            'delta_db': round(delta, 2),
            'peak_db': result['peak_power_db'],
            'active': is_active,
        })

        if is_active:
            now = time.time()
            if (now - self._last_logged) > self.holdover_seconds:
                self._last_logged = now
                self._total_detections += 1

                # Find strongest segment
                strongest_seg = max(result['segments'], key=lambda s: s['power_db'])

                metadata = json.dumps({
                    'band': self.band_name,
                    'delta_above_baseline_db': round(delta, 1),
                    'peak_power_db': result['peak_power_db'],
                    'baseline_db': self._baseline,
                })

                detection = SignalDetection.create(
                    signal_type=f"LTE-UPLINK-{self.band_name}",
                    frequency_hz=self.center_freq + strongest_seg['freq_offset'],
                    power_db=result['overall_power_db'],
                    noise_floor_db=self._baseline,
                    channel=self.band_name,
                    metadata=metadata,
                )
                self.logger.log(detection)

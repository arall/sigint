"""
GSM Uplink Burst Parser

Processes IQ sample blocks to detect GSM TDMA uplink bursts from handset
transmissions. Tracks burst activity per channel and estimates active device
count.
"""

import json
import time
from collections import defaultdict
from datetime import datetime

import numpy as np

from parsers.base import BaseParser
from dsp.gsm import detect_uplink_bursts, estimate_active_devices, GSM_CHANNEL_SPACING
from utils.logger import SignalDetection


class GSMBurstParser(BaseParser):
    """
    Detects GSM uplink bursts in IQ sample blocks.

    Tracks burst activity per 200 kHz channel and estimates the number
    of active handsets from TDMA timing patterns.
    """

    def __init__(self, logger, sample_rate, center_freq, band_name="GSM-900",
                 min_snr_db=5.0, holdover_seconds=3.0):
        super().__init__(logger)
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.band_name = band_name
        self.min_snr_db = min_snr_db
        self.holdover_seconds = holdover_seconds

        self._channel_activity = defaultdict(lambda: {
            'burst_count': 0,
            'peak_power_db': -100,
            'last_seen': None,
            'estimated_devices': 0,
        })
        self._last_logged = {}  # freq -> timestamp
        self._total_detections = 0
        self._last_result = None
        self._num_samples = None

    @property
    def last_detection_result(self):
        return self._last_result

    @property
    def channel_activity(self):
        return dict(self._channel_activity)

    @property
    def total_detections(self):
        return self._total_detections

    def handle_frame(self, samples):
        """Process IQ samples for GSM uplink bursts."""
        self._num_samples = len(samples)
        bursts, noise_db = detect_uplink_bursts(samples, self.sample_rate)

        self._last_result = {
            'bursts': bursts,
            'noise_db': noise_db,
            'burst_count': len(bursts),
        }

        if not bursts:
            return

        now = time.time()

        # Group bursts by 200 kHz GSM channel
        channel_bursts = defaultdict(list)
        for burst in bursts:
            freq_offset = (burst['start_sample'] / self._num_samples - 0.5) * self.sample_rate
            ch_freq = self.center_freq + freq_offset
            ch_freq = round(ch_freq / GSM_CHANNEL_SPACING) * GSM_CHANNEL_SPACING
            channel_bursts[ch_freq].append(burst)

        for ch_freq, ch_bursts in channel_bursts.items():
            peak_power = max(b['power_db'] for b in ch_bursts)
            avg_snr = np.mean([b['snr_db'] for b in ch_bursts])
            est_devices = estimate_active_devices(ch_bursts, self.sample_rate)

            # Update activity tracker
            activity = self._channel_activity[ch_freq]
            activity['burst_count'] += len(ch_bursts)
            activity['peak_power_db'] = max(activity['peak_power_db'], peak_power)
            activity['last_seen'] = datetime.now()
            activity['estimated_devices'] = max(activity['estimated_devices'], est_devices)

            # Log with holdover
            if ch_freq not in self._last_logged or (now - self._last_logged[ch_freq]) > self.holdover_seconds:
                self._last_logged[ch_freq] = now
                self._total_detections += 1

                metadata = json.dumps({
                    'burst_count': len(ch_bursts),
                    'estimated_devices': est_devices,
                    'avg_burst_duration_us': round(np.mean([b['duration_us'] for b in ch_bursts]), 1),
                })

                detection = SignalDetection.create(
                    signal_type=f"GSM-UPLINK-{self.band_name}",
                    frequency_hz=ch_freq,
                    power_db=peak_power,
                    noise_floor_db=noise_db,
                    channel=f"{ch_freq / 1e6:.2f}MHz",
                    metadata=metadata,
                )
                self.logger.log(detection)

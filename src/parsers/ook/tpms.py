"""
TPMS OOK/Manchester Parser

Processes IQ sample blocks to detect and decode TPMS (Tire Pressure
Monitoring System) transmissions. Extracts sensor IDs for vehicle tracking.

The pure DSP functions (detect_tpms_signal, manchester_decode, bits_to_hex)
are imported from scanners.tpms where they are defined. This parser adds
stateful transmission tracking on top.
"""

import json
import time
from collections import defaultdict

from parsers.base import BaseParser
from utils.logger import SignalDetection


class TPMSParser(BaseParser):
    """
    Parses IQ samples for TPMS signals.

    Implements per-transmission holdover: accumulates packets during
    a transmission, then logs when the transmission ends.
    """

    DETECTION_SNR_DB = 10.0
    TX_HOLDOVER_TIME = 0.3  # 300ms — TPMS transmissions are brief

    def __init__(self, logger, sample_rate, center_freq, min_snr_db=8.0):
        super().__init__(logger)
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.min_snr_db = min_snr_db

        from dsp.tpms import detect_tpms_signal
        self._detect_tpms = detect_tpms_signal

        # Per-transmission state
        self._last_result = None  # Last raw detection result (for display reuse)
        self._detection_count = 0
        self._last_detection_time = None
        self._tx_active = False
        self._tx_start = None
        self._tx_peak_snr = 0.0
        self._tx_packets = []

        # Track unique sensor IDs
        self._sensor_ids = defaultdict(int)

    @property
    def detection_count(self):
        return self._detection_count

    @property
    def sensor_ids(self):
        return dict(self._sensor_ids)

    @property
    def last_detection_result(self):
        """Last raw detection result dict (for display reuse, avoids recomputation)."""
        return self._last_result

    def handle_frame(self, samples):
        """Process an IQ sample block for TPMS signals."""
        # TPMS uses 1 MHz sample rate but shared capture may use 2 MHz.
        # Decimate if needed.
        if self.sample_rate > 1.5e6:
            # Simple 2x decimation for 2 MHz -> 1 MHz
            from scipy import signal as scipy_signal
            samples = scipy_signal.decimate(samples, 2, ftype='fir')
            effective_rate = self.sample_rate / 2
        else:
            effective_rate = self.sample_rate

        now = time.time()
        result = self._detect_tpms(
            samples, effective_rate, self.DETECTION_SNR_DB)
        self._last_result = result

        snr = result['snr_db']

        if result['detected']:
            self._tx_peak_snr = max(self._tx_peak_snr, snr)
            self._last_detection_time = now

            if result['packets']:
                self._tx_packets.extend(result['packets'])

            for sid in result['sensor_ids']:
                self._sensor_ids[sid] += 1

            if not self._tx_active:
                self._tx_active = True
                self._tx_start = now
                self._tx_peak_snr = snr

        elif self._tx_active:
            time_since_last = (now - self._last_detection_time
                               if self._last_detection_time else 999)

            if time_since_last > self.TX_HOLDOVER_TIME:
                duration = now - self._tx_start if self._tx_start else 0

                if self._tx_peak_snr >= self.min_snr_db and self._tx_packets:
                    tx_sensor_ids = []
                    for pkt in self._tx_packets:
                        if 'hex' in pkt and len(pkt['hex']) >= 8:
                            tx_sensor_ids.append(pkt['hex'][:8])
                    tx_sensor_ids = list(set(tx_sensor_ids))

                    detection = SignalDetection.create(
                        signal_type="tpms",
                        frequency_hz=self.center_freq,
                        power_db=result['peak_power_db'],
                        noise_floor_db=result['noise_floor_db'],
                        metadata=json.dumps({
                            "duration_s": round(duration, 3),
                            "sensor_ids": tx_sensor_ids,
                            "num_packets": len(self._tx_packets),
                        })
                    )
                    self.logger.log(detection)
                    self._detection_count += 1

                # Reset
                self._tx_active = False
                self._tx_start = None
                self._tx_peak_snr = 0.0
                self._tx_packets = []

    def get_display_state(self):
        """Return state needed for display rendering."""
        return {
            'tx_active': self._tx_active,
            'detection_count': self._detection_count,
            'sensor_ids': dict(self._sensor_ids),
        }

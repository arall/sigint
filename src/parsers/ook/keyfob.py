"""
Keyfob OOK/FSK Parser

Processes IQ sample blocks to detect and fingerprint keyfob/garage door
transmissions. Handles both OOK (PT2262, EV1527, KeeLoq) and FSK
(car keyfobs) modulation.

The pure DSP functions (detect_ook_signal, detect_fsk_signal,
fingerprint_protocol, etc.) are imported from scanners.keyfob where
they are defined. This parser adds the stateful transmission tracking
(holdover, accumulation, fingerprinting on TX end) on top.
"""

import json
import time

import numpy as np

from parsers.base import BaseParser
from utils.logger import SignalDetection


class KeyfobParser(BaseParser):
    """
    Parses IQ samples for keyfob/garage door OOK and FSK signals.

    Implements per-transmission holdover state machine: accumulates
    burst data during a transmission, then fingerprints and logs when
    the transmission ends.
    """

    DETECTION_SNR_DB = 8.0
    TX_HOLDOVER_TIME = 0.5  # seconds after last detection before TX ends

    def __init__(self, logger, sample_rate, center_freq, min_snr_db=10.0):
        super().__init__(logger)
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.min_snr_db = min_snr_db

        from dsp.ook import (
            detect_ook_signal, detect_fsk_signal,
            fingerprint_protocol, fingerprint_fsk_car,
            classify_device, TransmitterTracker,
        )
        self._detect_ook = detect_ook_signal
        self._detect_fsk = detect_fsk_signal
        self._fingerprint_protocol = fingerprint_protocol
        self._fingerprint_fsk_car = fingerprint_fsk_car
        self._classify_device = classify_device
        self.tracker = TransmitterTracker()

        # RF fingerprinting (optional — extract hardware-level transmitter ID)
        try:
            from dsp.rf_fingerprint import extract_from_ook_burst, fingerprint_hash
            self._rf_extract = extract_from_ook_burst
            self._rf_hash = fingerprint_hash
        except ImportError:
            self._rf_extract = None
            self._rf_hash = None

        # Per-transmission state
        self._last_result = None  # Last raw detection result (for display reuse)
        self._detection_count = 0
        self._last_detection_time = None
        self._tx_active = False
        self._tx_start = None
        self._tx_peak_snr = 0.0
        self._tx_peak_power = -100.0
        self._tx_bursts = []
        self._tx_iq_samples = []
        self._last_fingerprint = None

    @property
    def detection_count(self):
        return self._detection_count

    @property
    def last_fingerprint(self):
        return self._last_fingerprint

    @property
    def last_detection_result(self):
        """Last raw detection result dict (for display reuse, avoids recomputation)."""
        return self._last_result

    def handle_frame(self, samples):
        """Process an IQ sample block for keyfob signals."""
        now = time.time()
        result = self._detect_ook(
            samples, self.sample_rate, self.DETECTION_SNR_DB)
        self._last_result = result

        noise_floor_db = result['noise_floor_db']
        snr = result['snr_db']

        # Also check for strong signal (FSK appears as 1-2 big bursts to OOK)
        is_signal = result['detected'] or snr >= self.DETECTION_SNR_DB

        if is_signal:
            self._tx_peak_snr = max(self._tx_peak_snr, snr)
            self._tx_peak_power = max(self._tx_peak_power, result['peak_power_db'])
            self._last_detection_time = now

            self._tx_iq_samples.append(samples.copy())

            if len(result['bursts']) > len(self._tx_bursts):
                self._tx_bursts = result['bursts']

            if not self._tx_active:
                self._tx_active = True
                self._tx_start = now
                self._tx_peak_snr = snr
                self._tx_peak_power = result['peak_power_db']
                self._tx_bursts = result['bursts']
                self._tx_iq_samples = [samples.copy()]

        elif self._tx_active:
            time_since_last = (now - self._last_detection_time
                               if self._last_detection_time else 999)

            if time_since_last > self.TX_HOLDOVER_TIME:
                duration = now - self._tx_start if self._tx_start else 0

                if self._tx_peak_snr >= self.min_snr_db:
                    fp = self._fingerprint_transmission()
                    fp = self.tracker.track(fp)
                    self._last_fingerprint = fp

                    device_result = self._classify_device(
                        fp.get('protocol', 'Unknown'),
                        fp.get('code_type', 'unknown'),
                        self.center_freq, fp)
                    device_type = device_result[0] if device_result else "Unknown"

                    # RF fingerprint extraction
                    rf_fp_hash = ""
                    if (self._rf_extract and self._tx_iq_samples
                            and self._tx_bursts):
                        try:
                            combined_iq = np.concatenate(self._tx_iq_samples)
                            rf_fp = self._rf_extract(
                                combined_iq, self.sample_rate,
                                self._tx_bursts[0])
                            if rf_fp:
                                rf_fp_hash = self._rf_hash(rf_fp)
                        except Exception:
                            pass

                    meta = {
                        "duration_s": round(duration, 2),
                        "num_bursts": len(self._tx_bursts),
                        "protocol": fp['protocol'],
                        "code_type": fp['code_type'],
                        "bit_count": fp['bit_count'],
                        "data_hex": fp.get('data_hex', ''),
                        "confidence": fp['confidence'],
                        "device_type": device_type,
                        "modulation": fp.get('modulation', 'OOK'),
                        "deviation_khz": fp.get('deviation_khz', 0),
                        "datarate_hz": fp.get('datarate_hz', 0),
                        "repeat_count": fp.get('repeat_count', 0),
                    }
                    if rf_fp_hash:
                        meta["rf_fingerprint"] = rf_fp_hash

                    detection = SignalDetection.create(
                        signal_type="keyfob",
                        frequency_hz=self.center_freq,
                        power_db=self._tx_peak_power,
                        noise_floor_db=noise_floor_db,
                        metadata=json.dumps(meta),
                    )
                    self.logger.log(detection)
                    self._detection_count += 1

                # Reset
                self._tx_active = False
                self._tx_start = None
                self._tx_peak_snr = 0.0
                self._tx_peak_power = -100.0
                self._tx_bursts = []
                self._tx_iq_samples = []

    def _fingerprint_transmission(self):
        """Fingerprint a completed transmission — try OOK first, then FSK."""
        if len(self._tx_bursts) >= 10:
            fp = self._fingerprint_protocol(self._tx_bursts)
            if fp['protocol'] != 'Unknown':
                fp['modulation'] = 'OOK'
                return fp

        if self._tx_iq_samples:
            combined_iq = np.concatenate(self._tx_iq_samples)
            fsk_result = self._detect_fsk(combined_iq, self.sample_rate)
            if fsk_result:
                fp = self._fingerprint_fsk_car(fsk_result, self.center_freq)
                return fp

        if self._tx_bursts:
            fp = self._fingerprint_protocol(self._tx_bursts)
            fp['modulation'] = 'OOK'
            return fp

        return {
            'protocol': 'Unknown',
            'code_type': 'unknown',
            'bit_count': 0,
            'data_hex': '',
            'confidence': 'low',
            'details': 'Signal detected but could not fingerprint',
        }

    def get_display_state(self):
        """Return state needed for display rendering."""
        return {
            'tx_active': self._tx_active,
            'detection_count': self._detection_count,
            'known_transmitters': self.tracker.known_transmitters,
            'last_fingerprint': self._last_fingerprint,
        }

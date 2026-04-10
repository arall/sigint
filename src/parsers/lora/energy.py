"""
LoRa/Meshtastic Energy Detection Parser

Detects LoRa chirp spread spectrum transmissions by analyzing per-channel
energy in IQ sample blocks. Estimates bandwidth and chirp confidence.

LoRa uses CSS — we can't decode payloads with an RTL-SDR, but we can
detect the energy signature: wideband chirps sweeping 125-500 kHz.
"""

import json
import time
from datetime import datetime

import numpy as np
from scipy import signal as scipy_signal

from parsers.base import BaseParser
from utils.logger import SignalDetection

# Common LoRa bandwidths (kHz)
LORA_BANDWIDTHS = [125, 250, 500]


class LoRaEnergyParser(BaseParser):
    """
    Detects LoRa transmissions via FFT-based energy detection per channel.

    Configured with a set of channels to monitor. Each IQ block is analyzed
    for energy above threshold in each channel's bandwidth.
    """

    COOLDOWN = 2.0  # seconds between logging same channel

    def __init__(self, logger, sample_rate, center_freq, channels,
                 min_snr_db=8.0, min_chirp_confidence=0.0, region="EU"):
        super().__init__(logger)
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.channels = channels  # dict: name -> freq_hz
        self.min_snr_db = min_snr_db
        self.min_chirp_confidence = min_chirp_confidence
        self.region = region

        self._cooldown = {}  # channel -> last_log_time
        self._stats = {
            "total_detections": 0,
            "channels_active": set(),
        }

    @property
    def stats(self):
        return dict(self._stats)

    @property
    def detection_count(self):
        return self._stats["total_detections"]

    def handle_frame(self, samples):
        """Process an IQ sample block for LoRa energy."""
        detections = self._detect_bursts(samples)
        now = time.time()

        for det in detections:
            ch = det["channel"]

            if ch in self._cooldown and now - self._cooldown[ch] < self.COOLDOWN:
                continue

            chirp_score = self._estimate_chirp_rate(samples, det["frequency"])

            # Skip detections below chirp confidence threshold (filters noise)
            if chirp_score < self.min_chirp_confidence:
                continue

            signal_type = "LoRa"
            if chirp_score > 0.5:
                signal_type = "LoRa (chirp)"

            meta = {
                "bandwidth_khz": det["bandwidth_khz"],
                "chirp_confidence": round(chirp_score, 2),
                "region": self.region,
            }

            detection = SignalDetection.create(
                signal_type="lora",
                frequency_hz=det["frequency"],
                power_db=det["power_db"],
                noise_floor_db=det["noise_floor_db"],
                channel=ch,
                metadata=json.dumps(meta),
            )
            self.logger.log(detection)

            self._cooldown[ch] = now
            self._stats["total_detections"] += 1
            self._stats["channels_active"].add(ch)

            print(
                f"  [{datetime.now().strftime('%H:%M:%S')}] "
                f"{signal_type} on {ch} MHz | "
                f"SNR: {det['snr_db']:.1f} dB | "
                f"Power: {det['power_db']:.1f} dB | "
                f"BW: {det['bandwidth_khz']} kHz | "
                f"Chirp: {chirp_score:.0%}"
            )

    def _detect_bursts(self, samples):
        """Detect LoRa chirp bursts in IQ samples."""
        detections = []

        n_fft = 4096
        freqs = np.fft.fftfreq(n_fft, 1 / self.sample_rate)

        n_segments = len(samples) // n_fft
        if n_segments < 1:
            return detections

        psd_accum = np.zeros(n_fft)
        for i in range(n_segments):
            segment = samples[i * n_fft:(i + 1) * n_fft]
            window = np.hanning(n_fft)
            fft = np.fft.fft(segment * window)
            psd_accum += np.abs(fft) ** 2
        psd = psd_accum / n_segments

        psd_db = 10 * np.log10(psd + 1e-20)
        noise_floor_db = np.percentile(psd_db, 30)

        for ch_name, ch_freq in self.channels.items():
            offset = ch_freq - self.center_freq

            if abs(offset) > self.sample_rate / 2 - 150e3:
                continue

            for bw_khz in LORA_BANDWIDTHS:
                bw_hz = bw_khz * 1e3
                mask = (freqs > offset - bw_hz / 2) & (freqs < offset + bw_hz / 2)
                if np.sum(mask) < 2:
                    continue

                ch_power_db = 10 * np.log10(np.mean(psd[mask]) + 1e-20)
                snr = ch_power_db - noise_floor_db

                if snr >= self.min_snr_db:
                    detections.append({
                        "channel": ch_name,
                        "frequency": ch_freq,
                        "power_db": ch_power_db,
                        "noise_floor_db": noise_floor_db,
                        "snr_db": snr,
                        "bandwidth_khz": bw_khz,
                    })
                    break  # Only report widest matching BW per channel

        return detections

    def _estimate_chirp_rate(self, samples, ch_freq):
        """Estimate if the signal looks like a LoRa chirp (frequency sweep)."""
        offset = ch_freq - self.center_freq
        t = np.arange(len(samples)) / self.sample_rate
        baseband = samples * np.exp(-2j * np.pi * offset * t)

        nyq = self.sample_rate / 2
        cutoff = 150e3 / nyq
        if cutoff >= 1.0:
            cutoff = 0.99
        b, a = scipy_signal.butter(4, cutoff, btype='low')
        filtered = scipy_signal.lfilter(b, a, baseband)

        nperseg = 256
        noverlap = 192
        f, t_spec, Sxx = scipy_signal.spectrogram(
            filtered, fs=self.sample_rate,
            nperseg=nperseg, noverlap=noverlap,
            return_onesided=False,
        )

        if Sxx.shape[1] < 3:
            return 0.0

        peak_bins = np.argmax(np.abs(Sxx), axis=0)
        diffs = np.diff(peak_bins.astype(float))
        if len(diffs) < 2:
            return 0.0

        sign_consistency = abs(np.mean(np.sign(diffs)))
        return sign_consistency

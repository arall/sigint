"""
RTL-SDR Sweep Capture Source — tunes across a frequency range and emits
IQ sample blocks with their center frequency to registered parsers.

Used for scanners that need to cover a band wider than the SDR's
instantaneous bandwidth (e.g., GSM 890-915 MHz, LTE 832-915 MHz).

Emits (samples, center_freq) tuples.
"""

import time

from capture.base import BaseCaptureSource


class RTLSDRSweepCaptureSource(BaseCaptureSource):
    """Sweeps across a frequency range, emitting (samples, center_freq) tuples."""

    def __init__(
        self,
        band_start,
        band_end,
        sample_rate=2.0e6,
        gain=40,
        device_index=0,
        num_samples=256 * 1024,
        overlap=0.8,
    ):
        super().__init__()
        self.band_start = band_start
        self.band_end = band_end
        self.sample_rate = sample_rate
        self.gain = gain
        self.device_index = device_index
        self.num_samples = num_samples
        self.overlap = overlap
        self._sdr = None

        # Compute sweep frequencies
        step_size = sample_rate * overlap
        self.frequencies = []
        freq = band_start + step_size / 2
        while freq < band_end:
            self.frequencies.append(freq)
            freq += step_size

    def start(self):
        """Open SDR and sweep continuously. Blocks until stop()."""
        import utils.loader  # noqa: F401
        from rtlsdr import RtlSdr

        self._sdr = RtlSdr(self.device_index)
        try:
            self._sdr.sample_rate = self.sample_rate
            self._sdr.gain = self.gain
            self._sdr.center_freq = self.frequencies[0]

            print(f"[*] RTL-SDR sweep: {self.band_start/1e6:.1f}-{self.band_end/1e6:.1f} MHz, "
                  f"{len(self.frequencies)} steps, "
                  f"{self._sdr.sample_rate/1e6:.1f} MS/s, gain {self._sdr.gain} dB")

            time.sleep(1)  # Let AGC settle

            while not self._stop_event.is_set():
                for freq in self.frequencies:
                    if self._stop_event.is_set():
                        break
                    self._sdr.center_freq = freq
                    time.sleep(0.05)  # Let PLL settle
                    samples = self._sdr.read_samples(self.num_samples)
                    self._emit((samples, freq))

        finally:
            self._cleanup()

    def stop(self):
        """Signal the capture to stop."""
        self._stop_event.set()

    def _cleanup(self):
        if self._sdr:
            try:
                self._sdr.close()
            except Exception:
                pass
            self._sdr = None

"""
Channelizer — extracts narrowband channels from a wideband IQ capture.

Sits between a wideband capture source (e.g., HackRF at 20 MHz) and
individual narrowband parsers (e.g., keyfob at 433.92 MHz, PMR at 446 MHz).

For each channel definition, it:
1. Frequency-shifts via pre-computed oscillator table (fast)
2. Decimates with a short FIR anti-alias filter at the decimated rate
3. Emits the narrowband IQ to registered parser callbacks
"""

import numpy as np
from scipy import signal as scipy_signal


class Channel:
    """A narrowband channel extracted from wideband IQ."""

    def __init__(self, name, freq_hz, bandwidth_hz, output_sample_rate,
                 center_freq, capture_sample_rate, callback):
        self.name = name
        self.freq_hz = freq_hz
        self.bandwidth_hz = bandwidth_hz
        self.output_sample_rate = output_sample_rate
        self.callback = callback

        # Compute frequency offset from capture center
        self.offset_hz = freq_hz - center_freq

        # Compute decimation factor
        self.decimation = int(capture_sample_rate / output_sample_rate)
        if self.decimation < 1:
            self.decimation = 1

        # Pre-compute mixer oscillator table (one full block worth)
        # This avoids expensive np.exp() per frame
        self._phase = 0.0
        self._phase_inc = -2.0 * np.pi * self.offset_hz / capture_sample_rate

        # FIR low-pass filter at the decimated rate (after shift + decimate)
        decimated_rate = capture_sample_rate / self.decimation
        if self.decimation > 1:
            nyq = decimated_rate / 2
            cutoff = min((bandwidth_hz / 2) / nyq, 0.95)
            n_taps = 31
            h = scipy_signal.firwin(n_taps, cutoff, window='hamming')
            self._fir = h.astype(np.float32)
            self._fir_zi = np.zeros(n_taps - 1, dtype=np.complex64)
        else:
            self._fir = None
            self._fir_zi = None


class Channelizer:
    """
    Extracts multiple narrowband channels from wideband IQ samples.
    """

    def __init__(self, center_freq, sample_rate):
        self.center_freq = center_freq
        self.sample_rate = sample_rate
        self._channels = []
        # Pre-allocated mixer buffer (resized on first frame)
        self._mixer_buf_size = 0

    def add_channel(self, name, freq_hz, bandwidth_hz=2.0e6,
                    output_sample_rate=2.0e6, callback=None):
        """Add a narrowband channel to extract."""
        offset = abs(freq_hz - self.center_freq)
        max_offset = self.sample_rate / 2 - bandwidth_hz / 2
        if offset > max_offset:
            raise ValueError(
                f"Channel '{name}' at {freq_hz/1e6:.3f} MHz is outside "
                f"capture window ({self.center_freq/1e6:.3f} MHz ± "
                f"{self.sample_rate/2/1e6:.1f} MHz)")

        ch = Channel(
            name=name,
            freq_hz=freq_hz,
            bandwidth_hz=bandwidth_hz,
            output_sample_rate=output_sample_rate,
            center_freq=self.center_freq,
            capture_sample_rate=self.sample_rate,
            callback=callback,
        )
        self._channels.append(ch)
        print(f"[*] Channel '{name}': {freq_hz/1e6:.3f} MHz, "
              f"BW {bandwidth_hz/1e6:.1f} MHz, "
              f"offset {ch.offset_hz/1e6:+.3f} MHz, "
              f"decim {ch.decimation}x → {output_sample_rate/1e6:.1f} MS/s")

    def handle_frame(self, samples):
        """
        Process a wideband IQ block — extract each channel and deliver
        narrowband IQ to its parser.
        """
        n = len(samples)

        for ch in self._channels:
            if ch.callback is None:
                continue

            # Fast path: no shift or decimation needed
            if (abs(ch.offset_hz) < 100 and ch.decimation <= 1
                    and ch.bandwidth_hz >= self.sample_rate * 0.9):
                try:
                    ch.callback(samples)
                except Exception:
                    pass
                continue

            # 1+2. Frequency-shift and decimate in one step
            #       Only multiply the samples we keep (every Dth)
            D = ch.decimation
            if D > 1:
                # Pre-compute decimated mixer (D-strided, phase-corrected)
                nd = (n + D - 1) // D  # number of output samples
                if not hasattr(ch, '_dec_mixer_size') or ch._dec_mixer_size != nd:
                    t = np.arange(nd, dtype=np.float64) * D
                    ch._dec_mixer_base = np.exp(1j * t * ch._phase_inc).astype(np.complex64)
                    ch._dec_mixer_size = nd
                phase_offset = np.complex64(np.exp(1j * ch._phase))
                mixer = ch._dec_mixer_base * phase_offset
                decimated = samples[::D][:len(mixer)] * mixer
            else:
                if not hasattr(ch, '_full_mixer') or len(ch._full_mixer) != n:
                    t = np.arange(n, dtype=np.float64)
                    ch._full_mixer = np.exp(1j * t * ch._phase_inc).astype(np.complex64)
                phase_offset = np.complex64(np.exp(1j * ch._phase))
                decimated = samples * (ch._full_mixer * phase_offset)
            ch._phase = float((ch._phase + n * ch._phase_inc) % (2 * np.pi))

            # 3. FIR low-pass filter at decimated rate (removes aliases)
            if ch._fir is not None:
                narrowband, ch._fir_zi = scipy_signal.lfilter(
                    ch._fir, [np.float32(1.0)], decimated, zi=ch._fir_zi)
                narrowband = narrowband.astype(np.complex64)
            else:
                narrowband = decimated

            # 4. Deliver to parser
            try:
                ch.callback(narrowband)
            except Exception:
                pass

    @property
    def channels(self):
        """Return list of channel info dicts."""
        return [
            {
                "name": ch.name,
                "freq_hz": ch.freq_hz,
                "bandwidth_hz": ch.bandwidth_hz,
                "offset_hz": ch.offset_hz,
                "decimation": ch.decimation,
            }
            for ch in self._channels
        ]

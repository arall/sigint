"""
Channelizer — extracts narrowband channels from a wideband IQ capture.

Sits between a wideband capture source (e.g., HackRF at 20 MHz) and
individual narrowband parsers (e.g., keyfob at 433.92 MHz, PMR at 446 MHz).

For each channel definition, it:
1. Frequency-shifts the full wideband block
2. Anti-alias filters and decimates using a polyphase FIR (filter-before-decimate)
3. Coalesces small output blocks into ~100ms chunks for stable SNR estimation
4. Emits the narrowband IQ to registered parser callbacks

The polyphase approach is critical: decimating before filtering aliases wideband
noise into the narrowband output, destroying SNR. With 80x decimation (20 MHz →
250 kHz), naive decimate-then-filter loses ~19 dB of SNR. The polyphase FIR
filters at the input rate but only computes taps_per_phase multiply-adds per
output sample, making it both correct and efficient.
"""

import numpy as np
from scipy import signal as scipy_signal


class Channel:
    """A narrowband channel extracted from wideband IQ."""

    # Target ~100ms of output samples before delivering to parser.
    # This ensures stable noise floor estimation and meaningful FM demod
    # even at high decimation ratios (e.g., 20 MHz → 250 kHz = 80x).
    COALESCE_TARGET_S = 0.1  # seconds of output data to accumulate

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

        # Mixer phase state for frequency shifting
        self._phase = 0.0
        self._phase_inc = -2.0 * np.pi * self.offset_hz / capture_sample_rate

        # Anti-alias FIR designed at the INPUT rate for proper decimation.
        # Uses scipy.signal.upfirdn internally (polyphase decomposition),
        # so only ceil(n_taps/D) multiply-adds per output sample.
        D = self.decimation
        if D > 1:
            # Design prototype lowpass at input rate
            # Cutoff at output_rate/2, normalized to input Nyquist
            input_nyq = capture_sample_rate / 2
            cutoff = min((output_sample_rate / 2) / input_nyq, 0.95)
            # Scale taps with decimation factor for adequate stopband rejection
            n_taps = max(63, D * 8 + 1)  # ~8 taps per polyphase phase
            if n_taps % 2 == 0:
                n_taps += 1
            h = scipy_signal.firwin(n_taps, cutoff, window='blackmanharris')
            # Normalize for unity passband gain after decimation
            h = (h * D).astype(np.float32)
            self._fir = h
            # Overlap buffer: need (n_taps - 1) input samples from prior block
            self._overlap = np.zeros(n_taps - 1, dtype=np.complex64)
        else:
            self._fir = None
            self._overlap = None

        # Output coalescing buffer — accumulate small decimated blocks
        # before delivering to parser for stable SNR estimation
        self._coalesce_buf = []
        self._coalesce_samples = 0
        self._coalesce_target = int(output_sample_rate * self.COALESCE_TARGET_S)


class Channelizer:
    """
    Extracts multiple narrowband channels from wideband IQ samples.
    """

    def __init__(self, center_freq, sample_rate):
        self.center_freq = center_freq
        self.sample_rate = sample_rate
        self._channels = []

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
        taps_info = f", {len(ch._fir)} taps" if ch._fir is not None else ""
        print(f"[*] Channel '{name}': {freq_hz/1e6:.3f} MHz, "
              f"BW {bandwidth_hz/1e6:.1f} MHz, "
              f"offset {ch.offset_hz/1e6:+.3f} MHz, "
              f"decim {ch.decimation}x → {output_sample_rate/1e6:.1f} MS/s"
              f"{taps_info}")

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

            D = ch.decimation

            # 1. Frequency-shift ALL samples at input rate
            if abs(ch.offset_hz) >= 100:
                # Pre-compute full-rate mixer (cached per block size)
                if not hasattr(ch, '_mixer_n') or ch._mixer_n != n:
                    t = np.arange(n, dtype=np.float64)
                    ch._mixer_base = np.exp(
                        1j * t * ch._phase_inc).astype(np.complex64)
                    ch._mixer_n = n
                phase_offset = np.complex64(np.exp(1j * ch._phase))
                shifted = samples * (ch._mixer_base * phase_offset)
            else:
                shifted = samples
            ch._phase = float((ch._phase + n * ch._phase_inc) % (2 * np.pi))

            # 2. Anti-alias filter + decimate (polyphase via upfirdn)
            if ch._fir is not None and D > 1:
                # Prepend overlap from previous block for filter continuity
                x = np.concatenate([ch._overlap, shifted])
                # Save overlap for next block
                overlap_len = len(ch._fir) - 1
                ch._overlap = x[-overlap_len:].copy()
                # Polyphase filter + decimate in one step
                narrowband = scipy_signal.upfirdn(
                    ch._fir, x, up=1, down=D).astype(np.complex64)
                # Trim filter transient from prepended overlap
                skip = (overlap_len + D - 1) // D
                narrowband = narrowband[skip:]
                # Trim to expected output length
                expected = (n + D - 1) // D
                narrowband = narrowband[:expected]
            elif D > 1:
                narrowband = shifted[::D]
            else:
                narrowband = shifted

            # 3. Coalesce small blocks, then deliver to parser
            ch._coalesce_buf.append(narrowband)
            ch._coalesce_samples += len(narrowband)
            if ch._coalesce_samples >= ch._coalesce_target:
                merged = np.concatenate(ch._coalesce_buf)
                ch._coalesce_buf.clear()
                ch._coalesce_samples = 0
                try:
                    ch.callback(merged)
                except Exception:
                    pass

    def flush(self):
        """Deliver any buffered samples remaining in coalesce buffers."""
        for ch in self._channels:
            if ch._coalesce_buf and ch.callback is not None:
                merged = np.concatenate(ch._coalesce_buf)
                ch._coalesce_buf.clear()
                ch._coalesce_samples = 0
                try:
                    ch.callback(merged)
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

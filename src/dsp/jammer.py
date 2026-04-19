"""
Broadband-interference / jamming detection primitives.

Two things distinguish a jammer from a loud-but-legitimate emitter:

1. **Elevated noise floor** — a jammer saturates a whole band, raising
   the median PSD across the whole slice. A single strong signal only
   raises a narrow peak.
2. **Spectral flatness** — the ratio of the geometric mean to the
   arithmetic mean of the PSD. Flat (noisy / jammer) → ~1.0. Peaky
   (a strong narrowband signal) → much less than 1.0. White noise
   converges to 1.0; a clean tone to ~0.

The detector combines both: a candidate sample needs an elevation
threshold *and* sufficient flatness. This rejects the "a ham op is
transmitting nearby" false positive while still catching the cheap
noise-floor jammers that are the common real-world case.

All functions are pure and hardware-free — the scanner module calls
these with IQ samples from the SDR, tests call them with synthesised
PSDs or noise+signal mixtures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np


# Enough FFT bins to resolve the "broadband" vs "peaky" distinction at
# 2 MHz sample rate. 4096 was tried against pathological narrowband
# signals (-0.002 flatness) and across-band noise (~0.9 flatness) and
# separates them cleanly.
DEFAULT_FFT_SIZE = 4096


@dataclass
class BandSample:
    """One sample's worth of band statistics.

    `noise_floor_db` is the median PSD in the band (a robust "what's
    the quiet-state level" readout; outlier peaks from narrowband
    signals don't pull it). `peak_db` is the max bin for diagnostics.
    `flatness` is the spectral-flatness ratio in [0, 1].
    """
    noise_floor_db: float
    peak_db: float
    flatness: float
    bins: int


def psd_from_iq(samples: np.ndarray, sample_rate: float,
                fft_size: int = DEFAULT_FFT_SIZE) -> np.ndarray:
    """Welch-style PSD estimate from a complex IQ buffer.

    Returns linear-scale PSD (not dB) so downstream code can choose
    the reference. Uses scipy.signal.welch when available, else a
    simple windowed-FFT average.
    """
    if samples.size == 0:
        return np.array([])
    try:
        from scipy import signal as _sig
        _, psd = _sig.welch(samples, fs=sample_rate, nperseg=fft_size,
                            return_onesided=False)
        return psd
    except Exception:
        # scipy-free fallback: segment-average with a Hann window.
        nsegs = max(1, samples.size // fft_size)
        win = np.hanning(fft_size)
        acc = np.zeros(fft_size)
        for i in range(nsegs):
            seg = samples[i * fft_size:(i + 1) * fft_size]
            if seg.size < fft_size:
                break
            spec = np.abs(np.fft.fft(seg * win)) ** 2
            acc += spec
        return acc / max(nsegs, 1)


def spectral_flatness(psd: np.ndarray) -> float:
    """Wiener entropy — geometric mean / arithmetic mean of the PSD.

    Perfectly flat white noise tends to 1.0; a pure tone approaches 0.
    Guarded against empty / zero PSDs (returns 0 — treats "no signal"
    as peaky rather than flat, so silence can't trigger a jammer
    detection).
    """
    p = np.asarray(psd, dtype=np.float64)
    if p.size == 0:
        return 0.0
    # Drop any zero/negative bins (shouldn't happen on real PSDs but
    # can on synthetic inputs) so the log doesn't blow up.
    p = p[p > 0]
    if p.size == 0:
        return 0.0
    arith = float(np.mean(p))
    if arith <= 0:
        return 0.0
    # geo-mean via log-mean for numerical stability at small PSDs
    geo = float(math.exp(np.mean(np.log(p))))
    return min(1.0, max(0.0, geo / arith))


def band_sample_from_psd(psd: np.ndarray) -> BandSample:
    """Reduce a PSD to the three numbers the detector decides on."""
    p = np.asarray(psd, dtype=np.float64)
    if p.size == 0:
        return BandSample(noise_floor_db=-200.0, peak_db=-200.0,
                          flatness=0.0, bins=0)
    # Median is more robust than mean against narrowband peaks.
    med = float(np.median(p[p > 0])) if np.any(p > 0) else 1e-12
    peak = float(np.max(p)) if p.size else 1e-12
    return BandSample(
        noise_floor_db=10.0 * math.log10(max(med, 1e-20)),
        peak_db=10.0 * math.log10(max(peak, 1e-20)),
        flatness=spectral_flatness(p),
        bins=int(p.size),
    )


def band_sample_from_iq(samples: np.ndarray, sample_rate: float,
                        fft_size: int = DEFAULT_FFT_SIZE) -> BandSample:
    """Convenience: PSD → BandSample in one call."""
    return band_sample_from_psd(psd_from_iq(samples, sample_rate, fft_size))


@dataclass
class DetectionState:
    """Per-band rolling state the scanner feeds samples into.

    `baseline_db` is the quiet-state median noise floor, established
    during the calibration window and then sticky. `consec_hits`
    counts consecutive samples exceeding threshold; the scanner
    fires when it reaches `min_consec`, then enters cooldown until
    the signal falls back below baseline + hysteresis.
    """
    baseline_db: Optional[float] = None
    consec_hits: int = 0
    firing: bool = False


def decide(sample: BandSample, state: DetectionState,
           elevation_threshold_db: float = 10.0,
           flatness_threshold: float = 0.5,
           min_consec: int = 3,
           hysteresis_db: float = 3.0) -> tuple:
    """Update `state` with a new sample; return (fired, transition_off).

    - `fired` goes True when we cross the trigger conditions for
      `min_consec` samples in a row. Stays True until the signal drops.
    - `transition_off` goes True on the exact sample where we leave
      the firing state (signal fell below baseline + hysteresis).
      Useful for logging the end of a jamming event.

    If `state.baseline_db` is None the function only updates it (from
    the first non-peaky sample) and never fires — callers should treat
    the first few samples as calibration.
    """
    # Calibration: adopt a baseline from the first flat-enough sample.
    # If a real jammer is already active when the scanner starts, we'd
    # baseline to the elevated floor, so the scanner should ideally
    # run a multi-sample average during startup — `run_baseline` below.
    if state.baseline_db is None:
        state.baseline_db = sample.noise_floor_db
        return False, False

    elevated = (sample.noise_floor_db - state.baseline_db) >= elevation_threshold_db
    flat = sample.flatness >= flatness_threshold
    trigger = elevated and flat

    transition_off = False
    if state.firing:
        # Hysteresis: stay firing until the signal actually drops back
        # toward the baseline. Use only the hysteresis band here — the
        # elevation threshold is the ENTRY gate; the exit should be
        # softer so a dip from +20 dB to +9 dB (just below the entry
        # threshold) doesn't flap firing off mid-event.
        if (sample.noise_floor_db - state.baseline_db) < hysteresis_db:
            state.firing = False
            state.consec_hits = 0
            transition_off = True
        return state.firing, transition_off

    if trigger:
        state.consec_hits += 1
        if state.consec_hits >= min_consec:
            state.firing = True
            return True, False
    else:
        # Any non-trigger sample resets the counter — we want CONSECUTIVE
        # hits, not just "enough in a window."
        state.consec_hits = 0
    return False, False


def run_baseline(samples_iter, percentile: float = 50.0) -> float:
    """Compute a baseline noise floor from a batch of BandSamples.

    Median of medians — robust even if a few startup samples caught a
    transient signal. The scanner calls this with ~N samples collected
    over the calibration window.
    """
    vals = [s.noise_floor_db for s in samples_iter
            if s.noise_floor_db > -190.0]
    if not vals:
        return -100.0  # sane-ish default for a dead RTL-SDR / bad PSD
    return float(np.percentile(vals, percentile))

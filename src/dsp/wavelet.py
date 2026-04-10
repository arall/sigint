"""
Wavelet-Based Burst Detection

CWT (Continuous Wavelet Transform) signal detection for low-SNR transient
signals. Complements FFT energy detection — better at finding short bursts
(keyfobs, FHSS hops) buried in noise.

FFT spreads a short burst's energy across many time bins, reducing SNR.
CWT preserves time-frequency localization, detecting transients that FFT misses.

Usage:
    from dsp.wavelet import detect_bursts_cwt, detect_bursts_stft

    # CWT-based detection (best for unknown/variable burst durations)
    bursts = detect_bursts_cwt(samples, sample_rate, min_snr_db=8)

    # STFT-based detection (faster, good for narrowband signals)
    bursts = detect_bursts_stft(samples, sample_rate, min_snr_db=8)
"""

import numpy as np
from typing import List, Optional, Tuple


def _ricker(points, a):
    """Ricker (Mexican hat) wavelet.

    Reimplemented here because scipy.signal.ricker was removed in scipy >= 1.15.
    """
    A = 2 / (np.sqrt(3 * a) * (np.pi ** 0.25))
    wsq = a ** 2
    vec = np.arange(0, points) - (points - 1.0) / 2
    xsq = vec ** 2
    mod = (1 - xsq / wsq)
    gauss = np.exp(-xsq / (2 * wsq))
    return A * mod * gauss


def _cwt(data, widths):
    """Continuous Wavelet Transform using Ricker wavelet.

    Reimplemented because scipy.signal.cwt was removed in scipy >= 1.15.
    """
    output = np.empty((len(widths), len(data)))
    for i, width in enumerate(widths):
        N = min(10 * width, len(data))
        if N < 1:
            N = 1
        wavelet_data = _ricker(N, width)
        output[i] = np.convolve(data, wavelet_data, mode='same')
    return output


def detect_bursts_cwt(samples, sample_rate: float, min_snr_db: float = 8.0,
                      min_duration_ms: float = 0.1, max_duration_ms: float = 500.0,
                      widths: Optional[np.ndarray] = None) -> List[dict]:
    """Detect transient bursts using Continuous Wavelet Transform.

    Uses Ricker (Mexican hat) wavelet at multiple scales to find
    time-localized energy bursts across a range of durations.

    Args:
        samples: Complex IQ samples
        sample_rate: Sample rate in Hz
        min_snr_db: Minimum SNR threshold for detection
        min_duration_ms: Minimum burst duration in ms
        max_duration_ms: Maximum burst duration in ms
        widths: CWT scale widths (auto-computed if None)

    Returns:
        List of burst dicts: {
            "start_s": float,
            "duration_ms": float,
            "peak_power_db": float,
            "noise_floor_db": float,
            "snr_db": float,
            "center_freq_offset_hz": float,
            "bandwidth_hz": float,
            "scale_idx": int,
        }
    """
    envelope = np.abs(samples)

    # Compute scales corresponding to burst duration range
    # Ricker wavelet: effective duration ≈ 4 * width / sample_rate
    if widths is None:
        min_width = max(2, int(min_duration_ms * sample_rate / 4000))
        max_width = int(max_duration_ms * sample_rate / 4000)
        max_width = min(max_width, len(samples) // 4)
        if max_width <= min_width:
            max_width = min_width + 1
        # Log-spaced widths for uniform frequency coverage
        n_scales = min(32, max_width - min_width)
        widths = np.unique(np.logspace(
            np.log10(min_width), np.log10(max_width), n_scales
        ).astype(int))

    # CWT with Ricker wavelet (using local implementation for scipy compat)
    cwt_matrix = _cwt(envelope, widths)

    # Noise floor per scale (median of absolute values)
    bursts = []
    for scale_idx, width in enumerate(widths):
        row = np.abs(cwt_matrix[scale_idx])
        noise_floor = np.median(row)
        noise_db = 20 * np.log10(noise_floor + 1e-10)

        threshold = noise_floor * (10 ** (min_snr_db / 20))

        # Find peaks above threshold
        above = row > threshold
        transitions = np.diff(above.astype(int))
        starts = np.where(transitions == 1)[0]
        ends = np.where(transitions == -1)[0]

        if len(starts) == 0:
            continue
        if len(ends) == 0 or ends[0] < starts[0]:
            if len(ends) > 0:
                ends = ends[1:]
            else:
                continue

        min_len = min(len(starts), len(ends))
        for s, e in zip(starts[:min_len], ends[:min_len]):
            duration_ms = (e - s) / sample_rate * 1000

            if duration_ms < min_duration_ms or duration_ms > max_duration_ms:
                continue

            peak_val = np.max(row[s:e])
            peak_db = 20 * np.log10(peak_val + 1e-10)
            snr = peak_db - noise_db

            # Estimate center frequency from IQ phase at peak
            peak_idx = s + np.argmax(row[s:e])
            freq_offset = _estimate_freq_offset(samples, peak_idx, width, sample_rate)

            # Estimate bandwidth from the scale
            bw_hz = sample_rate / (2 * width)

            bursts.append({
                "start_s": s / sample_rate,
                "duration_ms": duration_ms,
                "peak_power_db": peak_db,
                "noise_floor_db": noise_db,
                "snr_db": snr,
                "center_freq_offset_hz": freq_offset,
                "bandwidth_hz": bw_hz,
                "scale_idx": int(scale_idx),
            })

    # Deduplicate: merge bursts that overlap in time (from different scales)
    bursts.sort(key=lambda b: b["start_s"])
    merged = _merge_overlapping(bursts)

    return merged


def detect_bursts_stft(samples, sample_rate: float, min_snr_db: float = 8.0,
                       window_ms: float = 5.0, overlap: float = 0.5,
                       min_duration_ms: float = 0.5) -> List[dict]:
    """Detect bursts using Short-Time FFT with adaptive noise floor.

    Faster than CWT but fixed time-frequency resolution. Good for
    narrowband signals with known approximate bandwidth.

    Args:
        samples: Complex IQ samples
        sample_rate: Sample rate in Hz
        min_snr_db: Minimum SNR threshold
        window_ms: Analysis window size in ms
        overlap: Window overlap fraction (0-1)
        min_duration_ms: Minimum burst duration in ms

    Returns:
        List of burst dicts (same format as detect_bursts_cwt)
    """
    nperseg = int(window_ms * sample_rate / 1000)
    nperseg = max(64, min(nperseg, len(samples) // 4))
    hop = max(1, int(nperseg * (1 - overlap)))

    n_frames = (len(samples) - nperseg) // hop + 1
    if n_frames < 3:
        return []

    # Compute STFT power per frame
    frame_power = np.empty(n_frames)
    frame_peak_freq = np.empty(n_frames)

    for i in range(n_frames):
        start = i * hop
        frame = samples[start:start + nperseg]
        spectrum = np.abs(np.fft.fft(frame))
        frame_power[i] = np.mean(spectrum ** 2)
        frame_peak_freq[i] = np.argmax(spectrum[:nperseg // 2])

    # Power in dB
    power_db = 10 * np.log10(frame_power + 1e-10)

    # Adaptive noise floor: rolling median
    kernel_size = max(3, n_frames // 10)
    if kernel_size % 2 == 0:
        kernel_size += 1

    # Pad for median filter
    padded = np.pad(power_db, kernel_size // 2, mode='edge')
    noise_floor = np.array([np.median(padded[i:i + kernel_size])
                            for i in range(n_frames)])

    snr = power_db - noise_floor

    # Find burst regions
    above = snr >= min_snr_db
    transitions = np.diff(above.astype(int))
    starts = np.where(transitions == 1)[0]
    ends = np.where(transitions == -1)[0]

    if len(starts) == 0:
        return []
    if len(ends) > 0 and ends[0] < starts[0]:
        ends = ends[1:]

    bursts = []
    min_len = min(len(starts), len(ends))
    for s, e in zip(starts[:min_len], ends[:min_len]):
        duration_ms = (e - s) * hop / sample_rate * 1000
        if duration_ms < min_duration_ms:
            continue

        peak_frame = s + np.argmax(power_db[s:e])
        peak_db_val = power_db[peak_frame]
        nf = noise_floor[peak_frame]

        # Frequency offset from peak FFT bin
        freq_bin = frame_peak_freq[peak_frame]
        freq_offset = (freq_bin / nperseg - 0.5) * sample_rate

        bursts.append({
            "start_s": s * hop / sample_rate,
            "duration_ms": duration_ms,
            "peak_power_db": peak_db_val,
            "noise_floor_db": nf,
            "snr_db": peak_db_val - nf,
            "center_freq_offset_hz": freq_offset,
            "bandwidth_hz": sample_rate / nperseg,
            "scale_idx": 0,
        })

    return bursts


def _estimate_freq_offset(samples, center_idx: int, width: int,
                          sample_rate: float) -> float:
    """Estimate instantaneous frequency at a given point using FM discriminator."""
    half = width
    start = max(0, center_idx - half)
    end = min(len(samples), center_idx + half)
    segment = samples[start:end]

    if len(segment) < 4:
        return 0.0

    # FM discriminator
    phase_diff = np.angle(segment[1:] * np.conj(segment[:-1]))
    freq = np.mean(phase_diff) * sample_rate / (2 * np.pi)
    return freq


def _merge_overlapping(bursts: List[dict], gap_ms: float = 1.0) -> List[dict]:
    """Merge bursts that overlap or are very close in time.

    Keeps the burst with highest SNR from each overlapping group.
    """
    if len(bursts) <= 1:
        return bursts

    merged = [bursts[0]]
    for burst in bursts[1:]:
        prev = merged[-1]
        prev_end = prev["start_s"] + prev["duration_ms"] / 1000
        gap = burst["start_s"] - prev_end

        if gap < gap_ms / 1000:
            # Overlapping — keep the one with higher SNR
            if burst["snr_db"] > prev["snr_db"]:
                # Extend previous with this one's end time
                new_end = burst["start_s"] + burst["duration_ms"] / 1000
                merged[-1] = burst
                merged[-1]["duration_ms"] = (new_end - prev["start_s"]) * 1000
                merged[-1]["start_s"] = prev["start_s"]
            else:
                # Extend previous to cover this one
                new_end = burst["start_s"] + burst["duration_ms"] / 1000
                prev["duration_ms"] = (new_end - prev["start_s"]) * 1000
        else:
            merged.append(burst)

    return merged

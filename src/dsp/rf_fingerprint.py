"""
RF Fingerprinting — Physical Transmitter Identification

Extracts IQ-level hardware imperfections from burst transients to identify
specific physical transmitters. Two identical radios transmitting the same
protocol will have different RF fingerprints due to:

  - Oscillator frequency offset (CFO)
  - I/Q amplitude imbalance
  - I/Q phase imbalance
  - Carrier phase offset
  - Rise time (turn-on transient shape)
  - Power ramp profile

Primary use case: keyfob/TPMS transmitter re-identification across sessions,
even when rolling codes change.

Caveat: Consumer SDRs (RTL-SDR, HackRF) have their own hardware imperfections
that can mask transmitter signatures. This is research-grade, not production.

Usage:
    from dsp.rf_fingerprint import extract_fingerprint, fingerprint_hash
    from dsp.rf_fingerprint import compare_fingerprints

    fp = extract_fingerprint(iq_samples, sample_rate, burst_start, burst_end)
    fp_hash = fingerprint_hash(fp)

    # Compare two fingerprints
    similarity = compare_fingerprints(fp1, fp2)
"""

import hashlib
import numpy as np
from typing import Optional, Tuple


# How many samples of the transient to analyze (from burst start)
TRANSIENT_SAMPLES_DEFAULT = 200

# Fingerprint feature weights for similarity comparison
FEATURE_WEIGHTS = {
    "cfo_hz": 0.25,
    "iq_amplitude_imbalance": 0.20,
    "iq_phase_imbalance_deg": 0.15,
    "rise_time_us": 0.15,
    "power_ramp_shape": 0.10,
    "carrier_phase_deg": 0.10,
    "spectral_asymmetry": 0.05,
}


def extract_fingerprint(samples, sample_rate: float,
                        burst_start: int, burst_end: int,
                        transient_samples: int = TRANSIENT_SAMPLES_DEFAULT) -> Optional[dict]:
    """Extract RF fingerprint from a burst's turn-on transient.

    Args:
        samples: Full IQ capture (complex numpy array)
        sample_rate: Sample rate in Hz
        burst_start: Sample index of burst start
        burst_end: Sample index of burst end
        transient_samples: Number of samples to analyze from burst start

    Returns:
        dict of fingerprint features, or None if burst too short
    """
    # Need pre-burst noise + transient + steady-state
    pre_samples = 50  # samples before burst for noise reference
    min_burst = transient_samples + pre_samples

    if burst_end - burst_start < min_burst:
        return None
    if burst_start < pre_samples:
        return None

    # Extract segments
    noise = samples[burst_start - pre_samples:burst_start]
    transient = samples[burst_start:burst_start + transient_samples]
    steady = samples[burst_start + transient_samples:burst_end]

    if len(steady) < 100:
        return None

    fp = {}

    # 1. Carrier Frequency Offset (CFO)
    fp["cfo_hz"] = _measure_cfo(steady, sample_rate)

    # 2. I/Q Imbalance
    amp_imb, phase_imb = _measure_iq_imbalance(steady)
    fp["iq_amplitude_imbalance"] = amp_imb
    fp["iq_phase_imbalance_deg"] = phase_imb

    # 3. Carrier phase at turn-on
    fp["carrier_phase_deg"] = _measure_carrier_phase(transient)

    # 4. Rise time
    fp["rise_time_us"] = _measure_rise_time(transient, sample_rate)

    # 5. Power ramp shape (normalized transient envelope)
    fp["power_ramp_shape"] = _measure_ramp_shape(transient)

    # 6. Spectral asymmetry
    fp["spectral_asymmetry"] = _measure_spectral_asymmetry(steady)

    # 7. Transient duration and noise level (for normalization)
    fp["noise_power_db"] = 20 * np.log10(np.mean(np.abs(noise)) + 1e-10)
    fp["signal_power_db"] = 20 * np.log10(np.mean(np.abs(steady)) + 1e-10)
    fp["sample_rate"] = sample_rate

    return fp


def _measure_cfo(steady_iq, sample_rate: float) -> float:
    """Measure carrier frequency offset from steady-state IQ."""
    phase_diff = np.angle(steady_iq[1:] * np.conj(steady_iq[:-1]))
    avg_phase_rate = np.mean(phase_diff)
    cfo = avg_phase_rate * sample_rate / (2 * np.pi)
    return float(cfo)


def _measure_iq_imbalance(steady_iq) -> Tuple[float, float]:
    """Measure I/Q amplitude and phase imbalance.

    Perfect hardware: I and Q have equal power and 90° phase difference.
    Real hardware: amplitude ratio ≠ 1, phase ≠ 90°.
    """
    i_signal = np.real(steady_iq)
    q_signal = np.imag(steady_iq)

    # Amplitude imbalance: ratio of I/Q RMS power
    i_rms = np.sqrt(np.mean(i_signal ** 2))
    q_rms = np.sqrt(np.mean(q_signal ** 2))
    amp_imbalance = (i_rms - q_rms) / (i_rms + q_rms + 1e-10)

    # Phase imbalance: deviation from 90° via cross-correlation
    # Perfect quadrature: correlation = 0
    correlation = np.mean(i_signal * q_signal) / (i_rms * q_rms + 1e-10)
    phase_imbalance_deg = np.degrees(np.arcsin(np.clip(correlation, -1, 1)))

    return float(amp_imbalance), float(phase_imbalance_deg)


def _measure_carrier_phase(transient_iq) -> float:
    """Measure carrier phase at burst onset."""
    # Use the first few stable samples after initial noise
    # Skip first 10% to avoid switch-on glitch
    skip = max(1, len(transient_iq) // 10)
    early = transient_iq[skip:skip + 20]
    if len(early) < 5:
        return 0.0
    return float(np.degrees(np.mean(np.angle(early))))


def _measure_rise_time(transient_iq, sample_rate: float) -> float:
    """Measure 10-90% rise time of the burst envelope."""
    envelope = np.abs(transient_iq)

    # Smooth envelope
    if len(envelope) > 10:
        kernel = np.ones(5) / 5
        envelope = np.convolve(envelope, kernel, mode='same')

    final_level = np.percentile(envelope[-20:], 50) if len(envelope) > 20 else np.max(envelope)
    level_10 = 0.1 * final_level
    level_90 = 0.9 * final_level

    # Find crossings
    idx_10 = np.argmax(envelope >= level_10)
    idx_90 = np.argmax(envelope >= level_90)

    if idx_90 <= idx_10:
        return 0.0

    rise_time_us = (idx_90 - idx_10) / sample_rate * 1e6
    return float(rise_time_us)


def _measure_ramp_shape(transient_iq) -> float:
    """Characterize the power ramp shape as a single metric.

    Returns a value 0-1 where:
        0 = linear ramp
        0.5 = typical transmitter
        1 = step function (instant on)
    """
    envelope = np.abs(transient_iq)
    if len(envelope) < 10:
        return 0.5

    # Normalize to 0-1
    env_min = np.min(envelope)
    env_max = np.max(envelope)
    if env_max - env_min < 1e-10:
        return 0.5
    normalized = (envelope - env_min) / (env_max - env_min)

    # Compare to linear ramp
    linear = np.linspace(0, 1, len(normalized))
    deviation = np.mean(np.abs(normalized - linear))

    return float(min(1.0, deviation * 2))


def _measure_spectral_asymmetry(steady_iq) -> float:
    """Measure asymmetry between positive and negative frequency content.

    Hardware imperfections cause the spectrum to be asymmetric around DC.
    """
    spectrum = np.abs(np.fft.fft(steady_iq))
    n = len(spectrum)
    pos = spectrum[1:n // 2]
    neg = spectrum[n // 2 + 1:][::-1]

    min_len = min(len(pos), len(neg))
    if min_len < 2:
        return 0.0

    pos = pos[:min_len]
    neg = neg[:min_len]

    pos_power = np.sum(pos ** 2)
    neg_power = np.sum(neg ** 2)
    total = pos_power + neg_power

    if total < 1e-10:
        return 0.0

    asymmetry = (pos_power - neg_power) / total
    return float(asymmetry)


def fingerprint_hash(fp: dict, precision: int = 2) -> str:
    """Generate a short hash from fingerprint features for quick comparison.

    Quantizes features to reduce sensitivity to measurement noise.
    Same transmitter should produce similar (but not necessarily identical)
    hashes across captures.

    Args:
        fp: Fingerprint dict from extract_fingerprint()
        precision: Decimal places for quantization

    Returns:
        12-character hex hash string
    """
    # Quantize key features
    parts = [
        round(fp.get("cfo_hz", 0) / 100) * 100,  # 100 Hz bins
        round(fp.get("iq_amplitude_imbalance", 0), precision),
        round(fp.get("iq_phase_imbalance_deg", 0), precision),
        round(fp.get("rise_time_us", 0) / 5) * 5,  # 5 µs bins
        round(fp.get("power_ramp_shape", 0), 1),
        round(fp.get("spectral_asymmetry", 0), precision),
    ]

    key = "|".join(str(p) for p in parts)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def compare_fingerprints(fp1: dict, fp2: dict) -> float:
    """Compare two fingerprints and return similarity score (0.0 to 1.0).

    Uses weighted Euclidean distance normalized by expected feature ranges.
    1.0 = identical, 0.0 = completely different.

    Args:
        fp1, fp2: Fingerprint dicts from extract_fingerprint()

    Returns:
        Similarity score 0.0 to 1.0
    """
    # Expected ranges for normalization
    ranges = {
        "cfo_hz": 5000.0,          # ±5 kHz typical spread
        "iq_amplitude_imbalance": 0.1,
        "iq_phase_imbalance_deg": 10.0,
        "rise_time_us": 50.0,
        "power_ramp_shape": 1.0,
        "carrier_phase_deg": 180.0,
        "spectral_asymmetry": 0.5,
    }

    total_weight = 0.0
    weighted_distance = 0.0

    for feature, weight in FEATURE_WEIGHTS.items():
        v1 = fp1.get(feature, 0.0)
        v2 = fp2.get(feature, 0.0)
        rng = ranges.get(feature, 1.0)

        # Normalized distance for this feature (0 to 1)
        dist = min(1.0, abs(v1 - v2) / (rng + 1e-10))
        weighted_distance += weight * dist
        total_weight += weight

    if total_weight < 1e-10:
        return 0.0

    # Convert distance to similarity
    similarity = 1.0 - weighted_distance / total_weight
    return max(0.0, min(1.0, similarity))


def extract_from_ook_burst(samples, sample_rate: float,
                           burst_info: dict) -> Optional[dict]:
    """Convenience: extract fingerprint from an OOK burst detection.

    Args:
        samples: Full IQ capture
        sample_rate: Sample rate in Hz
        burst_info: Dict with 'start_sample' key (from dsp.ook.detect_ook_signal)

    Returns:
        Fingerprint dict or None
    """
    start = burst_info.get("start_sample", 0)
    # Estimate burst end from pulse duration
    pulse_us = burst_info.get("pulse_us", 0)
    end = start + int(pulse_us * sample_rate / 1e6)

    if end <= start:
        end = start + TRANSIENT_SAMPLES_DEFAULT * 2

    return extract_fingerprint(samples, sample_rate, start, end)

"""
Automatic Modulation Classification (Heuristic)

Classifies unknown RF signals by modulation type from IQ samples using
signal statistics — no ML model or GPU required.

Classification categories:
    - CW          (unmodulated carrier)
    - AM          (amplitude modulation)
    - FM_narrow   (narrowband FM: PMR, FRS, etc.)
    - FM_wide     (wideband FM: broadcast)
    - OOK/ASK     (on-off keying: keyfobs, remotes)
    - FSK         (frequency shift keying)
    - PSK         (phase shift keying: BPSK, QPSK)
    - QAM         (quadrature amplitude modulation)
    - OFDM        (orthogonal frequency division: WiFi, LTE)
    - FHSS        (frequency hopping spread spectrum)
    - Noise       (no signal detected)

Based on signal features:
    - Envelope statistics (std/mean ratio, kurtosis)
    - Instantaneous frequency variance
    - Phase continuity
    - Spectral occupancy (bandwidth vs capture BW)
    - Cyclostationary features (symbol rate estimation)

Usage:
    from dsp.amc import classify_modulation
    result = classify_modulation(iq_samples, sample_rate)
    print(result["modulation"], result["confidence"])
"""

import numpy as np
from typing import Optional


def classify_modulation(samples, sample_rate: float,
                        min_snr_db: float = 15.0) -> dict:
    """Classify the modulation type of an IQ signal.

    Args:
        samples: Complex IQ samples (numpy array)
        sample_rate: Sample rate in Hz
        min_snr_db: Minimum SNR to attempt classification

    Returns:
        dict with:
            modulation: str — classification label
            confidence: float — 0.0 to 1.0
            features: dict — extracted signal features
            details: str — human-readable description
    """
    result = {
        "modulation": "Noise",
        "confidence": 0.0,
        "features": {},
        "details": "No signal detected",
    }

    if len(samples) < 256:
        return result

    # --- Feature extraction ---
    features = extract_features(samples, sample_rate)
    result["features"] = features

    # Check SNR
    if features["snr_db"] < min_snr_db:
        result["details"] = f"SNR too low ({features['snr_db']:.1f} dB)"
        return result

    # --- Classification decision tree ---
    # Based on signal statistics hierarchy

    env_std_ratio = features["envelope_std_ratio"]
    freq_std = features["inst_freq_std_hz"]
    phase_std = features["phase_std"]
    spectral_occ = features["spectral_occupancy"]
    kurtosis = features["envelope_kurtosis"]
    bandwidth_hz = features["occupied_bw_hz"]

    # 1. FHSS: high spectral occupancy + high frequency variance
    if spectral_occ > 0.6 and freq_std > sample_rate * 0.1:
        result["modulation"] = "FHSS"
        result["confidence"] = min(1.0, spectral_occ * 0.8 + 0.2)
        result["details"] = (
            f"Spread spectrum: {spectral_occ:.0%} BW occupied, "
            f"freq variance {freq_std/1000:.0f} kHz"
        )
        return result

    # 2. OFDM: high spectral occupancy + moderate envelope variation
    if spectral_occ > 0.4 and env_std_ratio > 0.3 and kurtosis > 2.0:
        result["modulation"] = "OFDM"
        result["confidence"] = min(1.0, spectral_occ * 0.6 + env_std_ratio * 0.4)
        result["details"] = (
            f"OFDM-like: {spectral_occ:.0%} BW, "
            f"envelope kurtosis {kurtosis:.1f}, BW {bandwidth_hz/1000:.0f} kHz"
        )
        return result

    # 3. OOK/ASK: bimodal envelope (near-zero when OFF)
    if env_std_ratio > 0.5 and features["envelope_bimodality"] > 0.4:
        result["modulation"] = "OOK/ASK"
        result["confidence"] = min(1.0, features["envelope_bimodality"])
        result["details"] = (
            f"On-off keying: envelope bimodality {features['envelope_bimodality']:.2f}, "
            f"duty cycle ~{features['ook_duty_cycle']:.0%}"
        )
        return result

    # 4. FM: high instantaneous frequency variance, constant envelope
    if freq_std > 1000 and env_std_ratio < 0.25:
        if bandwidth_hz > 50000:
            mod = "FM_wide"
            conf = min(1.0, 0.6 + (1.0 - env_std_ratio) * 0.4)
            detail = f"Wideband FM: BW {bandwidth_hz/1000:.0f} kHz, dev ~{freq_std/1000:.0f} kHz"
        else:
            mod = "FM_narrow"
            conf = min(1.0, 0.6 + (1.0 - env_std_ratio) * 0.4)
            detail = f"Narrowband FM: BW {bandwidth_hz/1000:.0f} kHz, dev ~{freq_std/1000:.0f} kHz"

        result["modulation"] = mod
        result["confidence"] = conf
        result["details"] = detail
        return result

    # 5. FSK: moderate frequency variance with discrete levels
    if features["freq_bimodality"] > 0.3 and env_std_ratio < 0.3:
        result["modulation"] = "FSK"
        result["confidence"] = min(1.0, features["freq_bimodality"] * 0.8 + 0.2)
        result["details"] = (
            f"FSK: deviation ~{freq_std/1000:.0f} kHz, "
            f"freq bimodality {features['freq_bimodality']:.2f}"
        )
        return result

    # 6. CW: very low envelope and frequency variance
    if env_std_ratio < 0.05 and freq_std < 500:
        result["modulation"] = "CW"
        result["confidence"] = min(1.0, 0.7 + (0.05 - env_std_ratio) * 6)
        result["details"] = f"Continuous wave: env σ/μ={env_std_ratio:.3f}, freq σ={freq_std:.0f} Hz"
        return result

    # 7. AM: envelope variation tracks the signal, constant frequency
    if env_std_ratio > 0.15 and freq_std < 5000 and phase_std < 1.0:
        result["modulation"] = "AM"
        result["confidence"] = min(1.0, env_std_ratio * 2)
        result["details"] = f"AM: envelope σ/μ={env_std_ratio:.2f}, modulation depth ~{env_std_ratio*2:.0%}"
        return result

    # 8. PSK: constant envelope, discrete phase changes
    if env_std_ratio < 0.2 and phase_std > 0.5:
        n_states = features.get("constellation_points", 0)
        if n_states in (2, 4, 8):
            labels = {2: "BPSK", 4: "QPSK", 8: "8PSK"}
            result["modulation"] = labels.get(n_states, "PSK")
        else:
            result["modulation"] = "PSK"
        result["confidence"] = min(1.0, 0.5 + (1.0 - env_std_ratio) * 0.3)
        result["details"] = (
            f"Phase-shift keying: {n_states} constellation points, "
            f"phase σ={phase_std:.2f}"
        )
        return result

    # 9. QAM: envelope AND phase variation
    if env_std_ratio > 0.15 and phase_std > 0.5:
        result["modulation"] = "QAM"
        result["confidence"] = 0.4
        result["details"] = (
            f"Digital modulation (QAM-like): env σ/μ={env_std_ratio:.2f}, "
            f"phase σ={phase_std:.2f}"
        )
        return result

    # 10. Fallback — unknown digital
    result["modulation"] = "Unknown_Digital"
    result["confidence"] = 0.2
    result["details"] = (
        f"Unclassified: env σ/μ={env_std_ratio:.2f}, freq σ={freq_std/1000:.1f} kHz, "
        f"phase σ={phase_std:.2f}, BW {bandwidth_hz/1000:.0f} kHz"
    )
    return result


def extract_features(samples, sample_rate: float) -> dict:
    """Extract signal features for modulation classification.

    Returns dict of numeric features used by the classifier.
    """
    # --- Envelope statistics ---
    envelope = np.abs(samples)
    env_mean = np.mean(envelope)
    env_std = np.std(envelope)
    env_std_ratio = env_std / (env_mean + 1e-10)

    # Kurtosis (peakedness — OFDM has high kurtosis due to PAPR)
    env_centered = envelope - env_mean
    env_m4 = np.mean(env_centered ** 4)
    env_m2 = np.mean(env_centered ** 2)
    env_kurtosis = env_m4 / (env_m2 ** 2 + 1e-10)

    # --- SNR ---
    # Use spectral approach: compare peak spectrum power to median (noise floor)
    # This works for both continuous and bursty signals
    spectrum_tmp = np.abs(np.fft.fft(samples))
    spec_db_tmp = 20 * np.log10(spectrum_tmp + 1e-10)
    spec_peak = np.max(spec_db_tmp)
    spec_median = np.median(spec_db_tmp)
    snr_db = spec_peak - spec_median

    # --- Envelope bimodality (for OOK detection) ---
    # Histogram the envelope and check for two peaks (on/off)
    bimodality = 0.0
    ook_duty = 0.5
    env_range = float(np.ptp(envelope))
    if env_range > 1e-6:
        try:
            hist, bin_edges = np.histogram(envelope, bins=50)
        except ValueError:
            try:
                hist, bin_edges = np.histogram(envelope, bins='auto')
            except ValueError:
                hist, bin_edges = np.histogram(envelope, bins=10, range=(float(np.min(envelope)), float(np.max(envelope)) + 1e-10))
        hist_norm = hist / (np.sum(hist) + 1e-10)

        # Find peaks in histogram
        peaks = []
        for i in range(1, len(hist_norm) - 1):
            if hist_norm[i] > hist_norm[i-1] and hist_norm[i] > hist_norm[i+1]:
                if hist_norm[i] > 0.02:
                    peaks.append((i, hist_norm[i]))

        if len(peaks) >= 2:
            peaks.sort(key=lambda x: x[1], reverse=True)
            top2 = peaks[:2]
            gap = abs(top2[0][0] - top2[1][0]) / len(hist_norm)
            bimodality = min(1.0, gap * 2)
            midpoint = (bin_edges[top2[0][0]] + bin_edges[top2[1][0]]) / 2
            ook_duty = np.mean(envelope > midpoint)

    # --- Instantaneous frequency ---
    phase_diff = np.angle(samples[1:] * np.conj(samples[:-1]))
    inst_freq = phase_diff * sample_rate / (2 * np.pi)
    freq_std = np.std(inst_freq)

    # Frequency bimodality (for FSK)
    freq_bimodality = 0.0
    freq_range = float(np.ptp(inst_freq))
    if freq_range > 1e-6:
        try:
            freq_hist, _ = np.histogram(inst_freq, bins=50)
        except ValueError:
            freq_hist, _ = np.histogram(inst_freq, bins='auto')
        freq_hist_norm = freq_hist / (np.sum(freq_hist) + 1e-10)
        freq_peaks = []
        for i in range(1, len(freq_hist_norm) - 1):
            if freq_hist_norm[i] > freq_hist_norm[i-1] and freq_hist_norm[i] > freq_hist_norm[i+1]:
                if freq_hist_norm[i] > 0.02:
                    freq_peaks.append((i, freq_hist_norm[i]))
        if len(freq_peaks) >= 2:
            freq_peaks.sort(key=lambda x: x[1], reverse=True)
            gap = abs(freq_peaks[0][0] - freq_peaks[1][0]) / len(freq_hist_norm)
            freq_bimodality = min(1.0, gap * 2)

    # --- Phase statistics ---
    # Unwrap phase and check for discrete jumps (PSK) vs smooth (FM)
    phase = np.angle(samples)
    phase_diff_unwrapped = np.diff(phase)
    # Wrap to [-pi, pi]
    phase_diff_unwrapped = (phase_diff_unwrapped + np.pi) % (2 * np.pi) - np.pi
    phase_std = np.std(phase_diff_unwrapped)

    # Constellation point estimation (for PSK/QAM)
    # Quantize phase into bins and count dominant clusters
    phase_quantized = np.round(phase / (np.pi / 4)) * (np.pi / 4)
    unique_phases = len(np.unique(phase_quantized))
    # Map to nearest standard constellation
    constellation_map = {2: 2, 3: 2, 4: 4, 5: 4, 6: 8, 7: 8, 8: 8}
    constellation_points = constellation_map.get(min(unique_phases, 8), 0)

    # --- Spectral occupancy ---
    spectrum = np.abs(np.fft.fftshift(np.fft.fft(samples)))
    spectrum_db = 20 * np.log10(spectrum + 1e-10)
    spec_noise = np.median(spectrum_db)
    occupied = np.sum(spectrum_db > spec_noise + 6)
    spectral_occ = occupied / len(spectrum)

    # Occupied bandwidth (at -10 dB from peak)
    spec_peak = np.max(spectrum_db)
    above_thresh = spectrum_db > (spec_peak - 10)
    occupied_bins = np.sum(above_thresh)
    occupied_bw = occupied_bins * sample_rate / len(spectrum)

    return {
        "snr_db": snr_db,
        "envelope_std_ratio": env_std_ratio,
        "envelope_kurtosis": env_kurtosis,
        "envelope_bimodality": bimodality,
        "ook_duty_cycle": ook_duty,
        "inst_freq_std_hz": freq_std,
        "freq_bimodality": freq_bimodality,
        "phase_std": phase_std,
        "constellation_points": constellation_points,
        "spectral_occupancy": spectral_occ,
        "occupied_bw_hz": occupied_bw,
    }


def classify_batch(samples, sample_rate: float, segment_ms: float = 50.0,
                   min_snr_db: float = 6.0) -> list:
    """Classify modulation in multiple segments of a long capture.

    Useful for wideband captures where different signals may be present
    at different times.

    Args:
        samples: Complex IQ samples
        sample_rate: Sample rate in Hz
        segment_ms: Segment duration for classification
        min_snr_db: Minimum SNR

    Returns:
        List of (start_s, result_dict) tuples
    """
    seg_len = int(segment_ms * sample_rate / 1000)
    if seg_len < 256:
        seg_len = 256

    results = []
    for i in range(0, len(samples) - seg_len + 1, seg_len):
        segment = samples[i:i + seg_len]
        result = classify_modulation(segment, sample_rate, min_snr_db)
        if result["modulation"] != "Noise":
            results.append((i / sample_rate, result))

    return results

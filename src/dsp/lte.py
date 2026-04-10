"""
LTE Uplink Power Density Analysis Functions

Pure signal processing for measuring LTE uplink band power density.
Detects aggregate phone activity as power rises above a baseline.
No hardware access, no state.
"""

import numpy as np

# Power density analysis
SEGMENT_BANDWIDTH = 1.0e6


def measure_power_spectrum(samples, sample_rate):
    """
    Compute power spectral density from IQ samples.

    Returns dict with overall power, per-segment power, and noise floor.
    """
    nfft = 4096
    window = np.hanning(len(samples))
    windowed = samples * window
    fft_result = np.fft.fftshift(np.fft.fft(windowed, nfft))
    power_spectrum = 20 * np.log10(np.abs(fft_result) + 1e-10)
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / sample_rate))

    overall_power = np.mean(power_spectrum)
    noise_floor = np.percentile(power_spectrum, 10)
    peak_power = np.max(power_spectrum)

    num_segments = max(1, int(sample_rate / SEGMENT_BANDWIDTH))
    segment_size = nfft // num_segments
    segments = []
    for i in range(num_segments):
        seg_start = i * segment_size
        seg_end = (i + 1) * segment_size
        seg_power = np.mean(power_spectrum[seg_start:seg_end])
        seg_freq_offset = freqs[seg_start + segment_size // 2]
        segments.append({
            'freq_offset': seg_freq_offset,
            'power_db': round(seg_power, 2),
        })

    return {
        'overall_power_db': round(overall_power, 2),
        'noise_floor_db': round(noise_floor, 2),
        'peak_power_db': round(peak_power, 2),
        'segments': segments,
    }


def compute_band_summary(measurements):
    """Compute summary statistics for a list of power measurements."""
    if not measurements:
        return None

    powers = [m['overall_power_db'] for m in measurements]
    return {
        'avg_power_db': round(np.mean(powers), 2),
        'peak_power_db': round(max(m['peak_power_db'] for m in measurements), 2),
        'noise_floor_db': round(np.mean([m['noise_floor_db'] for m in measurements]), 2),
        'num_steps': len(measurements),
    }

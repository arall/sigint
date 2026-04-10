"""
ELRS / Crossfire Drone Control Link Detection

Detects FPV drone control links by analyzing burst timing patterns in
the 868/915 MHz ISM band. These links use frequency-hopping spread
spectrum (FHSS) with distinctive periodic timing:

- ELRS: LoRa CSS modulation, hops at 50/150/250/500 Hz packet rates
- Crossfire (TBS): FSK modulation, fixed 150 Hz hop rate, ±42.48 kHz shift

Detection strategy:
1. Energy detection — find short bursts above noise floor
2. Burst timing analysis — measure inter-burst intervals
3. Periodicity detection — autocorrelation to find regular hop rates
4. Classification — match hop rate to known drone protocols

Distinguished from regular LoRa by timing: LoRa/Meshtastic has sporadic,
irregular bursts. ELRS/Crossfire has metronomic, clock-like periodicity.
"""

import numpy as np
from scipy import signal as scipy_signal

# Known drone control hop rates (Hz)
ELRS_RATES = [25, 50, 150, 250, 500]  # ELRS packet rates at 868/915 MHz
CROSSFIRE_RATE = 150  # TBS Crossfire is always 150 Hz

# Detection thresholds
BURST_SNR_THRESHOLD_DB = 6
MIN_BURSTS_FOR_DETECTION = 10
PERIODICITY_THRESHOLD = 0.4  # Autocorrelation peak must exceed this


def detect_fhss_bursts(samples, sample_rate, snr_threshold_db=BURST_SNR_THRESHOLD_DB):
    """
    Detect short energy bursts characteristic of FHSS drone control links.

    Returns list of burst start times (in seconds) and noise floor.
    ELRS/Crossfire bursts are 1-10 ms, much shorter than LoRa packets.
    """
    envelope = np.abs(samples)

    # Low-pass filter — wider than keyfob (FHSS hops are fast)
    nyq = sample_rate / 2
    cutoff = min(200000 / nyq, 0.99)
    b, a = scipy_signal.butter(3, cutoff, btype='low')
    envelope = scipy_signal.lfilter(b, a, envelope)

    noise_floor = np.percentile(envelope, 30)
    noise_db = 20 * np.log10(noise_floor + 1e-10)
    threshold = noise_floor * (10 ** (snr_threshold_db / 20))

    # Find burst edges
    above = envelope > threshold
    transitions = np.diff(above.astype(int))
    starts = np.where(transitions == 1)[0]
    ends = np.where(transitions == -1)[0]

    if len(starts) == 0 or len(ends) == 0:
        return [], noise_db, 0

    if ends[0] < starts[0]:
        ends = ends[1:]
    min_len = min(len(starts), len(ends))
    starts = starts[:min_len]
    ends = ends[:min_len]

    # Filter: FHSS bursts are 0.5-15 ms
    burst_times = []
    peak_power_db = noise_db
    for s, e in zip(starts, ends):
        duration_ms = (e - s) / sample_rate * 1000
        if 0.5 <= duration_ms <= 15:
            burst_times.append(s / sample_rate)
            burst_power = 20 * np.log10(np.mean(envelope[s:e]) + 1e-10)
            peak_power_db = max(peak_power_db, burst_power)

    return burst_times, noise_db, peak_power_db


def analyze_hop_periodicity(burst_times, candidate_rates=None):
    """
    Analyze burst timing for periodic hopping patterns.

    Uses autocorrelation of inter-burst intervals to detect regular
    hop rates. Returns the best matching rate and confidence score.

    Args:
        burst_times: List of burst start times in seconds
        candidate_rates: List of hop rates to check (Hz). Default: ELRS + Crossfire rates

    Returns:
        dict with: detected, hop_rate_hz, confidence, protocol, details
    """
    if candidate_rates is None:
        candidate_rates = ELRS_RATES + [CROSSFIRE_RATE]
        candidate_rates = sorted(set(candidate_rates))

    result = {
        'detected': False,
        'hop_rate_hz': 0,
        'confidence': 0.0,
        'protocol': 'Unknown',
        'num_bursts': len(burst_times),
        'details': '',
    }

    if len(burst_times) < MIN_BURSTS_FOR_DETECTION:
        result['details'] = f"Too few bursts ({len(burst_times)})"
        return result

    # Compute inter-burst intervals
    intervals = np.diff(burst_times)
    if len(intervals) < 5:
        return result

    intervals_ms = intervals * 1000

    # Direct approach: find the dominant interval from the median,
    # then match to known rates. This is more reliable than autocorrelation
    # for distinguishing 150 Hz from its subharmonics.
    median_interval_ms = np.median(intervals_ms)

    # Check how consistent the intervals are (low std = periodic)
    # Filter outliers first (> 3x median are likely missed bursts)
    clean_intervals = intervals_ms[intervals_ms < median_interval_ms * 3]
    if len(clean_intervals) < 5:
        return result

    interval_std = np.std(clean_intervals)
    consistency = 1.0 - min(1.0, interval_std / (median_interval_ms + 1e-10))

    if consistency < PERIODICITY_THRESHOLD:
        return result  # Not periodic enough

    # Match median interval to known rates
    measured_rate = 1000.0 / median_interval_ms  # Convert ms interval to Hz
    best_rate = 0
    best_score = 0
    for rate in candidate_rates:
        expected_ms = 1000.0 / rate
        # Allow 20% tolerance
        if abs(median_interval_ms - expected_ms) / expected_ms < 0.20:
            score = consistency * (1.0 - abs(median_interval_ms - expected_ms) / expected_ms)
            if score > best_score:
                best_score = score
                best_rate = rate

    # Classify
    if best_score >= PERIODICITY_THRESHOLD and best_rate > 0:
        result['detected'] = True
        result['hop_rate_hz'] = best_rate
        result['confidence'] = min(1.0, best_score)

        # Identify protocol
        if best_rate == 150:
            # Could be either ELRS 150 Hz or Crossfire
            # Check interval consistency — Crossfire is more precise
            expected_interval = 1000 / 150  # 6.67 ms
            matching = [i for i in intervals_ms if abs(i - expected_interval) < 1.0]
            consistency = len(matching) / len(intervals_ms) if intervals_ms.size > 0 else 0

            if consistency > 0.5:
                result['protocol'] = 'ELRS/Crossfire'
                result['details'] = (
                    f"150 Hz hop rate, {len(burst_times)} bursts, "
                    f"confidence {best_score:.2f}, "
                    f"interval consistency {consistency:.0%}"
                )
            else:
                result['protocol'] = 'ELRS'
                result['details'] = (
                    f"150 Hz hop rate (variable timing), "
                    f"{len(burst_times)} bursts, confidence {best_score:.2f}"
                )
        elif best_rate in ELRS_RATES:
            result['protocol'] = 'ELRS'
            result['details'] = (
                f"{best_rate} Hz hop rate, {len(burst_times)} bursts, "
                f"confidence {best_score:.2f}"
            )
        else:
            result['protocol'] = 'FHSS-Unknown'
            result['details'] = (
                f"{best_rate} Hz hop rate, {len(burst_times)} bursts, "
                f"confidence {best_score:.2f}"
            )

    return result

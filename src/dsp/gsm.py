"""
GSM Uplink Signal Analysis Functions

Pure signal processing for detecting GSM TDMA uplink bursts (~577us energy
pulses from handset transmissions). No hardware access, no state.
"""

import numpy as np
from scipy import signal as scipy_signal

# GSM TDMA parameters
GSM_TIMESLOT_US = 577
GSM_FRAME_US = 4615
GSM_CHANNEL_SPACING = 200e3

# Detection thresholds
BURST_MIN_DURATION_US = 400
BURST_MAX_DURATION_US = 800
BURST_SNR_THRESHOLD_DB = 8


def detect_uplink_bursts(samples, sample_rate, snr_threshold_db=BURST_SNR_THRESHOLD_DB):
    """
    Detect GSM uplink bursts (short energy pulses from handset transmissions).

    Returns (bursts_list, noise_floor_db).
    """
    envelope = np.abs(samples)

    nyq = sample_rate / 2
    cutoff = min(100000 / nyq, 0.99)
    b, a = scipy_signal.butter(3, cutoff, btype='low')
    envelope = scipy_signal.lfilter(b, a, envelope)

    noise_floor = np.percentile(envelope, 30)
    noise_db = 20 * np.log10(noise_floor + 1e-10)

    threshold = noise_floor * (10 ** (snr_threshold_db / 20))
    above = envelope > threshold

    transitions = np.diff(above.astype(int))
    starts = np.where(transitions == 1)[0]
    ends = np.where(transitions == -1)[0]

    if len(starts) == 0 or len(ends) == 0:
        return [], noise_db

    if ends[0] < starts[0]:
        ends = ends[1:]
    min_len = min(len(starts), len(ends))
    starts = starts[:min_len]
    ends = ends[:min_len]

    bursts = []
    for s, e in zip(starts, ends):
        duration_us = (e - s) / sample_rate * 1e6
        if BURST_MIN_DURATION_US <= duration_us <= BURST_MAX_DURATION_US:
            burst_power = np.mean(envelope[s:e])
            power_db = 20 * np.log10(burst_power + 1e-10)
            snr = power_db - noise_db
            bursts.append({
                'start_sample': int(s),
                'end_sample': int(e),
                'duration_us': round(duration_us, 1),
                'power_db': round(power_db, 1),
                'snr_db': round(snr, 1),
                'time_offset_ms': round(s / sample_rate * 1000, 2),
            })

    return bursts, noise_db


def estimate_active_devices(bursts, sample_rate):
    """
    Estimate number of active devices from burst patterns.

    Each GSM device uses one timeslot per frame. Bursts per frame ~ active devices.
    """
    if len(bursts) < 2:
        return len(bursts)

    frame_duration_samples = int(GSM_FRAME_US * sample_rate / 1e6)
    if len(bursts) == 0:
        return 0

    first_sample = bursts[0]['start_sample']
    last_sample = bursts[-1]['start_sample']
    total_frames = max(1, (last_sample - first_sample) / frame_duration_samples)

    bursts_per_frame = len(bursts) / total_frames
    return max(1, round(bursts_per_frame))

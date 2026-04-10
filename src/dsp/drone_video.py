"""
Drone Video Link Detection — DSP analysis for wideband OFDM signals.

Detects drone video downlink transmissions (DJI O4, Occusync, etc.) by
analysing IQ samples for wideband OFDM characteristics that differ from
standard 802.11 WiFi:

- Spectral flatness (OFDM flat-top signature)
- Occupied bandwidth not matching standard WiFi channel widths
- High duty cycle (continuous video stream vs bursty WiFi)
- Frequency-hopping behaviour across the ISM band

Pure functions — no hardware, no state.
"""

import numpy as np

# Standard 802.11 channel center frequencies in 2.4 GHz band (Hz)
WIFI_CHANNELS_24 = [
    2.412e9, 2.417e9, 2.422e9, 2.427e9, 2.432e9, 2.437e9,
    2.442e9, 2.447e9, 2.452e9, 2.457e9, 2.462e9, 2.467e9, 2.472e9,
]

# Tolerance for WiFi channel matching (Hz)
WIFI_CHANNEL_TOLERANCE = 1e6


def compute_spectrogram(samples, sample_rate, fft_size=1024, overlap=0.5):
    """Compute spectrogram from IQ samples.

    Returns (times, freqs, power_db) where power_db is in dB relative to
    full-scale.  *freqs* are frequency offsets from DC in Hz.
    """
    hop = int(fft_size * (1 - overlap))
    n_frames = max(1, (len(samples) - fft_size) // hop)
    window = np.hanning(fft_size)

    power = np.empty((n_frames, fft_size), dtype=np.float32)
    for i in range(n_frames):
        seg = samples[i * hop: i * hop + fft_size]
        spec = np.fft.fftshift(np.fft.fft(seg * window))
        power[i] = 10 * np.log10(np.abs(spec) ** 2 + 1e-20)

    freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, 1 / sample_rate))
    times = np.arange(n_frames) * hop / sample_rate
    return times, freqs, power


def detect_ofdm_bursts(samples, sample_rate, fft_size=1024,
                       min_bw_hz=5e6, min_snr_db=8.0):
    """Detect wideband OFDM-like energy bursts in IQ samples.

    Looks for time-frequency regions with:
    - Occupied bandwidth >= *min_bw_hz*
    - Spectral flatness consistent with OFDM
    - Power above noise + *min_snr_db*

    Returns list of dicts with keys: start_s, duration_s, center_freq_offset_hz,
    bandwidth_hz, power_db, noise_db, flatness.
    """
    times, freqs, power_db = compute_spectrogram(
        samples, sample_rate, fft_size)

    if len(times) == 0:
        return [], -100.0

    freq_res = freqs[1] - freqs[0]
    min_bins = int(min_bw_hz / freq_res)

    # Estimate noise floor from quietest 25% of all spectral frames
    frame_medians = np.median(power_db, axis=1)
    noise_db = float(np.percentile(frame_medians, 25))

    threshold = noise_db + min_snr_db
    bursts = []

    for i, t in enumerate(times):
        row = power_db[i]
        active = row > threshold

        # Find contiguous runs of active bins
        regions = _contiguous_regions(active)
        for start_bin, end_bin in regions:
            width = end_bin - start_bin
            if width < min_bins:
                continue

            region_power = row[start_bin:end_bin]
            bw = width * freq_res
            center_offset = (freqs[start_bin] + freqs[end_bin - 1]) / 2
            peak_power = float(np.max(region_power))
            flatness = _spectral_flatness(region_power)

            bursts.append({
                "start_s": float(t),
                "duration_s": float(times[1] - times[0]) if len(times) > 1 else 0,
                "center_freq_offset_hz": float(center_offset),
                "bandwidth_hz": float(bw),
                "power_db": peak_power,
                "noise_db": noise_db,
                "flatness": float(flatness),
            })

    return bursts, noise_db


def _contiguous_regions(mask):
    """Find start/end indices of contiguous True regions in a boolean array."""
    regions = []
    in_region = False
    start = 0
    for i, v in enumerate(mask):
        if v and not in_region:
            start = i
            in_region = True
        elif not v and in_region:
            regions.append((start, i))
            in_region = False
    if in_region:
        regions.append((start, len(mask)))
    return regions


def _spectral_flatness(power_db):
    """Compute spectral flatness (0-1) in dB domain.

    OFDM signals have high flatness (~0.7-1.0) due to uniform subcarrier
    power.  Narrowband or noise-like signals score lower.
    """
    linear = 10 ** (power_db / 10)
    geo_mean = np.exp(np.mean(np.log(linear + 1e-20)))
    arith_mean = np.mean(linear)
    if arith_mean < 1e-20:
        return 0.0
    return float(geo_mean / arith_mean)


def measure_duty_cycle(bursts, total_duration_s):
    """Fraction of time the signal is present.

    Drone video links have high duty cycle (>0.5) since they stream
    continuously.  WiFi is bursty (<0.3 typical).
    """
    if not bursts or total_duration_s <= 0:
        return 0.0
    active_time = sum(b["duration_s"] for b in bursts)
    return min(1.0, active_time / total_duration_s)


def is_wifi_channel(center_freq_hz, tolerance=WIFI_CHANNEL_TOLERANCE):
    """Check if a frequency matches a standard 2.4 GHz WiFi channel."""
    for ch_freq in WIFI_CHANNELS_24:
        if abs(center_freq_hz - ch_freq) < tolerance:
            return True
    return False


def classify_bursts(bursts, center_freq, sample_rate):
    """Classify detected OFDM bursts as drone video vs WiFi.

    Args:
        bursts: list from detect_ofdm_bursts()
        center_freq: capture center frequency in Hz
        sample_rate: capture sample rate in Hz

    Returns dict with:
        detected: bool — drone video link detected
        confidence: float 0-1
        bandwidth_hz: estimated signal bandwidth
        duty_cycle: fraction of time signal is present
        center_freq_hz: absolute center frequency
        is_wifi: bool — likely standard WiFi
        n_bursts: number of bursts
    """
    if not bursts:
        return {"detected": False, "confidence": 0, "n_bursts": 0}

    # Aggregate burst statistics
    bws = [b["bandwidth_hz"] for b in bursts]
    centers = [b["center_freq_offset_hz"] for b in bursts]
    flatnesses = [b["flatness"] for b in bursts]
    powers = [b["power_db"] for b in bursts]
    noises = [b["noise_db"] for b in bursts]

    median_bw = float(np.median(bws))
    median_center = float(np.median(centers))
    mean_flatness = float(np.mean(flatnesses))
    peak_power = float(np.max(powers))
    noise_db = float(np.median(noises))
    snr = peak_power - noise_db

    abs_center = center_freq + median_center
    total_duration = bursts[-1]["start_s"] - bursts[0]["start_s"]
    if total_duration <= 0:
        total_duration = bursts[0]["duration_s"] or 0.01
    duty = measure_duty_cycle(bursts, total_duration)

    wifi_match = is_wifi_channel(abs_center)

    # Score confidence that this is a drone video link
    confidence = 0.0

    # Wideband OFDM (>5 MHz): strong indicator
    if median_bw > 5e6:
        confidence += 0.3
    if median_bw > 10e6:
        confidence += 0.1

    # High spectral flatness (OFDM-like)
    if mean_flatness > 0.5:
        confidence += 0.2
    if mean_flatness > 0.7:
        confidence += 0.1

    # High duty cycle (continuous video stream)
    if duty > 0.5:
        confidence += 0.2
    if duty > 0.8:
        confidence += 0.1

    # Not on a standard WiFi channel: strong indicator
    if not wifi_match:
        confidence += 0.2

    # WiFi channel match reduces confidence
    if wifi_match:
        confidence -= 0.3

    # Low duty cycle reduces confidence
    if duty < 0.2:
        confidence -= 0.2

    confidence = max(0.0, min(1.0, confidence))
    detected = confidence >= 0.4 and snr > 6 and len(bursts) >= 3

    return {
        "detected": detected,
        "confidence": round(confidence, 2),
        "bandwidth_hz": round(median_bw),
        "duty_cycle": round(duty, 2),
        "center_freq_hz": round(abs_center),
        "snr_db": round(snr, 1),
        "flatness": round(mean_flatness, 2),
        "is_wifi": wifi_match,
        "n_bursts": len(bursts),
        "power_db": round(peak_power, 1),
        "noise_db": round(noise_db, 1),
    }

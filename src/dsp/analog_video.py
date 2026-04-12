"""
Analog Video DSP — detection, FM demodulation, and frame extraction
for analog FPV drone video (PAL/NTSC composite video over wideband FM).

Pure signal processing — no hardware, no state.
"""

import numpy as np
from scipy import signal as scipy_signal

# Video standards
PAL_LINE_FREQ = 15625.0
NTSC_LINE_FREQ = 15734.264
PAL_LINES = 625
NTSC_LINES = 525

# Detection thresholds
MIN_VIDEO_SNR_DB = 8.0
MIN_VIDEO_BW_MHZ = 3.0


def detect_video_carrier(samples, sample_rate):
    """Detect wideband FM video carrier in IQ samples.

    Returns dict with snr_db, bandwidth_mhz, detected (bool).
    """
    n_fft = 4096
    n_segments = max(1, min(16, len(samples) // n_fft))

    psd = np.zeros(n_fft)
    for i in range(n_segments):
        seg = samples[i * n_fft:(i + 1) * n_fft]
        if len(seg) < n_fft:
            break
        w = np.hanning(n_fft)
        fft = np.fft.fftshift(np.fft.fft(seg * w))
        psd += np.abs(fft) ** 2
    psd /= n_segments

    psd_db = 10 * np.log10(psd + 1e-20)
    noise_floor = np.percentile(psd_db, 20)
    peak_power = np.max(psd_db)
    snr = peak_power - noise_floor

    # Occupied bandwidth at -20 dB from peak
    bw_mask = psd_db > (peak_power - 20)
    occupied = np.sum(bw_mask)
    bw_mhz = occupied * (sample_rate / n_fft) / 1e6

    return {
        "detected": bool(snr >= MIN_VIDEO_SNR_DB and bw_mhz >= MIN_VIDEO_BW_MHZ),
        "snr_db": round(float(snr), 1),
        "peak_power_db": round(float(peak_power), 1),
        "noise_floor_db": round(float(noise_floor), 1),
        "bandwidth_mhz": round(float(bw_mhz), 1),
    }


def fm_demod_video(samples, sample_rate):
    """FM-demodulate IQ to composite video baseband.

    Returns (baseband, sample_rate) — baseband is float32, ±1 range.
    """
    phase_diff = np.angle(samples[1:] * np.conj(samples[:-1]))
    baseband = (phase_diff / np.pi).astype(np.float32)

    # Lowpass to video bandwidth (~6 MHz)
    nyq = sample_rate / 2
    cutoff = min(6e6, nyq * 0.9) / nyq
    b, a = scipy_signal.butter(4, cutoff, btype='low')
    baseband = scipy_signal.lfilter(b, a, baseband).astype(np.float32)

    return baseband, sample_rate


def detect_line_period(baseband, sample_rate):
    """Detect video line period using autocorrelation.

    Returns dict with standard, line_freq_hz, line_period_samples, or None.
    """
    # Use first 500k samples (25ms at 20 MS/s)
    seg = baseband[:min(500000, len(baseband))]
    if len(seg) < 10000:
        return None

    seg = seg - seg.mean()
    template = seg[:5000]
    acf = np.correlate(seg, template, mode='valid')

    # Search around expected PAL/NTSC intervals
    pal_expected = int(sample_rate / PAL_LINE_FREQ)
    ntsc_expected = int(sample_rate / NTSC_LINE_FREQ)

    best_standard = None
    best_period = 0
    best_score = 0

    for expected, name in [(pal_expected, "PAL"), (ntsc_expected, "NTSC")]:
        lo = max(1, int(expected * 0.9))
        hi = min(len(acf), int(expected * 1.1))
        if hi <= lo:
            continue
        region = acf[lo:hi]
        peak_idx = np.argmax(region) + lo
        peak_val = acf[peak_idx]
        if peak_val > best_score:
            best_score = peak_val
            best_period = peak_idx
            best_standard = name

    if best_period == 0 or best_score < acf[0] * 0.1:
        return None

    line_freq = sample_rate / best_period
    # Verify it's close enough to a known standard
    pal_err = abs(line_freq - PAL_LINE_FREQ) / PAL_LINE_FREQ
    ntsc_err = abs(line_freq - NTSC_LINE_FREQ) / NTSC_LINE_FREQ

    if pal_err < 0.05:
        standard = "PAL"
    elif ntsc_err < 0.05:
        standard = "NTSC"
    else:
        return None

    return {
        "standard": standard,
        "line_freq_hz": round(float(line_freq), 1),
        "line_period_samples": int(best_period),
    }


def extract_frame(baseband, sample_rate, line_period, width=320):
    """Extract a video frame as a grayscale numpy array.

    Uses derivative-based sync detection for robustness at low SNR.

    Returns (frame, width, height) or None.
    """
    # Find sync pulses via derivative (negative spikes at line start)
    deriv = np.diff(baseband)
    sync_threshold = np.percentile(deriv, 1)
    sync_raw = np.where(deriv < sync_threshold)[0]

    if len(sync_raw) < 20:
        return None

    # Cluster nearby positions into sync events
    syncs = [sync_raw[0]]
    for pos in sync_raw[1:]:
        if pos - syncs[-1] > line_period * 0.5:
            syncs.append(pos)
    syncs = np.array(syncs)

    if len(syncs) < 20:
        return None

    # Extract lines
    sync_frac = 0.12
    active_frac = 0.82
    sync_samples = int(line_period * sync_frac)
    active_samples = int(line_period * active_frac)
    n_lines = min(480, len(syncs))

    frame = np.zeros((n_lines, width), dtype=np.uint8)
    valid_lines = 0
    for i in range(n_lines):
        start = syncs[i] + sync_samples
        end = start + active_samples
        if end >= len(baseband):
            break
        line = baseband[start:end]
        if len(line) > 1:
            indices = np.linspace(0, len(line) - 1, width).astype(int)
            vals = line[indices]
            pmin, pmax = np.percentile(vals, [2, 98])
            if pmax > pmin:
                vals = (vals - pmin) / (pmax - pmin) * 255
                vals = np.clip(vals, 0, 255)
            frame[i] = vals.astype(np.uint8)
            valid_lines += 1

    if valid_lines < 20:
        return None

    return frame[:valid_lines], width, valid_lines


def frame_to_png(frame, width, height):
    """Encode a grayscale frame as PNG bytes (no PIL dependency)."""
    import struct
    import zlib

    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack(
            '>I', zlib.crc32(c) & 0xffffffff)

    raw = b''
    for row in frame[:height]:
        raw += b'\x00' + row[:width].tobytes()

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(raw))
    png += chunk(b'IEND', b'')
    return png

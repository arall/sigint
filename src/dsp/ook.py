"""
OOK/FSK Signal Analysis Functions

Pure signal processing functions for detecting and fingerprinting OOK
(On-Off Keying) and FSK (Frequency Shift Keying) radio signals. Used by
keyfob, garage door, and ISM band scanners.

These functions take IQ samples in, return analysis results out — no
hardware access, no logging, no state.
"""

from collections import defaultdict
from typing import Dict, List

import numpy as np


# ---------------------------------------------------------------------------
# OOK detection
# ---------------------------------------------------------------------------

def detect_ook_signal(samples, sample_rate, threshold_db=10):
    """Detect OOK/ASK signals and extract pulse + gap timing.

    Returns dict with detection result, power stats, and burst list.
    Each burst includes pulse_us (ON duration) and gap_us (OFF duration
    to next pulse).
    """
    from scipy import signal as scipy_signal

    envelope = np.abs(samples)

    # Low-pass filter the envelope to smooth out subcarrier oscillation
    # This prevents a single OOK pulse from fragmenting into many sub-pulses
    nyq = sample_rate / 2
    cutoff = min(50000 / nyq, 0.99)  # 50 kHz cutoff
    b, a = scipy_signal.butter(3, cutoff, btype='low')
    envelope = scipy_signal.lfilter(b, a, envelope)

    noise_floor = np.percentile(envelope, 30)
    peak = np.max(envelope)

    noise_db = 20 * np.log10(noise_floor + 1e-10)
    peak_db = 20 * np.log10(peak + 1e-10)
    snr = peak_db - noise_db

    threshold = noise_floor * (10 ** (threshold_db / 20))
    above_threshold = envelope > threshold

    transitions = np.diff(above_threshold.astype(int))
    burst_starts = np.where(transitions == 1)[0]
    burst_ends = np.where(transitions == -1)[0]

    burst_info = []
    if len(burst_starts) > 0 and len(burst_ends) > 0:
        for i, start in enumerate(burst_starts):
            # Find corresponding falling edge
            end_candidates = burst_ends[burst_ends > start]
            if len(end_candidates) == 0:
                break
            end = end_candidates[0]
            pulse_us = (end - start) / sample_rate * 1e6

            if pulse_us < 50:
                continue  # Noise

            # Find gap to next pulse
            gap_us = 0
            if i + 1 < len(burst_starts):
                gap_us = (burst_starts[i + 1] - end) / sample_rate * 1e6

            burst_info.append({
                'start_sample': int(start),
                'pulse_us': pulse_us,
                'gap_us': gap_us,
            })

            if len(burst_info) >= 200:  # Enough for analysis
                break

    valid_bursts = len(burst_info)
    is_keyfob_pattern = (
        snr > threshold_db
        and 2 <= valid_bursts <= 500
    )

    return {
        'detected': is_keyfob_pattern,
        'peak_power_db': peak_db,
        'noise_floor_db': noise_db,
        'snr_db': snr,
        'num_bursts': valid_bursts,
        'bursts': burst_info,
    }


# ---------------------------------------------------------------------------
# FSK detection (car keyfobs)
# ---------------------------------------------------------------------------



def detect_fsk_signal(samples, sample_rate, threshold_db=8):
    """Detect FSK-modulated signals by analyzing instantaneous frequency.

    FSK keyfobs transmit a continuous carrier that shifts between two
    frequencies. The OOK detector sees this as 1-2 long bursts because
    the signal is always ON. This function measures the frequency deviation
    and data rate from the phase of the IQ signal.

    Returns dict with FSK parameters or None if not FSK.
    """
    from scipy import signal as scipy_signal

    envelope = np.abs(samples)
    noise_floor = np.percentile(envelope, 30)
    peak = np.max(envelope)
    noise_db = 20 * np.log10(noise_floor + 1e-10)
    peak_db = 20 * np.log10(peak + 1e-10)
    snr = peak_db - noise_db

    if snr < threshold_db:
        return None

    # Find where signal is present (above threshold)
    threshold = noise_floor * (10 ** (threshold_db / 20))
    signal_mask = envelope > threshold
    signal_indices = np.where(signal_mask)[0]

    if len(signal_indices) < 1000:
        return None

    # Extract IQ samples where signal is present
    start = signal_indices[0]
    end = signal_indices[-1]
    duration_ms = (end - start) / sample_rate * 1000

    # FSK signals are typically >5ms continuous
    if duration_ms < 5:
        return None

    signal_iq = samples[start:end + 1]

    # Bandpass filter IQ to isolate the FSK signal (~±100 kHz around center)
    # This removes wideband noise that inflates the deviation measurement
    nyq = sample_rate / 2
    bp_cutoff = min(150000 / nyq, 0.99)  # ±150 kHz
    b_bp, a_bp = scipy_signal.butter(4, bp_cutoff, btype='low')
    signal_iq = scipy_signal.lfilter(b_bp, a_bp, signal_iq)

    # FM discriminator to get instantaneous frequency
    phase_diff = np.angle(signal_iq[1:] * np.conj(signal_iq[:-1]))
    inst_freq = phase_diff * sample_rate / (2 * np.pi)  # Hz

    # Smooth to remove discriminator noise spikes
    if len(inst_freq) > 100:
        lp_cutoff = min(80000 / nyq, 0.99)
        b_lp, a_lp = scipy_signal.butter(3, lp_cutoff, btype='low')
        inst_freq = scipy_signal.lfilter(b_lp, a_lp, inst_freq)

    # Measure frequency deviation (half of peak-to-peak)
    freq_p5 = np.percentile(inst_freq, 5)
    freq_p95 = np.percentile(inst_freq, 95)
    deviation_hz = (freq_p95 - freq_p5) / 2

    if deviation_hz < 5000:
        return None  # Not FSK (too narrow, likely just noise)

    # Measure data rate from zero-crossing rate of demodulated signal
    # The demodulated FSK signal oscillates between +deviation and -deviation
    mean_freq = np.mean(inst_freq)
    zero_crossings = np.where(np.diff(np.sign(inst_freq - mean_freq)))[0]

    if len(zero_crossings) < 10:
        return None

    # Average time between zero crossings = half bit period
    avg_crossing_interval = np.mean(np.diff(zero_crossings)) / sample_rate
    estimated_datarate = 1 / (2 * avg_crossing_interval) if avg_crossing_interval > 0 else 0

    return {
        'is_fsk': True,
        'deviation_hz': deviation_hz,
        'deviation_khz': deviation_hz / 1000,
        'datarate_hz': estimated_datarate,
        'duration_ms': duration_ms,
        'snr_db': snr,
        'peak_power_db': peak_db,
        'noise_floor_db': noise_db,
        'center_offset_hz': mean_freq,  # Offset from tuned frequency
    }


def fingerprint_fsk_car(fsk_result, frequency_hz):
    """Match FSK parameters against known car keyfob profiles.

    Returns dict with protocol, device_type, confidence, details.
    """
    dev_khz = fsk_result['deviation_khz']
    datarate = fsk_result['datarate_hz']
    duration = fsk_result['duration_ms']

    result = {
        'protocol': 'FSK',
        'code_type': 'rolling',  # All car FSK keyfobs use rolling codes
        'bit_count': int(datarate * duration / 1000) if datarate > 0 else 0,
        'data_hex': '',
        'confidence': 'low',
        'details': '',
        'modulation': 'FSK',
        'deviation_khz': round(dev_khz, 1),
        'datarate_hz': int(datarate),
    }

    result['details'] = (
        f"FSK signal, dev=\u00b1{dev_khz:.0f}kHz, "
        f"rate=~{datarate/1000:.0f}kbps, dur={duration:.0f}ms"
    )

    return result


# ---------------------------------------------------------------------------
# Protocol fingerprinting (OOK)
# ---------------------------------------------------------------------------

def _cluster_widths(values, tolerance=0.4):
    """Cluster pulse/gap widths into short and long groups.

    Returns (short_mean, long_mean, ratio) or None if can't separate.
    """
    if len(values) < 4:
        return None

    values = np.array(values, dtype=float)
    vmin, vmax = np.min(values), np.max(values)

    if vmax < 1 or vmin < 1:
        return None

    if vmax / vmin < 1.5:
        return None

    midpoint = (vmin + vmax) / 2
    short = values[values <= midpoint]
    long = values[values > midpoint]

    if len(short) < 2 or len(long) < 2:
        return None

    short_mean = np.mean(short)
    long_mean = np.mean(long)
    ratio = long_mean / short_mean

    if len(short) > 2 and np.std(short) / short_mean > tolerance:
        return None
    if len(long) > 2 and np.std(long) / long_mean > tolerance:
        return None

    return short_mean, long_mean, ratio


def _find_sync_gaps(bursts, threshold_factor=5):
    """Find sync/frame boundary gaps (abnormally long gaps)."""
    gaps = [b['gap_us'] for b in bursts if b['gap_us'] > 0]
    if len(gaps) < 5:
        return []

    median_gap = np.median(gaps)
    return [i for i, b in enumerate(bursts)
            if b['gap_us'] > median_gap * threshold_factor]


def _decode_bits_pulse_gap(bursts, short_threshold):
    """Decode bits from pulse widths: short pulse = 0, long pulse = 1."""
    bits = []
    for b in bursts:
        if b['pulse_us'] <= short_threshold:
            bits.append(0)
        else:
            bits.append(1)
    return bits


def _decode_bits_pt2262(bursts, T):
    """Decode PT2262/EV1527 bits from pulse+gap pairs."""
    bits = []
    for b in bursts:
        p = b['pulse_us']
        g = b['gap_us']
        if g == 0:
            break

        p_short = p < T * 2
        g_short = g < T * 2

        if p_short and not g_short:
            bits.append(0)
        elif not p_short and g_short:
            bits.append(1)
        elif p_short and g_short:
            bits.append('F')
        else:
            bits.append('?')
    return bits


def bits_to_hex(bits):
    """Convert bit list to hex string."""
    hex_str = ""
    for i in range(0, len(bits) - 7, 8):
        byte = 0
        for j in range(8):
            b = bits[i + j]
            if b in (0, 1):
                byte = (byte << 1) | b
            else:
                byte = (byte << 1)  # Treat F/? as 0
        hex_str += f"{byte:02X}"
    return hex_str


def fingerprint_protocol(bursts):
    """Identify OOK protocol from pulse timing patterns.

    Returns dict with:
        protocol: str - protocol name or "Unknown"
        code_type: str - "fixed", "rolling", or "unknown"
        bit_count: int - number of decoded bits
        data_hex: str - decoded data as hex string
        confidence: str - "high", "medium", "low"
        details: str - human-readable summary
    """
    result = {
        'protocol': 'Unknown',
        'code_type': 'unknown',
        'bit_count': 0,
        'data_hex': '',
        'confidence': 'low',
        'details': '',
    }

    if len(bursts) < 5:
        result['details'] = f"Too few pulses ({len(bursts)})"
        return result

    all_pulses = [b['pulse_us'] for b in bursts]
    all_gaps = [b['gap_us'] for b in bursts if b['gap_us'] > 0]

    first_sync = None
    if all_gaps:
        gap_median = np.median(all_gaps)
        for i, b in enumerate(bursts):
            if b['gap_us'] > gap_median * 5 and i >= 5:
                first_sync = i
                break

    frame_bursts = bursts[:first_sync + 1] if first_sync else bursts
    pulses = [b['pulse_us'] for b in frame_bursts]
    gaps = [b['gap_us'] for b in frame_bursts if b['gap_us'] > 0]

    # --- Check for KeeLoq / HCS301 preamble ---
    if len(pulses) >= 30:
        first_25 = pulses[:25]
        first_25_std = np.std(first_25) / (np.mean(first_25) + 1e-10)

        if first_25_std < 0.2:
            preamble_width = np.mean(first_25)
            if 200 < preamble_width < 800:
                remaining_pulses = pulses[23:]
                bit_count = len(remaining_pulses)

                if 60 <= bit_count <= 70:
                    result['protocol'] = 'HCS301 (KeeLoq)'
                    result['code_type'] = 'rolling'
                    result['bit_count'] = bit_count
                    result['confidence'] = 'high'
                    decoded = _decode_bits_pulse_gap(
                        bursts[23:], preamble_width * 1.5)
                    result['data_hex'] = bits_to_hex(decoded)
                    result['details'] = (
                        f"KeeLoq rolling code, {bit_count} bits, "
                        f"preamble={preamble_width:.0f}µs"
                    )
                    return result

                elif 28 <= bit_count <= 36:
                    result['protocol'] = 'HCS200'
                    result['code_type'] = 'rolling'
                    result['bit_count'] = bit_count
                    result['confidence'] = 'medium'
                    decoded = _decode_bits_pulse_gap(
                        bursts[23:], preamble_width * 1.5)
                    result['data_hex'] = bits_to_hex(decoded)
                    result['details'] = (
                        f"HCS200 rolling code, {bit_count} bits, "
                        f"preamble={preamble_width:.0f}µs"
                    )
                    return result

    # --- Check for PT2262 / EV1527 ---
    pulse_clusters = _cluster_widths(pulses)

    if gaps:
        gap_median = np.median(gaps)
        data_gaps = [g for g in gaps if g < gap_median * 5]
    else:
        data_gaps = []
    gap_clusters = _cluster_widths(data_gaps) if len(data_gaps) >= 4 else None

    if pulse_clusters:
        short_p, long_p, p_ratio = pulse_clusters
        T = short_p

        sync_indices = _find_sync_gaps(bursts)

        if 2.2 <= p_ratio <= 4.0 and (gap_clusters or len(pulses) >= 20):
            _, _, g_ratio = gap_clusters

            decoded = _decode_bits_pt2262(frame_bursts, T * 2)

            valid_bits = [b for b in decoded if b in (0, 1, 'F')]
            bit_count = len(valid_bits)

            has_floating = 'F' in valid_bits
            data_bits = [b if b in (0, 1) else 0 for b in valid_bits]

            if 10 <= bit_count <= 14:
                result['protocol'] = 'DIP-switch remote'
                result['code_type'] = 'fixed'
                result['bit_count'] = bit_count
                result['data_hex'] = bits_to_hex(data_bits)
                result['confidence'] = 'high'
                result['details'] = (
                    f"12-bit DIP-switch fixed code, {bit_count} bits, "
                    f"T={T:.0f}µs, ratio={p_ratio:.1f}"
                )
                return result

            elif 20 <= bit_count <= 28:
                if has_floating:
                    result['protocol'] = 'PT2262'
                    result['details'] = (
                        f"PT2262 fixed code, {bit_count} bits, "
                        f"T={T:.0f}µs, ratio={p_ratio:.1f}"
                    )
                else:
                    result['protocol'] = 'EV1527'
                    result['details'] = (
                        f"EV1527 fixed code, {bit_count} bits, "
                        f"T={T:.0f}µs, ratio={p_ratio:.1f}"
                    )

                result['code_type'] = 'fixed'
                result['bit_count'] = bit_count
                result['data_hex'] = bits_to_hex(data_bits)
                result['confidence'] = 'high' if 23 <= bit_count <= 25 else 'medium'
                return result

            elif 60 <= bit_count <= 70:
                result['protocol'] = 'OOK Rolling (Nice/CAME)'
                result['code_type'] = 'rolling'
                result['bit_count'] = bit_count
                result['data_hex'] = bits_to_hex(data_bits)
                result['confidence'] = 'medium'
                result['details'] = (
                    f"66-bit OOK rolling code, {bit_count} bits, "
                    f"T={T:.0f}µs, ratio={p_ratio:.1f}, "
                    f"likely Nice FLOR / CAME TOP series"
                )
                return result

            elif bit_count > 28:
                result['protocol'] = 'Fixed-code OOK'
                result['code_type'] = 'fixed'
                result['bit_count'] = bit_count
                result['data_hex'] = bits_to_hex(data_bits)
                result['confidence'] = 'medium'
                result['details'] = (
                    f"Fixed OOK, {bit_count} bits, "
                    f"T={T:.0f}µs, ratio={p_ratio:.1f}"
                )
                return result

    # --- Heuristic classification ---
    avg_pulse = np.mean(pulses)
    total_bursts = len(all_pulses)

    if first_sync and 20 <= first_sync <= 30:
        frames_detected = total_bursts / (first_sync + 1)
        if frames_detected >= 2:
            decoded = _decode_bits_pulse_gap(frame_bursts, avg_pulse * 1.5)
            data_hex = bits_to_hex(decoded)
            result['protocol'] = 'Fixed-code OOK'
            result['code_type'] = 'fixed'
            result['bit_count'] = len(decoded)
            result['data_hex'] = data_hex
            result['confidence'] = 'medium'
            result['details'] = (
                f"Fixed code (heuristic), {len(decoded)} bits/frame, "
                f"~{frames_detected:.0f} repeats, avg_pulse={avg_pulse:.0f}µs"
            )
            return result

    if total_bursts >= 50 and not first_sync:
        result['protocol'] = 'Rolling-code OOK'
        result['code_type'] = 'rolling'
        result['bit_count'] = total_bursts
        result['confidence'] = 'low'
        result['details'] = (
            f"Likely rolling code, {total_bursts} pulses, "
            f"no frame repetition detected, avg_pulse={avg_pulse:.0f}µs"
        )
        return result

    result['bit_count'] = len(frame_bursts)

    if pulse_clusters:
        short_p, long_p, ratio = pulse_clusters
        decoded = _decode_bits_pulse_gap(bursts, short_p * 1.5)
        result['data_hex'] = bits_to_hex(decoded)
        result['details'] = (
            f"OOK signal, {len(bursts)} pulses, "
            f"short={short_p:.0f}µs, long={long_p:.0f}µs, "
            f"ratio={ratio:.1f}"
        )
        result['confidence'] = 'low'
    else:
        result['details'] = (
            f"OOK signal, {len(bursts)} pulses, "
            f"avg={avg_pulse:.0f}µs"
        )

    return result


def classify_device(protocol, code_type, frequency_hz, fingerprint=None):
    """Estimate device type from protocol and frequency.

    Returns (device_type, icon) tuple.
    """
    freq_mhz = frequency_hz / 1e6
    is_us = abs(freq_mhz - 315) < 5
    is_eu = abs(freq_mhz - 433.92) < 5 or abs(freq_mhz - 868) < 5

    if fingerprint and fingerprint.get('modulation') == 'FSK':
        return "Car keyfob (FSK)", "🚗"

    if 'KeeLoq' in protocol or 'HCS' in protocol:
        region = "US" if is_us else "EU" if is_eu else ""
        return f"{region} car keyfob (rolling code)", "🚗"

    if 'Nice' in protocol or 'CAME' in protocol:
        return "Parking / garage gate remote (OOK rolling code)", "🅿️"

    if 'DIP-switch' in protocol:
        return "Parking / garage DIP-switch remote (fixed code)", "🅿️"

    if protocol in ('PT2262', 'EV1527', 'Fixed-code OOK'):
        if is_eu:
            return "Garage door / gate remote (fixed code)", "🏠"
        elif is_us:
            return "Garage door / remote (fixed code)", "🏠"
        return "Fixed-code remote", "📡"

    if code_type == 'rolling':
        return "Automotive keyfob (rolling code)", "🚗"
    if code_type == 'fixed':
        return "Fixed-code remote", "📡"

    return "Unknown device", "📻"


# ---------------------------------------------------------------------------
# Transmitter tracker
# ---------------------------------------------------------------------------

class TransmitterTracker:
    """Track unique transmitters across presses to determine fixed vs rolling."""

    def __init__(self):
        self._seen_codes: Dict[str, List[str]] = defaultdict(list)

    def track(self, fingerprint: dict) -> dict:
        """Track a fingerprint and determine code behavior."""
        proto = fingerprint['protocol']
        data = fingerprint['data_hex']

        if not data or proto == 'Unknown':
            return fingerprint

        key = f"{proto}_{data[:4]}"
        self._seen_codes[key].append(data)

        all_codes = self._seen_codes[key]
        exact_matches = all_codes.count(data)
        unique_codes = len(set(all_codes))

        fingerprint['repeat_count'] = exact_matches
        fingerprint['unique_codes'] = unique_codes

        if len(all_codes) >= 2:
            if unique_codes == 1:
                fingerprint['code_type'] = 'fixed'
            elif exact_matches == 1 and unique_codes == len(all_codes):
                fingerprint['code_type'] = 'rolling'

        return fingerprint

    @property
    def known_transmitters(self) -> int:
        return len(self._seen_codes)

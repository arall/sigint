"""
TPMS Signal Analysis Functions

Pure signal processing functions for detecting and decoding TPMS (Tire
Pressure Monitoring System) transmissions. Extracts sensor IDs from
OOK/Manchester encoded packets.

These functions take IQ samples in, return analysis results out — no
hardware access, no logging, no state.
"""

import numpy as np
from scipy import signal as scipy_signal


def manchester_decode(bits):
    """
    Decode Manchester encoded bits.
    Manchester (IEEE 802.3): 01 = 0, 10 = 1
    Tolerates isolated errors by skipping invalid pairs instead of stopping.
    """
    decoded = []
    for i in range(0, len(bits) - 1, 2):
        if bits[i] == 0 and bits[i + 1] == 1:
            decoded.append(0)
        elif bits[i] == 1 and bits[i + 1] == 0:
            decoded.append(1)
        # else: skip invalid pair (sync error or noise)
    return decoded


def bits_to_hex(bits):
    """Convert bit array to hex string."""
    hex_str = ""
    for i in range(0, len(bits) - 7, 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        hex_str += f"{byte:02X}"
    return hex_str


def detect_tpms_signal(samples, sample_rate, threshold_db=10):
    """
    Detect TPMS signals using OOK demodulation.

    TPMS typically uses:
    - OOK or FSK modulation
    - ~20 kbps data rate
    - Manchester encoding
    - Packet length ~70-100 bits

    Returns dict with detection info and decoded data if successful.
    """
    # Get amplitude envelope
    envelope = np.abs(samples)

    # Low-pass filter the envelope to smooth it
    nyq = sample_rate / 2
    cutoff = 50000 / nyq  # 50 kHz cutoff
    b, a = scipy_signal.butter(4, cutoff, btype='low')
    envelope_filtered = scipy_signal.lfilter(b, a, envelope)

    # Calculate noise floor and peak
    noise_floor = np.percentile(envelope_filtered, 30)
    peak = np.max(envelope_filtered)

    noise_db = 20 * np.log10(noise_floor + 1e-10)
    peak_db = 20 * np.log10(peak + 1e-10)
    snr = peak_db - noise_db

    # Threshold for bit detection
    threshold = noise_floor * (10 ** (threshold_db / 20))

    # Convert to binary
    binary = (envelope_filtered > threshold).astype(int)

    # Find transitions
    transitions = np.diff(binary)
    rising_edges = np.where(transitions == 1)[0]
    falling_edges = np.where(transitions == -1)[0]

    # Decode bits based on pulse widths
    decoded_bits = []
    packets = []

    if len(rising_edges) > 10 and len(falling_edges) > 10:
        pulse_widths_us = []
        for i, rise in enumerate(rising_edges[:-1]):
            falls_after = falling_edges[falling_edges > rise]
            if len(falls_after) > 0:
                fall = falls_after[0]
                width_us = (fall - rise) / sample_rate * 1e6
                pulse_widths_us.append(width_us)

        # Filter valid TPMS-range pulses (20-200 µs)
        valid_pulses = [w for w in pulse_widths_us if 20 < w < 200]

        if len(valid_pulses) > 8:
            median_width = np.median(valid_pulses)
            threshold_us = median_width * 1.5

            for i, rise in enumerate(rising_edges[:-1]):
                falls_after = falling_edges[falling_edges > rise]
                if len(falls_after) > 0:
                    fall = falls_after[0]
                    width_us = (fall - rise) / sample_rate * 1e6

                    if 20 < width_us < 200:
                        if width_us < threshold_us:
                            decoded_bits.append(0)
                        else:
                            decoded_bits.append(1)

            # Try Manchester decoding on the raw bits
            manchester_bits = manchester_decode(decoded_bits)
            if len(manchester_bits) >= 20:
                decoded_bits = manchester_bits

            # Extract packet (flexible length: take up to 80 bits)
            if len(decoded_bits) >= 16:
                pkt_len = min(len(decoded_bits), 80)
                hex_data = bits_to_hex(decoded_bits[:pkt_len])
                packets.append({
                    'bits': decoded_bits[:pkt_len],
                    'hex': hex_data,
                    'num_pulses': len(valid_pulses)
                })

    # Extract potential sensor ID from packets
    sensor_ids = []
    for packet in packets:
        if len(packet['hex']) >= 8:
            potential_id = packet['hex'][:8]
            if potential_id != "00000000" and potential_id != "FFFFFFFF":
                sensor_ids.append(potential_id)

    return {
        'detected': snr > threshold_db and len(packets) > 0,
        'peak_power_db': peak_db,
        'noise_floor_db': noise_db,
        'snr_db': snr,
        'packets': packets,
        'sensor_ids': sensor_ids,
        'num_pulses': len(rising_edges)
    }

#!/usr/bin/env python3
"""
Generate TPMS-like OOK test signal via HackRF.
Transmits a Manchester-encoded packet at 433.92 MHz.
"""

import numpy as np
import subprocess
import tempfile
import os

FREQUENCY = 433_920_000  # 433.92 MHz
SAMPLE_RATE = 2_000_000
TX_AMP = 0
VGA_GAIN = 20


def generate_tpms_signal(sample_rate, bit_rate=20000, num_repeats=3):
    """Generate TPMS-like OOK packet with Manchester encoding.

    Simulates: preamble (0xAA 0xAA) + sensor_id (0xDEADBEEF) + pressure/temp + checksum
    """
    # TPMS packet: preamble + data
    preamble = [1, 0] * 16  # 0xAAAA preamble (Manchester-friendly)
    sensor_id = []
    for byte in [0xDE, 0xAD, 0xBE, 0xEF]:
        for bit in range(7, -1, -1):
            sensor_id.append((byte >> bit) & 1)
    # Pressure (30 PSI = 0x1E) + temp (25C = 0x19) + dummy checksum (0xFF)
    payload = []
    for byte in [0x1E, 0x19, 0xFF]:
        for bit in range(7, -1, -1):
            payload.append((byte >> bit) & 1)

    raw_bits = preamble + sensor_id + payload

    # Manchester encode: 0 -> 01, 1 -> 10
    manchester = []
    for b in raw_bits:
        if b == 0:
            manchester.extend([0, 1])
        else:
            manchester.extend([1, 0])

    # Convert to OOK samples
    samples_per_half_bit = int(sample_rate / bit_rate / 2)
    silence_pad = int(sample_rate * 0.1)
    gap = int(sample_rate * 10e-3)  # 10ms between repeats

    all_samples = []
    all_samples.append(np.zeros(silence_pad, dtype=np.complex64))

    for rep in range(num_repeats):
        for bit in manchester:
            if bit == 1:
                t = np.arange(samples_per_half_bit) / sample_rate
                carrier = np.exp(2j * np.pi * 50000 * t).astype(np.complex64) * 0.9
                all_samples.append(carrier)
            else:
                all_samples.append(np.zeros(samples_per_half_bit, dtype=np.complex64))
        all_samples.append(np.zeros(gap, dtype=np.complex64))

    all_samples.append(np.zeros(silence_pad, dtype=np.complex64))
    return np.concatenate(all_samples)


def iq_to_hackrf_format(iq_samples):
    i = np.real(iq_samples) * 127
    q = np.imag(iq_samples) * 127
    interleaved = np.empty(len(iq_samples) * 2, dtype=np.int8)
    interleaved[0::2] = i.astype(np.int8)
    interleaved[1::2] = q.astype(np.int8)
    return interleaved


def main():
    print("Generating TPMS test signal (Manchester OOK, sensor ID 0xDEADBEEF)...")
    iq = generate_tpms_signal(SAMPLE_RATE)
    raw = iq_to_hackrf_format(iq)
    print(f"  {len(iq)} samples, {len(iq)/SAMPLE_RATE*1000:.0f} ms duration")

    tmpfile = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    raw.tofile(tmpfile)
    tmpfile.close()

    print(f"\nTransmitting at {FREQUENCY/1e6} MHz...")
    cmd = [
        "hackrf_transfer", "-t", tmpfile.name,
        "-f", str(FREQUENCY), "-s", str(SAMPLE_RATE),
        "-x", str(VGA_GAIN), "-a", str(TX_AMP), "-R",
    ]
    try:
        subprocess.run(cmd, timeout=5, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        print("  TX completed")
    finally:
        os.unlink(tmpfile.name)
    print("Done.")


if __name__ == "__main__":
    main()

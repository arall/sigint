#!/usr/bin/env python3
"""TX a KeeLoq/HCS301-style rolling-code signal (car keyfob)."""

import numpy as np
import subprocess
import tempfile
import os

FREQUENCY = 433_920_000
SAMPLE_RATE = 2_000_000
VGA_GAIN = 20

# KeeLoq HCS301: 23-pulse preamble + 66-bit encrypted payload
PREAMBLE_PULSES = 23
PREAMBLE_WIDTH = 500e-6  # 500µs per preamble pulse
PREAMBLE_GAP = 500e-6
DATA_SHORT = 400e-6  # Short pulse = 0
DATA_LONG = 800e-6   # Long pulse = 1
DATA_GAP = 400e-6
HEADER_GAP = 10e-3   # 10ms gap after preamble


def generate_keeloq(sample_rate, num_repeats=3):
    """Generate KeeLoq-style OOK signal with preamble + data."""
    # Random 66-bit payload (simulates encrypted rolling code)
    rng = np.random.RandomState(42)
    payload = rng.randint(0, 2, 66).tolist()

    samples = []
    pad = np.zeros(int(sample_rate * 0.1), dtype=np.complex64)
    samples.append(pad)

    for rep in range(num_repeats):
        # Preamble: 23 identical short pulses
        for _ in range(PREAMBLE_PULSES):
            t = np.arange(int(sample_rate * PREAMBLE_WIDTH)) / sample_rate
            carrier = np.exp(2j * np.pi * 50000 * t).astype(np.complex64) * 0.9
            samples.append(carrier)
            samples.append(np.zeros(int(sample_rate * PREAMBLE_GAP), dtype=np.complex64))

        # Header gap
        samples.append(np.zeros(int(sample_rate * HEADER_GAP), dtype=np.complex64))

        # Data: 66 bits
        for bit in payload:
            if bit == 0:
                width = DATA_SHORT
            else:
                width = DATA_LONG
            t = np.arange(int(sample_rate * width)) / sample_rate
            carrier = np.exp(2j * np.pi * 50000 * t).astype(np.complex64) * 0.9
            samples.append(carrier)
            samples.append(np.zeros(int(sample_rate * DATA_GAP), dtype=np.complex64))

        # Inter-frame gap
        samples.append(np.zeros(int(sample_rate * 0.02), dtype=np.complex64))

    samples.append(pad)
    return np.concatenate(samples)


def iq_to_hackrf(iq):
    i = np.real(iq) * 127
    q = np.imag(iq) * 127
    out = np.empty(len(iq) * 2, dtype=np.int8)
    out[0::2] = i.astype(np.int8)
    out[1::2] = q.astype(np.int8)
    return out


def main():
    print("Generating KeeLoq/HCS301 rolling-code signal...")
    print(f"  {PREAMBLE_PULSES}-pulse preamble + 66-bit payload, 3 repeats")

    iq = generate_keeloq(SAMPLE_RATE)
    raw = iq_to_hackrf(iq)
    print(f"  {len(iq)/SAMPLE_RATE*1000:.0f} ms duration")

    tmpfile = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    raw.tofile(tmpfile)
    tmpfile.close()

    print(f"\nTransmitting at {FREQUENCY/1e6} MHz...")
    try:
        subprocess.run([
            "hackrf_transfer", "-t", tmpfile.name,
            "-f", str(FREQUENCY), "-s", str(SAMPLE_RATE),
            "-x", str(VGA_GAIN), "-a", "0",
        ], timeout=8, capture_output=True)
    except subprocess.TimeoutExpired:
        pass
    finally:
        os.unlink(tmpfile.name)
    print("Done.")


if __name__ == "__main__":
    main()

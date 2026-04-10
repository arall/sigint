#!/usr/bin/env python3
"""TX a PT2262-style fixed-code signal (garage door / cheap remote)."""

import numpy as np
import subprocess
import tempfile
import os

FREQUENCY = 433_920_000
SAMPLE_RATE = 2_000_000
VGA_GAIN = 20

# PT2262: T=350µs, short pulse=1T, long pulse=3T, sync gap=31T
T = 350e-6  # Base time unit in seconds
CODE = [0, 1, 0, 1, 1, 0, 0, 1,  # 8 address bits
        1, 0, 1, 1,                 # 4 data bits
        0, 1, 0, 1, 1, 0, 0, 1,    # Repeat for 24 bits total
        1, 0, 1, 1]


def generate_pt2262(sample_rate, code, T, num_repeats=4):
    """Generate PT2262 OOK signal.

    Encoding: 0 = short(1T) pulse + long(3T) gap
              1 = long(3T) pulse + short(1T) gap
    Frame ends with sync: short(1T) pulse + 31T gap
    """
    samples = []
    pad = np.zeros(int(sample_rate * 0.1), dtype=np.complex64)
    samples.append(pad)

    for _ in range(num_repeats):
        for bit in code:
            if bit == 0:
                pulse = int(sample_rate * T * 1)
                gap = int(sample_rate * T * 3)
            else:
                pulse = int(sample_rate * T * 3)
                gap = int(sample_rate * T * 1)

            t = np.arange(pulse) / sample_rate
            t = np.arange(pulse) / sample_rate
            carrier = np.exp(2j * np.pi * 50000 * t).astype(np.complex64) * 0.9
            samples.append(carrier)
            samples.append(np.zeros(gap, dtype=np.complex64))

        # Sync gap: short pulse + 31T gap
        t = np.arange(int(sample_rate * T)) / sample_rate
        t_sync = np.arange(int(sample_rate * T)) / sample_rate
        samples.append(np.exp(2j * np.pi * 50000 * t_sync).astype(np.complex64) * 0.9)
        samples.append(np.zeros(int(sample_rate * T * 31), dtype=np.complex64))

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
    print("Generating PT2262 fixed-code signal...")
    print(f"  Code: {''.join(str(b) for b in CODE)} (24 bits)")
    print(f"  T={T*1e6:.0f}µs, 4 repeats + sync gaps")

    iq = generate_pt2262(SAMPLE_RATE, CODE, T)
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
        ], timeout=5, capture_output=True)
    except subprocess.TimeoutExpired:
        pass
    finally:
        os.unlink(tmpfile.name)
    print("Done.")


if __name__ == "__main__":
    main()

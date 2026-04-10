#!/usr/bin/env python3
"""
Generate OOK keyfob-like test signal via HackRF.
Transmits a short burst pattern at 433.92 MHz for testing the keyfob scanner.

Uses hackrf_transfer with a pre-generated IQ file.
Minimum TX power, short duration.
"""

import numpy as np
import subprocess
import tempfile
import os
import sys

FREQUENCY = 433_920_000  # 433.92 MHz
SAMPLE_RATE = 2_000_000  # 2 MHz
TX_AMP = 0               # TX amplifier off (minimum power)
VGA_GAIN = 0             # Minimum VGA gain

def generate_ook_signal(sample_rate, num_repeats=5):
    """Generate OOK keyfob-like IQ samples.

    Pattern: 10 short pulses (300us on, 300us off) repeated num_repeats times
    with 5ms gaps between repeats. Typical of PT2262-style keyfobs.
    """
    pulse_on = int(sample_rate * 300e-6)   # 300us pulse
    pulse_off = int(sample_rate * 300e-6)  # 300us gap
    gap = int(sample_rate * 5e-3)          # 5ms between repeats
    silence_pad = int(sample_rate * 0.1)   # 100ms silence before/after

    samples = []

    # Leading silence
    samples.append(np.zeros(silence_pad, dtype=np.complex64))

    for rep in range(num_repeats):
        # 10-pulse burst
        for _ in range(10):
            # On: carrier tone
            t = np.arange(pulse_on) / sample_rate
            carrier = np.exp(2j * np.pi * 50000 * t).astype(np.complex64) * 0.9
            samples.append(carrier)
            # Off: silence
            samples.append(np.zeros(pulse_off, dtype=np.complex64))

        # Gap between repeats
        samples.append(np.zeros(gap, dtype=np.complex64))

    # Trailing silence
    samples.append(np.zeros(silence_pad, dtype=np.complex64))

    return np.concatenate(samples)


def iq_to_hackrf_format(iq_samples):
    """Convert complex64 IQ to interleaved int8 (HackRF format)."""
    i = np.real(iq_samples) * 127
    q = np.imag(iq_samples) * 127
    interleaved = np.empty(len(iq_samples) * 2, dtype=np.int8)
    interleaved[0::2] = i.astype(np.int8)
    interleaved[1::2] = q.astype(np.int8)
    return interleaved


def main():
    print("Generating OOK keyfob test signal...")
    iq = generate_ook_signal(SAMPLE_RATE, num_repeats=5)
    raw = iq_to_hackrf_format(iq)

    duration_ms = len(iq) / SAMPLE_RATE * 1000
    print(f"  {len(iq)} samples, {duration_ms:.0f} ms duration")

    # Write to temp file
    tmpfile = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    raw.tofile(tmpfile)
    tmpfile.close()
    print(f"  Written to {tmpfile.name}")

    # Transmit via hackrf_transfer
    print(f"\nTransmitting at {FREQUENCY/1e6} MHz (min power)...")
    cmd = [
        "hackrf_transfer",
        "-t", tmpfile.name,
        "-f", str(FREQUENCY),
        "-s", str(SAMPLE_RATE),
        "-x", str(VGA_GAIN),       # TX VGA gain (0 = minimum)
        "-a", str(TX_AMP),         # TX amp off
        "-R",                      # Repeat until file ends
    ]
    print(f"  cmd: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, timeout=5, capture_output=True, text=True)
        print(result.stderr[-500:] if result.stderr else "(no stderr)")
    except subprocess.TimeoutExpired:
        print("  TX completed (timeout = expected)")
    finally:
        os.unlink(tmpfile.name)
        print("Done.")


if __name__ == "__main__":
    main()

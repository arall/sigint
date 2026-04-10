#!/usr/bin/env python3
"""
Generate FM-modulated PMR446 test signal via HackRF.
Transmits a 1 kHz tone on PMR CH1 (446.00625 MHz) for testing the PMR scanner.
"""

import numpy as np
import subprocess
import tempfile
import os

FREQUENCY = 446_006_250  # PMR446 CH1
SAMPLE_RATE = 2_000_000  # 2 MHz
TX_AMP = 0
VGA_GAIN = 30            # Moderate TX VGA gain (range 0-47)


def generate_fm_tone(sample_rate, tone_freq=1000, fm_deviation=2500, duration_s=2.0):
    """Generate FM-modulated 1 kHz tone (NBFM, ±2.5 kHz deviation)."""
    t = np.arange(int(sample_rate * duration_s)) / sample_rate

    # Modulating signal: 1 kHz sine
    modulator = np.sin(2 * np.pi * tone_freq * t)

    # FM modulation: phase is integral of modulator
    phase = 2 * np.pi * fm_deviation * np.cumsum(modulator) / sample_rate
    iq = np.exp(1j * phase).astype(np.complex64) * 0.9

    # Add 200ms silence before and after
    pad = np.zeros(int(sample_rate * 0.2), dtype=np.complex64)
    return np.concatenate([pad, iq, pad])


def iq_to_hackrf_format(iq_samples):
    """Convert complex64 IQ to interleaved int8."""
    i = np.real(iq_samples) * 127
    q = np.imag(iq_samples) * 127
    interleaved = np.empty(len(iq_samples) * 2, dtype=np.int8)
    interleaved[0::2] = i.astype(np.int8)
    interleaved[1::2] = q.astype(np.int8)
    return interleaved


def main():
    print("Generating FM PMR446 CH1 test signal (1 kHz tone, ±2.5 kHz dev)...")
    iq = generate_fm_tone(SAMPLE_RATE, tone_freq=1000, fm_deviation=2500, duration_s=2.0)
    raw = iq_to_hackrf_format(iq)

    duration_ms = len(iq) / SAMPLE_RATE * 1000
    print(f"  {len(iq)} samples, {duration_ms:.0f} ms duration")

    tmpfile = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    raw.tofile(tmpfile)
    tmpfile.close()

    print(f"\nTransmitting at {FREQUENCY/1e6:.5f} MHz (PMR CH1, min power)...")
    cmd = [
        "hackrf_transfer",
        "-t", tmpfile.name,
        "-f", str(FREQUENCY),
        "-s", str(SAMPLE_RATE),
        "-x", str(VGA_GAIN),
        "-a", str(TX_AMP),
        "-R",
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

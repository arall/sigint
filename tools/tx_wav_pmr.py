#!/usr/bin/env python3
"""
Transmit a WAV file as FM-modulated audio on a PMR446 channel via HackRF.

Useful for end-to-end testing of the PMR voice pipeline (capture, demod,
recording, transcription) without needing a real walkie-talkie.

Usage:
    sudo python3 tools/tx_wav_pmr.py                              # random channel, default WAV
    sudo python3 tools/tx_wav_pmr.py path/to/voice.wav            # custom WAV
    sudo python3 tools/tx_wav_pmr.py --channel 3                  # specific channel
    sudo python3 tools/tx_wav_pmr.py --channel 5 --gain 47        # higher TX power
    sudo python3 tools/tx_wav_pmr.py --amp                        # enable RF amplifier
    sudo python3 tools/tx_wav_pmr.py --serial <hackrf_serial>     # specific HackRF

Requires hackrf_transfer in PATH and a HackRF One that's not in use.
"""

import argparse
import os
import random
import subprocess
import sys
import tempfile

import numpy as np
from scipy.io import wavfile
from scipy import signal as scipy_signal

# PMR446 analog channel center frequencies (Hz)
PMR_CHANNELS = {
    1: 446_006_250,
    2: 446_018_750,
    3: 446_031_250,
    4: 446_043_750,
    5: 446_056_250,
    6: 446_068_750,
    7: 446_081_250,
    8: 446_093_750,
}

SAMPLE_RATE = 2_000_000  # HackRF minimum
FM_DEVIATION = 2_500     # PMR446 narrowband FM deviation

DEFAULT_WAV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "tests", "data", "original_voice.wav",
)


def load_wav(path):
    """Load a WAV and return (rate, mono float64 in [-1, 1])."""
    rate, audio = wavfile.read(path)
    if audio.dtype == np.int16:
        audio = audio.astype(np.float64) / 32768.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float64) / 2147483648.0
    elif audio.dtype == np.uint8:
        audio = (audio.astype(np.float64) - 128.0) / 128.0
    else:
        audio = audio.astype(np.float64)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return rate, audio


def fm_modulate(audio, audio_rate, sdr_rate, fm_deviation):
    """FM modulate mono audio to complex64 IQ at sdr_rate."""
    num = int(len(audio) * sdr_rate / audio_rate)
    audio_resampled = scipy_signal.resample(audio, num)
    audio_resampled = np.clip(audio_resampled, -1.0, 1.0) * 0.8
    phase = 2 * np.pi * fm_deviation * np.cumsum(audio_resampled) / sdr_rate
    return (np.exp(1j * phase).astype(np.complex64) * 0.9)


def iq_to_int8(iq):
    """Pack complex64 IQ into HackRF interleaved int8 format."""
    i = (np.real(iq) * 127).astype(np.int8)
    q = (np.imag(iq) * 127).astype(np.int8)
    out = np.empty(len(iq) * 2, dtype=np.int8)
    out[0::2] = i
    out[1::2] = q
    return out


def main():
    p = argparse.ArgumentParser(
        description="Transmit a WAV as FM voice on a PMR446 channel via HackRF.")
    p.add_argument("wav", nargs="?", default=DEFAULT_WAV,
                   help=f"WAV file to transmit (default: {DEFAULT_WAV})")
    p.add_argument("--channel", "-c", type=int, choices=range(1, 9),
                   help="PMR446 channel 1-8 (default: random)")
    p.add_argument("--gain", "-g", type=int, default=10,
                   help="TX VGA gain 0-47 (default: 10, low to avoid receiver saturation)")
    p.add_argument("--amp", action="store_true",
                   help="Enable RF amplifier (+11 dB)")
    p.add_argument("--serial", "-s",
                   help="HackRF serial number (default: first available)")
    args = p.parse_args()

    if not os.path.exists(args.wav):
        print(f"WAV not found: {args.wav}", file=sys.stderr)
        sys.exit(1)

    rate, audio = load_wav(args.wav)
    print(f"  WAV: {len(audio)} samples, "
          f"{len(audio) / rate:.2f}s @ {rate} Hz")

    channel = args.channel or random.choice(list(PMR_CHANNELS.keys()))
    freq = PMR_CHANNELS[channel]
    print(f"  Channel: PMR CH{channel} ({freq / 1e6:.5f} MHz)")

    print("  FM modulating...")
    iq = fm_modulate(audio, rate, SAMPLE_RATE, FM_DEVIATION)
    pad = np.zeros(int(SAMPLE_RATE * 0.3), dtype=np.complex64)
    iq = np.concatenate([pad, iq, pad])
    raw = iq_to_int8(iq)
    duration = len(iq) / SAMPLE_RATE
    print(f"  IQ: {len(iq)} samples ({duration:.2f}s)")

    tmp = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    raw.tofile(tmp)
    tmp.close()

    cmd = [
        "hackrf_transfer", "-t", tmp.name,
        "-f", str(freq),
        "-s", str(SAMPLE_RATE),
        "-x", str(args.gain),
        "-a", "1" if args.amp else "0",
    ]
    if args.serial:
        cmd.extend(["-d", args.serial])

    print(f"  Transmitting on PMR CH{channel}...")
    try:
        result = subprocess.run(
            cmd, timeout=int(duration + 5),
            capture_output=True, text=True)
        if result.returncode == 0:
            print("  TX OK")
        else:
            print(f"  TX rc={result.returncode}\n  stderr: {result.stderr.strip()}")
    finally:
        os.unlink(tmp.name)


if __name__ == "__main__":
    main()

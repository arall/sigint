#!/usr/bin/env python3
"""
Generate FM-modulated voice signal on PMR CH1 via HackRF.
Uses macOS text-to-speech to create a realistic voice test.
"""

import numpy as np
import subprocess
import tempfile
import os
from scipy.io import wavfile
from scipy import signal as scipy_signal

FREQUENCY = 446_006_250  # PMR446 CH1
SAMPLE_RATE = 2_000_000
TX_AMP = 0
VGA_GAIN = 40


def generate_voice_wav(text="Alpha Bravo Charlie, radio check, over"):
    """Use macOS TTS to generate a voice WAV file."""
    tmpfile = tempfile.NamedTemporaryFile(suffix=".aiff", delete=False)
    tmpfile.close()
    subprocess.run(["say", "-o", tmpfile.name, text], check=True)

    # Convert AIFF to WAV via scipy (read with afconvert first)
    wav_tmp = tmpfile.name.replace(".aiff", ".wav")
    subprocess.run([
        "afconvert", "-f", "WAVE", "-d", "LEI16@16000",
        tmpfile.name, wav_tmp
    ], check=True)
    os.unlink(tmpfile.name)

    rate, audio = wavfile.read(wav_tmp)
    os.unlink(wav_tmp)
    return rate, audio.astype(np.float64) / 32768.0  # Normalize to [-1, 1]


def fm_modulate(audio, audio_rate, sdr_rate, fm_deviation=2500):
    """FM modulate audio to IQ samples at SDR sample rate."""
    # Resample audio to SDR rate
    num_sdr_samples = int(len(audio) * sdr_rate / audio_rate)
    audio_resampled = scipy_signal.resample(audio, num_sdr_samples)

    # Limit audio amplitude to prevent over-deviation
    audio_resampled = np.clip(audio_resampled, -1, 1) * 0.8

    # FM modulate: phase = 2*pi*deviation * integral(audio)
    phase = 2 * np.pi * fm_deviation * np.cumsum(audio_resampled) / sdr_rate
    iq = np.exp(1j * phase).astype(np.complex64) * 0.9

    return iq


def iq_to_hackrf_format(iq_samples):
    i = np.real(iq_samples) * 127
    q = np.imag(iq_samples) * 127
    interleaved = np.empty(len(iq_samples) * 2, dtype=np.int8)
    interleaved[0::2] = i.astype(np.int8)
    interleaved[1::2] = q.astype(np.int8)
    return interleaved


def main():
    # Use a fixed 300Hz tone to test for pitch shift
    import sys
    if "--tone" in sys.argv:
        from scipy.io import wavfile as wf
        tone_path = os.path.join(os.path.dirname(__file__), '..', '..', 'output', 'audio', 'test_300hz.wav')
        audio_rate, audio_raw = wf.read(tone_path)
        audio = audio_raw.astype(np.float64) / 32768.0
        text = "300 Hz test tone"
    else:
        text = "Alpha Bravo Charlie, radio check, over"
        audio_rate, audio = generate_voice_wav(text)
    print(f"  TTS: {len(audio)} samples, {len(audio)/audio_rate:.1f}s at {audio_rate} Hz")

    # Save original for comparison
    orig_path = os.path.join(os.path.dirname(__file__), '..', '..', 'output', 'audio', 'original_voice.wav')
    wavfile.write(orig_path, audio_rate, (audio * 32767).astype(np.int16))
    print(f"  Original saved to: {orig_path}")

    print("FM modulating...")
    iq = fm_modulate(audio, audio_rate, SAMPLE_RATE)

    # Add 200ms silence padding
    pad = np.zeros(int(SAMPLE_RATE * 0.2), dtype=np.complex64)
    iq = np.concatenate([pad, iq, pad])

    raw = iq_to_hackrf_format(iq)
    duration_s = len(iq) / SAMPLE_RATE
    print(f"  IQ: {len(iq)} samples, {duration_s:.1f}s")

    tmpfile = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    raw.tofile(tmpfile)
    tmpfile.close()

    print(f"\nTransmitting on PMR CH1 ({FREQUENCY/1e6:.5f} MHz)...")
    cmd = [
        "hackrf_transfer", "-t", tmpfile.name,
        "-f", str(FREQUENCY), "-s", str(SAMPLE_RATE),
        "-x", str(VGA_GAIN), "-a", str(TX_AMP),
    ]

    try:
        result = subprocess.run(cmd, timeout=int(duration_s + 3),
                                capture_output=True, text=True)
        if result.returncode == 0:
            print("  TX completed successfully")
        else:
            print(f"  TX finished (rc={result.returncode})")
    except subprocess.TimeoutExpired:
        print("  TX completed (timeout)")
    finally:
        os.unlink(tmpfile.name)
    print("Done.")


if __name__ == "__main__":
    main()

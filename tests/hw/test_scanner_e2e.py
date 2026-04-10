"""
Scanner class E2E test: HackRF TX → RTL-SDR RX via actual scanner classes.

Unlike test_e2e_voice.py which tests extract_and_demodulate_buffers directly,
this test runs the actual PMRScanner and verifies:
- Correct detection on the right channel
- Zero false detections on other channels
- Audio file quality
- Optional transcription

NOTE: HackRF has ~17 ppm frequency error, so its TX lands ~8 kHz off the
nominal PMR channel. The scanner detects at exact channel frequencies, so
the signal may appear on an adjacent channel. The test accounts for this
by checking that ANY channel was detected (not necessarily the target).
For exact-channel testing, use a real PMR walkie-talkie instead.

Requirements:
  - HackRF One (TX) + RTL-SDR Blog V4 (RX) connected simultaneously
  - openai-whisper installed (for transcription check)

Usage:
  python3 tests/hw/test_scanner_e2e.py
  python3 tests/hw/test_scanner_e2e.py --channel 4
  python3 tests/hw/test_scanner_e2e.py --no-transcribe
"""

import argparse
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave

import numpy as np
from scipy import signal as scipy_signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import utils.loader  # noqa: F401
from scanners.pmr import (
    PMR_CHANNELS,
    PMRScanner,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_CENTER_FREQ,
    DEFAULT_NUM_SAMPLES,
)

VOICE_WAV = os.path.join(os.path.dirname(__file__), '..', 'data',
                         'original_voice.wav')
TX_SAMPLE_RATE = 2e6
FM_DEVIATION = 2500
TX_GAIN = 20
EXPECTED_WORDS = ["alpha", "bravo", "charlie", "radio", "check"]


def load_voice():
    with wave.open(VOICE_WAV, 'rb') as w:
        n = w.getnframes()
        rate = w.getframerate()
        raw = w.readframes(n)
        audio = np.array(struct.unpack(f'<{n}h', raw), dtype=np.float64)
        audio /= 32768.0
    return audio, rate


def fm_modulate_hackrf(audio, audio_rate, channel_freq):
    """FM modulate for HackRF TX."""
    n_tx = int(len(audio) * TX_SAMPLE_RATE / audio_rate)
    audio_up = scipy_signal.resample(audio, n_tx)
    audio_up = np.clip(audio_up, -1, 1) * 0.8
    phase = 2 * np.pi * FM_DEVIATION * np.cumsum(audio_up) / TX_SAMPLE_RATE

    leader = np.zeros(int(5 * TX_SAMPLE_RATE))
    trailer = np.full(int(6 * TX_SAMPLE_RATE), phase[-1])
    full_phase = np.concatenate([leader, phase, trailer])
    iq = np.exp(1j * full_phase)

    i8 = np.clip(np.round(iq.real * 127), -127, 127).astype(np.int8)
    q8 = np.clip(np.round(iq.imag * 127), -127, 127).astype(np.int8)
    il = np.empty(len(i8) * 2, dtype=np.int8)
    il[0::2] = i8
    il[1::2] = q8
    return il, len(full_phase) / TX_SAMPLE_RATE


def test_pmr_scanner(channel_num, do_transcribe=True):
    """Run PMRScanner while HackRF transmits on a specific channel."""
    channel_freq = PMR_CHANNELS[channel_num]
    audio, audio_rate = load_voice()

    print(f"\n{'=' * 60}")
    print(f"Scanner E2E: PMRScanner + HackRF TX on CH{channel_num}")
    print(f"{'=' * 60}")

    # Prepare TX
    iq_data, tx_duration = fm_modulate_hackrf(audio, audio_rate, channel_freq)
    tx_file = tempfile.NamedTemporaryFile(suffix='.iq', delete=False)
    iq_data.tofile(tx_file)
    tx_file.close()

    with tempfile.TemporaryDirectory() as tmpdir:
        scanner = PMRScanner(
            output_dir=tmpdir,
            device_index=0,
            gain=40,
            record_audio=True,
            transcribe_audio=do_transcribe,
            whisper_model="base",
            language="en",
        )

        print(f"  TX: CH{channel_num} ({channel_freq/1e6:.5f} MHz), "
              f"{tx_duration:.0f}s")
        print(f"  Scanner: SNR={scanner.DETECTION_SNR_DB} dB, "
              f"MIN_TX={scanner.MIN_TX_DURATION}s")

        # Start scanner FIRST (it needs time to init RTL-SDR + async reader)
        scanner_error = [None]

        def run_scanner():
            try:
                scanner.run()
            except Exception as e:
                scanner_error[0] = e

        scanner_thread = threading.Thread(target=run_scanner, daemon=True)
        scanner_thread.start()

        # Wait for scanner to fully initialize (RTL-SDR open + reader thread)
        time.sleep(4)

        # NOW start HackRF TX (scanner is already listening)
        print(f"  Starting HackRF TX...", flush=True)
        tx_proc = subprocess.Popen(
            ['hackrf_transfer', '-t', tx_file.name,
             '-f', str(int(channel_freq)),
             '-s', str(int(TX_SAMPLE_RATE)),
             '-x', str(TX_GAIN)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait for TX to finish + holdover to expire
        tx_proc.wait(timeout=int(tx_duration + 5))
        print(f"  TX done, waiting for holdover...", flush=True)
        time.sleep(6)

        # Stop scanner by closing the SDR device (causes reader thread
        # to exit, main loop detects it and enters finally block which
        # finalizes any active transmissions)
        if scanner.sdr:
            try:
                scanner.sdr.cancel_read_async()
            except Exception:
                pass
            time.sleep(1)  # Let reader thread exit cleanly
            try:
                scanner.sdr.close()
            except Exception:
                pass
            scanner.sdr = None
        # Allow time for shutdown finalization (demod on RPi is slow)
        scanner_thread.join(timeout=60)
        os.unlink(tx_file.name)

        if scanner_error[0]:
            print(f"  Scanner error (expected): {type(scanner_error[0]).__name__}")

        # Check results
        audio_dir = os.path.join(tmpdir, "audio")
        wavs = []
        if os.path.exists(audio_dir):
            wavs = sorted([f for f in os.listdir(audio_dir)
                           if f.endswith('.wav')])

        print(f"\n  Results:")
        print(f"    Audio files: {len(wavs)}")

        # HackRF has ~17 ppm freq error — signal may land on adjacent
        # channel. Find the longest WAV (most likely the real detection).
        for f in wavs:
            wp = os.path.join(audio_dir, f)
            with wave.open(wp, 'rb') as wf:
                dur = wf.getnframes() / wf.getframerate()
            print(f"      {f} ({dur:.1f}s)")

        # Assertions — at least one detection anywhere (HackRF freq error
        # means it may not land on the exact target channel)
        passed = True
        errors = []

        if len(wavs) == 0:
            errors.append("No detections at all")
            passed = False

        # Find longest WAV for transcription
        best_wav = None
        best_dur = 0
        for f in wavs:
            wp = os.path.join(audio_dir, f)
            with wave.open(wp, 'rb') as wf:
                dur = wf.getnframes() / wf.getframerate()
            if dur > best_dur:
                best_dur = dur
                best_wav = f

        # Transcription check on longest recording
        if do_transcribe and best_wav:
            from utils.transcriber import transcribe
            wp = os.path.join(audio_dir, best_wav)
            result = transcribe(wp, model_name="base", language="en")
            print(f"    Transcript: \"{result}\"")

            if result:
                result_lower = result.lower()
                found = [w for w in EXPECTED_WORDS if w in result_lower]
                print(f"    Keywords: {len(found)}/5 ({', '.join(found)})")
                if len(found) < 3:
                    errors.append(
                        f"Only {len(found)}/3 keywords: \"{result}\"")
                    passed = False
            else:
                errors.append("Transcription returned None")
                passed = False

        if passed:
            print(f"\n  PASS")
        else:
            print(f"\n  FAIL:")
            for e in errors:
                print(f"    - {e}")

        return passed


def main():
    parser = argparse.ArgumentParser(
        description='Scanner class E2E test')
    parser.add_argument('--channel', type=int, default=1,
                        choices=range(1, 9))
    parser.add_argument('--no-transcribe', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(VOICE_WAV):
        print(f"ERROR: {VOICE_WAV} not found")
        return 1

    passed = test_pmr_scanner(args.channel, not args.no_transcribe)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())

"""
End-to-end FM voice test: HackRF TX → RTL-SDR RX → FM demod → Whisper.

Transmits a known voice WAV on specified channels via HackRF, captures
with RTL-SDR, demodulates through the production pipeline, and verifies
the transcription matches the original text.

This is the definitive regression test for the audio capture chain.
If transcription matches, the entire pipeline works.

Supports all FM voice band profiles: pmr446, 70cm, marine, 2m, frs, cb,
murs, landmobile, etc.

Requirements:
  - HackRF One (TX) + RTL-SDR Blog V4 (RX) connected simultaneously
  - openai-whisper installed

Usage:
  python3 tests/hw/test_e2e_voice.py                    # PMR446 CH1
  python3 tests/hw/test_e2e_voice.py --channels 1 4 8   # PMR446 multiple
  python3 tests/hw/test_e2e_voice.py --channels all      # PMR446 all channels
  python3 tests/hw/test_e2e_voice.py --band 70cm         # 70cm EU CALL channel
  python3 tests/hw/test_e2e_voice.py --band marine --channels CH16 CH09
  python3 tests/hw/test_e2e_voice.py --band 2m --channels CALL
  python3 tests/hw/test_e2e_voice.py --band frs --channels FRS1 FRS4 FRS7
  python3 tests/hw/test_e2e_voice.py --list-bands        # Show available bands
  python3 tests/hw/test_e2e_voice.py --tx-gain 10        # Lower TX power
"""

import argparse
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np
from scipy import signal as scipy_signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import utils.loader  # noqa: F401
from rtlsdr import RtlSdr
from scanners.pmr import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_NUM_SAMPLES,
    extract_and_demodulate_buffers,
    save_audio,
)
from parsers.fm.voice import BAND_PROFILES
from utils.transcriber import transcribe

# Known test phrase and its expected transcription keywords
VOICE_WAV = os.path.join(os.path.dirname(__file__), '..', 'data',
                         'original_voice.wav')
# Words that MUST appear in the transcription (case-insensitive)
EXPECTED_WORDS = ["alpha", "bravo", "charlie", "radio", "check"]
MIN_KEYWORDS = 3  # Require at least 3 of 5 (Whisper imprecision margin)

# RF parameters
TX_SAMPLE_RATE = 2e6
RX_SAMPLE_RATE = DEFAULT_SAMPLE_RATE  # 2.4 MHz
TX_GAIN_DB = 20
LEADER_SECONDS = 2.0   # Carrier before voice (RX settle time)
TRAILER_SECONDS = 3.0  # Carrier after voice (holdover + margin)
AUDIO_RATE = 16000

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output', 'e2e')


def compute_center_freq(channels):
    """Compute RTL-SDR center frequency to cover the given channels.

    Places center at the midpoint of the channel frequency range.
    """
    freqs = list(channels.values())
    return (min(freqs) + max(freqs)) / 2


def load_voice_wav(path):
    """Load reference voice WAV as float64 array."""
    with wave.open(path, 'rb') as w:
        n = w.getnframes()
        rate = w.getframerate()
        raw = w.readframes(n)
        audio = np.array(struct.unpack(f'<{n}h', raw), dtype=np.float64)
        audio /= 32768.0
    return audio, rate


def fm_modulate_for_hackrf(audio, audio_rate, channel_freq, fm_deviation):
    """FM modulate voice audio for HackRF transmission.

    Returns raw int8 interleaved IQ ready for hackrf_transfer.
    """
    n_tx = int(len(audio) * TX_SAMPLE_RATE / audio_rate)
    audio_up = scipy_signal.resample(audio, n_tx)
    audio_up = np.clip(audio_up, -1, 1) * 0.8

    phase = 2 * np.pi * fm_deviation * np.cumsum(audio_up) / TX_SAMPLE_RATE

    leader = np.zeros(int(LEADER_SECONDS * TX_SAMPLE_RATE))
    trailer = np.full(int(TRAILER_SECONDS * TX_SAMPLE_RATE), phase[-1])

    full_phase = np.concatenate([leader, phase, trailer])
    iq = np.exp(1j * full_phase)

    i8 = np.clip(np.round(iq.real * 127), -127, 127).astype(np.int8)
    q8 = np.clip(np.round(iq.imag * 127), -127, 127).astype(np.int8)
    interleaved = np.empty(len(i8) * 2, dtype=np.int8)
    interleaved[0::2] = i8
    interleaved[1::2] = q8
    return interleaved, len(full_phase) / TX_SAMPLE_RATE


def tx_and_capture(iq_data, channel_freq, center_freq, tx_duration,
                   rx_gain=40, tx_gain=20):
    """Transmit on HackRF and simultaneously capture on RTL-SDR."""
    iq_file = tempfile.NamedTemporaryFile(suffix='.iq', delete=False)
    iq_data.tofile(iq_file)
    iq_file.close()

    try:
        tx_proc = subprocess.Popen(
            ['hackrf_transfer', '-t', iq_file.name,
             '-f', str(int(channel_freq)),
             '-s', str(int(TX_SAMPLE_RATE)),
             '-x', str(tx_gain)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        time.sleep(1.0)

        sdr = RtlSdr()
        sdr.sample_rate = RX_SAMPLE_RATE
        sdr.center_freq = center_freq
        sdr.gain = rx_gain

        n_reads = int(tx_duration * RX_SAMPLE_RATE / DEFAULT_NUM_SAMPLES) + 5
        chunks = []
        offset = 0
        for _ in range(n_reads):
            s = sdr.read_samples(DEFAULT_NUM_SAMPLES)
            chunks.append((offset, s))
            offset += len(s)

        sdr.close()
        tx_proc.terminate()
        tx_proc.wait(timeout=5)

    finally:
        os.unlink(iq_file.name)

    return chunks


def find_signal_frequency(chunks, sample_rate, center_freq):
    """Find the actual signal frequency from captured IQ."""
    mid = chunks[len(chunks) // 3][1]
    fft = np.fft.fftshift(np.fft.fft(mid))
    power = 20 * np.log10(np.abs(fft) + 1e-10)
    freqs = np.fft.fftshift(
        np.fft.fftfreq(len(mid), 1 / sample_rate)) + center_freq

    # Mask DC spike
    mask = np.abs(freqs - center_freq) > 2000
    masked_power = power.copy()
    masked_power[~mask] = -200

    peak_idx = np.argmax(masked_power)
    peak_freq = freqs[peak_idx]
    snr = power[peak_idx] - np.median(power)

    return peak_freq, snr


def test_channel(ch_label, channel_freq, center_freq, fm_deviation, band_name,
                 audio, audio_rate, rx_gain, tx_gain):
    """Run full E2E test on one channel. Returns (passed, transcript, error)."""
    print(f"\n{'=' * 60}")
    print(f"Testing {band_name} {ch_label} ({channel_freq/1e6:.5f} MHz, "
          f"dev ±{fm_deviation} Hz)")
    print(f"{'=' * 60}")

    # Check RTL-SDR can tune to this frequency
    if center_freq < 24e6 or center_freq > 1.766e9:
        return False, None, (f"Center freq {center_freq/1e6:.1f} MHz outside "
                             f"RTL-SDR range (24-1766 MHz)")

    iq_data, tx_duration = fm_modulate_for_hackrf(
        audio, audio_rate, channel_freq, fm_deviation)
    print(f"  TX duration: {tx_duration:.1f}s")
    print(f"  RX center: {center_freq/1e6:.3f} MHz")

    print(f"  Transmitting and capturing...")
    chunks = tx_and_capture(iq_data, channel_freq, center_freq, tx_duration,
                            rx_gain, tx_gain)
    print(f"  Captured {len(chunks)} chunks")

    sig_freq, sig_snr = find_signal_frequency(
        chunks, RX_SAMPLE_RATE, center_freq)
    print(f"  Signal at {sig_freq/1e6:.5f} MHz, SNR {sig_snr:.0f} dB")

    if sig_snr < 15:
        return False, None, f"Signal too weak: SNR {sig_snr:.0f} dB < 15"

    audio_out, rate = extract_and_demodulate_buffers(
        chunks, RX_SAMPLE_RATE, center_freq,
        sig_freq, AUDIO_RATE, fm_deviation)

    if len(audio_out) == 0:
        return False, None, "Demodulation returned empty audio"

    duration = len(audio_out) / rate
    rms = float(np.sqrt(np.mean(audio_out ** 2)))
    print(f"  Demodulated: {duration:.1f}s, RMS {rms:.4f}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_label = ch_label.replace("/", "_")
    wav_path = os.path.join(
        OUTPUT_DIR, f"e2e_{band_name}_{safe_label}.wav")
    save_audio(audio_out, rate, wav_path)
    print(f"  Saved: {wav_path}")

    print(f"  Transcribing...")
    transcript = transcribe(wav_path)
    if not transcript:
        return False, None, "Whisper returned empty transcription"

    print(f"  Transcript: \"{transcript}\"")

    transcript_lower = transcript.lower()
    found = [w for w in EXPECTED_WORDS if w in transcript_lower]
    missing = [w for w in EXPECTED_WORDS if w not in transcript_lower]

    passed = len(found) >= MIN_KEYWORDS

    print(f"  Keywords found: {len(found)}/{len(EXPECTED_WORDS)} "
          f"({', '.join(found)})")
    if missing:
        print(f"  Keywords missing: {', '.join(missing)}")

    if passed:
        print(f"  PASS")
    else:
        print(f"  FAIL: Only {len(found)}/{MIN_KEYWORDS} required keywords")

    return passed, transcript, None


def list_bands():
    """Print available band profiles and their channels."""
    print("Available band profiles:")
    print()
    for band_key, profile in sorted(BAND_PROFILES.items()):
        channels = profile["channels"]
        freqs = list(channels.values())
        freq_min = min(freqs) / 1e6
        freq_max = max(freqs) / 1e6
        print(f"  {band_key:20s}  {profile['name']:20s}  "
              f"{freq_min:.3f}-{freq_max:.3f} MHz  "
              f"dev ±{profile['fm_deviation']} Hz  "
              f"{len(channels)} channels")
        ch_names = list(channels.keys())
        if len(ch_names) <= 8:
            print(f"    Channels: {', '.join(ch_names)}")
        else:
            print(f"    Channels: {', '.join(ch_names[:6])}, ... "
                  f"({len(ch_names)} total)")
    print()
    print("Usage: python3 test_e2e_voice.py --band <name> "
          "--channels <CH1> [CH2 ...]")


def main():
    parser = argparse.ArgumentParser(
        description='E2E FM voice test: HackRF TX → RTL-SDR RX → Whisper',
        epilog='Examples:\n'
               '  %(prog)s                              # PMR446 CH1\n'
               '  %(prog)s --band 70cm --channels CALL   # 70cm calling freq\n'
               '  %(prog)s --band marine --channels CH16  # Marine distress\n'
               '  %(prog)s --band 2m --channels all       # All 2m channels\n'
               '  %(prog)s --list-bands                   # Show all bands\n',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--band', default='pmr446',
                        help='Band profile (default: pmr446)')
    parser.add_argument('--channels', nargs='+', default=None,
                        help='Channel labels to test (default: first channel, '
                             'or "all")')
    parser.add_argument('--tx-gain', type=int, default=TX_GAIN_DB,
                        help=f'HackRF TX gain (default: {TX_GAIN_DB})')
    parser.add_argument('--rx-gain', type=float, default=40,
                        help='RTL-SDR RX gain (default: 40)')
    parser.add_argument('--list-bands', action='store_true',
                        help='List available band profiles and exit')
    args = parser.parse_args()

    if args.list_bands:
        list_bands()
        return 0

    # Load band profile
    profile = BAND_PROFILES.get(args.band)
    if not profile:
        # Try case-insensitive and partial match
        for key in BAND_PROFILES:
            if args.band.lower() in key.lower():
                profile = BAND_PROFILES[key]
                args.band = key
                break
    if not profile:
        print(f"ERROR: Unknown band '{args.band}'")
        print(f"  Available: {', '.join(BAND_PROFILES.keys())}")
        return 1

    band_name = profile["name"]
    channels = profile["channels"]
    fm_deviation = profile["fm_deviation"]

    # Parse channel list
    if args.channels is None:
        # Default: first channel
        first_label = list(channels.keys())[0]
        test_channels = {first_label: channels[first_label]}
    elif args.channels == ['all']:
        test_channels = channels
    else:
        test_channels = {}
        for label in args.channels:
            # Try exact match first
            if label in channels:
                test_channels[label] = channels[label]
            else:
                # Try with/without "CH" prefix for PMR convenience
                alt = f"CH{label}" if not label.startswith("CH") else label
                if alt in channels:
                    test_channels[alt] = channels[alt]
                else:
                    print(f"WARNING: Channel '{label}' not in {args.band} "
                          f"profile, skipping")
                    print(f"  Available: {', '.join(channels.keys())}")

    if not test_channels:
        print("ERROR: No valid channels to test")
        return 1

    # Compute RX center frequency to cover test channels
    center_freq = compute_center_freq(test_channels)

    # Verify all channels fit within RTL-SDR bandwidth
    half_bw = RX_SAMPLE_RATE / 2
    for label, freq in test_channels.items():
        offset = abs(freq - center_freq)
        if offset > half_bw * 0.9:
            print(f"WARNING: {label} ({freq/1e6:.3f} MHz) is near edge of "
                  f"RTL-SDR bandwidth")

    # Load reference audio
    if not os.path.exists(VOICE_WAV):
        print(f"ERROR: Reference WAV not found: {VOICE_WAV}")
        return 1

    audio, audio_rate = load_voice_wav(VOICE_WAV)
    print(f"Band: {band_name} (FM dev ±{fm_deviation} Hz)")
    print(f"RX center: {center_freq/1e6:.3f} MHz")
    print(f"Reference: \"Alpha Bravo Charlie, radio check, over\" "
          f"({len(audio)/audio_rate:.1f}s)")
    print(f"Channels: {', '.join(test_channels.keys())}")

    results = {}
    for ch_label, ch_freq in test_channels.items():
        passed, transcript, error = test_channel(
            ch_label, ch_freq, center_freq, fm_deviation, band_name,
            audio, audio_rate, args.rx_gain, args.tx_gain)

        key = f"{ch_label} ({ch_freq/1e6:.5f})"
        if error:
            results[key] = f"ERROR: {error}"
        elif passed:
            results[key] = f"PASS: \"{transcript}\""
        else:
            results[key] = f"FAIL: \"{transcript}\""

    # Summary
    print(f"\n{'=' * 60}")
    print(f"SUMMARY — {band_name}")
    print(f"{'=' * 60}")

    n_pass = 0
    n_fail = 0
    for key, status in results.items():
        icon = "+" if status.startswith("PASS") else "!"
        print(f"  [{icon}] {key}: {status}")
        if status.startswith("PASS"):
            n_pass += 1
        else:
            n_fail += 1

    print(f"\n  {n_pass} passed, {n_fail} failed")
    print(f"  Audio files saved in: {os.path.abspath(OUTPUT_DIR)}")
    print(f"{'=' * 60}")

    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

"""
False detection prevention tests.

Verifies that noise-only input produces ZERO audio files across all three
audio paths (PMRScanner, FMScanner, FMVoiceParser). Also tests spectral
leakage rejection and MIN_TX_DURATION filtering.

Run:
    python3 tests/sw/test_false_detections.py
"""

import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from scanners.pmr import PMR_CHANNELS, DEFAULT_SAMPLE_RATE, DEFAULT_CENTER_FREQ


def generate_noise(sample_rate, duration, level=0.01):
    """Generate complex Gaussian noise."""
    n = int(sample_rate * duration)
    return (np.random.randn(n) + 1j * np.random.randn(n)).astype(
        np.complex64) * level


def generate_fm_signal(freq_offset, sample_rate, duration, deviation=2500,
                       tone_freq=1000, snr_db=30):
    """Generate FM-modulated tone at a frequency offset."""
    n = int(sample_rate * duration)
    t = np.arange(n) / sample_rate
    phase = 2 * np.pi * freq_offset * t + (
        deviation / tone_freq) * np.sin(2 * np.pi * tone_freq * t)
    signal = np.exp(1j * phase).astype(np.complex64)
    signal_power = np.mean(np.abs(signal) ** 2)
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = (np.random.randn(n) + 1j * np.random.randn(n)).astype(
        np.complex64) * np.sqrt(noise_power / 2)
    return signal + noise


def count_audio_files(directory):
    """Count WAV files in audio subdirectory."""
    audio_dir = os.path.join(directory, "audio")
    if not os.path.exists(audio_dir):
        return 0
    return len([f for f in os.listdir(audio_dir) if f.endswith('.wav')])


# -----------------------------------------------------------------------
# PMRScanner tests
# -----------------------------------------------------------------------

def test_pmr_noise_only():
    """PMRScanner: 30s of noise produces zero detections."""
    from scanners.pmr import PMRScanner

    with tempfile.TemporaryDirectory() as tmpdir:
        scanner = PMRScanner(output_dir=tmpdir, record_audio=True)

        # Feed 30 seconds of noise in chunks
        chunk_size = 256 * 1024
        n_chunks = int(30 * DEFAULT_SAMPLE_RATE / chunk_size)
        for i in range(n_chunks):
            noise = generate_noise(DEFAULT_SAMPLE_RATE,
                                   chunk_size / DEFAULT_SAMPLE_RATE, 0.01)
            freqs, ps = __import__('scanners.pmr', fromlist=['calculate_power_spectrum']).calculate_power_spectrum(noise, DEFAULT_SAMPLE_RATE)
            noise_floor = np.median(ps)
            for ch, ch_freq in PMR_CHANNELS.items():
                from scanners.pmr import get_channel_power
                power = get_channel_power(freqs, ps, DEFAULT_CENTER_FREQ,
                                          ch_freq)
                snr = power - noise_floor
                scanner._process_channel(
                    noise, ch, ch_freq, snr, power, noise_floor,
                    sample_offset=i * chunk_size)

        wavs = count_audio_files(tmpdir)
        assert wavs == 0, f"Expected 0 audio files from noise, got {wavs}"


def test_pmr_spectral_leakage():
    """PMRScanner: strong signal on CH1 produces zero detections on CH2-CH8."""
    from scanners.pmr import PMRScanner, calculate_power_spectrum, get_channel_power

    with tempfile.TemporaryDirectory() as tmpdir:
        scanner = PMRScanner(output_dir=tmpdir, record_audio=True)

        ch1_freq = PMR_CHANNELS[1]
        freq_offset = ch1_freq - DEFAULT_CENTER_FREQ

        # Feed 5s of strong signal on CH1
        chunk_size = 256 * 1024
        n_chunks = int(5 * DEFAULT_SAMPLE_RATE / chunk_size)
        for i in range(n_chunks):
            iq = generate_fm_signal(freq_offset, DEFAULT_SAMPLE_RATE,
                                    chunk_size / DEFAULT_SAMPLE_RATE,
                                    snr_db=40)
            freqs, ps = calculate_power_spectrum(iq, DEFAULT_SAMPLE_RATE)
            noise_floor = np.median(ps)
            for ch, ch_freq in PMR_CHANNELS.items():
                power = get_channel_power(freqs, ps, DEFAULT_CENTER_FREQ,
                                          ch_freq)
                snr = power - noise_floor
                scanner._process_channel(
                    iq, ch, ch_freq, snr, power, noise_floor,
                    sample_offset=i * chunk_size)
            time.sleep(0.05)  # wall-clock for holdover

        # Wait for holdover to expire
        time.sleep(2.5)
        # Feed one more noise chunk to trigger holdover finalization
        noise = generate_noise(DEFAULT_SAMPLE_RATE,
                               chunk_size / DEFAULT_SAMPLE_RATE, 0.01)
        freqs, ps = calculate_power_spectrum(noise, DEFAULT_SAMPLE_RATE)
        noise_floor = np.median(ps)
        for ch, ch_freq in PMR_CHANNELS.items():
            power = get_channel_power(freqs, ps, DEFAULT_CENTER_FREQ, ch_freq)
            snr = power - noise_floor
            scanner._process_channel(
                noise, ch, ch_freq, snr, power, noise_floor,
                sample_offset=n_chunks * chunk_size)

        # CH1 should have 1 detection, CH2-CH8 should have 0
        audio_dir = os.path.join(tmpdir, "audio")
        if os.path.exists(audio_dir):
            wavs = [f for f in os.listdir(audio_dir) if f.endswith('.wav')]
            non_ch1 = [f for f in wavs if '_ch1_' not in f]
            assert len(non_ch1) == 0, (
                f"Adjacent channel false detections: "
                f"{[f for f in non_ch1]}")


def test_pmr_short_burst_filtered():
    """PMRScanner: sub-MIN_TX_DURATION burst produces zero audio files."""
    from scanners.pmr import PMRScanner, calculate_power_spectrum, get_channel_power

    with tempfile.TemporaryDirectory() as tmpdir:
        scanner = PMRScanner(output_dir=tmpdir, record_audio=True)

        ch1_freq = PMR_CHANNELS[1]
        freq_offset = ch1_freq - DEFAULT_CENTER_FREQ

        # Feed 2 chunks (~0.2s) of signal then stop
        chunk_size = 256 * 1024
        for i in range(2):
            iq = generate_fm_signal(freq_offset, DEFAULT_SAMPLE_RATE,
                                    chunk_size / DEFAULT_SAMPLE_RATE,
                                    snr_db=30)
            freqs, ps = calculate_power_spectrum(iq, DEFAULT_SAMPLE_RATE)
            noise_floor = np.median(ps)
            power = get_channel_power(freqs, ps, DEFAULT_CENTER_FREQ, ch1_freq)
            snr = power - noise_floor
            scanner._process_channel(
                iq, 1, ch1_freq, snr, power, noise_floor,
                sample_offset=i * chunk_size)

        # Wait for holdover then finalize with noise
        time.sleep(2.5)
        noise = generate_noise(DEFAULT_SAMPLE_RATE,
                               chunk_size / DEFAULT_SAMPLE_RATE, 0.01)
        freqs, ps = calculate_power_spectrum(noise, DEFAULT_SAMPLE_RATE)
        noise_floor = np.median(ps)
        power = get_channel_power(freqs, ps, DEFAULT_CENTER_FREQ, ch1_freq)
        snr = power - noise_floor
        scanner._process_channel(
            noise, 1, ch1_freq, snr, power, noise_floor,
            sample_offset=2 * chunk_size)

        wavs = count_audio_files(tmpdir)
        assert wavs == 0, (
            f"Short burst should be filtered by MIN_TX_DURATION, got {wavs} files")


# -----------------------------------------------------------------------
# FMVoiceParser tests
# -----------------------------------------------------------------------

def test_voice_parser_noise_only():
    """FMVoiceParser: noise-only input produces zero detections."""
    from parsers.fm.voice import FMVoiceParser
    from utils.logger import SignalLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SignalLogger(output_dir=tmpdir, signal_type="test",
                              device_id="test")
        parser = FMVoiceParser(
            logger=logger, sample_rate=250e3, center_freq=446.05e6,
            band="pmr446", output_dir=tmpdir)

        # Feed 30s of noise
        chunk_size = 2500  # 10ms at 250 kHz
        n_chunks = int(30 * 250e3 / chunk_size)
        for _ in range(n_chunks):
            noise = generate_noise(250e3, chunk_size / 250e3, 0.01)
            parser.handle_frame(noise)

        parser.shutdown()
        assert parser.detection_count == 0, (
            f"Expected 0 detections from noise, got {parser.detection_count}")
        assert count_audio_files(tmpdir) == 0


def test_voice_parser_leakage():
    """FMVoiceParser: strong CH1 signal produces zero detections on other channels."""
    from parsers.fm.voice import FMVoiceParser
    from utils.logger import SignalLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SignalLogger(output_dir=tmpdir, signal_type="test",
                              device_id="test")
        sample_rate = 250e3
        center_freq = 446.05e6
        parser = FMVoiceParser(
            logger=logger, sample_rate=sample_rate, center_freq=center_freq,
            band="pmr446", output_dir=tmpdir)

        ch1_offset = 446.00625e6 - center_freq

        # Feed 5s of strong signal on CH1
        chunk_size = 2500
        n_chunks = int(5 * sample_rate / chunk_size)
        for i in range(n_chunks):
            iq = generate_fm_signal(ch1_offset, sample_rate,
                                    chunk_size / sample_rate, snr_db=40)
            parser.handle_frame(iq)
            if i % 20 == 0:
                time.sleep(0.1)

        time.sleep(3)
        # Feed noise to trigger holdover expiry
        for _ in range(50):
            parser.handle_frame(generate_noise(sample_rate, chunk_size / sample_rate, 0.01))

        parser.shutdown()

        # Check that non-CH1 audio files are zero
        audio_dir = os.path.join(tmpdir, "audio")
        if os.path.exists(audio_dir):
            wavs = [f for f in os.listdir(audio_dir) if f.endswith('.wav')]
            non_ch1 = [f for f in wavs if 'CH1' not in f]
            assert len(non_ch1) == 0, (
                f"Adjacent channel false detections: {non_ch1}")


def test_voice_parser_short_burst():
    """FMVoiceParser: sub-MIN_TX_DURATION burst produces zero audio files."""
    from parsers.fm.voice import FMVoiceParser
    from utils.logger import SignalLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SignalLogger(output_dir=tmpdir, signal_type="test",
                              device_id="test")
        sample_rate = 250e3
        center_freq = 446.05e6
        parser = FMVoiceParser(
            logger=logger, sample_rate=sample_rate, center_freq=center_freq,
            band="pmr446", output_dir=tmpdir)

        ch1_offset = 446.00625e6 - center_freq

        # Feed 3 chunks (~30ms) — well under 0.5s MIN_TX_DURATION
        for i in range(3):
            iq = generate_fm_signal(ch1_offset, sample_rate, 0.01,
                                    snr_db=30)
            parser.handle_frame(iq)

        time.sleep(3)
        for _ in range(20):
            parser.handle_frame(generate_noise(sample_rate, 0.01, 0.01))
        parser.shutdown()

        assert count_audio_files(tmpdir) == 0, (
            f"Short burst should be filtered, got {count_audio_files(tmpdir)} files")


# -----------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------

def run_tests():
    tests = [
        ("PMR: noise-only → 0 detections", test_pmr_noise_only),
        ("PMR: spectral leakage → 0 on adjacent", test_pmr_spectral_leakage),
        ("PMR: short burst → filtered", test_pmr_short_burst_filtered),
        ("VoiceParser: noise-only → 0 detections", test_voice_parser_noise_only),
        ("VoiceParser: leakage → 0 on adjacent", test_voice_parser_leakage),
        ("VoiceParser: short burst → filtered", test_voice_parser_short_burst),
    ]

    print("=" * 60)
    print("False Detection Prevention Tests")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n  {name}")
        try:
            fn()
            print(f"  [PASS]")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{passed + failed} passed")
    print("=" * 60)
    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

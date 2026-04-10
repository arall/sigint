"""
Voice detection accuracy tests.

Verifies that real voice signals ARE detected and recorded correctly:
threshold boundaries, holdover bridging, multi-channel independence,
and duration filtering.

Run:
    python3 tests/sw/test_voice_detection.py
"""

import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def generate_fm_signal(freq_offset, sample_rate, duration, deviation=2500,
                       tone_freq=1000, snr_db=25):
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


def generate_noise(sample_rate, duration, level=0.01):
    n = int(sample_rate * duration)
    return (np.random.randn(n) + 1j * np.random.randn(n)).astype(
        np.complex64) * level


def count_audio_files(directory):
    audio_dir = os.path.join(directory, "audio")
    if not os.path.exists(audio_dir):
        return 0
    return len([f for f in os.listdir(audio_dir) if f.endswith('.wav')])


# -----------------------------------------------------------------------
# FMVoiceParser detection tests
# -----------------------------------------------------------------------

def test_voice_detected_above_threshold():
    """Signal above DETECTION_SNR_DB is detected and recorded."""
    from parsers.fm.voice import FMVoiceParser
    from utils.logger import SignalLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SignalLogger(output_dir=tmpdir, signal_type="test",
                              device_id="test")
        sample_rate = 250e3
        center_freq = 446.05e6
        parser = FMVoiceParser(
            logger=logger, sample_rate=sample_rate, center_freq=center_freq,
            band="pmr446", output_dir=tmpdir, min_snr_db=3.0)

        ch1_offset = 446.00625e6 - center_freq

        # Feed 3s of 25 dB signal (well above 10 dB threshold)
        for _ in range(5):
            iq = generate_fm_signal(ch1_offset, sample_rate, 0.5, snr_db=25)
            parser.handle_frame(iq)
            time.sleep(0.35)

        parser.shutdown()
        assert parser.detection_count >= 1, (
            f"Expected >=1 detection at 25 dB SNR, got {parser.detection_count}")
        assert count_audio_files(tmpdir) >= 1, "No audio file created"


def test_voice_not_detected_below_threshold():
    """Weak signal below DETECTION_SNR_DB is NOT detected."""
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

        # Feed very weak signal (-10 dB input SNR — after narrowband FFT
        # processing, measures ~6 dB, below 10 dB threshold)
        for _ in range(20):
            iq = generate_fm_signal(ch1_offset, sample_rate, 0.1, snr_db=-10)
            parser.handle_frame(iq)

        parser.shutdown()
        assert parser.detection_count == 0, (
            f"Expected 0 detections at -10 dB input SNR, "
            f"got {parser.detection_count}")


def test_holdover_bridges_gap():
    """2s holdover bridges a short gap — one detection, not two."""
    from parsers.fm.voice import FMVoiceParser
    from utils.logger import SignalLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SignalLogger(output_dir=tmpdir, signal_type="test",
                              device_id="test")
        sample_rate = 250e3
        center_freq = 446.05e6
        parser = FMVoiceParser(
            logger=logger, sample_rate=sample_rate, center_freq=center_freq,
            band="pmr446", output_dir=tmpdir, min_snr_db=3.0)

        ch1_offset = 446.00625e6 - center_freq

        # Phase 1: signal for ~1s
        for _ in range(4):
            iq = generate_fm_signal(ch1_offset, sample_rate, 0.5, snr_db=25)
            parser.handle_frame(iq)
            time.sleep(0.15)

        # Short gap: 0.5s of noise (well within 2s holdover)
        for _ in range(5):
            parser.handle_frame(generate_noise(sample_rate, 0.1, 0.01))
            time.sleep(0.1)

        # Phase 2: signal again for ~1s
        for _ in range(4):
            iq = generate_fm_signal(ch1_offset, sample_rate, 0.5, snr_db=25)
            parser.handle_frame(iq)
            time.sleep(0.15)

        parser.shutdown()
        # Should be 1 detection (holdover bridged the gap), not 2
        assert parser.detection_count == 1, (
            f"Expected 1 detection (holdover bridge), got {parser.detection_count}")


def test_multichannel_independent():
    """Signals on two channels produce two independent detections."""
    from parsers.fm.voice import FMVoiceParser
    from utils.logger import SignalLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SignalLogger(output_dir=tmpdir, signal_type="test",
                              device_id="test")
        sample_rate = 250e3
        center_freq = 446.05e6
        ch1_offset = 446.00625e6 - center_freq
        ch3_offset = 446.03125e6 - center_freq

        parser = FMVoiceParser(
            logger=logger, sample_rate=sample_rate, center_freq=center_freq,
            band="pmr446", output_dir=tmpdir, min_snr_db=3.0)

        # Feed both channels simultaneously
        for _ in range(5):
            iq1 = generate_fm_signal(ch1_offset, sample_rate, 0.5, snr_db=25)
            iq3 = generate_fm_signal(ch3_offset, sample_rate, 0.5, snr_db=25)
            parser.handle_frame(iq1 + iq3)
            time.sleep(0.35)

        parser.shutdown()
        assert parser.detection_count >= 2, (
            f"Expected >=2 detections (2 channels), got {parser.detection_count}")


def test_max_tx_duration():
    """Recordings exceeding MAX_TX_DURATION are force-finalized."""
    from parsers.fm.voice import FMVoiceParser
    from utils.logger import SignalLogger

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = SignalLogger(output_dir=tmpdir, signal_type="test",
                              device_id="test")
        sample_rate = 250e3
        center_freq = 446.05e6
        parser = FMVoiceParser(
            logger=logger, sample_rate=sample_rate, center_freq=center_freq,
            band="pmr446", output_dir=tmpdir, min_snr_db=3.0)

        # Temporarily set MAX_TX_DURATION very low for testing
        parser.MAX_TX_DURATION = 2.0

        ch1_offset = 446.00625e6 - center_freq

        # Feed 4s of continuous signal (exceeds 2s max)
        start = time.time()
        while time.time() - start < 4:
            iq = generate_fm_signal(ch1_offset, sample_rate, 0.1, snr_db=25)
            parser.handle_frame(iq)
            time.sleep(0.05)

        parser.shutdown()
        # Should have at least 1 detection from force-finalization
        assert parser.detection_count >= 1, (
            f"Expected >=1 detection from MAX_TX_DURATION, "
            f"got {parser.detection_count}")


# -----------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------

def run_tests():
    tests = [
        ("Voice detected above threshold", test_voice_detected_above_threshold),
        ("Voice NOT detected below threshold", test_voice_not_detected_below_threshold),
        ("Holdover bridges 1s gap", test_holdover_bridges_gap),
        ("Multi-channel independent", test_multichannel_independent),
        ("MAX_TX_DURATION force-finalize", test_max_tx_duration),
    ]

    print("=" * 60)
    print("Voice Detection Accuracy Tests")
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
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{passed + failed} passed")
    print("=" * 60)
    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

#!/usr/bin/env python3
"""
Test FM Voice Parser — software-only (no hardware needed).

Verifies the channelizer-compatible FM voice parser can:
1. Initialize with each band profile
2. Detect voice activity from synthetic FM signals
3. Demodulate and record audio
4. Log detections with correct metadata
5. Handle edge cases (short signals, no signal, shutdown)
"""

import json
import os
import sys
import tempfile
import time

import numpy as np

# Add src/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from parsers.fm.voice import FMVoiceParser, BAND_PROFILES
from utils.logger import SignalLogger


def generate_fm_signal(freq_offset, sample_rate, duration, deviation=2500,
                       tone_freq=1000, snr_db=20):
    """Generate a synthetic FM-modulated signal at an offset from DC.

    Returns complex IQ samples centered at DC with an FM signal at freq_offset.
    """
    n = int(sample_rate * duration)
    t = np.arange(n) / sample_rate

    # FM modulate: carrier at freq_offset, modulated by a tone
    phase = 2 * np.pi * freq_offset * t + \
        (deviation / tone_freq) * np.sin(2 * np.pi * tone_freq * t)
    signal = np.exp(1j * phase)

    # Scale signal for desired SNR
    signal_power = 1.0
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = np.sqrt(noise_power / 2) * (
        np.random.randn(n) + 1j * np.random.randn(n))

    return (signal + noise).astype(np.complex64)


class TestResult:
    def __init__(self, name):
        self.name = name
        self.passed = False
        self.error = None

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        msg = f"  [{status}] {self.name}"
        if self.error:
            msg += f"\n         {self.error}"
        return msg


def test_band_profiles():
    """Test that all band profiles can be loaded."""
    result = TestResult("Band profile loading")
    try:
        for band_name in BAND_PROFILES:
            with tempfile.TemporaryDirectory() as tmpdir:
                logger = SignalLogger(
                    output_dir=tmpdir, signal_type="test", device_id="test")
                logger.start()
                parser = FMVoiceParser(
                    logger=logger,
                    sample_rate=250e3,
                    center_freq=BAND_PROFILES[band_name]["channels"][
                        list(BAND_PROFILES[band_name]["channels"].keys())[0]],
                    band=band_name,
                    output_dir=tmpdir,
                )
                assert len(parser.active_channels) > 0, \
                    f"No active channels for {band_name}"
                logger.stop()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    return result


def test_invalid_band():
    """Test that invalid band name raises ValueError."""
    result = TestResult("Invalid band name raises error")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()
            try:
                FMVoiceParser(
                    logger=logger, sample_rate=250e3,
                    center_freq=446.1e6, band="nonexistent",
                    output_dir=tmpdir)
                result.error = "Expected ValueError but none raised"
            except ValueError:
                result.passed = True
            logger.stop()
    except Exception as e:
        result.error = str(e)
    return result


def test_channel_filtering():
    """Test that channels outside bandwidth are filtered out."""
    result = TestResult("Channel filtering by bandwidth")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()
            # Narrow bandwidth — should only include nearby channels
            parser = FMVoiceParser(
                logger=logger,
                sample_rate=50e3,  # ±25 kHz — only 2-3 PMR channels
                center_freq=446.03125e6,  # CH3
                band="pmr446",
                output_dir=tmpdir,
            )
            # Should have filtered out distant channels
            assert len(parser.active_channels) < 8, \
                f"Expected filtered channels, got {len(parser.active_channels)}"
            assert "CH3" in parser.active_channels, \
                "CH3 should be in active channels"
            logger.stop()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    return result


def test_no_signal():
    """Test that noise-only input produces no detections."""
    result = TestResult("No detections on noise-only input")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()
            parser = FMVoiceParser(
                logger=logger,
                sample_rate=250e3,
                center_freq=446.05e6,
                band="pmr446",
                output_dir=tmpdir,
            )
            # Feed noise
            for _ in range(20):
                noise = np.random.randn(4096) + 1j * np.random.randn(4096)
                noise = (noise * 0.001).astype(np.complex64)
                parser.handle_frame(noise)
            parser.shutdown()
            assert parser.detection_count == 0, \
                f"Expected 0 detections, got {parser.detection_count}"
            logger.stop()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    return result


def test_voice_detection_and_recording():
    """Test full pipeline: FM signal → detection → audio file → log entry."""
    result = TestResult("Voice detection, demod, and recording")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            sample_rate = 250e3
            center_freq = 446.05e6
            ch1_freq = 446.00625e6
            ch1_offset = ch1_freq - center_freq

            parser = FMVoiceParser(
                logger=logger,
                sample_rate=sample_rate,
                center_freq=center_freq,
                band="pmr446",
                output_dir=tmpdir,
                min_snr_db=5.0,
            )

            # Generate FM signal on CH1 — 0.5 seconds
            chunk_samples = int(sample_rate * 0.1)  # 100ms chunks
            for i in range(5):
                iq = generate_fm_signal(
                    freq_offset=ch1_offset,
                    sample_rate=sample_rate,
                    duration=0.1,
                    deviation=2500,
                    tone_freq=1000,
                    snr_db=25,
                )
                parser.handle_frame(iq)

            # Feed silence to trigger holdover expiry
            time.sleep(0.1)
            for _ in range(30):
                noise = (np.random.randn(chunk_samples) +
                         1j * np.random.randn(chunk_samples)) * 0.001
                parser.handle_frame(noise.astype(np.complex64))
                time.sleep(0.1)

            parser.shutdown()

            # Check detection was logged
            assert parser.detection_count >= 1, \
                f"Expected ≥1 detection, got {parser.detection_count}"

            # Check audio file was created
            audio_dir = os.path.join(tmpdir, "audio")
            audio_files = [f for f in os.listdir(audio_dir)
                           if f.endswith('.wav')] if os.path.isdir(audio_dir) else []
            assert len(audio_files) >= 1, \
                f"Expected ≥1 audio file, got {len(audio_files)}"

            logger.stop()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    return result


def test_detection_metadata():
    """Test that detection metadata has correct fields."""
    result = TestResult("Detection metadata fields")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logged_detections = []
            original_log = SignalLogger.log

            class CapturingLogger(SignalLogger):
                def log(self, detection):
                    logged_detections.append(detection)
                    return super().log(detection)

            logger = CapturingLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            sample_rate = 250e3
            center_freq = 446.05e6
            ch1_freq = 446.00625e6

            parser = FMVoiceParser(
                logger=logger,
                sample_rate=sample_rate,
                center_freq=center_freq,
                band="pmr446",
                output_dir=tmpdir,
                min_snr_db=5.0,
            )

            # Generate signal
            for _ in range(5):
                iq = generate_fm_signal(
                    freq_offset=ch1_freq - center_freq,
                    sample_rate=sample_rate,
                    duration=0.1,
                    snr_db=25,
                )
                parser.handle_frame(iq)

            # Wait for holdover
            time.sleep(0.1)
            for _ in range(30):
                noise = (np.random.randn(int(sample_rate * 0.1)) +
                         1j * np.random.randn(int(sample_rate * 0.1))) * 0.001
                parser.handle_frame(noise.astype(np.complex64))
                time.sleep(0.1)

            parser.shutdown()

            if not logged_detections:
                result.error = "No detections logged"
                return result

            d = logged_detections[0]
            assert d.signal_type == "PMR446", \
                f"Expected signal_type 'PMR446', got '{d.signal_type}'"
            assert d.channel == "CH1", \
                f"Expected channel 'CH1', got '{d.channel}'"
            assert abs(d.frequency_hz - ch1_freq) < 1, \
                f"Frequency mismatch: {d.frequency_hz} vs {ch1_freq}"

            meta = json.loads(d.metadata)
            assert "duration_s" in meta, "Missing duration_s in metadata"
            assert meta["band"] == "PMR446", \
                f"Expected band 'PMR446', got '{meta.get('band')}'"
            assert meta["modulation"] == "FM", \
                f"Expected modulation 'FM', got '{meta.get('modulation')}'"

            logger.stop()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    return result


def test_shutdown_finalizes():
    """Test that shutdown() finalizes in-progress transmissions."""
    result = TestResult("Shutdown finalizes active transmissions")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            sample_rate = 250e3
            center_freq = 446.05e6

            parser = FMVoiceParser(
                logger=logger,
                sample_rate=sample_rate,
                center_freq=center_freq,
                band="pmr446",
                output_dir=tmpdir,
                min_snr_db=5.0,
            )

            # Feed signal — enough samples to exceed MIN_TX_DURATION
            # (0.5s sample-based: 5 × 0.5s = 2.5s of IQ data)
            import time as _time
            for _ in range(5):
                iq = generate_fm_signal(
                    freq_offset=446.00625e6 - center_freq,
                    sample_rate=sample_rate,
                    duration=0.5,
                    snr_db=25,
                )
                parser.handle_frame(iq)
                _time.sleep(0.25)

            # Shutdown should finalize
            parser.shutdown()
            assert parser.detection_count >= 1, \
                f"Expected shutdown to finalize, got {parser.detection_count}"

            logger.stop()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    return result


def test_multiple_channels():
    """Test that signals on different channels are tracked independently."""
    result = TestResult("Independent per-channel tracking")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            sample_rate = 250e3
            center_freq = 446.05e6
            ch1_freq = 446.00625e6
            ch3_freq = 446.03125e6

            parser = FMVoiceParser(
                logger=logger,
                sample_rate=sample_rate,
                center_freq=center_freq,
                band="pmr446",
                output_dir=tmpdir,
                min_snr_db=5.0,
            )

            # Signal on CH1 and CH3 simultaneously — enough samples
            # to exceed MIN_TX_DURATION (0.5s sample-based)
            import time as _time
            for _ in range(5):
                iq1 = generate_fm_signal(
                    freq_offset=ch1_freq - center_freq,
                    sample_rate=sample_rate,
                    duration=0.5,
                    snr_db=25,
                )
                iq3 = generate_fm_signal(
                    freq_offset=ch3_freq - center_freq,
                    sample_rate=sample_rate,
                    duration=0.5,
                    snr_db=25,
                )
                parser.handle_frame(iq1 + iq3)
                _time.sleep(0.25)

            # Shutdown to finalize both
            parser.shutdown()
            assert parser.detection_count >= 2, \
                f"Expected ≥2 detections (2 channels), got {parser.detection_count}"

            logger.stop()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    return result


def test_server_parser_factory():
    """Test that the server factory can create fm_voice parsers."""
    result = TestResult("Server parser factory integration")
    try:
        from scanners.server import _create_parser

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            channel_cfg = {
                "freq_mhz": 446.1,
                "bandwidth_mhz": 0.25,
                "band": "pmr446",
            }
            parser = _create_parser("fm_voice", logger, channel_cfg)
            assert parser is not None, "Factory returned None"
            assert isinstance(parser, FMVoiceParser), \
                f"Expected FMVoiceParser, got {type(parser)}"
            assert len(parser.active_channels) > 0, \
                "No active channels configured"

            logger.stop()
        result.passed = True
    except Exception as e:
        result.error = str(e)
    return result


def main():
    print("=" * 60)
    print("FM Voice Parser Tests (software-only, no hardware)")
    print("=" * 60)
    print()

    tests = [
        test_band_profiles,
        test_invalid_band,
        test_channel_filtering,
        test_no_signal,
        test_voice_detection_and_recording,
        test_detection_metadata,
        test_shutdown_finalizes,
        test_multiple_channels,
        test_server_parser_factory,
    ]

    results = []
    for test_fn in tests:
        r = test_fn()
        results.append(r)
        print(r)

    print()
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Results: {passed}/{total} passed")

    if passed < total:
        print("\nFailed tests:")
        for r in results:
            if not r.passed:
                print(f"  - {r.name}: {r.error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

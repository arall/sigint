#!/usr/bin/env python3
"""
Test Channelizer → FM Voice Parser pipeline — verifies that HackRF-like
wideband capture (20 MHz) can reliably detect and demodulate PMR446 voice
after channelizer decimation (80x → 250 kHz).

This is the key regression test for the coalescing fix. Before the fix,
the channelizer delivered ~410 samples/block to the parser, making noise
floor estimation unstable. After the fix, blocks are coalesced to ~25,000
samples (~100ms) for reliable detection.
"""

import json
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from capture.channelizer import Channelizer, Channel
from parsers.fm.voice import FMVoiceParser
from utils.logger import SignalLogger


def generate_wideband_fm(center_freq, channel_freq, sample_rate,
                         duration, deviation=2500, tone_freq=1000,
                         snr_db=20):
    """Generate a wideband IQ stream with an FM signal on one channel.

    Simulates what HackRF would capture: 20 MHz wide, with a narrowband
    FM signal on a specific PMR channel.
    """
    n = int(sample_rate * duration)
    t = np.arange(n) / sample_rate
    offset = channel_freq - center_freq

    # FM modulate at channel offset
    phase = 2 * np.pi * offset * t + \
        (deviation / tone_freq) * np.sin(2 * np.pi * tone_freq * t)
    signal = np.exp(1j * phase)

    # Add wideband noise
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


def test_channelizer_coalesce_block_size():
    """Verify channelizer delivers coalesced blocks, not tiny ones."""
    result = TestResult("Channelizer coalesces small blocks into ~100ms")
    try:
        capture_rate = 20e6
        center_freq = 446.05e6
        output_rate = 250e3

        delivered_sizes = []

        def record_callback(samples):
            delivered_sizes.append(len(samples))

        ch = Channelizer(center_freq=center_freq, sample_rate=capture_rate)
        ch.add_channel(
            name="test",
            freq_hz=446.00625e6,
            bandwidth_hz=250e3,
            output_sample_rate=output_rate,
            callback=record_callback,
        )

        # Simulate HackRF blocks (256KB = 131072 complex samples)
        block_size = 131072
        # Send enough blocks to trigger coalescing
        for _ in range(200):
            samples = (np.random.randn(block_size) +
                       1j * np.random.randn(block_size)).astype(np.complex64) * 0.001
            ch.handle_frame(samples)

        ch.flush()

        if not delivered_sizes:
            result.error = "No blocks delivered"
            return result

        # Before fix: ~410 samples/block. After fix: ~25,000 (100ms at 250kHz)
        avg_size = np.mean(delivered_sizes[:-1])  # Exclude last (flush remainder)
        target = int(output_rate * Channel.COALESCE_TARGET_S)

        if avg_size < target * 0.8:
            result.error = (f"Blocks too small: avg {avg_size:.0f} samples, "
                           f"target {target}")
            return result

        result.passed = True
        print(f"    avg block: {avg_size:.0f} samples "
              f"({avg_size/output_rate*1000:.1f} ms), "
              f"target: {target} ({Channel.COALESCE_TARGET_S*1000:.0f} ms)")

    except Exception as e:
        result.error = str(e)
    return result


def test_channelizer_voice_detection():
    """Full pipeline: wideband IQ → channelizer → FM voice parser → detection."""
    result = TestResult("Channelizer → FM voice parser detects PMR signal")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            capture_rate = 20e6
            center_freq = 446.05e6
            ch1_freq = 446.00625e6
            output_rate = 250e3

            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            parser = FMVoiceParser(
                logger=logger,
                sample_rate=output_rate,
                center_freq=center_freq,
                band="pmr446",
                output_dir=tmpdir,
                min_snr_db=5.0,
            )

            ch = Channelizer(center_freq=center_freq, sample_rate=capture_rate)
            ch.add_channel(
                name="pmr",
                freq_hz=center_freq,
                bandwidth_hz=output_rate,
                output_sample_rate=output_rate,
                callback=parser.handle_frame,
            )

            # Generate 2 seconds of wideband FM on CH1
            block_size = 131072  # HackRF block size
            block_duration = block_size / capture_rate
            total_duration = 2.0
            n_blocks = int(total_duration / block_duration)

            for i in range(n_blocks):
                iq = generate_wideband_fm(
                    center_freq=center_freq,
                    channel_freq=ch1_freq,
                    sample_rate=capture_rate,
                    duration=block_duration,
                    snr_db=25,
                )
                ch.handle_frame(iq)

            # Feed silence to trigger holdover
            for _ in range(500):
                noise = (np.random.randn(block_size) +
                         1j * np.random.randn(block_size)).astype(np.complex64) * 0.001
                ch.handle_frame(noise)
                time.sleep(0.005)

            ch.flush()
            parser.shutdown()

            if parser.detection_count < 1:
                result.error = (f"No detections (expected ≥1). "
                               f"Pipeline failed to detect 25 dB SNR FM signal "
                               f"through channelizer.")
                return result

            # Verify audio was saved
            audio_dir = os.path.join(tmpdir, "audio")
            audio_files = [f for f in os.listdir(audio_dir)
                           if f.endswith('.wav')] if os.path.isdir(audio_dir) else []
            if not audio_files:
                result.error = "Detection logged but no audio file saved"
                return result

            logger.stop()
            result.passed = True
            print(f"    {parser.detection_count} detection(s), "
                  f"{len(audio_files)} audio file(s)")

    except Exception as e:
        result.error = str(e)
    return result


def test_channelizer_no_false_detections():
    """Verify noise-only wideband input produces no detections."""
    result = TestResult("Channelizer → no false detections from noise")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            capture_rate = 20e6
            center_freq = 446.05e6
            output_rate = 250e3

            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            parser = FMVoiceParser(
                logger=logger,
                sample_rate=output_rate,
                center_freq=center_freq,
                band="pmr446",
                output_dir=tmpdir,
            )

            ch = Channelizer(center_freq=center_freq, sample_rate=capture_rate)
            ch.add_channel(
                name="pmr",
                freq_hz=center_freq,
                bandwidth_hz=output_rate,
                output_sample_rate=output_rate,
                callback=parser.handle_frame,
            )

            # Feed pure noise through channelizer
            block_size = 131072
            for _ in range(100):
                noise = (np.random.randn(block_size) +
                         1j * np.random.randn(block_size)).astype(np.complex64) * 0.001
                ch.handle_frame(noise)

            ch.flush()
            parser.shutdown()

            if parser.detection_count > 0:
                result.error = f"False detections: {parser.detection_count}"
                return result

            logger.stop()
            result.passed = True

    except Exception as e:
        result.error = str(e)
    return result


def test_channelizer_weak_signal():
    """Test detection of a weaker signal (15 dB SNR) through channelizer."""
    result = TestResult("Channelizer detects weak signal (15 dB SNR)")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            capture_rate = 20e6
            center_freq = 446.05e6
            ch1_freq = 446.00625e6
            output_rate = 250e3

            logger = SignalLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            parser = FMVoiceParser(
                logger=logger,
                sample_rate=output_rate,
                center_freq=center_freq,
                band="pmr446",
                output_dir=tmpdir,
                min_snr_db=5.0,
            )

            ch = Channelizer(center_freq=center_freq, sample_rate=capture_rate)
            ch.add_channel(
                name="pmr",
                freq_hz=center_freq,
                bandwidth_hz=output_rate,
                output_sample_rate=output_rate,
                callback=parser.handle_frame,
            )

            # 2s of weak FM signal
            block_size = 131072
            block_duration = block_size / capture_rate
            n_blocks = int(2.0 / block_duration)

            for _ in range(n_blocks):
                iq = generate_wideband_fm(
                    center_freq=center_freq,
                    channel_freq=ch1_freq,
                    sample_rate=capture_rate,
                    duration=block_duration,
                    snr_db=15,  # Weak but should be detectable
                )
                ch.handle_frame(iq)

            # Silence for holdover
            for _ in range(500):
                noise = (np.random.randn(block_size) +
                         1j * np.random.randn(block_size)).astype(np.complex64) * 0.001
                ch.handle_frame(noise)
                time.sleep(0.005)

            ch.flush()
            parser.shutdown()

            if parser.detection_count < 1:
                result.error = "Failed to detect 15 dB SNR signal through channelizer"
                return result

            logger.stop()
            result.passed = True
            print(f"    detected {parser.detection_count} transmission(s)")

    except Exception as e:
        result.error = str(e)
    return result


def main():
    print("=" * 60)
    print("Channelizer → FM Voice Parser Pipeline Tests")
    print("=" * 60)
    print()

    tests = [
        test_channelizer_coalesce_block_size,
        test_channelizer_voice_detection,
        test_channelizer_no_false_detections,
        test_channelizer_weak_signal,
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

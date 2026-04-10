"""
Test PMR446 async streaming pipeline.

Verifies that switching from sync read+sleep to async streaming
eliminates sample gaps and produces correct continuous audio.
"""

import sys
import os
import threading
import queue
import time

import numpy as np

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from scanners.pmr import (
    PMR_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_CENTER_FREQ,
    DEFAULT_NUM_SAMPLES,
    extract_and_demodulate_buffers,
    calculate_power_spectrum,
    get_channel_power,
)


def generate_fm_signal(freq_hz, sample_rate, center_freq, num_samples,
                       offset=0, tone_hz=1000, fm_deviation=2500):
    """Generate IQ samples with an FM-modulated tone on a given frequency."""
    t = (np.arange(num_samples) + offset) / sample_rate
    freq_offset = freq_hz - center_freq
    # FM modulate: carrier at freq_offset with tone modulation
    phase = 2 * np.pi * freq_offset * t + (fm_deviation / tone_hz) * np.sin(2 * np.pi * tone_hz * t)
    signal = np.exp(1j * phase).astype(np.complex64)
    # Add some noise
    noise = (np.random.randn(num_samples) + 1j * np.random.randn(num_samples)) * 0.01
    return (signal + noise).astype(np.complex64)


def test_continuous_vs_gapped_buffers():
    """Compare audio output from continuous buffers vs gapped (old sleep-based) buffers.

    Continuous buffers (async) should produce audio with ~100% non-silent samples.
    Gapped buffers (sync+sleep) should have ~65% silence from the gaps.
    """
    sample_rate = DEFAULT_SAMPLE_RATE
    center_freq = DEFAULT_CENTER_FREQ
    channel_freq = PMR_CHANNELS[1]  # CH1
    num_samples = DEFAULT_NUM_SAMPLES
    tone_hz = 1000

    num_chunks = 20
    read_time = num_samples / sample_rate  # ~109ms per chunk

    # --- Continuous buffers (async streaming, no gaps) ---
    continuous_buffers = []
    offset = 0
    for _ in range(num_chunks):
        samples = generate_fm_signal(channel_freq, sample_rate, center_freq,
                                     num_samples, offset=offset, tone_hz=tone_hz)
        continuous_buffers.append((offset, samples))
        offset += num_samples  # No gap

    continuous_audio, audio_rate = extract_and_demodulate_buffers(
        continuous_buffers, sample_rate, center_freq, channel_freq)

    # --- Gapped buffers (simulating old sync+sleep, 200ms sleep between reads) ---
    gapped_buffers = []
    offset = 0
    sleep_samples = int(0.2 * sample_rate)  # 200ms sleep gap in samples
    for _ in range(num_chunks):
        samples = generate_fm_signal(channel_freq, sample_rate, center_freq,
                                     num_samples, offset=offset, tone_hz=tone_hz)
        gapped_buffers.append((offset, samples))
        offset += num_samples + sleep_samples  # Gap from sleep

    gapped_audio, _ = extract_and_demodulate_buffers(
        gapped_buffers, sample_rate, center_freq, channel_freq)

    # --- Verify continuous audio has no silence gaps ---
    # Split continuous audio into chunks and check none are silent
    chunk_size = int(audio_rate * 0.05)  # 50ms chunks
    continuous_silent = 0
    total_chunks_c = len(continuous_audio) // chunk_size
    for i in range(total_chunks_c):
        chunk = continuous_audio[i * chunk_size:(i + 1) * chunk_size]
        rms = np.sqrt(np.mean(chunk ** 2))
        if rms < 0.01:
            continuous_silent += 1

    continuous_coverage = 1.0 - (continuous_silent / max(total_chunks_c, 1))

    # --- Verify gapped audio has silence from gaps ---
    gapped_silent = 0
    total_chunks_g = len(gapped_audio) // chunk_size
    for i in range(total_chunks_g):
        chunk = gapped_audio[i * chunk_size:(i + 1) * chunk_size]
        rms = np.sqrt(np.mean(chunk ** 2))
        if rms < 0.01:
            gapped_silent += 1

    gapped_coverage = 1.0 - (gapped_silent / max(total_chunks_g, 1))

    print(f"Continuous audio: {len(continuous_audio)} samples, "
          f"{continuous_coverage:.0%} non-silent")
    print(f"Gapped audio:     {len(gapped_audio)} samples, "
          f"{gapped_coverage:.0%} non-silent")

    # Continuous should be >95% non-silent
    assert continuous_coverage > 0.95, (
        f"Continuous audio should be >95% non-silent, got {continuous_coverage:.0%}")

    # Gapped should have significantly more silence (< 60% non-silent)
    assert gapped_coverage < 0.60, (
        f"Gapped audio should be <60% non-silent, got {gapped_coverage:.0%}")

    print("PASS: Continuous streaming eliminates audio gaps\n")


def test_async_queue_pipeline():
    """Test that the async queue pipeline processes all chunks without dropping."""
    sample_rate = DEFAULT_SAMPLE_RATE
    center_freq = DEFAULT_CENTER_FREQ
    num_samples = DEFAULT_NUM_SAMPLES
    num_chunks = 30

    sample_queue = queue.Queue(maxsize=64)
    stop_event = threading.Event()
    chunks_produced = []
    chunks_consumed = []

    # Simulate async reader thread pushing chunks
    def producer():
        offset = 0
        for i in range(num_chunks):
            if stop_event.is_set():
                break
            samples = generate_fm_signal(
                PMR_CHANNELS[1], sample_rate, center_freq,
                num_samples, offset=offset)
            sample_queue.put(samples)
            chunks_produced.append(offset)
            offset += num_samples
            # Simulate real-time: each chunk represents ~109ms of data
            time.sleep(0.01)  # Fast for testing
        stop_event.set()

    producer_thread = threading.Thread(target=producer, daemon=True)
    producer_thread.start()

    # Simulate consumer (main loop)
    while not stop_event.is_set() or not sample_queue.empty():
        try:
            samples = sample_queue.get(timeout=0.5)
            chunks_consumed.append(len(samples))
        except queue.Empty:
            continue

    producer_thread.join(timeout=5)

    print(f"Produced: {len(chunks_produced)} chunks")
    print(f"Consumed: {len(chunks_consumed)} chunks")

    assert len(chunks_consumed) == len(chunks_produced), (
        f"Dropped chunks: produced {len(chunks_produced)}, "
        f"consumed {len(chunks_consumed)}")

    print("PASS: Queue pipeline processes all chunks without dropping\n")


def test_signal_detection_on_continuous_stream():
    """Verify channel power detection works correctly on continuous samples."""
    sample_rate = DEFAULT_SAMPLE_RATE
    center_freq = DEFAULT_CENTER_FREQ
    channel_freq = PMR_CHANNELS[3]  # CH3

    # Generate signal on CH3
    samples = generate_fm_signal(channel_freq, sample_rate, center_freq,
                                 DEFAULT_NUM_SAMPLES)
    freqs, power_spectrum = calculate_power_spectrum(samples, sample_rate)
    noise_floor = np.median(power_spectrum)

    # CH3 should have strong signal
    ch3_power = get_channel_power(freqs, power_spectrum, center_freq, channel_freq)
    ch3_snr = ch3_power - noise_floor

    # CH8 (furthest from CH3) should be much weaker
    ch8_power = get_channel_power(freqs, power_spectrum, center_freq, PMR_CHANNELS[8])
    ch8_snr = ch8_power - noise_floor

    print(f"CH3 (signal):  power={ch3_power:.1f} dB, SNR={ch3_snr:.1f} dB")
    print(f"CH8 (no signal): power={ch8_power:.1f} dB, SNR={ch8_snr:.1f} dB")

    assert ch3_snr > 10, f"CH3 should have >10 dB SNR, got {ch3_snr:.1f}"
    assert ch3_snr > ch8_snr + 10, (
        f"CH3 should be >10 dB stronger than CH8, got {ch3_snr:.1f} vs {ch8_snr:.1f}")

    print("PASS: Signal detection works on continuous stream\n")


if __name__ == "__main__":
    print("=" * 60)
    print("PMR446 Async Streaming Tests")
    print("=" * 60 + "\n")

    test_signal_detection_on_continuous_stream()
    test_async_queue_pipeline()
    test_continuous_vs_gapped_buffers()

    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)

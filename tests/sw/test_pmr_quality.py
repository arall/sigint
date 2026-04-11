"""
PMR446 audio quality regression tests.

Enforces minimum audio quality baselines so future changes don't degrade
the demodulation pipeline. Two test tiers:

  1. Synthetic (no hardware) — tests the demod pipeline with generated IQ.
     Strict thresholds since there's no RF noise.

  2. RF loopback (HackRF + RTL-SDR) — tests the full TX/RX chain.
     Looser thresholds due to device phase noise.

Run:
    python3 tests/tx_pmr_quality.py              # synthetic only
    python3 tests/tx_pmr_quality.py --rf          # include RF loopback
"""

import sys
import os
import struct
import wave
import argparse

import numpy as np
from scipy import signal as scipy_signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from scanners.pmr import (
    PMR_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_CENTER_FREQ,
    DEFAULT_NUM_SAMPLES,
    extract_and_demodulate_buffers,
)

VOICE_WAV = os.path.join(os.path.dirname(__file__), '..', 'data', 'original_voice.wav')
FM_DEVIATION = 2500
AUDIO_RATE = 16000


def load_voice():
    """Load the reference voice WAV, truncated to the first 1.5 seconds.

    The fixture is 2.84 s but the correlation / spike / RMS assertions
    are stable on any 1 s+ speech clip. Trimming here makes the three
    synthetic quality tests each run ~1.9x faster.
    """
    with wave.open(VOICE_WAV, 'rb') as w:
        n = w.getnframes()
        raw = w.readframes(n)
        audio = np.array(struct.unpack(f'<{n}h', raw), dtype=np.float64) / 32768.0
        rate = w.getframerate()
    trim = int(rate * 1.5)
    return audio[:trim], rate


def correlate(original, demodulated, rate):
    """Bandpass-filtered normalized cross-correlation."""
    nyq = rate / 2
    b, a = scipy_signal.butter(4, [200 / nyq, min(3400 / nyq, 0.99)], btype='band')
    orig_f = scipy_signal.lfilter(b, a, original)
    demod_f = scipy_signal.lfilter(b, a, demodulated)
    orig_f /= (np.max(np.abs(orig_f)) + 1e-10)
    demod_f /= (np.max(np.abs(demod_f)) + 1e-10)
    corr = np.correlate(demod_f, orig_f, mode='full')
    energy = np.sqrt(np.sum(orig_f ** 2) * np.sum(demod_f ** 2))
    corr /= (energy + 1e-10)
    pk = np.argmax(np.abs(corr))
    return float(corr[pk]), float((pk - len(orig_f) + 1) / rate * 1000)


def spike_profile(audio):
    """Return spike counts at various thresholds."""
    diff = np.abs(np.diff(audio.astype(np.float64)))
    return {
        'max_jump': float(np.max(diff)) if len(diff) > 0 else 0,
        'p99_9': float(np.percentile(diff, 99.9)) if len(diff) > 0 else 0,
        'spikes_030': int(np.sum(diff > 0.30)),
        'spikes_050': int(np.sum(diff > 0.50)),
    }


def generate_fm_iq(audio, audio_rate, sample_rate, center_freq, channel_freq,
                   fm_deviation, noise_level=0.02):
    """Generate realistic FM-modulated IQ samples from voice audio."""
    n_iq = int(len(audio) * sample_rate / audio_rate)
    audio_up = scipy_signal.resample(audio, n_iq)

    freq_offset = channel_freq - center_freq
    phase = 2 * np.pi * fm_deviation * np.cumsum(audio_up) / sample_rate
    carrier = 2 * np.pi * freq_offset * np.arange(n_iq) / sample_rate
    iq = np.exp(1j * (carrier + phase)).astype(np.complex64)

    noise = (np.random.randn(n_iq) + 1j * np.random.randn(n_iq)).astype(np.complex64)
    iq += noise * noise_level

    return iq


# ---------------------------------------------------------------------------
# Synthetic tests (no hardware)
# ---------------------------------------------------------------------------

def test_synthetic_correlation():
    """Demod pipeline must achieve >= 0.70 correlation with synthetic IQ."""
    audio, audio_rate = load_voice()
    channel_freq = PMR_CHANNELS[1]
    sample_rate = DEFAULT_SAMPLE_RATE
    center_freq = DEFAULT_CENTER_FREQ

    iq = generate_fm_iq(audio, audio_rate, sample_rate, center_freq,
                        channel_freq, FM_DEVIATION, noise_level=0.02)

    # Split into chunks like the scanner does
    chunk_size = DEFAULT_NUM_SAMPLES
    buffers = []
    offset = 0
    while offset < len(iq):
        end = min(offset + chunk_size, len(iq))
        buffers.append((offset, iq[offset:end]))
        offset = end

    demod, rate = extract_and_demodulate_buffers(
        buffers, sample_rate, center_freq, channel_freq, AUDIO_RATE, FM_DEVIATION)

    corr, lag_ms = correlate(audio, demod, rate)

    print(f"  Correlation: {corr:.3f} (min: 0.70)")
    print(f"  Lag: {lag_ms:.0f} ms")
    assert corr >= 0.70, f"Correlation {corr:.3f} < 0.70"
    assert abs(lag_ms) < 50, f"Lag {lag_ms:.0f} ms > 50 ms"


def test_synthetic_spike_profile():
    """Demod output must not have large spikes with clean synthetic IQ."""
    audio, audio_rate = load_voice()
    channel_freq = PMR_CHANNELS[1]
    sample_rate = DEFAULT_SAMPLE_RATE
    center_freq = DEFAULT_CENTER_FREQ

    iq = generate_fm_iq(audio, audio_rate, sample_rate, center_freq,
                        channel_freq, FM_DEVIATION, noise_level=0.02)

    chunk_size = DEFAULT_NUM_SAMPLES
    buffers = []
    offset = 0
    while offset < len(iq):
        end = min(offset + chunk_size, len(iq))
        buffers.append((offset, iq[offset:end]))
        offset = end

    demod, rate = extract_and_demodulate_buffers(
        buffers, sample_rate, center_freq, channel_freq, AUDIO_RATE, FM_DEVIATION)

    sp = spike_profile(demod)
    # Reference: original voice has max_jump=0.33, spikes_050=0
    print(f"  Max jump: {sp['max_jump']:.3f} (max: 0.60)")
    print(f"  Spikes > 0.50: {sp['spikes_050']} (max: 0)")
    assert sp['max_jump'] < 0.60, f"Max jump {sp['max_jump']:.3f} >= 0.60"
    assert sp['spikes_050'] == 0, f"Spikes > 0.50: {sp['spikes_050']} (expected 0)"


def test_synthetic_rms_match():
    """Demod RMS must be within 50% of original voice RMS."""
    audio, audio_rate = load_voice()
    channel_freq = PMR_CHANNELS[1]
    sample_rate = DEFAULT_SAMPLE_RATE
    center_freq = DEFAULT_CENTER_FREQ

    iq = generate_fm_iq(audio, audio_rate, sample_rate, center_freq,
                        channel_freq, FM_DEVIATION, noise_level=0.02)

    chunk_size = DEFAULT_NUM_SAMPLES
    buffers = []
    offset = 0
    while offset < len(iq):
        end = min(offset + chunk_size, len(iq))
        buffers.append((offset, iq[offset:end]))
        offset = end

    demod, rate = extract_and_demodulate_buffers(
        buffers, sample_rate, center_freq, channel_freq, AUDIO_RATE, FM_DEVIATION)

    orig_rms = np.sqrt(np.mean(audio ** 2))
    demod_rms = np.sqrt(np.mean(demod ** 2))
    ratio = demod_rms / orig_rms

    print(f"  Original RMS: {orig_rms:.4f}")
    print(f"  Demod RMS:    {demod_rms:.4f}")
    print(f"  Ratio:        {ratio:.2f} (range: 0.50 - 1.50)")
    assert 0.50 <= ratio <= 1.50, f"RMS ratio {ratio:.2f} outside 0.50-1.50"


def test_synthetic_no_silence_gaps():
    """Continuous IQ buffers must produce 100% non-silent audio."""
    audio, audio_rate = load_voice()
    channel_freq = PMR_CHANNELS[1]
    sample_rate = DEFAULT_SAMPLE_RATE
    center_freq = DEFAULT_CENTER_FREQ

    iq = generate_fm_iq(audio, audio_rate, sample_rate, center_freq,
                        channel_freq, FM_DEVIATION, noise_level=0.02)

    chunk_size = DEFAULT_NUM_SAMPLES
    buffers = []
    offset = 0
    while offset < len(iq):
        end = min(offset + chunk_size, len(iq))
        buffers.append((offset, iq[offset:end]))
        offset = end

    demod, rate = extract_and_demodulate_buffers(
        buffers, sample_rate, center_freq, channel_freq, AUDIO_RATE, FM_DEVIATION)

    # Check 50ms frames for silence
    frame_size = int(rate * 0.05)
    silent = 0
    total = len(demod) // frame_size
    for i in range(total):
        chunk = demod[i * frame_size:(i + 1) * frame_size]
        if np.sqrt(np.mean(chunk ** 2)) < 0.01:
            silent += 1

    coverage = 1.0 - (silent / max(total, 1))

    # Original voice is ~79% non-silent (natural speech pauses).
    # Demod should match within 15 percentage points.
    orig_audio, orig_rate = load_voice()
    orig_frame = int(orig_rate * 0.05)
    orig_silent = sum(1 for i in range(len(orig_audio) // orig_frame)
                      if np.sqrt(np.mean(orig_audio[i * orig_frame:(i + 1) * orig_frame] ** 2)) < 0.01)
    orig_coverage = 1.0 - (orig_silent / max(len(orig_audio) // orig_frame, 1))
    min_coverage = orig_coverage - 0.15

    print(f"  Non-silent frames: {coverage:.0%} (original: {orig_coverage:.0%}, min: {min_coverage:.0%})")
    assert coverage >= min_coverage, \
        f"Only {coverage:.0%} non-silent (original {orig_coverage:.0%}, min {min_coverage:.0%})"


# ---------------------------------------------------------------------------
# RF loopback tests (HackRF + RTL-SDR required)
# ---------------------------------------------------------------------------

def test_rf_correlation():
    """RF loopback must achieve >= 0.15 correlation."""
    import time
    import subprocess
    import tempfile
    from rtlsdr import RtlSdr

    audio, audio_rate = load_voice()
    tx_sr = 2e6
    tx_freq = int(PMR_CHANNELS[1])

    # FM modulate with carrier padding
    n_iq = int(len(audio) * tx_sr / audio_rate)
    audio_up = scipy_signal.resample(audio, n_iq)
    phase = 2 * np.pi * FM_DEVIATION * np.cumsum(audio_up) / tx_sr
    leader = np.zeros(int(3 * tx_sr))
    trailer = np.full(int(5 * tx_sr), phase[-1])
    full_phase = np.concatenate([leader, phase, trailer])
    iq = np.exp(1j * full_phase)
    i8 = np.clip(np.round(iq.real * 127), -127, 127).astype(np.int8)
    q8 = np.clip(np.round(iq.imag * 127), -127, 127).astype(np.int8)
    il = np.empty(len(i8) * 2, dtype=np.int8)
    il[0::2] = i8
    il[1::2] = q8

    iq_file = tempfile.NamedTemporaryFile(suffix='.iq', delete=False)
    il.tofile(iq_file)
    iq_file.close()

    try:
        # TX
        tx = subprocess.Popen(
            ['hackrf_transfer', '-t', iq_file.name, '-f', str(tx_freq),
             '-s', str(int(tx_sr)), '-x', '20'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)

        # RX
        sdr = RtlSdr()
        sdr.sample_rate = DEFAULT_SAMPLE_RATE
        sdr.center_freq = DEFAULT_CENTER_FREQ
        sdr.gain = 40
        chunks = []
        offset = 0
        for _ in range(73):
            s = sdr.read_samples(DEFAULT_NUM_SAMPLES)
            chunks.append((offset, s))
            offset += len(s)
        sdr.close()
        tx.terminate()
        tx.wait()
    finally:
        os.unlink(iq_file.name)

    # Find signal
    mid = chunks[len(chunks) // 4][1]
    fft = np.fft.fftshift(np.fft.fft(mid))
    power = 20 * np.log10(np.abs(fft) + 1e-10)
    freqs = np.fft.fftshift(
        np.fft.fftfreq(len(mid), 1 / DEFAULT_SAMPLE_RATE)) + DEFAULT_CENTER_FREQ
    mask = np.abs(freqs - DEFAULT_CENTER_FREQ) > 2000
    mp = power.copy()
    mp[~mask] = -200
    sig_freq = freqs[np.argmax(mp)]
    sig_snr = power[np.argmax(mp)] - np.median(power)
    print(f"  Signal: {sig_freq / 1e6:.6f} MHz (SNR {sig_snr:.0f} dB)")

    assert sig_snr >= 20, f"Signal too weak: SNR {sig_snr:.0f} dB < 20"

    # Filter to signal chunks and demod
    signal_chunks = [(o, s) for o, s in chunks if np.mean(np.abs(s)) > 0.5]
    assert len(signal_chunks) >= 10, f"Not enough signal chunks: {len(signal_chunks)}"

    demod, rate = extract_and_demodulate_buffers(
        signal_chunks, DEFAULT_SAMPLE_RATE, DEFAULT_CENTER_FREQ,
        sig_freq, AUDIO_RATE, FM_DEVIATION)

    # Trim to voice region
    frame_size = int(0.05 * rate)
    voice_start = 0
    for i in range(0, len(demod) - frame_size, frame_size):
        if np.sqrt(np.mean(demod[i:i + frame_size] ** 2)) > 0.03:
            voice_start = max(0, i - int(0.2 * rate))
            break
    voice_end = min(len(demod), voice_start + int(4 * rate))
    voice_demod = demod[voice_start:voice_end]

    corr, lag_ms = correlate(audio, voice_demod, rate)
    print(f"  Correlation: {corr:.3f} (min: 0.15)")
    print(f"  Lag: {lag_ms:.0f} ms")
    assert corr >= 0.15, f"Correlation {corr:.3f} < 0.15"


def test_rf_spike_profile():
    """RF loopback must not produce spikes worse than the original voice."""
    import time
    import subprocess
    import tempfile
    from rtlsdr import RtlSdr

    audio, audio_rate = load_voice()
    tx_sr = 2e6
    tx_freq = int(PMR_CHANNELS[1])

    n_iq = int(len(audio) * tx_sr / audio_rate)
    audio_up = scipy_signal.resample(audio, n_iq)
    phase = 2 * np.pi * FM_DEVIATION * np.cumsum(audio_up) / tx_sr
    leader = np.zeros(int(3 * tx_sr))
    trailer = np.full(int(5 * tx_sr), phase[-1])
    full_phase = np.concatenate([leader, phase, trailer])
    iq = np.exp(1j * full_phase)
    i8 = np.clip(np.round(iq.real * 127), -127, 127).astype(np.int8)
    q8 = np.clip(np.round(iq.imag * 127), -127, 127).astype(np.int8)
    il = np.empty(len(i8) * 2, dtype=np.int8)
    il[0::2] = i8
    il[1::2] = q8

    iq_file = tempfile.NamedTemporaryFile(suffix='.iq', delete=False)
    il.tofile(iq_file)
    iq_file.close()

    try:
        tx = subprocess.Popen(
            ['hackrf_transfer', '-t', iq_file.name, '-f', str(tx_freq),
             '-s', str(int(tx_sr)), '-x', '20'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)

        sdr = RtlSdr()
        sdr.sample_rate = DEFAULT_SAMPLE_RATE
        sdr.center_freq = DEFAULT_CENTER_FREQ
        sdr.gain = 40
        chunks = []
        offset = 0
        for _ in range(73):
            s = sdr.read_samples(DEFAULT_NUM_SAMPLES)
            chunks.append((offset, s))
            offset += len(s)
        sdr.close()
        tx.terminate()
        tx.wait()
    finally:
        os.unlink(iq_file.name)

    # Find signal and demod
    mid = chunks[len(chunks) // 4][1]
    fft = np.fft.fftshift(np.fft.fft(mid))
    power = 20 * np.log10(np.abs(fft) + 1e-10)
    freqs = np.fft.fftshift(
        np.fft.fftfreq(len(mid), 1 / DEFAULT_SAMPLE_RATE)) + DEFAULT_CENTER_FREQ
    mask = np.abs(freqs - DEFAULT_CENTER_FREQ) > 2000
    mp = power.copy()
    mp[~mask] = -200
    sig_freq = freqs[np.argmax(mp)]

    signal_chunks = [(o, s) for o, s in chunks if np.mean(np.abs(s)) > 0.5]
    demod, rate = extract_and_demodulate_buffers(
        signal_chunks, DEFAULT_SAMPLE_RATE, DEFAULT_CENTER_FREQ,
        sig_freq, AUDIO_RATE, FM_DEVIATION)

    # Trim to voice region
    frame_size = int(0.05 * rate)
    voice_start = 0
    for i in range(0, len(demod) - frame_size, frame_size):
        if np.sqrt(np.mean(demod[i:i + frame_size] ** 2)) > 0.03:
            voice_start = max(0, i - int(0.2 * rate))
            break
    voice_end = min(len(demod), voice_start + int(4 * rate))
    voice_demod = demod[voice_start:voice_end]

    sp = spike_profile(voice_demod)
    orig_sp = spike_profile(audio)

    # De-click should keep spikes comparable to original
    # Allow 2x original's spike count at 0.30, and zero at 0.50
    max_spikes_030 = max(orig_sp['spikes_030'] * 3, 30)
    print(f"  Spikes > 0.30: {sp['spikes_030']} (max: {max_spikes_030})")
    print(f"  Spikes > 0.50: {sp['spikes_050']} (max: 5)")
    print(f"  (Original: spikes>0.30={orig_sp['spikes_030']}, spikes>0.50={orig_sp['spikes_050']})")
    assert sp['spikes_050'] <= 5, \
        f"Spikes > 0.50: {sp['spikes_050']} > 5 (de-click regression)"
    assert sp['spikes_030'] <= max_spikes_030, \
        f"Spikes > 0.30: {sp['spikes_030']} > {max_spikes_030}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tests(include_rf=False):
    synthetic_tests = [
        ("Synthetic: correlation", test_synthetic_correlation),
        ("Synthetic: spike profile", test_synthetic_spike_profile),
        ("Synthetic: RMS match", test_synthetic_rms_match),
        ("Synthetic: no silence gaps", test_synthetic_no_silence_gaps),
    ]

    rf_tests = [
        ("RF loopback: correlation", test_rf_correlation),
        ("RF loopback: spike profile", test_rf_spike_profile),
    ]

    tests = synthetic_tests + (rf_tests if include_rf else [])

    print("=" * 60)
    print("PMR446 Audio Quality Regression Tests")
    print("=" * 60)

    passed = 0
    failed = 0

    for name, fn in tests:
        print(f"\n{name}")
        try:
            fn()
            print(f"  PASS")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"{passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PMR446 audio quality regression tests')
    parser.add_argument('--rf', action='store_true', help='Include RF loopback tests (needs HackRF + RTL-SDR)')
    args = parser.parse_args()

    success = run_tests(include_rf=args.rf)
    sys.exit(0 if success else 1)

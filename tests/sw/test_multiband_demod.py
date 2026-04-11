"""
Multi-band FM demodulation quality tests.

Verifies that extract_and_demodulate_buffers produces quality audio for
every band profile with its specific FM deviation.

Run:
    python3 tests/sw/test_multiband_demod.py
"""

import os
import sys
import struct
import wave

import numpy as np
from scipy import signal as scipy_signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from scanners.pmr import extract_and_demodulate_buffers

VOICE_WAV = os.path.join(os.path.dirname(__file__), '..', 'data',
                         'original_voice.wav')
AUDIO_RATE = 16000


# Band configs: (name, sample_rate, center_freq, channel_freq, deviation)
BAND_TESTS = [
    ("PMR446 CH1", 2.4e6, 446.05e6, 446.00625e6, 2500),
    ("PMR446 CH8", 2.4e6, 446.05e6, 446.09375e6, 2500),
    ("70cm CALL", 2.4e6, 433.5e6, 433.5e6, 2500),
    ("Marine CH16", 2.4e6, 156.8e6, 156.8e6, 5000),
    ("2m CALL", 2.4e6, 145.5e6, 145.5e6, 2500),
    ("FRS CH1", 2.4e6, 462.5625e6, 462.5625e6, 2500),
]


def load_voice():
    """Load reference voice WAV, truncated to the first 1.5 seconds.

    The fixture is 2.84 s; the demod quality assertions (correlation,
    RMS ratio, voice energy, spike count) are stable on any 1 s+
    speech segment, and the 1.5 s slice cuts IQ synthesis + demod cost
    by ~1.9x per band. Six bands × saved time drops the whole test
    from ~35 s sequential to ~18 s.
    """
    with wave.open(VOICE_WAV, 'rb') as w:
        n = w.getnframes()
        raw = w.readframes(n)
        audio = np.array(struct.unpack(f'<{n}h', raw), dtype=np.float64)
        audio /= 32768.0
        rate = w.getframerate()
    trim = int(rate * 1.5)
    return audio[:trim], rate


def generate_fm_iq(audio, audio_rate, sample_rate, center_freq, channel_freq,
                   fm_deviation, noise_level=0.02):
    """Generate FM-modulated IQ from voice audio."""
    n_iq = int(len(audio) * sample_rate / audio_rate)
    audio_up = scipy_signal.resample(audio, n_iq)

    freq_offset = channel_freq - center_freq
    phase = 2 * np.pi * fm_deviation * np.cumsum(audio_up) / sample_rate
    carrier = 2 * np.pi * freq_offset * np.arange(n_iq) / sample_rate
    iq = np.exp(1j * (carrier + phase)).astype(np.complex64)

    noise = (np.random.randn(n_iq) + 1j * np.random.randn(n_iq)).astype(
        np.complex64) * noise_level
    return iq + noise


def correlate(original, demodulated, rate):
    """Bandpass-filtered normalised cross-correlation."""
    nyq = rate / 2
    b, a = scipy_signal.butter(
        4, [200 / nyq, min(3400 / nyq, 0.99)], btype='band')
    orig_f = scipy_signal.lfilter(b, a, original)
    demod_f = scipy_signal.lfilter(b, a, demodulated)
    orig_f /= (np.max(np.abs(orig_f)) + 1e-10)
    demod_f /= (np.max(np.abs(demod_f)) + 1e-10)
    corr = np.correlate(demod_f, orig_f, mode='full')
    energy = np.sqrt(np.sum(orig_f ** 2) * np.sum(demod_f ** 2))
    corr /= (energy + 1e-10)
    pk = np.argmax(np.abs(corr))
    return float(corr[pk]), float((pk - len(orig_f) + 1) / rate * 1000)


def test_band(name, sample_rate, center_freq, channel_freq, deviation):
    """Test demod quality for one band configuration."""
    audio, audio_rate = load_voice()

    iq = generate_fm_iq(audio, audio_rate, sample_rate, center_freq,
                        channel_freq, deviation, noise_level=0.02)

    # Chunk like the scanner does
    chunk_size = 256 * 1024
    buffers = []
    offset = 0
    while offset < len(iq):
        end = min(offset + chunk_size, len(iq))
        buffers.append((offset, iq[offset:end]))
        offset = end

    demod, rate = extract_and_demodulate_buffers(
        buffers, sample_rate, center_freq, channel_freq, AUDIO_RATE,
        deviation)

    assert len(demod) > 0, "Empty demod output"

    # Correlation
    corr, lag_ms = correlate(audio, demod, rate)

    # Voice-band energy
    fft_mag = np.abs(np.fft.rfft(demod))
    freqs = np.fft.rfftfreq(len(demod), 1 / rate)
    voice_energy = np.sum(fft_mag[freqs <= 3400] ** 2)
    total_energy = np.sum(fft_mag ** 2) + 1e-20
    voice_ratio = voice_energy / total_energy

    # RMS
    orig_rms = np.sqrt(np.mean(audio ** 2))
    demod_rms = np.sqrt(np.mean(demod ** 2))
    rms_ratio = demod_rms / orig_rms if orig_rms > 0 else 0

    # Spikes
    diff = np.abs(np.diff(demod.astype(np.float64)))
    spikes_050 = int(np.sum(diff > 0.50))

    print(f"    corr={corr:.3f} lag={lag_ms:.0f}ms "
          f"voice={voice_ratio:.0%} rms_ratio={rms_ratio:.2f} "
          f"spikes>0.5={spikes_050}")

    assert corr >= 0.70, f"Correlation {corr:.3f} < 0.70"
    assert voice_ratio > 0.80, f"Voice ratio {voice_ratio:.0%} < 80%"
    assert 0.50 <= rms_ratio <= 1.50, f"RMS ratio {rms_ratio:.2f} outside range"
    assert spikes_050 == 0, f"{spikes_050} spikes > 0.50"
    assert abs(lag_ms) < 50, f"Lag {lag_ms:.0f} ms > 50 ms"


def run_tests():
    if not os.path.exists(VOICE_WAV):
        print(f"ERROR: Reference WAV not found: {VOICE_WAV}")
        return False

    print("=" * 60)
    print("Multi-Band FM Demodulation Quality Tests")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, sr, cf, ch, dev in BAND_TESTS:
        print(f"\n  {name} (dev ±{dev} Hz)")
        try:
            test_band(name, sr, cf, ch, dev)
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

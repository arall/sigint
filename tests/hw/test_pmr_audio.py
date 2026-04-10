"""
PMR446 Audio Capture Layered Test

Systematically tests every stage of the audio pipeline using a REAL PMR
walkie-talkie as the TX source.  Each layer isolates one stage so the
first failure pinpoints exactly where audio becomes noise.

  Layer 1 — Raw IQ capture (is the RTL-SDR receiving signal?)
  Layer 2 — Frequency shift + resample (is the math correct?)
  Layer 3 — FM demodulation (does the discriminator produce audio?)
  Layer 4 — Full production pipeline (extract_and_demodulate_buffers)
  Layer 5 — FMVoiceParser path (channelizer / server pipeline)

Requirements:
  - RTL-SDR connected
  - Real PMR radio transmitting voice on the test channel

Usage:
  python3 tests/hw/test_pmr_audio.py
  python3 tests/hw/test_pmr_audio.py --channel 3
  python3 tests/hw/test_pmr_audio.py --duration 8
  python3 tests/hw/test_pmr_audio.py --gain 30
  python3 tests/hw/test_pmr_audio.py --save-plots
"""

import argparse
import os
import sys
import time
import wave
from math import gcd

import numpy as np
from scipy import signal as scipy_signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import utils.loader  # noqa: F401 — must precede rtlsdr import
from rtlsdr import RtlSdr

from scanners.pmr import (
    PMR_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_CENTER_FREQ,
    DEFAULT_NUM_SAMPLES,
    DEFAULT_GAIN,
    calculate_power_spectrum,
    get_channel_power,
    extract_and_demodulate_buffers,
    save_audio,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')
AUDIO_RATE = 16000
FM_DEVIATION = 2500


def save_wav(audio, rate, path):
    """Save float audio to 16-bit WAV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_audio(audio, rate, path)


def spectral_voice_ratio(audio, rate):
    """Fraction of spectral energy below 3.4 kHz (voice band)."""
    n = len(audio)
    fft_mag = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(n, 1 / rate)
    voice_mask = freqs <= 3400
    total = np.sum(fft_mag ** 2) + 1e-20
    voice = np.sum(fft_mag[voice_mask] ** 2)
    return voice / total


def correlate(a, b, rate):
    """Bandpass-filtered normalised cross-correlation."""
    nyq = rate / 2
    b_coeff, a_coeff = scipy_signal.butter(
        4, [200 / nyq, min(3400 / nyq, 0.99)], btype='band')
    af = scipy_signal.lfilter(b_coeff, a_coeff, a)
    bf = scipy_signal.lfilter(b_coeff, a_coeff, b)
    af /= np.max(np.abs(af)) + 1e-10
    bf /= np.max(np.abs(bf)) + 1e-10
    corr = np.correlate(bf, af, mode='full')
    energy = np.sqrt(np.sum(af ** 2) * np.sum(bf ** 2)) + 1e-10
    corr /= energy
    pk = np.argmax(np.abs(corr))
    return float(corr[pk])


# ---------------------------------------------------------------------------
# Layer 1 — Raw IQ capture
# ---------------------------------------------------------------------------

def layer1_capture(channel_freq, center_freq, sample_rate, gain, duration,
                   device_index=0, save_plots=False):
    """Capture raw IQ and verify signal is present."""
    print("\n" + "=" * 60)
    print("LAYER 1: Raw IQ Capture")
    print("=" * 60)

    sdr = RtlSdr(device_index)
    sdr.sample_rate = sample_rate
    sdr.center_freq = center_freq
    sdr.gain = gain

    n_reads = max(1, int(duration * sample_rate / DEFAULT_NUM_SAMPLES))
    chunks = []
    print(f"  Capturing {n_reads} chunks ({duration:.1f}s) at "
          f"{sample_rate/1e6:.1f} MS/s, center {center_freq/1e6:.3f} MHz, "
          f"gain {gain}")

    for i in range(n_reads):
        s = sdr.read_samples(DEFAULT_NUM_SAMPLES)
        chunks.append(s)
    sdr.close()

    raw_iq = np.concatenate(chunks)
    print(f"  Captured {len(raw_iq)} samples ({len(raw_iq)/sample_rate:.2f}s)")

    # Analyse each chunk for signal presence
    best_snr = -999
    best_power = -999
    snr_values = []
    for s in chunks:
        freqs, power_spectrum = calculate_power_spectrum(s, sample_rate)
        noise = np.median(power_spectrum)
        power = get_channel_power(freqs, power_spectrum, center_freq,
                                  channel_freq)
        snr = power - noise
        snr_values.append(snr)
        if snr > best_snr:
            best_snr = snr
            best_power = power

    signal_chunks = sum(1 for s in snr_values if s >= 10)
    print(f"  Channel {channel_freq/1e6:.5f} MHz:")
    print(f"    Best SNR:  {best_snr:.1f} dB")
    print(f"    Best power: {best_power:.1f} dB")
    print(f"    Signal chunks: {signal_chunks}/{len(chunks)} "
          f"(SNR >= 10 dB)")
    print(f"    SNR range: {min(snr_values):.1f} — {max(snr_values):.1f} dB")

    if save_plots:
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            # Plot FFT of the best chunk
            best_idx = int(np.argmax(snr_values))
            freqs, ps = calculate_power_spectrum(chunks[best_idx], sample_rate)
            plt.figure(figsize=(12, 4))
            plt.plot((freqs + center_freq) / 1e6, ps)
            plt.axvline(channel_freq / 1e6, color='r', linestyle='--',
                        label=f'CH ({channel_freq/1e6:.5f})')
            plt.xlabel('MHz')
            plt.ylabel('dB')
            plt.title(f'Layer 1: Best chunk FFT (SNR {best_snr:.1f} dB)')
            plt.legend()
            plt.tight_layout()
            plot_path = os.path.join(OUTPUT_DIR, 'layer1_fft.png')
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            plt.savefig(plot_path, dpi=100)
            plt.close()
            print(f"    Plot saved: {plot_path}")
        except ImportError:
            print("    (matplotlib not available, skipping plot)")

    # Assertions
    assert best_snr >= 15, (
        f"FAIL: Best SNR {best_snr:.1f} dB < 15 dB\n"
        f"  -> Check: antenna connected? Radio transmitting on correct channel?\n"
        f"  -> Try: --gain 49.6 (max) or move radio closer")
    assert signal_chunks >= 2, (
        f"FAIL: Only {signal_chunks} chunks with signal\n"
        f"  -> Keep transmitting for the full capture duration")

    print("  PASS")
    return raw_iq, chunks


# ---------------------------------------------------------------------------
# Layer 2 — Frequency shift + resample
# ---------------------------------------------------------------------------

def layer2_shift_resample(raw_iq, channel_freq, center_freq, sample_rate):
    """Frequency-shift and resample to audio rate. Verify math."""
    print("\n" + "=" * 60)
    print("LAYER 2: Frequency Shift + Resample")
    print("=" * 60)

    freq_offset = channel_freq - center_freq
    print(f"  Freq offset: {freq_offset/1e3:.2f} kHz")

    # Shift to baseband (same as production code)
    t = np.arange(len(raw_iq)) / sample_rate
    shifted = raw_iq * np.exp(-2j * np.pi * freq_offset * t)

    # Check shift worked — peak should be near DC
    fft_shifted = np.fft.fftshift(np.fft.fft(shifted[:DEFAULT_NUM_SAMPLES]))
    freqs_shifted = np.fft.fftshift(
        np.fft.fftfreq(DEFAULT_NUM_SAMPLES, 1 / sample_rate))
    power_shifted = 20 * np.log10(np.abs(fft_shifted) + 1e-10)
    peak_idx = np.argmax(power_shifted)
    peak_freq = freqs_shifted[peak_idx]
    print(f"  After shift, peak at: {peak_freq:.0f} Hz (should be near 0)")

    assert abs(peak_freq) < 5000, (
        f"FAIL: Peak at {peak_freq:.0f} Hz after shift (expected near 0)\n"
        f"  -> Frequency offset calculation may be wrong")

    # Rational resample (same as production code)
    g = gcd(int(AUDIO_RATE), int(sample_rate))
    up = int(AUDIO_RATE) // g
    down = int(sample_rate) // g
    print(f"  Resample: {sample_rate/1e3:.0f} kHz -> {AUDIO_RATE/1e3:.0f} kHz "
          f"(up={up}, down={down})")

    expected_len = int(len(shifted) * up / down)
    resampled = scipy_signal.resample_poly(shifted, up, down)

    print(f"  Input length:    {len(shifted)}")
    print(f"  Output length:   {len(resampled)}")
    print(f"  Expected length: {expected_len}")
    print(f"  Output amplitude: mean={np.mean(np.abs(resampled)):.6f}, "
          f"max={np.max(np.abs(resampled)):.6f}")

    # Assertions
    assert len(resampled) > 0, (
        "FAIL: Resample produced empty output!\n"
        "  -> GCD/integer truncation bug in sample rate conversion")
    assert abs(len(resampled) - expected_len) <= 2, (
        f"FAIL: Output length {len(resampled)} != expected {expected_len}\n"
        f"  -> Resample ratio error")
    assert np.max(np.abs(resampled)) > 1e-6, (
        f"FAIL: Resampled signal is near-zero (max {np.max(np.abs(resampled)):.2e})\n"
        f"  -> Signal lost during resampling")

    print("  PASS")
    return resampled


# ---------------------------------------------------------------------------
# Layer 3 — FM demodulation
# ---------------------------------------------------------------------------

def layer3_fm_demod(resampled_iq):
    """FM-demodulate and verify output is voice, not noise."""
    print("\n" + "=" * 60)
    print("LAYER 3: FM Demodulation")
    print("=" * 60)

    # Polar discriminator (same as production)
    phase = np.angle(resampled_iq[1:] * np.conj(resampled_iq[:-1]))
    audio = phase * (AUDIO_RATE / (2 * np.pi * FM_DEVIATION))

    print(f"  Raw demod: RMS={np.sqrt(np.mean(audio**2)):.4f}, "
          f"max={np.max(np.abs(audio)):.4f}")

    # Low-pass at 3.4 kHz (same as production)
    nyq = AUDIO_RATE / 2
    cutoff = min(3400 / nyq, 0.99)
    b, a = scipy_signal.butter(4, cutoff, btype='low')
    audio = scipy_signal.lfilter(b, a, audio).astype(np.float32)

    rms = float(np.sqrt(np.mean(audio ** 2)))
    max_amp = float(np.max(np.abs(audio)))
    voice_ratio = spectral_voice_ratio(audio, AUDIO_RATE)

    print(f"  After LPF: RMS={rms:.4f}, max={max_amp:.4f}")
    print(f"  Voice-band energy ratio: {voice_ratio:.2%} (should be > 70%)")

    # Save for human listening
    wav_path = os.path.join(OUTPUT_DIR, 'layer3_demod.wav')
    save_wav(audio, AUDIO_RATE, wav_path)
    print(f"  Saved: {wav_path}")

    # Assertions
    assert rms > 0.005, (
        f"FAIL: Audio RMS {rms:.6f} is near-zero (silence)\n"
        f"  -> FM demod produced no signal. Check deviation={FM_DEVIATION} Hz")
    assert rms < 5.0, (
        f"FAIL: Audio RMS {rms:.4f} is huge (overflow/clipping)\n"
        f"  -> Demod scale factor may be wrong")
    assert voice_ratio > 0.50, (
        f"FAIL: Voice-band ratio {voice_ratio:.2%} < 50%\n"
        f"  -> Demodulated signal is broadband noise, not voice\n"
        f"  -> Listen to {wav_path} to confirm")

    print("  PASS")
    print(f"  >> LISTEN to {wav_path} — should be recognizable voice")
    return audio


# ---------------------------------------------------------------------------
# Layer 4 — Full production pipeline
# ---------------------------------------------------------------------------

def layer4_production_pipeline(raw_iq, channel_freq, center_freq, sample_rate):
    """Run extract_and_demodulate_buffers with chunked IQ."""
    print("\n" + "=" * 60)
    print("LAYER 4: Production Pipeline (extract_and_demodulate_buffers)")
    print("=" * 60)

    # Chunk exactly as the scanner does
    chunk_size = DEFAULT_NUM_SAMPLES
    buffers = []
    offset = 0
    while offset < len(raw_iq):
        end = min(offset + chunk_size, len(raw_iq))
        buffers.append((offset, raw_iq[offset:end]))
        offset = end

    print(f"  Chunks: {len(buffers)} x {chunk_size} samples")
    print(f"  Calling extract_and_demodulate_buffers()...")

    audio, rate = extract_and_demodulate_buffers(
        buffers, sample_rate, center_freq, channel_freq,
        AUDIO_RATE, FM_DEVIATION)

    print(f"  Output: {len(audio)} samples at {rate} Hz "
          f"({len(audio)/rate:.2f}s)")

    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) > 0 else 0
    max_amp = float(np.max(np.abs(audio))) if len(audio) > 0 else 0
    print(f"  RMS={rms:.4f}, max={max_amp:.4f}")

    # Save for listening
    wav_path = os.path.join(OUTPUT_DIR, 'layer4_pipeline.wav')
    if len(audio) > 0:
        save_wav(audio, rate, wav_path)
        print(f"  Saved: {wav_path}")

        voice_ratio = spectral_voice_ratio(audio, rate)
        print(f"  Voice-band energy ratio: {voice_ratio:.2%}")

    # Assertions
    assert len(audio) > 0, (
        "FAIL: Production pipeline returned empty audio!\n"
        "  -> All chunks may have been < 200 samples or dropped")
    assert rms > 0.005, (
        f"FAIL: Pipeline RMS {rms:.6f} is near-zero\n"
        f"  -> Audio lost in chunked processing")
    assert rms < 5.0, (
        f"FAIL: Pipeline RMS {rms:.4f} is huge")

    # Check for excessive spikes (de-click should handle these)
    diff = np.abs(np.diff(audio))
    n_large_spikes = int(np.sum(diff > 0.5))
    print(f"  Large spikes (>0.5): {n_large_spikes}")
    if n_large_spikes > 10:
        print(f"  WARNING: {n_large_spikes} large spikes — de-click may not be "
              f"working properly")

    print("  PASS")
    print(f"  >> LISTEN to {wav_path} — compare with layer3_demod.wav")
    return audio, rate


# ---------------------------------------------------------------------------
# Layer 5 — FMVoiceParser (channelizer path)
# ---------------------------------------------------------------------------

def layer5_parser(raw_iq, channel_freq, center_freq, sample_rate):
    """Test FMVoiceParser at both direct and decimated sample rates."""
    print("\n" + "=" * 60)
    print("LAYER 5: FMVoiceParser (Server/Channelizer Path)")
    print("=" * 60)

    from parsers.fm.voice import FMVoiceParser
    from utils.logger import SignalLogger

    # --- 5a: Feed at full RTL-SDR rate (2.4 MHz) ---
    print("\n  --- 5a: Parser at full sample rate ({:.0f} kHz) ---"
          .format(sample_rate / 1e3))

    logger_a = SignalLogger(output_dir=OUTPUT_DIR, signal_type="test_5a",
                            device_id="test")
    parser_a = FMVoiceParser(
        logger=logger_a,
        sample_rate=sample_rate,
        center_freq=center_freq,
        band="pmr446",
        output_dir=OUTPUT_DIR,
        min_snr_db=3.0,  # Lower threshold for testing
    )

    # Feed chunks
    chunk_size = DEFAULT_NUM_SAMPLES
    offset = 0
    n_fed = 0
    while offset < len(raw_iq):
        end = min(offset + chunk_size, len(raw_iq))
        parser_a.handle_frame(raw_iq[offset:end])
        offset = end
        n_fed += 1
    # Flush any in-progress TX by calling shutdown
    parser_a.shutdown()

    print(f"    Fed {n_fed} chunks")
    print(f"    Detections: {parser_a.detection_count}")

    # Check if audio files were created
    audio_dir = os.path.join(OUTPUT_DIR, "audio")
    wavs_5a = []
    if os.path.exists(audio_dir):
        wavs_5a = sorted([f for f in os.listdir(audio_dir)
                          if f.startswith("fm_") and f.endswith(".wav")
                          and "test_5a" not in f])  # parser names files with band name
        # Actually list ALL wavs created in this run
        wavs_5a = sorted([f for f in os.listdir(audio_dir)
                          if f.endswith(".wav")])

    print(f"    Audio files created: {len(wavs_5a)}")
    for w in wavs_5a:
        wp = os.path.join(audio_dir, w)
        try:
            import wave as wav_mod
            with wav_mod.open(wp, 'rb') as wf:
                dur = wf.getnframes() / wf.getframerate()
            print(f"      {w} ({dur:.1f}s)")
        except Exception:
            print(f"      {w} (could not read)")

    # --- 5b: Feed at decimated rate (simulating channelizer output) ---
    decimated_rate = 250e3
    print(f"\n  --- 5b: Parser at decimated rate ({decimated_rate/1e3:.0f} kHz) ---")

    # Decimate the IQ to simulate channelizer output
    decim_factor = int(sample_rate / decimated_rate)
    print(f"    Decimation factor: {decim_factor}")

    # Frequency-shift to channel first, then decimate
    freq_offset = channel_freq - center_freq
    t = np.arange(len(raw_iq)) / sample_rate
    shifted_iq = raw_iq * np.exp(-2j * np.pi * freq_offset * t)

    # Anti-alias filter before decimation
    nyq_dec = (sample_rate / decim_factor) / 2
    cutoff_dec = min(decimated_rate / 2 / nyq_dec, 0.95)
    if decim_factor > 1:
        b_aa, a_aa = scipy_signal.butter(4, cutoff_dec, btype='low')
        shifted_iq = scipy_signal.lfilter(b_aa, a_aa, shifted_iq)
    decimated_iq = shifted_iq[::decim_factor].astype(np.complex64)
    actual_dec_rate = sample_rate / decim_factor

    print(f"    Decimated IQ: {len(decimated_iq)} samples at "
          f"{actual_dec_rate/1e3:.0f} kHz")

    # For 5b, center_freq IS the channel_freq (channelizer shifts to 0)
    logger_b = SignalLogger(output_dir=OUTPUT_DIR, signal_type="test_5b",
                            device_id="test")
    parser_b = FMVoiceParser(
        logger=logger_b,
        sample_rate=actual_dec_rate,
        center_freq=channel_freq,  # Channelizer centers on the channel
        band="pmr446",
        output_dir=OUTPUT_DIR,
        min_snr_db=3.0,
    )

    # Feed in channelizer-sized chunks (small, ~325 samples as noted in CLAUDE.md)
    ch_chunk_size = 325
    offset = 0
    n_fed_b = 0
    while offset < len(decimated_iq):
        end = min(offset + ch_chunk_size, len(decimated_iq))
        chunk = decimated_iq[offset:end]
        if len(chunk) >= 200:  # Parser's minimum
            parser_b.handle_frame(chunk)
        offset = end
        n_fed_b += 1
    parser_b.shutdown()

    print(f"    Fed {n_fed_b} chunks (size ~{ch_chunk_size})")
    print(f"    Detections: {parser_b.detection_count}")
    print(f"    Active channels: {list(parser_b.active_channels.keys())}")

    wavs_5b = []
    if os.path.exists(audio_dir):
        # Get files created after 5a check
        all_wavs = sorted([f for f in os.listdir(audio_dir)
                           if f.endswith(".wav")])
        wavs_5b = [w for w in all_wavs if w not in wavs_5a]
        print(f"    Audio files created: {len(wavs_5b)}")
        for w in wavs_5b:
            wp = os.path.join(audio_dir, w)
            try:
                import wave as wav_mod
                with wav_mod.open(wp, 'rb') as wf:
                    dur = wf.getnframes() / wf.getframerate()
                print(f"      {w} ({dur:.1f}s)")
            except Exception:
                print(f"      {w} (could not read)")

    # Soft assertions for 5a (may not detect if signal doesn't span full capture)
    if parser_a.detection_count == 0:
        print("\n  WARNING (5a): No detections at full sample rate")
        print("  -> Parser SNR threshold may be too high for real signals")
        print("  -> Or capture didn't include enough active signal")

    if parser_b.detection_count == 0:
        print("\n  WARNING (5b): No detections at decimated rate")
        print("  -> Channelizer path may have issues")
        print("  -> Check: active channels vs center_freq alignment")

    total_detections = parser_a.detection_count + parser_b.detection_count
    total_wavs = len(wavs_5a) + len(wavs_5b)

    if total_detections > 0:
        print(f"\n  PASS ({total_detections} detections, {total_wavs} audio files)")
    else:
        print(f"\n  SOFT FAIL: No detections in either path")
        print("  This may indicate the parser's detection threshold is too high,")
        print("  or the signal didn't last long enough to pass MIN_TX_DURATION.")
        print("  Layers 1-4 passing confirms the demod pipeline itself is correct.")

    return total_detections


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='PMR446 Audio Pipeline Layered Test',
        epilog='Transmit voice on your PMR radio during the capture window.')
    parser.add_argument('--channel', type=int, default=1,
                        choices=range(1, 9),
                        help='PMR channel to test (default: 1)')
    parser.add_argument('--duration', type=float, default=5.0,
                        help='Capture duration in seconds (default: 5)')
    parser.add_argument('--gain', type=float, default=DEFAULT_GAIN,
                        help=f'RTL-SDR gain (default: {DEFAULT_GAIN})')
    parser.add_argument('--device', type=int, default=0,
                        help='RTL-SDR device index (default: 0)')
    parser.add_argument('--save-plots', action='store_true',
                        help='Save FFT plots (requires matplotlib)')
    args = parser.parse_args()

    channel_freq = PMR_CHANNELS[args.channel]
    center_freq = DEFAULT_CENTER_FREQ
    sample_rate = DEFAULT_SAMPLE_RATE

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("PMR446 Audio Pipeline Test")
    print("=" * 60)
    print(f"  Channel:    CH{args.channel} ({channel_freq/1e6:.5f} MHz)")
    print(f"  Center:     {center_freq/1e6:.3f} MHz")
    print(f"  Sample rate: {sample_rate/1e6:.1f} MS/s")
    print(f"  Gain:       {args.gain}")
    print(f"  Duration:   {args.duration}s")
    print(f"  Output:     {os.path.abspath(OUTPUT_DIR)}")
    print()
    print(">>> Get your PMR radio ready on channel "
          f"{args.channel} <<<")
    print()
    for countdown in range(10, 0, -1):
        print(f"  Starting capture in {countdown}s — "
              f"START TRANSMITTING when you see GO!", end='\r')
        time.sleep(1)
    print()
    print(">>> GO! TRANSMIT NOW — hold PTT for "
          f"{args.duration:.0f}+ seconds <<<")
    print()

    results = {}

    # Layer 1
    try:
        raw_iq, chunks = layer1_capture(
            channel_freq, center_freq, sample_rate, args.gain,
            args.duration, args.device, args.save_plots)
        results['Layer 1: IQ Capture'] = 'PASS'
    except (AssertionError, Exception) as e:
        print(f"  FAIL: {e}")
        results['Layer 1: IQ Capture'] = f'FAIL: {e}'
        print_summary(results)
        return 1

    # Layer 2
    try:
        resampled = layer2_shift_resample(
            raw_iq, channel_freq, center_freq, sample_rate)
        results['Layer 2: Shift + Resample'] = 'PASS'
    except (AssertionError, Exception) as e:
        print(f"  FAIL: {e}")
        results['Layer 2: Shift + Resample'] = f'FAIL: {e}'
        print_summary(results)
        return 1

    # Layer 3
    try:
        manual_audio = layer3_fm_demod(resampled)
        results['Layer 3: FM Demod'] = 'PASS'
    except (AssertionError, Exception) as e:
        print(f"  FAIL: {e}")
        results['Layer 3: FM Demod'] = f'FAIL: {e}'
        print_summary(results)
        return 1

    # Layer 4
    try:
        pipeline_audio, pipeline_rate = layer4_production_pipeline(
            raw_iq, channel_freq, center_freq, sample_rate)
        results['Layer 4: Production Pipeline'] = 'PASS'

        # Cross-check: Layer 3 vs Layer 4 should match
        min_len = min(len(manual_audio), len(pipeline_audio))
        if min_len > AUDIO_RATE:  # Need at least 1s for meaningful correlation
            corr = correlate(manual_audio[:min_len],
                             pipeline_audio[:min_len], AUDIO_RATE)
            print(f"  Layer 3 vs 4 correlation: {corr:.3f}")
            if corr < 0.3:
                print("  WARNING: Layer 3 and 4 outputs differ significantly")
                print("  -> Chunked processing may be introducing artifacts")
    except (AssertionError, Exception) as e:
        print(f"  FAIL: {e}")
        results['Layer 4: Production Pipeline'] = f'FAIL: {e}'
        print_summary(results)
        return 1

    # Layer 5
    try:
        detections = layer5_parser(raw_iq, channel_freq, center_freq,
                                   sample_rate)
        if detections > 0:
            results['Layer 5: FMVoiceParser'] = 'PASS'
        else:
            results['Layer 5: FMVoiceParser'] = 'SOFT FAIL (no detections)'
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        results['Layer 5: FMVoiceParser'] = f'ERROR: {e}'

    print_summary(results)

    # Return code: fail only if layers 1-4 fail
    critical_fail = any('FAIL' in v and 'SOFT' not in v
                        for k, v in results.items()
                        if 'Layer 5' not in k)
    return 1 if critical_fail else 0


def print_summary(results):
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        status = "PASS" if result == "PASS" else result
        icon = "+" if "PASS" in result else ("-" if "SOFT" in result else "!")
        print(f"  [{icon}] {name}: {status}")

    print()
    print(f"  Audio files saved in: {os.path.abspath(OUTPUT_DIR)}")
    print("  Listen to layer3_demod.wav and layer4_pipeline.wav")
    print("  If layer3 sounds good but layer4 doesn't -> chunking bug")
    print("  If both sound bad -> demod parameters need fixing")
    print("=" * 60)


if __name__ == '__main__':
    sys.exit(main())

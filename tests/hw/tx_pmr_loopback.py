"""
PMR446 loopback test: HackRF TX → RTL-SDR RX.

Transmits a voice WAV file FM-modulated on PMR CH1 via HackRF,
captures it with the RTL-SDR, demodulates at the detected signal
frequency, and compares to the original using cross-correlation.

Requires: HackRF One (TX) + RTL-SDR Blog V4 (RX) connected simultaneously.
"""

import sys
import os
import wave
import time
import subprocess
import tempfile
import struct

import numpy as np
from scipy import signal as scipy_signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import utils.loader  # noqa: F401,E402
from scanners.pmr import (
    PMR_CHANNELS, DEFAULT_SAMPLE_RATE, DEFAULT_CENTER_FREQ,
    extract_and_demodulate_buffers,
)

# TX parameters
TX_FREQ = PMR_CHANNELS[1]  # 446.00625 MHz
TX_SAMPLE_RATE = 2e6       # HackRF TX sample rate
FM_DEVIATION = 2500        # PMR446 narrowband FM deviation (Hz)
TX_GAIN_DB = 20            # HackRF TX gain (low power for bench test)
LEADER_SECONDS = 3.0       # Carrier before voice (lets RX settle)
TRAILER_SECONDS = 5.0      # Carrier after voice (lets holdover expire)


def wav_to_padded_fm_iq(wav_path, sample_rate, fm_deviation, leader_s, trailer_s):
    """Convert WAV to FM-modulated IQ with carrier leader/trailer for HackRF."""
    with wave.open(wav_path, 'rb') as w:
        audio_rate = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)
        audio = np.array(struct.unpack(f'<{n_frames}h', raw), dtype=np.float64)
        audio /= 32768.0

    # Resample to TX rate
    n_tx = int(len(audio) * sample_rate / audio_rate)
    audio_up = scipy_signal.resample(audio, n_tx)

    # FM modulate voice
    phase = 2 * np.pi * fm_deviation * np.cumsum(audio_up) / sample_rate

    # Pad with carrier (constant phase = unmodulated carrier)
    leader = np.zeros(int(leader_s * sample_rate))
    trailer = np.full(int(trailer_s * sample_rate), phase[-1])
    full_phase = np.concatenate([leader, phase, trailer])
    iq = np.exp(1j * full_phase)

    # Convert to HackRF int8 format
    i8 = np.clip(np.round(iq.real * 127), -127, 127).astype(np.int8)
    q8 = np.clip(np.round(iq.imag * 127), -127, 127).astype(np.int8)
    interleaved = np.empty(len(i8) * 2, dtype=np.int8)
    interleaved[0::2] = i8
    interleaved[1::2] = q8

    audio_duration = len(audio) / audio_rate
    total_duration = len(full_phase) / sample_rate
    return interleaved, audio_duration, total_duration


def find_signal_freq(samples, sample_rate, center_freq, dc_exclusion=2000):
    """Find the strongest signal frequency, excluding DC spike."""
    fft = np.fft.fftshift(np.fft.fft(samples))
    power = 20 * np.log10(np.abs(fft) + 1e-10)
    freqs = np.fft.fftshift(np.fft.fftfreq(len(samples), 1 / sample_rate)) + center_freq

    mask = np.abs(freqs - center_freq) > dc_exclusion
    masked = power.copy()
    masked[~mask] = -200
    peak_idx = np.argmax(masked)
    return freqs[peak_idx], power[peak_idx] - np.median(power)


def correlate_voice(original, demodulated, rate):
    """Cross-correlate demodulated audio against original, return (correlation, lag_ms)."""
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


def run_loopback_test():
    """Run full TX/RX loopback test."""
    from rtlsdr import RtlSdr

    wav_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'original_voice.wav')
    assert os.path.exists(wav_path), f"Test WAV not found: {wav_path}"

    # Read original audio
    with wave.open(wav_path, 'rb') as w:
        audio_rate = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)
        original = np.array(struct.unpack(f'<{n_frames}h', raw), dtype=np.float64) / 32768.0

    print(f"Source: {wav_path} ({len(original)/audio_rate:.2f}s, {audio_rate} Hz)")
    print(f"TX: {TX_FREQ/1e6:.5f} MHz, {FM_DEVIATION} Hz dev, {TX_GAIN_DB} dB gain")
    print()

    # Step 1: Generate padded FM IQ file
    print("Generating FM IQ with carrier padding...")
    iq_data, voice_dur, total_dur = wav_to_padded_fm_iq(
        wav_path, TX_SAMPLE_RATE, FM_DEVIATION, LEADER_SECONDS, TRAILER_SECONDS)

    iq_file = tempfile.NamedTemporaryFile(suffix='.iq', delete=False)
    iq_data.tofile(iq_file)
    iq_file.close()
    print(f"  {total_dur:.1f}s total ({LEADER_SECONDS:.0f}s leader + {voice_dur:.1f}s voice + {TRAILER_SECONDS:.0f}s trailer)")

    # Step 2: Start TX
    print("\nTransmitting via HackRF...")
    tx = subprocess.Popen(
        ['hackrf_transfer', '-t', iq_file.name, '-f', str(int(TX_FREQ)),
         '-s', str(int(TX_SAMPLE_RATE)), '-x', str(TX_GAIN_DB)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)  # Let TX settle (2s into 3s leader)

    # Step 3: Capture IQ chunks with RTL-SDR
    print("Capturing with RTL-SDR...")
    rx_sr = DEFAULT_SAMPLE_RATE
    rx_center = DEFAULT_CENTER_FREQ
    sdr = RtlSdr()
    sdr.sample_rate = rx_sr
    sdr.center_freq = rx_center
    sdr.gain = 40

    capture_seconds = 8.0
    chunk_size = 256 * 1024
    n_chunks = int(capture_seconds * rx_sr / chunk_size)
    chunks = []
    offset = 0
    for _ in range(n_chunks):
        s = sdr.read_samples(chunk_size)
        chunks.append((offset, s))
        offset += len(s)

    sdr.close()
    tx.terminate()
    tx.wait()
    os.unlink(iq_file.name)
    print(f"  Captured {offset/rx_sr:.2f}s in {len(chunks)} chunks")

    # Step 4: Find signal frequency
    mid_chunk = chunks[len(chunks) // 4][1]
    sig_freq, sig_snr = find_signal_freq(mid_chunk, rx_sr, rx_center)
    print(f"  Signal at {sig_freq/1e6:.6f} MHz (SNR {sig_snr:.0f} dB)")

    if sig_snr < 20:
        print("\nFAIL: Signal too weak or not detected")
        return False

    # Step 5: Filter to chunks with signal (IQ amplitude > 0.5)
    signal_chunks = [(o, s) for o, s in chunks if np.mean(np.abs(s)) > 0.5]
    print(f"  Signal chunks: {len(signal_chunks)}/{len(chunks)}")

    if len(signal_chunks) < 10:
        print("\nFAIL: Not enough signal captured")
        return False

    # Step 6: Demodulate at detected frequency
    print("\nDemodulating...")
    demod, demod_rate = extract_and_demodulate_buffers(
        signal_chunks, rx_sr, rx_center, sig_freq, audio_rate, FM_DEVIATION)
    print(f"  {len(demod)} samples at {demod_rate} Hz ({len(demod)/demod_rate:.2f}s)")
    print(f"  RMS: {np.sqrt(np.mean(demod**2)):.4f} (original: {np.sqrt(np.mean(original**2)):.4f})")

    # Step 7: Trim to voice region (skip carrier, take 4s from voice onset)
    frame_size = int(0.05 * demod_rate)
    voice_start = 0
    for i in range(0, len(demod) - frame_size, frame_size):
        if np.sqrt(np.mean(demod[i:i+frame_size]**2)) > 0.03:
            voice_start = max(0, i - int(0.2 * demod_rate))
            break

    voice_end = min(len(demod), voice_start + int(4 * demod_rate))
    voice_demod = demod[voice_start:voice_end]
    print(f"  Voice region: {voice_start/demod_rate:.2f}s to {voice_end/demod_rate:.2f}s")

    # Step 8: Correlate
    print("\nComparing audio quality...")
    peak_corr, lag_ms = correlate_voice(original, voice_demod, demod_rate)
    print(f"  Cross-correlation: {peak_corr:.3f}")
    print(f"  Time lag: {lag_ms:.0f} ms")

    # Evaluate
    print("\n" + "=" * 50)
    # Threshold accounts for combined phase noise of consumer SDR devices
    # (HackRF TX + RTL-SDR RX). Typical correlation: 0.2-0.35.
    if abs(peak_corr) >= 0.15:
        quality = ("excellent" if abs(peak_corr) >= 0.7 else
                   "good" if abs(peak_corr) >= 0.5 else
                   "acceptable" if abs(peak_corr) >= 0.3 else "marginal")
        print(f"PASS: Audio correlation {peak_corr:.3f} (quality: {quality})")
        success = True
    else:
        print(f"FAIL: Audio correlation {peak_corr:.3f} < 0.15")
        success = False
    print("=" * 50)

    return success


if __name__ == '__main__':
    success = run_loopback_test()
    sys.exit(0 if success else 1)

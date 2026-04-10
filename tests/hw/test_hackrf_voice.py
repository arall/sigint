#!/usr/bin/env python3
"""
HackRF voice E2E test: HackRF TX → HackRF RX (channelizer) → FM voice parser.

Transmits a 1 kHz FM tone on PMR CH1 via one HackRF, receives on the other
through the channelizer pipeline, and verifies detection + audio demod.

Requires two HackRF One units connected simultaneously.

Usage:
  python3 tests/hw/test_hackrf_voice.py
  python3 tests/hw/test_hackrf_voice.py --tx-gain 30
  python3 tests/hw/test_hackrf_voice.py --duration 5
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from capture.channelizer import Channelizer
from parsers.fm.voice import FMVoiceParser
from utils.logger import SignalLogger


# PMR CH1
CHANNEL_FREQ = 446_006_250
CENTER_FREQ = 446_050_000
FM_DEVIATION = 2500
TX_SAMPLE_RATE = 2_000_000
RX_SAMPLE_RATE = 20_000_000
OUTPUT_RATE = 250_000


def get_hackrf_serials():
    """Get serial numbers of connected HackRFs."""
    result = subprocess.run(['hackrf_info'], capture_output=True, text=True)
    serials = []
    for line in result.stdout.splitlines():
        if 'Serial number:' in line:
            serials.append(line.split(':')[-1].strip())
    return serials


def generate_fm_tone(sample_rate, duration, tone_freq=1000,
                     fm_deviation=2500):
    """Generate FM-modulated tone as HackRF int8 IQ."""
    n = int(sample_rate * duration)
    t = np.arange(n) / sample_rate

    modulator = np.sin(2 * np.pi * tone_freq * t)
    phase = 2 * np.pi * fm_deviation * np.cumsum(modulator) / sample_rate
    iq = np.exp(1j * phase) * 0.9

    # Add leader/trailer silence
    pad = np.zeros(int(sample_rate * 0.5), dtype=np.complex64)
    iq = np.concatenate([pad, iq, pad])

    i8 = np.clip(np.round(iq.real * 127), -127, 127).astype(np.int8)
    q8 = np.clip(np.round(iq.imag * 127), -127, 127).astype(np.int8)
    interleaved = np.empty(len(i8) * 2, dtype=np.int8)
    interleaved[0::2] = i8
    interleaved[1::2] = q8
    return interleaved, len(iq) / sample_rate


def tx_hackrf(serial, iq_file, freq, sample_rate, gain, duration):
    """Transmit on HackRF (blocking, runs in thread)."""
    cmd = [
        'hackrf_transfer',
        '-t', iq_file,
        '-f', str(int(freq)),
        '-s', str(int(sample_rate)),
        '-x', str(gain),
        '-a', '0',
        '-d', serial,
    ]
    try:
        subprocess.run(cmd, timeout=duration + 5,
                       capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        pass


def rx_hackrf(serial, center_freq, sample_rate, duration,
              lna_gain=32, vga_gain=40):
    """Capture IQ from HackRF (blocking). Returns list of complex64 blocks."""
    block_bytes = 256 * 1024 * 2  # 256K complex samples = 512KB raw

    cmd = [
        'hackrf_transfer',
        '-r', '-',
        '-f', str(int(center_freq)),
        '-s', str(int(sample_rate)),
        '-l', str(lna_gain),
        '-g', str(vga_gain),
        '-d', serial,
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            bufsize=block_bytes * 4)

    blocks = []
    end_time = time.time() + duration
    try:
        while time.time() < end_time:
            raw = proc.stdout.read(block_bytes)
            if not raw:
                break
            iq_int8 = np.frombuffer(raw, dtype=np.int8)
            iq_int8 = iq_int8[:len(iq_int8) - len(iq_int8) % 2]
            iq_pairs = iq_int8.reshape(-1, 2)
            samples = (iq_pairs[:, 0].astype(np.float32) +
                       1j * iq_pairs[:, 1].astype(np.float32)) / 128.0
            blocks.append(samples)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    return blocks


def main():
    parser = argparse.ArgumentParser(
        description='HackRF TX → HackRF RX channelizer voice test')
    parser.add_argument('--tx-gain', type=int, default=20,
                        help='TX VGA gain 0-47 (default: 20)')
    parser.add_argument('--lna-gain', type=int, default=32,
                        help='RX LNA gain (default: 32)')
    parser.add_argument('--vga-gain', type=int, default=40,
                        help='RX VGA gain (default: 40)')
    parser.add_argument('--rx-ppm', type=int, default=0,
                        help='RX HackRF crystal error in ppm (default: 0)')
    parser.add_argument('--duration', type=float, default=3.0,
                        help='Tone duration in seconds (default: 3)')
    args = parser.parse_args()

    # Check hardware
    serials = get_hackrf_serials()
    if len(serials) < 2:
        print(f"ERROR: Need 2 HackRFs, found {len(serials)}")
        return 1

    tx_serial = serials[0]
    rx_serial = serials[1]
    print(f"TX HackRF: {tx_serial}")
    print(f"RX HackRF: {rx_serial}")
    print(f"Channel: PMR CH1 ({CHANNEL_FREQ/1e6:.5f} MHz)")
    print(f"TX gain: {args.tx_gain}, RX LNA: {args.lna_gain}, "
          f"RX VGA: {args.vga_gain}")
    print()

    # Generate TX signal
    print("[1/4] Generating FM tone...")
    iq_data, tx_duration = generate_fm_tone(
        TX_SAMPLE_RATE, args.duration,
        tone_freq=1000, fm_deviation=FM_DEVIATION)

    iq_file = tempfile.NamedTemporaryFile(suffix='.iq', delete=False)
    iq_data.tofile(iq_file)
    iq_file.close()
    print(f"  {tx_duration:.1f}s signal ({len(iq_data)//2} IQ samples)")

    try:
        # Start TX in background
        print("[2/4] TX + RX simultaneously...")
        tx_thread = threading.Thread(
            target=tx_hackrf,
            args=(tx_serial, iq_file.name, CHANNEL_FREQ,
                  TX_SAMPLE_RATE, args.tx_gain, tx_duration))
        tx_thread.start()

        # Wait for TX to start
        time.sleep(1.0)

        # Capture on RX
        rx_duration = tx_duration + 2.0
        blocks = rx_hackrf(
            rx_serial, CENTER_FREQ, RX_SAMPLE_RATE, rx_duration,
            lna_gain=args.lna_gain, vga_gain=args.vga_gain)

        tx_thread.join(timeout=10)
        print(f"  Captured {len(blocks)} blocks "
              f"({sum(len(b) for b in blocks)} samples)")

        if not blocks:
            print("ERROR: No RX data captured")
            return 1

        # Check raw signal presence via FFT on a middle block
        mid_block = blocks[len(blocks) // 2]
        fft = np.fft.fftshift(np.fft.fft(mid_block))
        power = 20 * np.log10(np.abs(fft) + 1e-10)
        freqs = np.fft.fftshift(
            np.fft.fftfreq(len(mid_block), 1 / RX_SAMPLE_RATE))
        freqs += CENTER_FREQ

        # Find peak near channel
        ch_mask = np.abs(freqs - CHANNEL_FREQ) < 50000
        if np.any(ch_mask):
            peak_power = np.max(power[ch_mask])
            noise_floor = np.median(power)
            raw_snr = peak_power - noise_floor
            print(f"  Raw signal: peak {peak_power:.1f} dB, "
                  f"noise {noise_floor:.1f} dB, SNR {raw_snr:.1f} dB")
        else:
            raw_snr = 0
            print("  WARNING: Could not measure raw signal")

        # Feed through channelizer → FM voice parser
        print("[3/4] Channelizer → FM voice parser pipeline...")
        with tempfile.TemporaryDirectory() as tmpdir:
            logged = []

            class CapLogger(SignalLogger):
                def log(self, detection):
                    logged.append(detection)
                    return super().log(detection)

            logger = CapLogger(
                output_dir=tmpdir, signal_type="test", device_id="test")
            logger.start()

            # Account for RX HackRF crystal error
            rx_ppm = getattr(args, 'rx_ppm', 0)
            actual_center = CENTER_FREQ * (1 + rx_ppm * 1e-6) if rx_ppm else CENTER_FREQ

            voice_parser = FMVoiceParser(
                logger=logger,
                sample_rate=OUTPUT_RATE,
                center_freq=actual_center,
                band="pmr446",
                output_dir=tmpdir,
                min_snr_db=5.0,
            )
            channelizer = Channelizer(
                center_freq=actual_center, sample_rate=RX_SAMPLE_RATE)
            channelizer.add_channel(
                name="pmr",
                freq_hz=actual_center,
                bandwidth_hz=OUTPUT_RATE,
                output_sample_rate=OUTPUT_RATE,
                callback=voice_parser.handle_frame,
            )

            # Diagnostic: check channelizer output SNR on first few blocks
            diag_snrs = []
            orig_cb = voice_parser.handle_frame
            def diag_cb(samples):
                if len(diag_snrs) < 5:
                    from parsers.fm.voice import _channel_power_linear
                    p, n = _channel_power_linear(
                        samples, OUTPUT_RATE, CENTER_FREQ,
                        CHANNEL_FREQ, 12500)
                    snr = p - n
                    diag_snrs.append(snr)
                    print(f"    block {len(diag_snrs)}: {len(samples)} samples, "
                          f"CH1 SNR={snr:.1f} dB")
                orig_cb(samples)

            # Re-wire channelizer to use diagnostic callback
            channelizer._channels[0].callback = diag_cb

            # Feed captured blocks through channelizer
            for block in blocks:
                channelizer.handle_frame(block)

            # Feed silence for holdover expiry
            silence_blocks = int(3.0 * RX_SAMPLE_RATE / len(blocks[0])) + 1
            for _ in range(silence_blocks):
                noise = (np.random.randn(len(blocks[0])) +
                         1j * np.random.randn(len(blocks[0]))
                         ).astype(np.complex64) * 0.001
                channelizer.handle_frame(noise)
                time.sleep(0.01)

            channelizer.flush()
            voice_parser.shutdown()

            # Results
            print(f"\n[4/4] Results:")
            print(f"  Detections: {voice_parser.detection_count}")

            audio_dir = os.path.join(tmpdir, "audio")
            audio_files = []
            if os.path.isdir(audio_dir):
                audio_files = [f for f in os.listdir(audio_dir)
                               if f.endswith('.wav')]
            print(f"  Audio files: {len(audio_files)}")

            if logged:
                d = logged[0]
                import json
                meta = json.loads(d.metadata) if d.metadata else {}
                print(f"  Signal type: {d.signal_type}")
                print(f"  Channel: {d.channel}")
                print(f"  Power: {d.power_db:.1f} dB")
                print(f"  Duration: {meta.get('duration_s', '?')}s")

            # Copy audio to persistent location
            if audio_files:
                out_dir = os.path.join(
                    os.path.dirname(__file__), '..', 'output', 'hackrf_voice')
                os.makedirs(out_dir, exist_ok=True)
                import shutil
                for f in audio_files:
                    src = os.path.join(audio_dir, f)
                    dst = os.path.join(out_dir, f)
                    shutil.copy2(src, dst)
                    print(f"  Saved: {dst}")

            logger.stop()

            # Verdict
            print()
            if voice_parser.detection_count >= 1 and audio_files:
                print("PASS — HackRF channelizer detected and demodulated PMR voice")
                return 0
            elif raw_snr < 10:
                print("FAIL — Signal too weak in raw capture. "
                      "Move HackRFs closer or increase TX gain.")
                return 1
            else:
                print(f"FAIL — Signal present (SNR {raw_snr:.0f} dB) but "
                      f"pipeline produced {voice_parser.detection_count} "
                      f"detections, {len(audio_files)} audio files")
                return 1

    finally:
        os.unlink(iq_file.name)


if __name__ == '__main__':
    sys.exit(main())

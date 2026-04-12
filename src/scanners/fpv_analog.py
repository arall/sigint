"""
FPV Analog Video Scanner — detects and demodulates analog video from
FPV drones on 5.8 GHz and 1.2 GHz bands.

Scans known FPV channels for wideband FM video carriers, FM-demodulates
to composite video (PAL/NTSC), and extracts frames. Detected channels
are logged as signal detections; the latest frame is available for web
streaming via the server's /api/fpv/frame endpoint.

Requires: HackRF One (tunes to 5.8 GHz, 20 MHz BW).
"""

import json
import os
import sys
import signal as sig
import threading
import time
from datetime import datetime

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dsp.analog_video import (  # noqa: E402
    detect_video_carrier, fm_demod_video, detect_line_period,
    extract_frame, frame_to_png,
)
from utils.logger import SignalLogger, SignalDetection  # noqa: E402

# ── FPV channel tables (MHz) ───────────────────────────────────────
FPV_CHANNELS_58 = {
    "R1": 5658, "R2": 5695, "R3": 5732, "R4": 5769,
    "R5": 5806, "R6": 5843, "R7": 5880, "R8": 5917,
    "F1": 5740, "F2": 5760, "F3": 5780, "F4": 5800,
    "F5": 5820, "F6": 5840, "F7": 5860, "F8": 5880,
    "E1": 5705, "E2": 5685, "E3": 5665, "E4": 5645,
    "E5": 5885, "E6": 5905, "E7": 5925, "E8": 5945,
    "A1": 5865, "A2": 5845, "A3": 5825, "A4": 5805,
    "A5": 5785, "A6": 5765, "A7": 5745, "A8": 5725,
    "B1": 5733, "B2": 5752, "B3": 5771, "B4": 5790,
    "B5": 5809, "B6": 5828, "B7": 5847, "B8": 5866,
}

FPV_CHANNELS_12 = {
    "L1": 1080, "L2": 1120, "L3": 1160, "L4": 1200,
    "L5": 1240, "L6": 1280, "L7": 1320, "L8": 1360,
}

SAMPLE_RATE = 20_000_000
SCAN_DWELL_S = 0.3


class FPVAnalogScanner:
    """Scans FPV channels for analog video, demodulates and extracts frames."""

    def __init__(self, output_dir=None, device_id="hackrf-001",
                 serial=None, band="5.8", lna_gain=40, vga_gain=40,
                 amp=False):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.output_dir = output_dir
        self.serial = serial
        self.band = band
        self.lna_gain = lna_gain
        self.vga_gain = vga_gain
        self.amp = amp
        self.channels = FPV_CHANNELS_58 if band == "5.8" else FPV_CHANNELS_12

        os.makedirs(output_dir, exist_ok=True)

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="fpv_analog",
            device_id=device_id,
            min_snr_db=0,
        )

        # Shared state for web streaming
        self._latest_frame_png = None  # bytes
        self._latest_frame_info = None  # dict
        self._frame_lock = threading.Lock()
        self._active_channel = None
        self._detection_count = 0
        self._stop_event = threading.Event()

    @property
    def latest_frame_png(self):
        """Latest captured frame as PNG bytes, or None."""
        with self._frame_lock:
            return self._latest_frame_png

    @property
    def latest_frame_info(self):
        """Info about the latest frame: channel, freq, standard, etc."""
        with self._frame_lock:
            return self._latest_frame_info

    def _capture_iq(self, freq_mhz, dwell_s=SCAN_DWELL_S):
        """Capture IQ from HackRF on a single frequency."""
        import subprocess
        n_bytes = int(SAMPLE_RATE * dwell_s * 2)
        cmd = [
            "hackrf_transfer", "-r", "-",
            "-f", str(int(freq_mhz * 1e6)),
            "-s", str(SAMPLE_RATE),
            "-n", str(n_bytes),
            "-l", str(self.lna_gain),
            "-g", str(self.vga_gain),
        ]
        if self.serial:
            cmd.extend(["-d", self.serial])
        if self.amp:
            cmd.extend(["-a", "1"])

        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=dwell_s + 10,
                stderr=subprocess.DEVNULL)
            if proc.returncode != 0 or len(proc.stdout) < 1000:
                return None
            raw = np.frombuffer(proc.stdout, dtype=np.int8)
            iq = raw.astype(np.float32)
            return (iq[0::2] + 1j * iq[1::2]).astype(np.complex64)
        except (subprocess.TimeoutExpired, OSError):
            return None

    def _process_channel(self, label, freq_mhz, samples):
        """Analyze captured IQ for video, extract frame if found."""
        det = detect_video_carrier(samples, SAMPLE_RATE)
        if not det["detected"]:
            return False

        # FM demodulate
        baseband, br = fm_demod_video(samples, SAMPLE_RATE)
        line_info = detect_line_period(baseband, br)

        standard = "unknown"
        frame_data = None

        if line_info:
            standard = line_info["standard"]
            frame_data = extract_frame(
                baseband, br, line_info["line_period_samples"])

        # Log detection
        meta = {
            "bandwidth_mhz": det["bandwidth_mhz"],
            "standard": standard,
            "has_frame": frame_data is not None,
        }
        if line_info:
            meta["line_freq_hz"] = line_info["line_freq_hz"]

        detection = SignalDetection.create(
            signal_type="FPV-Analog",
            frequency_hz=freq_mhz * 1e6,
            power_db=det["peak_power_db"],
            noise_floor_db=det["noise_floor_db"],
            channel=label,
            metadata=json.dumps(meta),
        )
        self.logger.log(detection)
        self._detection_count += 1

        # Update latest frame for web streaming
        if frame_data:
            frame, w, h = frame_data
            png_bytes = frame_to_png(frame, w, h)
            with self._frame_lock:
                self._latest_frame_png = png_bytes
                self._latest_frame_info = {
                    "channel": label,
                    "freq_mhz": freq_mhz,
                    "standard": standard,
                    "width": w,
                    "height": h,
                    "snr_db": det["snr_db"],
                    "timestamp": datetime.now().isoformat(),
                }
            # Write to file for web server access
            fpv_path = os.path.join(self.output_dir, "fpv_latest.png")
            try:
                tmp = fpv_path + ".tmp"
                with open(tmp, 'wb') as f:
                    f.write(png_bytes)
                os.replace(tmp, fpv_path)
            except OSError:
                pass

        return True

    def scan(self):
        """Run the FPV analog video scanner."""
        def _handler(signum, frame):
            self._stop_event.set()
        sig.signal(sig.SIGINT, _handler)
        sig.signal(sig.SIGTERM, _handler)

        print("=" * 60)
        print("    FPV Analog Video Scanner")
        print("=" * 60)
        print(f"Band: {self.band} GHz ({len(self.channels)} channels)")
        print(f"Sample rate: {SAMPLE_RATE / 1e6:.0f} MS/s")
        print(f"Gains: LNA {self.lna_gain}, VGA {self.vga_gain}"
              f"{', AMP' if self.amp else ''}")
        print("-" * 60)

        log_path = self.logger.start()
        print(f"Logging to: {log_path}")
        print("Scanning...\n")

        scan_num = 0
        try:
            while not self._stop_event.is_set():
                scan_num += 1
                t0 = time.time()
                active = []

                for label in sorted(self.channels.keys()):
                    if self._stop_event.is_set():
                        break
                    freq = self.channels[label]
                    samples = self._capture_iq(freq, SCAN_DWELL_S)
                    if samples is None:
                        continue
                    if self._process_channel(label, freq, samples):
                        active.append(label)
                        print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                              f"VIDEO: {label} ({freq} MHz)")

                elapsed = time.time() - t0
                if not active:
                    print(f"\r[Scan #{scan_num}] No video "
                          f"({elapsed:.1f}s, {self._detection_count} total)",
                          end="", flush=True)
                else:
                    print(f"[Scan #{scan_num}] Active: "
                          f"{', '.join(active)} ({elapsed:.1f}s)")
        finally:
            total = self.logger.stop()
            print(f"\n\nScanner stopped. {total} detections logged.")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="FPV Analog Video Scanner")
    parser.add_argument("--band", "-b", default="5.8",
                        choices=["5.8", "1.2"])
    parser.add_argument("--serial", "-d", help="HackRF serial")
    parser.add_argument("--lna-gain", type=int, default=40)
    parser.add_argument("--vga-gain", type=int, default=40)
    parser.add_argument("--amp", action="store_true")
    parser.add_argument("--output", "-o")
    args = parser.parse_args()

    scanner = FPVAnalogScanner(
        band=args.band, serial=args.serial,
        lna_gain=args.lna_gain, vga_gain=args.vga_gain,
        amp=args.amp, output_dir=args.output)
    scanner.scan()


if __name__ == "__main__":
    main()

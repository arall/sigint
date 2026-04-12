"""
LTE Uplink Power Density Scanner
Detects cellular phone presence by monitoring LTE uplink bands for elevated
RF energy above a quiet baseline.

Unlike GSM (which has distinct per-device bursts), LTE uses OFDMA where
multiple devices share bandwidth simultaneously. Individual devices can't be
isolated, but aggregate phone activity is detectable as a rise in power
density above the noise floor.

LTE Uplink Bands (phone -> tower, within RTL-SDR range):
- Band 20 (800 MHz EU): 832-862 MHz
- Band 8 (900 MHz EU):  880-915 MHz  (overlaps GSM-900 uplink)
- Band 5 (850 MHz US):  824-849 MHz

LEGAL NOTE: This tool is for educational and authorized security research only.
Only passive RF energy measurement is performed - no signal decoding or interception.
"""

import sys
import os
import time
import signal as sig

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.rtlsdr_sweep import RTLSDRSweepCaptureSource  # noqa: E402
from parsers.cellular.lte import LTEPowerParser  # noqa: E402
from utils.logger import SignalLogger  # noqa: E402

# Re-export for backward compatibility
from dsp.lte import measure_power_spectrum, compute_band_summary  # noqa: E402,F401

# LTE uplink bands reachable by RTL-SDR
LTE_UPLINK_BANDS = {
    "Band-20": {"label": "LTE Band 20 (800 MHz EU)", "start": 832.0e6, "end": 862.0e6},
    "Band-8":  {"label": "LTE Band 8 (900 MHz EU)",  "start": 880.0e6, "end": 915.0e6},
    "Band-5":  {"label": "LTE Band 5 (850 MHz US)",  "start": 824.0e6, "end": 849.0e6},
}

DEFAULT_SAMPLE_RATE = 2.0e6
DEFAULT_GAIN = 40
ACTIVITY_THRESHOLD_DB = 3.0
BASELINE_SAMPLES = 5


class LTEScanner:
    """LTE uplink scanner — detects aggregate phone presence."""

    def __init__(
        self,
        output_dir=None,
        device_id="rtlsdr-001",
        device_index=0,
        min_snr_db=3.0,
        gain=DEFAULT_GAIN,
        bands=None,
        sample_rate=DEFAULT_SAMPLE_RATE,
        activity_threshold_db=ACTIVITY_THRESHOLD_DB,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        if bands is None:
            bands = ["Band-20", "Band-8"]
        self.bands = {}
        for b in bands:
            if b not in LTE_UPLINK_BANDS:
                raise ValueError(f"Unknown band: {b}. Choose from: {list(LTE_UPLINK_BANDS.keys())}")
            self.bands[b] = LTE_UPLINK_BANDS[b]

        self.sample_rate = sample_rate
        self.activity_threshold_db = activity_threshold_db

        os.makedirs(output_dir, exist_ok=True)
        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="lte",
            device_id=device_id,
            min_snr_db=0,
        )

        # One sweep capture covering all bands
        all_starts = [b['start'] for b in self.bands.values()]
        all_ends = [b['end'] for b in self.bands.values()]
        band_start = min(all_starts)
        band_end = max(all_ends)

        self.capture = RTLSDRSweepCaptureSource(
            band_start=band_start,
            band_end=band_end,
            sample_rate=sample_rate,
            gain=gain,
            device_index=device_index,
        )

        # One parser per band
        self.parsers = {}
        for band_name in self.bands:
            self.parsers[band_name] = LTEPowerParser(
                logger=self.logger,
                sample_rate=sample_rate,
                band_name=band_name,
                activity_threshold_db=activity_threshold_db,
            )

        # Wire
        self._sweep_count = 0
        self._calibrating = True
        self._cal_counts = {b: 0 for b in self.bands}
        self.capture.add_parser(self._handle_sweep_chunk)

    def _handle_sweep_chunk(self, frame):
        """Receive (samples, center_freq) from sweep capture."""
        samples, center_freq = frame

        # Route to the right band parser(s)
        for band_name, band_config in self.bands.items():
            if band_config['start'] <= center_freq <= band_config['end']:
                parser = self.parsers[band_name]

                if self._calibrating:
                    done = parser.calibrate(samples)
                    if done:
                        self._cal_counts[band_name] = BASELINE_SAMPLES
                        print(f"  {band_name}: baseline = {parser.baseline:.1f} dB")
                    else:
                        self._cal_counts[band_name] += 1
                        print(".", end="", flush=True)

                    # Check if all bands calibrated
                    if all(v >= BASELINE_SAMPLES for v in self._cal_counts.values()):
                        self._calibrating = False
                        print("\nCalibration complete. Monitoring...\n")
                else:
                    parser.handle_frame(samples, center_freq=center_freq)

        self._sweep_count += 1
        n_freqs = len(self.capture.frequencies)
        if not self._calibrating and self._sweep_count % n_freqs == 0:
            sweep_num = self._sweep_count // n_freqs
            parts = []
            for band_name, parser in self.parsers.items():
                history = parser.history
                if history:
                    last = history[-1]
                    indicator = "+" if last['active'] else "-"
                    parts.append(f"{band_name}: {indicator}{abs(last['delta_db']):.1f}dB")
            total = sum(p.total_detections for p in self.parsers.values())
            status = " | ".join(parts)
            print(f"\r[Sweep #{sweep_num:3d}] {status} | Detections: {total}", end="", flush=True)

    def scan(self):
        """Run the LTE uplink scanner."""
        def _signal_handler(signum, frame):
            self.capture.stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        total_range = (f"{min(b['start'] for b in self.bands.values())/1e6:.0f}-"
                       f"{max(b['end'] for b in self.bands.values())/1e6:.0f} MHz")

        print("=" * 60)
        print("     LTE Uplink Scanner - Phone Presence Detector")
        print("=" * 60)
        print(f"\nBands: {', '.join(self.bands.keys())}")
        print(f"Range: {total_range}")
        print(f"Activity threshold: +{self.activity_threshold_db:.1f} dB above baseline")
        print("Passive RF energy measurement only.")
        print("-" * 60)

        output_file = self.logger.start()
        print(f"Logging to: {output_file}")
        print(f"\nCalibrating baseline ({BASELINE_SAMPLES} sweeps per band)...")

        try:
            self.capture.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.capture.stop()
            total = self.logger.stop()

            print(f"\n\nTotal detections logged: {total}")
            for band_name, parser in self.parsers.items():
                history = parser.history
                if history:
                    active_count = sum(1 for h in history if h['active'])
                    max_delta = max(h['delta_db'] for h in history)
                    print(f"  {band_name}: {len(history)} sweeps, "
                          f"{active_count} active ({active_count*100//len(history)}%), "
                          f"max rise: {max_delta:+.1f} dB")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LTE Uplink Scanner")
    parser.add_argument("--bands", "-b", nargs="+", default=["Band-20", "Band-8"],
                        choices=list(LTE_UPLINK_BANDS.keys()))
    parser.add_argument("--gain", "-g", type=int, default=40)
    parser.add_argument("--threshold", "-t", type=float, default=3.0)
    args = parser.parse_args()
    scanner = LTEScanner(bands=args.bands, gain=args.gain, activity_threshold_db=args.threshold)
    scanner.scan()

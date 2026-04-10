"""
GSM Uplink Scanner Module
Passively detects mobile phone transmissions by monitoring GSM uplink frequencies.

Phones transmit on uplink bands when making calls, sending SMS, or performing
location updates. GSM uses TDMA with ~577us timeslots, producing distinctive
short energy bursts that can be detected and counted.

GSM Uplink Bands (phone -> tower):
- GSM-900 (EU): 890-915 MHz
- GSM-850 (US): 824-849 MHz

This scanner:
- Detects energy bursts from handset transmissions on uplink frequencies
- Measures signal strength per burst for RSSI-based triangulation
- Estimates number of active devices by counting concurrent timeslot activity

LEGAL NOTE: This tool is for educational and authorized security research only.
Only passive RF energy detection is performed - no signal decoding or interception.
"""

import sys
import os
import time
import signal as sig
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.rtlsdr_sweep import RTLSDRSweepCaptureSource  # noqa: E402
from parsers.cellular.gsm import GSMBurstParser  # noqa: E402
from utils.logger import SignalLogger  # noqa: E402

# Re-export for backward compatibility
from dsp.gsm import (  # noqa: E402,F401
    detect_uplink_bursts, estimate_active_devices,
    GSM_CHANNEL_SPACING, GSM_TIMESLOT_US, GSM_FRAME_US,
)

# GSM uplink band definitions
GSM_UPLINK_BANDS = {
    "GSM-900": {"start": 890.0e6, "end": 915.0e6},
    "GSM-850": {"start": 824.0e6, "end": 849.0e6},
}

DEFAULT_SAMPLE_RATE = 2.0e6
DEFAULT_GAIN = 40


class GSMScanner:
    """GSM uplink scanner — detects mobile phone transmissions."""

    def __init__(
        self,
        output_dir=None,
        device_id="rtlsdr-001",
        device_index=0,
        min_snr_db=5.0,
        gain=DEFAULT_GAIN,
        band="GSM-900",
        sample_rate=DEFAULT_SAMPLE_RATE,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        if band not in GSM_UPLINK_BANDS:
            raise ValueError(f"Unknown band: {band}. Choose from: {list(GSM_UPLINK_BANDS.keys())}")

        self.band = band
        self.band_config = GSM_UPLINK_BANDS[band]
        self.sample_rate = sample_rate

        os.makedirs(output_dir, exist_ok=True)
        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="gsm",
            device_id=device_id,
            min_snr_db=0,
        )

        # Sweep capture across the uplink band
        self.capture = RTLSDRSweepCaptureSource(
            band_start=self.band_config['start'],
            band_end=self.band_config['end'],
            sample_rate=sample_rate,
            gain=gain,
            device_index=device_index,
        )

        # Parser
        center = (self.band_config['start'] + self.band_config['end']) / 2
        self.parser = GSMBurstParser(
            logger=self.logger,
            sample_rate=sample_rate,
            center_freq=center,
            band_name=band,
            min_snr_db=min_snr_db,
        )

        # Wire
        self._sweep_count = 0
        self.capture.add_parser(self._handle_sweep_chunk)

    def _handle_sweep_chunk(self, frame):
        """Receive (samples, center_freq) from sweep capture."""
        samples, center_freq = frame
        # Update parser's center freq for this chunk
        self.parser.center_freq = center_freq
        self.parser.handle_frame(samples)

        self._sweep_count += 1
        n_freqs = len(self.capture.frequencies)
        if self._sweep_count % n_freqs == 0:
            sweep_num = self._sweep_count // n_freqs
            activity = self.parser.channel_activity
            active = sum(1 for a in activity.values()
                         if a['last_seen'] and (datetime.now() - a['last_seen']).seconds < 5)
            total_devices = sum(a['estimated_devices'] for a in activity.values()
                                if a['last_seen'] and (datetime.now() - a['last_seen']).seconds < 5)
            print(f"\r[Sweep #{sweep_num:3d}] "
                  f"Active channels: {active:2d} | "
                  f"Est. devices: {total_devices:2d} | "
                  f"Logged: {self.parser.total_detections}", end="", flush=True)

    def scan(self):
        """Run the GSM uplink scanner."""
        def _signal_handler(signum, frame):
            self.capture.stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        print("=" * 60)
        print("       GSM Uplink Scanner - Phone Activity Detector")
        print("=" * 60)
        print(f"\nBand: {self.band} uplink "
              f"({self.band_config['start']/1e6:.0f}-{self.band_config['end']/1e6:.0f} MHz)")
        print("Detecting handset transmissions (passive RF energy detection only).")
        print("-" * 60)

        output_file = self.logger.start()
        print(f"Logging to: {output_file}")
        print("\nScanning... (Ctrl+C to stop)\n")

        try:
            self.capture.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.capture.stop()
            total = self.logger.stop()

            activity = self.parser.channel_activity
            print(f"\n\nActive channels: {len(activity)}")
            print(f"Total detections logged: {total}")

            if activity:
                sorted_ch = sorted(activity.items(),
                                   key=lambda x: x[1]['burst_count'], reverse=True)
                print(f"\n{'Frequency':>12} | {'Bursts':>7} | {'Peak dB':>8} | {'Devices':>7}")
                print("-" * 45)
                for freq, info in sorted_ch[:20]:
                    print(f"{freq/1e6:>10.2f} MHz | {info['burst_count']:>7} | "
                          f"{info['peak_power_db']:>8.1f} | {info['estimated_devices']:>7}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GSM Uplink Scanner")
    parser.add_argument("--band", "-b", default="GSM-900",
                        choices=["GSM-900", "GSM-850"])
    parser.add_argument("--gain", "-g", type=int, default=40)
    parser.add_argument("--min-snr", type=float, default=5.0)
    args = parser.parse_args()
    scanner = GSMScanner(band=args.band, gain=args.gain, min_snr_db=args.min_snr)
    scanner.scan()

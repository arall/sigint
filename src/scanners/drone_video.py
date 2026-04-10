"""
Drone Video Link Scanner — detects drone video downlinks on 2.4/5.8 GHz.

Uses HackRF for 20 MHz wideband IQ capture to detect OFDM video
transmissions from drones (DJI O4, OcuSync, etc.). Reports bandwidth,
duty cycle, and confidence to CSV/TAK.

Requires: HackRF One hardware + hackrf_transfer.
"""

import os
import sys
import signal as sig

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.hackrf_iq import HackRFCaptureSource  # noqa: E402
from parsers.drone.video_link import DroneVideoLinkParser  # noqa: E402
from utils.logger import SignalLogger  # noqa: E402

# Band presets
BANDS = {
    "2.4": {
        "center_freq": 2.44e9,
        "label": "2.4 GHz ISM",
        "range": "2.430-2.450 GHz (20 MHz window)",
    },
    "5.8": {
        "center_freq": 5.785e9,
        "label": "5.8 GHz ISM",
        "range": "5.775-5.795 GHz (20 MHz window)",
    },
}

DEFAULT_SAMPLE_RATE = 20e6
DEFAULT_LNA_GAIN = 32
DEFAULT_VGA_GAIN = 40


class DroneVideoScanner:
    """Detects drone video downlinks — HackRF capture + OFDM parser."""

    def __init__(
        self,
        output_dir=None,
        device_id="hackrf-001",
        band="2.4",
        lna_gain=DEFAULT_LNA_GAIN,
        vga_gain=DEFAULT_VGA_GAIN,
        amp=False,
        min_snr_db=8.0,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        band_info = BANDS.get(band, BANDS["2.4"])
        self.center_freq = band_info["center_freq"]
        self.band_label = band_info["label"]
        self.band_range = band_info["range"]

        os.makedirs(output_dir, exist_ok=True)
        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="drone_video",
            device_id=device_id,
            min_snr_db=0,
        )

        self.capture = HackRFCaptureSource(
            center_freq=self.center_freq,
            sample_rate=DEFAULT_SAMPLE_RATE,
            lna_gain=lna_gain,
            vga_gain=vga_gain,
            amp_enable=amp,
        )

        self.parser = DroneVideoLinkParser(
            logger=self.logger,
            sample_rate=DEFAULT_SAMPLE_RATE,
            center_freq=self.center_freq,
            min_snr_db=min_snr_db,
        )

        self._frame_count = 0
        self.capture.add_parser(self._handle_samples)

    def _handle_samples(self, samples):
        """Feed IQ to parser and print periodic status."""
        self.parser.handle_frame(samples)
        self._frame_count += 1

        if self._frame_count % 50 == 0:
            elapsed = self._frame_count * len(samples) / DEFAULT_SAMPLE_RATE
            result = self.parser.last_result or {}
            n_bursts = result.get("n_bursts", 0)
            print(
                f"\r  [{elapsed:.0f}s] "
                f"Frames: {self._frame_count} | "
                f"Detections: {self.parser.detection_count} | "
                f"Bursts/frame: {n_bursts}",
                end="", flush=True,
            )

    def scan(self):
        """Run the drone video link scanner."""
        def _signal_handler(signum, frame):
            self.capture.stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        print("=" * 70)
        print("          Drone Video Link Scanner (HackRF)")
        print("=" * 70)
        print(f"\nBand: {self.band_label}")
        print(f"Coverage: {self.band_range}")
        print(f"Center: {self.center_freq / 1e6:.3f} MHz")
        print("-" * 70)

        output_file = self.logger.start()
        print(f"Logging to: {output_file}")
        print("\nScanning for drone video transmissions...\n")

        try:
            self.capture.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.capture.stop()
            total = self.logger.stop()
            print(f"\n\nTotal detections logged: {total}")


if __name__ == "__main__":
    scanner = DroneVideoScanner()
    scanner.scan()

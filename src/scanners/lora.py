"""
LoRa/Meshtastic Scanner Module
Detects LoRa transmissions in ISM bands (868 MHz EU / 915 MHz US).

LoRa uses Chirp Spread Spectrum (CSS) — we can't decode payloads with
an RTL-SDR, but we can detect the energy signature: wideband chirps
sweeping 125-500 kHz over 1-100ms depending on spreading factor.

This scanner detects LoRa presence, estimates bandwidth and duty cycle,
and logs transmissions with RSSI for triangulation.
"""

import os
import sys
import time
import signal as sig

# Get project root (parent of src)
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.rtlsdr_iq import RTLSDRCaptureSource  # noqa: E402
from parsers.lora.energy import LoRaEnergyParser  # noqa: E402
from utils.logger import SignalLogger  # noqa: E402

# EU LoRa channels (868 MHz ISM band)
LORA_CHANNELS_EU = {
    "868.1": 868.1e6,   # Default Meshtastic EU channel
    "868.3": 868.3e6,   # LoRaWAN ch2
    "868.5": 868.5e6,   # LoRaWAN ch3
    "869.525": 869.525e6,  # LoRaWAN RX2 / high power
}

# US LoRa channels (915 MHz ISM band)
LORA_CHANNELS_US = {
    "906.875": 906.875e6,  # Meshtastic US default
    "903.08": 903.08e6,
    "905.24": 905.24e6,
    "907.40": 907.40e6,
    "909.56": 909.56e6,
    "911.72": 911.72e6,
    "913.88": 913.88e6,
}

DEFAULT_SAMPLE_RATE = 2.4e6
DEFAULT_GAIN = 40


class LoRaScanner:
    """Detects LoRa/Meshtastic transmissions — thin orchestrator."""

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        min_snr_db: float = 8.0,
        gain: int = DEFAULT_GAIN,
        region: str = "eu",
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.region = region.upper()
        channels = LORA_CHANNELS_EU if self.region == "EU" else LORA_CHANNELS_US

        # Center frequency covers all channels in the band
        freqs = list(channels.values())
        center_freq = (min(freqs) + max(freqs)) / 2

        os.makedirs(output_dir, exist_ok=True)
        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="lora",
            device_id=device_id,
            min_snr_db=0,
        )

        # Capture layer
        self.capture = RTLSDRCaptureSource(
            center_freq=center_freq,
            sample_rate=DEFAULT_SAMPLE_RATE,
            gain=gain,
            device_index=device_index,
            block_size=256 * 1024,
        )

        # Parser
        self.parser = LoRaEnergyParser(
            logger=self.logger,
            sample_rate=DEFAULT_SAMPLE_RATE,
            center_freq=center_freq,
            channels=channels,
            min_snr_db=min_snr_db,
            region=self.region,
        )

        # Wire parser + status display
        self._sweep_count = 0
        self._samples_per_block = 256 * 1024
        self.capture.add_parser(self._handle_samples)

        # Store for display
        self._channels = channels
        self._center_freq = center_freq

    def _handle_samples(self, samples):
        """Feed samples to parser and print periodic status."""
        self.parser.handle_frame(samples)
        self._sweep_count += 1

        if self._sweep_count % 50 == 0:
            stats = self.parser.stats
            elapsed = self._sweep_count * self._samples_per_block / DEFAULT_SAMPLE_RATE
            print(
                f"\r  [{elapsed:.0f}s] "
                f"Sweeps: {self._sweep_count} | "
                f"Detections: {stats['total_detections']} | "
                f"Active channels: {len(stats['channels_active'])}",
                end="", flush=True,
            )

    def scan(self):
        """Run the LoRa scanner."""
        def _signal_handler(signum, frame):
            self.capture.stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        band = "868 MHz (EU)" if self.region == "EU" else "915 MHz (US)"
        channel_names = list(self._channels.keys())

        print("=" * 70)
        print("            LoRa / Meshtastic Scanner")
        print("=" * 70)
        print(f"\nBand: {band}")
        print(f"Channels: {', '.join(channel_names)} MHz")
        print(f"Center: {self._center_freq / 1e6:.3f} MHz")
        print("-" * 70)

        output_file = self.logger.start()
        print(f"Logging to: {output_file}")
        print("\nScanning for LoRa transmissions...\n")

        try:
            self.capture.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.capture.stop()
            total = self.logger.stop()
            stats = self.parser.stats
            print(f"\n\nTotal detections logged: {total}")
            print(f"Channels with activity: {stats['channels_active'] or 'none'}")


if __name__ == "__main__":
    scanner = LoRaScanner()
    scanner.scan()

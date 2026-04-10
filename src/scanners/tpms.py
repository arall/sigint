"""
TPMS (Tire Pressure Monitoring System) Scanner Module
Detects and decodes tire pressure sensors at 315 MHz (US) or 433.92 MHz (EU).

TPMS sensors transmit:
- Unique sensor ID (can identify specific vehicles)
- Tire pressure
- Temperature
- Battery status

This is useful for vehicle detection/tracking since each car has 4 unique sensor IDs.
"""

import sys
import os
import time

# Get project root (parent of src)
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import SignalLogger  # noqa: E402

# Re-export signal analysis functions from dsp/ for backward compatibility.
from dsp.tpms import (  # noqa: E402,F401
    detect_tpms_signal, manchester_decode, bits_to_hex,
)

# TPMS frequencies
TPMS_FREQUENCIES = {
    "433.92 MHz (EU)": 433.92e6,
    "315 MHz (US)": 315.0e6,
}

# Default configuration
DEFAULT_SAMPLE_RATE = 1.0e6  # 1 MHz sample rate (sufficient for TPMS)
DEFAULT_GAIN = 40


class TPMSScanner:
    """TPMS sensor scanner — thin orchestrator over RTLSDRCaptureSource + TPMSParser."""

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        min_snr_db: float = 8.0,
        gain: float = DEFAULT_GAIN,
        frequency: float = 433.92e6,
    ):
        self.center_freq = frequency
        self.sample_rate = DEFAULT_SAMPLE_RATE

        if output_dir:
            self.output_dir = output_dir
        else:
            self.output_dir = os.path.join(PROJECT_ROOT, "output")
        os.makedirs(self.output_dir, exist_ok=True)

        self.logger = SignalLogger(self.output_dir)

        # Capture layer
        from capture.rtlsdr_iq import RTLSDRCaptureSource
        self.capture = RTLSDRCaptureSource(
            center_freq=frequency,
            sample_rate=DEFAULT_SAMPLE_RATE,
            gain=gain,
            device_index=device_index,
            block_size=128 * 1024,
        )

        # Parser
        from parsers.ook.tpms import TPMSParser
        self.parser = TPMSParser(
            logger=self.logger,
            sample_rate=DEFAULT_SAMPLE_RATE,
            center_freq=frequency,
            min_snr_db=min_snr_db,
        )

        # Wire parser to capture — plus display wrapper
        self._last_display_time = 0
        self.capture.add_parser(self._handle_samples)

    def _get_frequency_name(self):
        for name, freq in TPMS_FREQUENCIES.items():
            if abs(freq - self.center_freq) < 1e5:
                return name
        return f"{self.center_freq/1e6:.2f} MHz"

    def _handle_samples(self, samples):
        """Feed samples to parser and update display."""
        self.parser.handle_frame(samples)

        now = time.time()
        if now - self._last_display_time >= 0.3:
            self._last_display_time = now
            result = self.parser.last_detection_result
            if result:
                self._print_display(result, result['noise_floor_db'])

    def _print_display(self, result, noise_floor_db):
        state = self.parser.get_display_state()
        print("\033[2J\033[H", end="")
        print("=" * 60)
        print("        TPMS (Tire Pressure) Scanner - RTL-SDR")
        print("=" * 60)
        print(f"\nFrequency: {self._get_frequency_name()}")
        print(f"Noise Floor: {noise_floor_db:.1f} dB")
        print(f"Detections logged: {state['detection_count']}")
        print(f"Unique sensor IDs: {len(state['sensor_ids'])}")
        print("-" * 60)

        snr = result['snr_db']
        bar_width = 40
        bar_fill = max(0, int(min(snr / 30 * bar_width, bar_width)))

        if result['detected']:
            status = "🔴 TPMS SIGNAL"
            bar_char = "█"
        elif snr > 5:
            status = "🟡 ACTIVITY"
            bar_char = "▓"
        else:
            status = "⚪ IDLE"
            bar_char = "░"

        bar = bar_char * bar_fill + "░" * (bar_width - bar_fill)
        print(f"\nSignal: [{bar}] {snr:.1f} dB SNR  {status}")
        print(f"  Pulses: {result['num_pulses']}  Packets: {len(result['packets'])}  "
              f"Peak: {result['peak_power_db']:.1f} dB  Floor: {result['noise_floor_db']:.1f} dB")

        if result['detected'] and result['sensor_ids']:
            print(f"\n  🚗 Sensor IDs detected:")
            for sid in result['sensor_ids'][:4]:
                count = state['sensor_ids'].get(sid, 0)
                print(f"     {sid} (seen {count}x)")

        if state['sensor_ids']:
            print(f"\n  📡 Known sensors ({len(state['sensor_ids'])} total):")
            sorted_ids = sorted(state['sensor_ids'].items(), key=lambda x: -x[1])
            for sid, count in sorted_ids[:8]:
                print(f"     {sid}: {count} detections")

        print("-" * 60)
        print("\nPress Ctrl+C to exit")
        print("Drive a car nearby to detect TPMS signals")

    def scan(self):
        """Start scanning for TPMS signals."""
        import signal as sig

        def _signal_handler(signum, frame):
            self.capture.stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        print(f"Initializing RTL-SDR at {self._get_frequency_name()}...")
        log_path = self.logger.start()
        print(f"Logging to: {log_path}")

        try:
            self.capture.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.capture.stop()
            logged_count = self.logger.stop()
            sensor_ids = self.parser.sensor_ids
            print(f"\nScanner stopped. {logged_count} signals logged.")
            print(f"Unique sensor IDs seen: {len(sensor_ids)}")
            if sensor_ids:
                print("\nSensor ID summary:")
                for sid, count in sorted(sensor_ids.items(), key=lambda x: -x[1]):
                    print(f"  {sid}: {count} detections")
            if logged_count > 0 and hasattr(self.logger, '_csv_path'):
                print(f"Log file: {self.logger._csv_path}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="TPMS Scanner")
    parser.add_argument(
        "--frequency", "-f",
        type=float,
        default=433.92,
        help="Frequency in MHz (default: 433.92 EU, use 315 for US)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Output directory for logs"
    )
    parser.add_argument(
        "--gain", "-g",
        type=float,
        default=DEFAULT_GAIN,
        help=f"RF gain (default: {DEFAULT_GAIN})"
    )
    parser.add_argument(
        "--device-id",
        type=str,
        default="rtlsdr-001",
        help="Device identifier for logging"
    )

    args = parser.parse_args()

    scanner = TPMSScanner(
        output_dir=args.output,
        device_id=args.device_id,
        gain=args.gain,
        frequency=args.frequency * 1e6,
    )
    scanner.scan()


if __name__ == "__main__":
    main()

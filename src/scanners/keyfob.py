"""
Keyfob Scanner Module
Scans for car keyfobs and garage door openers at 315 MHz and 433.92 MHz.
Identifies protocol (PT2262, EV1527, KeeLoq), code type (fixed/rolling),
and estimates device type from pulse timing analysis.
"""

import sys
import os
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import SignalLogger  # noqa: E402

# Re-export signal analysis functions from dsp/ for backward compatibility.
# ISM scanner and other code may import these from scanners.keyfob.
from dsp.ook import (  # noqa: E402,F401
    detect_ook_signal, detect_fsk_signal, fingerprint_protocol,
    fingerprint_fsk_car, classify_device, TransmitterTracker,
    CAR_FSK_PROFILES, bits_to_hex,
)

# Common keyfob frequencies
KEYFOB_FREQUENCIES = {
    "433.92 MHz (EU/Worldwide)": 433.92e6,
    "315 MHz (US)": 315.0e6,
    "868 MHz (EU)": 868.0e6,
    "312 MHz": 312.0e6,
    "318 MHz": 318.0e6,
    "390 MHz": 390.0e6,
}

DEFAULT_SAMPLE_RATE = 2.0e6
DEFAULT_GAIN = 40


# ---------------------------------------------------------------------------
# Scanner (thin orchestrator: RTLSDRCaptureSource + KeyfobParser)
# ---------------------------------------------------------------------------

class KeyfobScanner:
    """Keyfob/garage door opener scanner with protocol identification."""

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        min_snr_db: float = 10.0,
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
        )

        # Parser
        from parsers.ook.keyfob import KeyfobParser
        self.parser = KeyfobParser(
            logger=self.logger,
            sample_rate=DEFAULT_SAMPLE_RATE,
            center_freq=frequency,
            min_snr_db=min_snr_db,
        )

        # Wire parser to capture — plus display wrapper
        self._last_display_time = 0
        self.capture.add_parser(self._handle_samples)

    def _get_frequency_name(self):
        for name, freq in KEYFOB_FREQUENCIES.items():
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
        print("=" * 66)
        print("      Keyfob/Garage Door Scanner - Protocol Analysis")
        print("=" * 66)
        print(f"  Frequency: {self._get_frequency_name()}")
        print(f"  Noise: {noise_floor_db:.1f} dB  |  Threshold: 8.0 dB SNR")
        print(f"  Detections: {state['detection_count']}  |  "
              f"Unique transmitters: {state['known_transmitters']}")
        print("-" * 66)

        snr = result['snr_db']
        bar_width = 40
        bar_fill = max(0, int(min(snr / 30 * bar_width, bar_width)))

        if result['detected']:
            bar = "\033[91m" + "█" * bar_fill + "\033[0m" + "░" * (bar_width - bar_fill)
            status = "🔴 SIGNAL"
        elif snr > 5:
            bar = "\033[93m" + "▓" * bar_fill + "\033[0m" + "░" * (bar_width - bar_fill)
            status = "🟡 WEAK"
        else:
            bar = "░" * bar_width
            status = "⚪ IDLE"

        print(f"  [{bar}] {snr:.1f} dB  {status}")
        print(f"  Pulses: {result['num_bursts']}  |  TX: {'Active' if state['tx_active'] else 'Idle'}")
        print("-" * 66)

        fp = state['last_fingerprint']
        if fp and fp['protocol'] != 'Unknown':
            device_type, icon = classify_device(
                fp['protocol'], fp['code_type'], self.center_freq, fp)

            mod = fp.get('modulation', 'OOK')
            if mod == 'FSK':
                color = "\033[96m"
            elif fp['code_type'] == 'rolling':
                color = "\033[91m"
            elif fp['code_type'] == 'fixed':
                color = "\033[92m"
            else:
                color = "\033[93m"
            reset = "\033[0m"

            print(f"  {icon} {color}{fp['protocol']}{reset}"
                  f"  [{fp['code_type'].upper()}]"
                  f"  ({fp['confidence']} confidence)")
            print(f"  Device: {device_type}")
            if fp.get('deviation_khz'):
                print(f"  FSK:    ±{fp['deviation_khz']:.0f} kHz deviation,"
                      f"  ~{fp.get('datarate_hz', 0)/1000:.0f} kbps")
            if fp.get('bit_count'):
                print(f"  Bits:   ~{fp['bit_count']}")
            if fp.get('data_hex'):
                print(f"  Data:   0x{fp['data_hex']}")
            if fp.get('repeat_count', 0) > 1:
                print(f"  Seen:   {fp['repeat_count']}x same code"
                      f"  ({fp.get('unique_codes', '?')} unique)")
            if fp.get('details'):
                print(f"  Detail: {fp['details']}")
        elif state['tx_active']:
            print(f"  Analyzing signal...")
        else:
            print(f"  Waiting for signal...")

        print("-" * 66)
        print("  Ctrl+C to stop  |  Press keyfob button to detect")

    def scan(self):
        """Start scanning for keyfob signals."""
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
            print(f"\nScanner stopped. {logged_count} signals logged.")
            if logged_count > 0 and getattr(self.logger, "db_path", None):
                print(f"Log file: {self.logger.db_path}")

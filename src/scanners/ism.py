"""
ISM Band Scanner Module (433 MHz / 868 MHz / 915 MHz)
Wraps rtl_433 to decode 200+ device protocols: weather stations, TPMS,
keyfobs, door sensors, thermometers, smoke detectors, smart home devices, etc.

Unknown signals (not decoded by rtl_433) are analyzed with native FSK/OOK
detection to identify car keyfobs and other unrecognized transmitters.

Logs all decoded transmissions with device model, ID, and full metadata.

Requires: rtl_433 (apt install rtl-433 or build from github.com/merbanan/rtl_433)
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime

import numpy as np

# Get project root (parent of src)
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import SignalLogger, SignalDetection  # noqa: E402

# Frequency presets
ISM_FREQUENCIES = {
    "433.92 MHz (EU)": 433.92e6,
    "868 MHz (EU)": 868.0e6,
    "315 MHz (US)": 315.0e6,
    "915 MHz (US)": 915.0e6,
}

DEFAULT_FREQUENCY = 433.92e6
DEFAULT_GAIN = 40

# rtl_433 saves unknown signals as g001_433.92M_250ks.cu8 etc.
# Sample rate used by rtl_433 internally (250 kHz default)
RTL433_SAMPLE_RATE = 250000


def _load_cu8(filepath):
    """Load rtl_433 .cu8 file (uint8 I/Q pairs) as complex64 numpy array."""
    raw = np.fromfile(filepath, dtype=np.uint8)
    # Convert unsigned 8-bit to float centered at 0
    iq = raw.astype(np.float32) - 127.5
    # Interleaved I, Q
    iq_complex = iq[0::2] + 1j * iq[1::2]
    return iq_complex


class ISMScanner:
    """
    ISM band scanner using rtl_433 + native FSK/OOK analysis.

    - Known protocols: decoded by rtl_433 (200+ device types)
    - Unknown signals: saved by rtl_433, analyzed with native FSK/OOK
      detection from keyfob module (car keyfobs, unrecognized remotes)
    """

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        gain: int = DEFAULT_GAIN,
        frequency: float = DEFAULT_FREQUENCY,
        hop: bool = False,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.output_dir = output_dir
        self.device_id = device_id
        self.device_index = device_index
        self.gain = gain
        self.frequency = frequency
        self.hop = hop

        # Directory for rtl_433 unknown signal dumps
        self._unknown_dir = os.path.join(output_dir, "ism_unknown")
        os.makedirs(self._unknown_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="ism",
            device_id=device_id,
            min_snr_db=0,
        )

        self._process = None
        self._detection_count = 0
        self._devices = defaultdict(int)  # "model:id" -> count
        self._last_events = []  # Last N events for display
        self._processed_files = set()  # Already-analyzed .cu8 files

    def _get_frequency_name(self):
        """Get human-readable name for current frequency."""
        for name, freq in ISM_FREQUENCIES.items():
            if abs(freq - self.frequency) < 1e5:
                return name
        return f"{self.frequency / 1e6:.2f} MHz"

    def _build_command(self):
        """Build rtl_433 command line."""
        cmd = ["rtl_433"]

        if not self.hop:
            cmd += ["-f", str(int(self.frequency))]

        cmd += ["-g", str(self.gain)]

        # JSON output, one object per line
        cmd += ["-F", "json"]

        # Include signal level and UTC timestamps
        cmd += ["-M", "level"]
        cmd += ["-M", "time:utc"]

        # Save unknown signals as .cu8 files for native analysis
        cmd += ["-S", "unknown"]

        return cmd

    def _parse_event(self, line):
        """Parse a JSON event from rtl_433 and log it."""
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None

        model = event.get("model", "unknown")
        dev_id = event.get("id", event.get("channel", ""))
        device_key = f"{model}:{dev_id}" if dev_id else model

        self._devices[device_key] += 1
        self._detection_count += 1

        # Extract signal level if available
        snr_db = event.get("snr", 0)
        rssi_db = event.get("rssi", event.get("level", 0))
        noise_db = rssi_db - snr_db if snr_db else rssi_db - 10

        # Extract frequency if reported
        freq_hz = event.get("freq", self.frequency / 1e6)
        if freq_hz < 1e6:  # rtl_433 reports in MHz
            freq_hz *= 1e6

        # Build metadata from all fields
        meta = {k: v for k, v in event.items() if k not in (
            "time", "model", "id", "snr", "rssi", "noise", "freq", "level"
        )}

        detection = SignalDetection.create(
            signal_type=f"ISM:{model}",
            frequency_hz=freq_hz,
            power_db=rssi_db,
            noise_floor_db=noise_db,
            channel=str(dev_id) if dev_id else None,
            device_id=self.device_id,
            metadata=json.dumps(meta),
        )
        self.logger.log(detection)

        # Keep last 10 events for display
        self._last_events.append({
            "time": event.get("time", ""),
            "model": model,
            "id": dev_id,
            "summary": self._summarize_event(event),
        })
        if len(self._last_events) > 10:
            self._last_events.pop(0)

        return event

    def _summarize_event(self, event):
        """Create a one-line summary of an event."""
        parts = []
        for key in ("temperature_C", "temperature_F", "humidity", "pressure_kPa",
                     "pressure_PSI", "battery_ok", "wind_avg_km_h", "rain_mm",
                     "status", "code", "button", "command", "data"):
            if key in event:
                val = event[key]
                short_key = key.replace("temperature_", "temp_").replace("pressure_", "p_")
                parts.append(f"{short_key}={val}")
        return ", ".join(parts[:4]) if parts else ""

    def _analyze_unknown_signal(self, filepath):
        """Run native FSK/OOK analysis on an unknown signal .cu8 file."""
        try:
            samples = _load_cu8(filepath)
        except Exception:
            return

        if len(samples) < 500:
            return

        # Try FSK detection first (car keyfobs)
        from dsp.ook import (detect_fsk_signal, fingerprint_fsk_car,
                             detect_ook_signal, fingerprint_protocol,
                             classify_device)

        fsk_result = detect_fsk_signal(samples, RTL433_SAMPLE_RATE, threshold_db=6)
        if fsk_result:
            fp = fingerprint_fsk_car(fsk_result, self.frequency)
            device_type, icon = classify_device(
                fp['protocol'], fp['code_type'], self.frequency, fp)

            brands = fp.get('device_brands', '')
            model_name = f"FSK:{brands}" if brands else "FSK:unknown"
            device_key = model_name
            self._devices[device_key] += 1
            self._detection_count += 1

            detection = SignalDetection.create(
                signal_type=f"ISM:{model_name}",
                frequency_hz=self.frequency,
                power_db=fsk_result['peak_power_db'],
                noise_floor_db=fsk_result['noise_floor_db'],
                device_id=self.device_id,
                metadata=json.dumps({
                    "modulation": "FSK",
                    "device_type": device_type,
                    "deviation_khz": round(fsk_result['deviation_khz'], 1),
                    "datarate_hz": int(fsk_result['datarate_hz']),
                    "duration_ms": round(fsk_result['duration_ms'], 1),
                    "protocol": fp['protocol'],
                    "confidence": fp['confidence'],
                    "source_file": os.path.basename(filepath),
                }),
            )
            self.logger.log(detection)

            self._last_events.append({
                "time": datetime.utcnow().strftime("%H:%M:%S"),
                "model": f"{icon} {device_type[:23]}",
                "id": "",
                "summary": f"±{fsk_result['deviation_khz']:.0f}kHz {fsk_result['datarate_hz']/1000:.0f}kbps",
            })
            if len(self._last_events) > 10:
                self._last_events.pop(0)
            return

        # Try OOK detection
        ook_result = detect_ook_signal(samples, RTL433_SAMPLE_RATE, threshold_db=6)
        if ook_result['detected'] and len(ook_result['bursts']) >= 5:
            fp = fingerprint_protocol(ook_result['bursts'])
            device_type, icon = classify_device(
                fp['protocol'], fp['code_type'], self.frequency, fp)

            model_name = f"OOK:{fp['protocol']}"
            device_key = model_name
            self._devices[device_key] += 1
            self._detection_count += 1

            detection = SignalDetection.create(
                signal_type=f"ISM:{model_name}",
                frequency_hz=self.frequency,
                power_db=ook_result['peak_power_db'],
                noise_floor_db=ook_result['noise_floor_db'],
                device_id=self.device_id,
                metadata=json.dumps({
                    "modulation": "OOK",
                    "device_type": device_type,
                    "protocol": fp['protocol'],
                    "code_type": fp['code_type'],
                    "bit_count": fp['bit_count'],
                    "data_hex": fp.get('data_hex', ''),
                    "confidence": fp['confidence'],
                    "source_file": os.path.basename(filepath),
                }),
            )
            self.logger.log(detection)

            self._last_events.append({
                "time": datetime.utcnow().strftime("%H:%M:%S"),
                "model": f"{icon} {fp['protocol'][:23]}",
                "id": fp.get('data_hex', '')[:10],
                "summary": f"{fp['code_type']}, {fp['bit_count']} bits",
            })
            if len(self._last_events) > 10:
                self._last_events.pop(0)

    def _unknown_watcher_thread(self):
        """Background thread: watch for new .cu8 files and analyze them."""
        while self._running:
            try:
                cu8_files = sorted(glob.glob(os.path.join(self._unknown_dir, "*.cu8")))
                for f in cu8_files:
                    if f not in self._processed_files:
                        # Wait for file to finish writing
                        try:
                            size1 = os.path.getsize(f)
                            time.sleep(0.3)
                            size2 = os.path.getsize(f)
                            if size2 != size1:
                                continue  # Still being written
                        except OSError:
                            continue
                        self._processed_files.add(f)
                        self._analyze_unknown_signal(f)
                        try:
                            os.remove(f)
                        except OSError:
                            pass
            except Exception:
                pass
            time.sleep(0.3)

    def _print_display(self):
        """Print the scanner display."""
        print("\033[2J\033[H", end="")
        print("=" * 70)
        print("       ISM Band Scanner - rtl_433 + native FSK/OOK")
        print("=" * 70)
        print(f"\nFrequency: {self._get_frequency_name()}"
              f"{'  (hopping)' if self.hop else ''}")
        print(f"Detections: {self._detection_count}")
        print(f"Unique devices: {len(self._devices)}")
        print("-" * 70)

        # Show known devices
        if self._devices:
            print(f"\n  Devices ({len(self._devices)}):")
            sorted_devices = sorted(self._devices.items(), key=lambda x: -x[1])
            for device_key, count in sorted_devices[:12]:
                print(f"    {device_key:40s}  {count:4d} msgs")

        # Show recent events
        if self._last_events:
            print(f"\n  Recent:")
            for evt in self._last_events[-8:]:
                ts = evt["time"].split("T")[-1][:8] if "T" in str(evt["time"]) else str(evt["time"])[-8:]
                model = evt["model"][:25]
                dev_id = str(evt["id"])[:10] if evt["id"] else ""
                summary = evt["summary"][:30]
                print(f"    {ts}  {model:25s} {dev_id:10s}  {summary}")

        print("-" * 70)
        print("\nPress Ctrl+C to exit")

    def scan(self):
        """Start scanning ISM band with rtl_433 + native analysis."""
        if not shutil.which("rtl_433"):
            print("Error: rtl_433 not found.")
            print("Install it:")
            print("  sudo apt install rtl-433")
            print("  # or build from: github.com/merbanan/rtl_433")
            sys.exit(1)

        cmd = self._build_command()
        print(f"Starting: {' '.join(cmd)}")
        print(f"Unknown signals saved to: {self._unknown_dir}")

        log_path = self.logger.start()
        print(f"Logging to: {log_path}")
        print("Waiting for signals...\n")

        self._running = True

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self._unknown_dir,  # .cu8 files saved here
            )

            # Background thread: watch for unknown .cu8 files and analyze
            watcher_thread = threading.Thread(
                target=self._unknown_watcher_thread,
                daemon=True,
            )
            watcher_thread.start()

            # Read stdout in background thread, push lines to queue
            import queue
            stdout_queue = queue.Queue()

            def _read_stdout():
                for line in self._process.stdout:
                    line = line.strip()
                    if line:
                        stdout_queue.put(line)
            stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
            stdout_thread.start()

            # Drain stderr but count unknown signal saves
            def _drain_stderr():
                for line in self._process.stderr:
                    if "Saving signal" in line:
                        self._last_events.append({
                            "time": datetime.utcnow().strftime("%H:%M:%S"),
                            "model": "[rtl_433 saving .cu8]",
                            "id": "",
                            "summary": line.strip()[-40:],
                        })
                        if len(self._last_events) > 10:
                            self._last_events.pop(0)
            stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
            stderr_thread.start()

            last_display_time = 0

            while True:
                # Process any queued rtl_433 JSON events
                updated = False
                try:
                    while True:
                        line = stdout_queue.get_nowait()
                        self._parse_event(line)
                        updated = True
                except queue.Empty:
                    pass

                now = time.time()
                if now - last_display_time >= 1.0 or updated:
                    self._print_display()
                    last_display_time = now

                time.sleep(0.2)

        except KeyboardInterrupt:
            print("\n\nStopping scanner...")
        finally:
            self._running = False
            if self._process:
                self._process.terminate()
                self._process.wait(timeout=5)
            logged_count = self.logger.stop()
            print(f"Scanner stopped. {logged_count} signals logged.")
            print(f"Unique devices seen: {len(self._devices)}")
            if self._devices:
                print("\nDevice summary:")
                for device_key, count in sorted(self._devices.items(), key=lambda x: -x[1]):
                    print(f"  {device_key}: {count} messages")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="ISM Band Scanner (rtl_433)")
    parser.add_argument(
        "--frequency", "-f",
        type=float,
        default=433.92,
        help="Frequency in MHz (default: 433.92)",
    )
    parser.add_argument(
        "--gain", "-g",
        type=int,
        default=DEFAULT_GAIN,
        help=f"RF gain (default: {DEFAULT_GAIN})",
    )
    parser.add_argument(
        "--hop",
        action="store_true",
        help="Enable frequency hopping (433/868/915 MHz)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Output directory for logs",
    )
    parser.add_argument(
        "--device-id",
        type=str,
        default="rtlsdr-001",
        help="Device identifier for logging",
    )

    args = parser.parse_args()

    scanner = ISMScanner(
        output_dir=args.output,
        device_id=args.device_id,
        gain=args.gain,
        frequency=args.frequency * 1e6,
        hop=args.hop,
    )
    scanner.scan()


if __name__ == "__main__":
    main()

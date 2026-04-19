"""
AIS Scanner Module
Receives and decodes AIS (Automatic Identification System) signals from vessels.

AIS operates on two VHF frequencies:
- AIS1: 161.975 MHz (Channel 87B)
- AIS2: 162.025 MHz (Channel 88B)

This scanner can:
1. Use rtl_ais for decoding (recommended)
2. Perform native Python spectrum monitoring (educational)
"""

import sys
import os
import json
import shutil
import signal as sig
import socket
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.marine.ais import AISParser  # noqa: E402
from utils.logger import SignalLogger  # noqa: E402

# Re-export for backward compatibility
from dsp.ais import (  # noqa: E402,F401
    Vessel, decode_ais_message, decode_ais_string, decode_ais_signed,
    decode_ais_unsigned, nmea_to_bits,
    AIS_MESSAGE_TYPES, SHIP_TYPES, NAV_STATUS,
)

# AIS Constants
AIS_FREQ_1 = 161.975e6
AIS_FREQ_2 = 162.025e6
AIS_CENTER_FREQ = 162.0e6
AIS_SAMPLE_RATE = 1.6e6
DEFAULT_GAIN = 40


def check_tools_installed():
    """Check which AIS decoding tools are available."""
    tools = {
        'rtl_ais': shutil.which('rtl_ais'),
        'multimon-ng': shutil.which('multimon-ng'),
    }
    return {k: v is not None for k, v in tools.items()}


class RTLAISClient:
    """Client to receive decoded NMEA from rtl_ais via UDP."""

    def __init__(self, parser, host="127.0.0.1", port=10110):
        self.host = host
        self.port = port
        self.parser = parser
        self.socket = None
        self.running = False
        self._thread = None

    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind((self.host, self.port))
            self.socket.settimeout(1.0)
            return True
        except Exception as e:
            print(f"Could not bind to UDP port: {e}")
            return False

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _receive_loop(self):
        while self.running:
            try:
                data, addr = self.socket.recvfrom(4096)
                lines = data.decode('ascii', errors='ignore').strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line.startswith('!'):
                        self.parser.handle_frame(line)
            except socket.timeout:
                continue
            except Exception:
                if self.running:
                    pass


class AISScanner:
    """AIS vessel scanner — orchestrator using AISParser."""

    def __init__(
        self,
        output_dir=None,
        device_id="rtlsdr-001",
        device_index=0,
        gain=DEFAULT_GAIN,
        use_rtl_ais=True,
        rssi_device_index=None,
    ):
        """
        rssi_device_index: optional index of a SECOND RTL-SDR used
            exclusively for RSSI sampling of AIS1/AIS2 channels in
            parallel with rtl_ais. rtl_ais holds the primary SDR; we
            can't split it, so actual AIS-RSSI calibration requires
            two dongles. Leave unset if only one dongle is present —
            everything still works, just with power_db=0 on the
            detections (AIS calibration extractor gracefully skips
            those, matching pre-commit behaviour).
        """
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.device_index = device_index
        self.gain = gain
        self.use_rtl_ais = use_rtl_ais
        self.rssi_device_index = rssi_device_index

        os.makedirs(output_dir, exist_ok=True)
        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="ais",
            device_id=device_id,
            min_snr_db=0,
        )

        # Optional parallel RSSI monitor — owned by the scanner so its
        # lifetime lines up with rtl_ais.
        self._rssi_monitor = None
        if rssi_device_index is not None:
            from parsers.marine.ais_rssi import AISChannelRSSI
            self._rssi_monitor = AISChannelRSSI(
                device_index=rssi_device_index, gain=gain,
            )

        self.parser = AISParser(logger=self.logger,
                                rssi_monitor=self._rssi_monitor)
        self.tools = check_tools_installed()
        self._rtl_ais_process = None
        self._rtl_ais_client = None

    def scan(self):
        """Run the AIS scanner."""
        def _signal_handler(signum, frame):
            self._stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        print("=" * 70)
        print("              AIS Vessel Scanner")
        print("=" * 70)
        print(f"\nFrequencies: {AIS_FREQ_1/1e6:.3f} MHz, {AIS_FREQ_2/1e6:.3f} MHz")
        print(f"Gain: {self.gain} dB")

        print("\nChecking AIS tools:")
        for tool, available in self.tools.items():
            status = "installed" if available else "not found"
            print(f"  {tool}: {status}")
        print("-" * 70)

        output_file = self.logger.start()
        print(f"Logging to: {output_file}")

        try:
            if self.use_rtl_ais and self.tools.get('rtl_ais'):
                self._scan_rtl_ais()
            else:
                if self.use_rtl_ais:
                    print("\nrtl_ais not found. Install with:")
                    print("  Linux: apt install rtl-ais")
                    print("  Or build from: https://github.com/dgiardini/rtl-ais")
                    print("\nUsing native spectrum monitor instead.\n")
                self._scan_native()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop()

    def _scan_rtl_ais(self):
        """Scan using rtl_ais subprocess + AISParser."""
        print("Starting rtl_ais...")
        # Primary SDR passed explicitly so rtl_ais doesn't grab the
        # wrong dongle when a secondary RSSI monitor owns device index
        # `rssi_device_index`.
        rtl_ais_cmd = ['rtl_ais', '-g', str(self.gain), '-n', '-P', '10110',
                       '-d', str(self.device_index)]
        self._rtl_ais_process = subprocess.Popen(
            rtl_ais_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(2)

        self._rtl_ais_client = RTLAISClient(parser=self.parser, port=10110)
        if not self._rtl_ais_client.connect():
            print("Failed to connect to rtl_ais. Falling back to native mode.")
            self._scan_native()
            return

        self._rtl_ais_client.start()
        print("rtl_ais started. Receiving vessel data...\n")

        # Start the parallel RSSI monitor alongside rtl_ais if the user
        # provided a second SDR index. rtl_ais holds the primary — this
        # needs a different dongle to work.
        if self._rssi_monitor is not None:
            print(f"Starting AIS RSSI monitor on device index "
                  f"{self.rssi_device_index}...")
            self._rssi_monitor.start()

        while True:
            self._display_vessels()
            time.sleep(1.0)

    def _scan_native(self):
        """Spectrum monitor mode — shows power on AIS channels."""
        import utils.loader  # noqa: F401
        from rtlsdr import RtlSdr
        from scipy import signal as scipy_signal
        import numpy as np

        print("Using native spectrum monitoring mode...")
        print("Note: Install rtl_ais for full vessel decoding.\n")

        sdr = RtlSdr(self.device_index)
        try:
            sdr.sample_rate = AIS_SAMPLE_RATE
            sdr.center_freq = AIS_CENTER_FREQ
            sdr.gain = self.gain

            while True:
                samples = sdr.read_samples(256 * 1024)
                freqs, psd = scipy_signal.welch(samples, fs=AIS_SAMPLE_RATE, nperseg=4096)
                freqs = freqs + AIS_CENTER_FREQ - AIS_SAMPLE_RATE / 2

                ais1_mask = np.abs(freqs - AIS_FREQ_1) < 12500
                ais2_mask = np.abs(freqs - AIS_FREQ_2) < 12500

                ais1_power = 10 * np.log10(np.mean(psd[ais1_mask]) + 1e-10)
                ais2_power = 10 * np.log10(np.mean(psd[ais2_mask]) + 1e-10)

                print("\033[H\033[J", end="")
                print("=" * 70)
                print("           AIS Channel Monitor (Native Mode)")
                print("=" * 70)

                def power_bar(power, min_p=-80, max_p=-30):
                    normalized = max(0, min(1, (power - min_p) / (max_p - min_p)))
                    bar_len = int(normalized * 40)
                    return "█" * bar_len + "░" * (40 - bar_len)

                print(f"\nAIS 1 (161.975 MHz): {power_bar(ais1_power)} {ais1_power:.1f} dB")
                print(f"AIS 2 (162.025 MHz): {power_bar(ais2_power)} {ais2_power:.1f} dB")
                print(f"\nUpdated: {datetime.now().strftime('%H:%M:%S')}")
                print("\nPress Ctrl+C to exit")
                time.sleep(0.5)
        finally:
            sdr.close()

    def _display_vessels(self):
        """Display tracked vessels."""
        vessel_db = self.parser.vessel_db
        now = datetime.now()

        # Remove stale vessels
        stale = [m for m, v in vessel_db.items()
                 if (now - v.last_seen).total_seconds() > 300]
        for m in stale:
            del vessel_db[m]

        print("\033[H\033[J", end="")
        print("=" * 120)
        print("                                    AIS Vessel Tracker")
        print("=" * 120)

        if not vessel_db:
            print("\nNo vessels detected yet. Waiting for signals...")
        else:
            sorted_vessels = sorted(vessel_db.values(), key=lambda x: x.last_seen, reverse=True)
            print(f"\n{'MMSI':<12} | {'Name':<20} | {'Type':<12} | {'SOG':>5} | {'COG':>5} | "
                  f"{'Lat':>9} | {'Lon':>10} | {'Status':<15} | {'Msgs':>4}")
            print("-" * 120)

            for v in sorted_vessels[:25]:
                name = (v.name or "--------")[:20]
                sog = f"{v.sog:>5.1f}" if v.sog is not None else " ----"
                cog = f"{v.cog:>5.0f}" if v.cog is not None else " ----"
                lat = f"{v.latitude:>9.4f}" if v.latitude is not None else "   ------"
                lon = f"{v.longitude:>10.4f}" if v.longitude is not None else "    ------"
                status = v.nav_status_name[:15] if v.nav_status is not None else "Unknown"
                print(f"  {v.mmsi:<10} | {name:<20} | {v.ship_type_name[:12]:<12} | "
                      f"{sog} | {cog} | {lat} | {lon} | {status:<15} | {v.message_count:>4}")

        print("-" * 120)
        print(f"Vessels: {len(vessel_db)} | Logged: {self.parser.total_detections} | "
              f"{now.strftime('%H:%M:%S')}")
        print("Ctrl+C to exit")

    def _stop(self):
        """Clean shutdown."""
        if self._rssi_monitor is not None:
            self._rssi_monitor.stop()
        if self._rtl_ais_client:
            self._rtl_ais_client.stop()
        if self._rtl_ais_process:
            self._rtl_ais_process.terminate()
            try:
                self._rtl_ais_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._rtl_ais_process.kill()

        total = self.logger.stop()
        print(f"\n\nTotal vessels logged: {total}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AIS Vessel Scanner")
    parser.add_argument("--gain", "-g", type=int, default=DEFAULT_GAIN)
    parser.add_argument("--native", action="store_true",
                        help="Use native spectrum monitor instead of rtl_ais")
    args = parser.parse_args()
    scanner = AISScanner(gain=args.gain, use_rtl_ais=not args.native)
    scanner.scan()

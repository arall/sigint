"""
Bluetooth Low Energy (BLE) Advertisement Scanner Module
Passively scans BLE advertisements to detect nearby devices.

Phones, smartwatches, fitness trackers, earbuds, and IoT devices constantly
broadcast BLE advertisements. This scanner captures them via HCI and extracts:

- Manufacturer data (Apple, Samsung, Google, etc.)
- Device names (when broadcast)
- TX power (for distance estimation)
- RSSI (for triangulation)

Modern devices use BLE MAC randomization, so this scanner applies persona
fingerprinting similar to the WiFi scanner:

1. Manufacturer ID + advertisement structure -> device type fingerprint
2. Device name correlation -> links randomized MACs
3. Persistent persona DB -> cross-session recognition

Additionally, drones broadcasting Open Drone ID (RemoteID) over BLE are
automatically detected and logged with position and operator information.

Requirements:
- Bluetooth adapter with BLE support (RPi built-in or USB like Alfa)
- bluez tools: hcitool, hcidump
- Root/sudo privileges for raw HCI access

LEGAL NOTE: This tool is for educational and authorized security research only.
Only passive BLE advertisement monitoring is performed.
"""

import os
import sys
import threading

import signal as sig

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.ble import BLECaptureSource  # noqa: E402
from parsers.ble.apple_continuity import AppleContinuityParser  # noqa: E402
from parsers.ble.remote_id import RemoteIDParser  # noqa: E402
from utils.logger import SignalLogger  # noqa: E402

# Detection parameters
DEFAULT_MIN_RSSI = -90  # dBm


class BluetoothScanner:
    """Scans BLE advertisements to detect and fingerprint nearby devices."""

    def __init__(
        self,
        adapter="hci1",
        min_rssi=DEFAULT_MIN_RSSI,
        output_dir="output",
        device_id="bt-001",
        min_snr=5.0,
        gps=None,
    ):
        # Project root (parent of src)
        project_root = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(project_root, output_dir)

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="ble_adv",
            device_id=device_id,
            min_snr_db=min_snr,
        )
        if gps:
            self.logger.gps = gps

        # Capture layer — owns the BLE adapter
        self.capture = BLECaptureSource(adapter=adapter)

        # Parsers
        persona_db_path = os.path.join(output_dir, "personas_bt.json")
        self.continuity_parser = AppleContinuityParser(
            logger=self.logger,
            min_rssi=min_rssi,
            persona_db_path=persona_db_path,
        )
        self.remoteid_parser = RemoteIDParser(
            logger=self.logger,
            min_rssi=min_rssi,
        )

        # Wire parsers to capture
        self.capture.add_parser(self.continuity_parser.handle_frame)
        self.capture.add_parser(self.remoteid_parser.handle_frame)

    def scan(self):
        """Main scan loop."""
        def _signal_handler(signum, frame):
            self.capture.stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        db_path = self.logger.start()
        print(f"[*] Logging to: {db_path}")
        print(f"[*] Adapter: {self.capture.adapter}  Min RSSI: {self.continuity_parser.min_rssi} dBm")

        try:
            self.capture.start()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

    def _shutdown(self):
        """Clean shutdown — stop parsers, print summary."""
        self.capture.stop()

        count = self.logger.stop()

        # Shutdown parsers (persist state)
        self.continuity_parser.shutdown()

        # Print BLE persona summary
        n_personas, n_macs, personas, db_summary = self.continuity_parser.get_summary()

        print(f"\n[*] Session: {n_personas} personas ({n_macs} MACs), "
              f"{count} detections logged")
        if db_summary:
            print(f"[*] Persona DB: {db_summary['total']} total known, "
                  f"{db_summary['returning']} returning")

        # Print RemoteID drone summary
        drones = self.remoteid_parser.get_summary()
        if drones:
            print(f"\n[*] Drones detected: {len(drones)}")
            for drone_id, state in drones.items():
                print(f"  {drone_id}: {state['count']} adverts, "
                      f"RSSI {state.get('last_rssi', 'N/A')} dBm")

        if n_personas > 0:
            print(f"\n{'Persona':<10} {'Device':<22} {'MACs':>5} {'RSSI':>8} "
                  f"{'Adverts':>8} {'Seen':>5}  Name")
            print("-" * 90)
            for pid, p in sorted(personas.items()):
                names = ", ".join(sorted(p.get("names", set()))) or "(unnamed)"
                rssi_str = f"{p['last_rssi']} dBm" if p.get("last_rssi") else "N/A"
                apple_dev = p.get("apple_device")
                mfr = p.get("mfr_name") or (
                    f"CID:{p['mfr_id']}" if p.get("mfr_id") is not None else "?"
                )
                if apple_dev:
                    device = f"Apple {apple_dev}"
                else:
                    device = mfr
                sessions = p.get("prior_sessions", 0) + 1
                seen_str = f"{sessions}x" if sessions > 1 else ""
                rnd = " (rand)" if p.get("randomized") else ""
                print(f"  P{pid:03d}     {(device+rnd)[:22]:<22} {len(p.get('macs', set())):>5} "
                      f"{rssi_str:>8} {p.get('count', 0):>8} {seen_str:>5}  {names}")
                if len(p.get("macs", set())) > 1:
                    for m in sorted(p["macs"]):
                        print(f"             └─ {m}")

"""
WiFi Probe Request Scanner Module
Passively sniffs WiFi probe requests to detect nearby devices (phones, laptops).

Phones constantly broadcast probe requests looking for known networks, even when
not connected to WiFi. Modern devices use MAC address randomization, so this
scanner fingerprints devices using:

1. Device signature — hash of (IE IDs, supported rates, HT capabilities, vendor OUIs)
   This identifies the device model/chipset.
2. SSID set — the networks a device probes for create a per-person fingerprint.
   Even with rotating MACs, the same person's phone probes for the same SSIDs.
3. Sequence number continuity — 802.11 seq numbers often continue across MAC
   rotations, linking old and new MACs within a session.

These combined into a "persona" — a cluster of MACs that belong to the same
physical device/person, robust against MAC randomization.

Additionally, drones broadcasting Open Drone ID (RemoteID) over WiFi are
automatically detected and logged with position and operator information.

Enriched with:
- OUI manufacturer lookup (IEEE database) for non-randomized MACs
- Persistent persona database (JSON) for cross-session device recognition

Requirements:
- WiFi adapter supporting monitor mode (e.g., Alfa AWUS036ACH)
- scapy: pip install scapy
- Root/sudo privileges for monitor mode and raw packet capture

LEGAL NOTE: This tool is for educational and authorized security research only.
Only passive RF monitoring is performed - no deauthentication or active probing.
"""

import os
import sys
import signal as sig

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.wifi import WiFiCaptureSource  # noqa: E402
from parsers.wifi.probe_request import ProbeRequestParser  # noqa: E402
from parsers.wifi.remote_id import WiFiRemoteIDParser  # noqa: E402
from utils.logger import SignalLogger  # noqa: E402
from utils.oui import get_device_description  # noqa: E402

# Detection parameters
DEFAULT_MIN_RSSI = -85  # dBm


class WiFiScanner:
    """Sniffs WiFi probe requests to detect and fingerprint nearby devices."""

    def __init__(
        self,
        interface="wlan1",
        channels=None,
        hop_interval=0.5,
        min_rssi=DEFAULT_MIN_RSSI,
        output_dir="output",
        device_id="wifi-001",
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
            signal_type="wifi_probe",
            device_id=device_id,
            min_snr_db=min_snr,
        )
        if gps:
            self.logger.gps = gps

        # Capture layer — owns the WiFi adapter
        self.capture = WiFiCaptureSource(
            interface=interface,
            channels=channels,
            hop_interval=hop_interval,
        )

        # Parsers
        persona_db_path = os.path.join(output_dir, "personas.json")
        self.probe_parser = ProbeRequestParser(
            logger=self.logger,
            min_rssi=min_rssi,
            persona_db_path=persona_db_path,
        )
        self.remoteid_parser = WiFiRemoteIDParser(
            logger=self.logger,
            min_rssi=min_rssi,
        )

        # Wire parsers to capture
        self.capture.add_parser(self.probe_parser.handle_frame)
        self.capture.add_parser(self.remoteid_parser.handle_frame)

    def scan(self):
        """Main scan loop."""
        def _signal_handler(signum, frame):
            self.capture.stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        db_path = self.logger.start()
        print(f"[*] Logging to: {db_path}")
        print(f"[*] Min RSSI: {self.probe_parser.min_rssi} dBm")

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
        self.probe_parser.shutdown()

        # Print probe request persona summary
        n_personas, n_macs, personas, db_summary = self.probe_parser.get_summary()

        print(f"\n[*] Session: {n_personas} personas ({n_macs} MACs), "
              f"{count} detections logged")
        if db_summary:
            print(f"[*] Persona DB: {db_summary['total']} total known, "
                  f"{db_summary['returning']} returning")

        # Print RemoteID drone summary
        drones = self.remoteid_parser.get_summary()
        if drones:
            print(f"\n[*] Drones detected (WiFi): {len(drones)}")
            for drone_id, state in drones.items():
                print(f"  {drone_id}: {state['count']} frames, "
                      f"RSSI {state.get('last_rssi', 'N/A')} dBm")

        if n_personas > 0:
            print(f"\n{'Persona':<10} {'Device':<22} {'MACs':>5} {'RSSI':>8} "
                  f"{'Probes':>7} {'Seen':>5}  SSIDs")
            print("-" * 95)
            for pid, p in sorted(personas.items()):
                ssids = ", ".join(sorted(p.get("ssids", set()))) or "(broadcast only)"
                rssi_str = f"{p['last_rssi']} dBm" if p.get("last_rssi") else "N/A"
                dev = (p.get("device_desc") or "?")[:20]
                sessions = p.get("prior_sessions", 0) + 1
                seen_str = f"{sessions}x" if sessions > 1 else ""
                print(f"  P{pid:03d}     {dev:<22} {len(p.get('macs', set())):>5} "
                      f"{rssi_str:>8} {p.get('count', 0):>7} {seen_str:>5}  {ssids}")
                if len(p.get("macs", set())) > 1:
                    for m in sorted(p["macs"]):
                        desc = get_device_description(m)
                        print(f"             └─ {m}  [{desc}]")

"""
Meshtastic Scanner Module

Connects to a Meshtastic device (Heltec LoRa ESP32, RAK, T-Beam, etc.)
via serial and decodes mesh traffic: positions, text messages, telemetry,
node info, traceroutes, neighbor info.

Unlike the LoRa scanner (RTL-SDR energy detection), this decodes actual
Meshtastic protocol payloads. Requires a Meshtastic device with serial
access (USB or UART).
"""

import os
import sys
import signal as sig
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.meshtastic import MeshtasticCaptureSource  # noqa: E402
from parsers.meshtastic.mesh import MeshtasticParser  # noqa: E402
from utils.logger import SignalLogger  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))


class MeshtasticScanner:
    """Meshtastic mesh traffic scanner — thin orchestrator."""

    def __init__(
        self,
        dev_path=None,
        output_dir=None,
        device_id="mesh-001",
        region="eu",
        gps=None,
        min_snr=0.0,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")
        os.makedirs(output_dir, exist_ok=True)

        self.region = region.upper()
        self.gps = gps

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="meshtastic",
            device_id=device_id,
            min_snr_db=min_snr,
        )
        if gps:
            self.logger.gps = gps

        self.capture = MeshtasticCaptureSource(dev_path=dev_path)

        self.parser = MeshtasticParser(
            logger=self.logger,
            capture_source=self.capture,
            region=region,
        )

        self.capture.add_parser(self.parser.handle_frame)

        # For display
        self._dev_path = dev_path
        self._start_time = None

    def _print_status(self):
        """Print device and mesh info."""
        nodes = self.capture.node_db
        my_node = self.capture.my_node

        print("\n" + "=" * 60)
        print("         Meshtastic Mesh Scanner")
        print("=" * 60)

        if my_node:
            user = my_node.get("user", {})
            print(f"  Device: {user.get('longName', '?')} [{user.get('shortName', '?')}]")
            print(f"  HW:     {user.get('hwModel', '?')}")
            print(f"  Role:   {user.get('role', '?')}")
            pos = my_node.get("position", {})
            if pos.get("latitude"):
                print(f"  GPS:    {pos['latitude']:.6f}, {pos['longitude']:.6f}")

        band = "868 MHz (EU)" if self.region == "EU" else "915 MHz (US)"
        print(f"  Band:   {band}")
        print(f"  Nodes:  {len(nodes)} known")
        print("-" * 60)

        # Show known nodes sorted by last heard
        sorted_nodes = sorted(
            nodes.items(),
            key=lambda x: x[1].get("lastHeard") or 0,
            reverse=True,
        )
        for nid, node in sorted_nodes[:15]:
            user = node.get("user", {})
            name = user.get("shortName") or user.get("longName") or nid
            hw = user.get("hwModel", "?")
            last = node.get("lastHeard")
            ago = ""
            if last:
                dt = time.time() - last
                if dt < 60:
                    ago = f"{dt:.0f}s"
                elif dt < 3600:
                    ago = f"{dt / 60:.0f}m"
                else:
                    ago = f"{dt / 3600:.0f}h"
            snr_val = node.get("snr")
            snr_str = f" SNR:{snr_val:.0f}" if snr_val else ""
            pos = node.get("position", {})
            pos_str = ""
            if pos.get("latitude"):
                pos_str = f" {pos['latitude']:.4f},{pos['longitude']:.4f}"
            print(f"  {name:<16s} {hw:<16s} {ago:>5s}{snr_str}{pos_str}")

        if len(nodes) > 15:
            print(f"  ... and {len(nodes) - 15} more")
        print("=" * 60)

    def scan(self):
        """Run the Meshtastic scanner."""
        def _signal_handler(signum, frame):
            self.capture.stop()
        sig.signal(sig.SIGINT, _signal_handler)
        sig.signal(sig.SIGTERM, _signal_handler)

        output_file = self.logger.start()
        print(f"  Logging to: {output_file}")
        dev_str = self._dev_path or "auto-detect"
        print(f"  Connecting to {dev_str}...")

        self._start_time = time.time()

        try:
            # Start capture in a thread so we can print status after connect
            import threading
            started = threading.Event()

            def _run():
                try:
                    self.capture.start()
                except Exception as e:
                    print(f"  ERROR: {e}")
                finally:
                    started.set()

            t = threading.Thread(target=_run, daemon=True)
            t.start()

            # Wait for the interface to be ready
            for _ in range(30):
                if self.capture._iface is not None:
                    break
                if started.is_set():
                    break
                time.sleep(0.5)

            if self.capture._iface is None:
                print("  ERROR: Could not connect to Meshtastic device")
                return

            self._print_status()
            print(f"\n  Monitoring mesh traffic (Ctrl+C to stop)...\n")

            # Block until capture thread exits
            t.join()

        except KeyboardInterrupt:
            pass
        finally:
            self.capture.stop()
            total = self.logger.stop()
            elapsed = time.time() - self._start_time if self._start_time else 0
            print(f"\n  Total detections: {total}")
            print(f"  Duration: {elapsed:.0f}s")

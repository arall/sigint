"""
Meshtastic Serial Capture Source

Connects to a Meshtastic device via serial (e.g. Heltec LoRa ESP32 V3)
and emits decoded mesh packets to registered parser callbacks.

Emitted frame: dict with keys from the meshtastic pubsub packet:
  fromId, toId, from, to, decoded (portnum, payload/text/position/...),
  rxSnr, rxRssi, hopLimit, hopStart, channel, etc.
"""

import threading
import time

from capture.base import BaseCaptureSource


class MeshtasticCaptureSource(BaseCaptureSource):
    """Capture source that reads packets from a Meshtastic serial device."""

    def __init__(self, dev_path=None):
        super().__init__()
        self.dev_path = dev_path
        self._iface = None
        self._connect_thread = None

    def _on_receive(self, packet, interface=None):
        """Pubsub callback — emit packet dict to parsers."""
        if not self.stopped:
            self._emit(packet)

    def _on_connection(self, interface, topic=None):
        pass

    def _on_lost(self, interface):
        if not self.stopped:
            print("  [Meshtastic] Connection lost")

    @property
    def node_db(self):
        """Access the device's node database (for name resolution)."""
        if self._iface and hasattr(self._iface, "nodes"):
            return self._iface.nodes or {}
        return {}

    @property
    def my_info(self):
        """Access local device info."""
        if self._iface:
            return self._iface.myInfo
        return None

    @property
    def my_node(self):
        """Access local node info dict."""
        if self._iface:
            try:
                return self._iface.getMyNodeInfo()
            except Exception:
                pass
        return None

    def start(self):
        """Connect to device and block until stop() is called."""
        from meshtastic.serial_interface import SerialInterface
        from pubsub import pub

        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_connection, "meshtastic.connection.established")
        pub.subscribe(self._on_lost, "meshtastic.connection.lost")

        try:
            self._iface = SerialInterface(devPath=self.dev_path)
        except Exception as e:
            raise RuntimeError(f"Could not connect to Meshtastic device: {e}")

        # Block until stopped
        try:
            while not self.stopped:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    def stop(self):
        """Disconnect and release the serial port."""
        self._stop_event.set()
        if self._iface:
            try:
                self._iface.close()
            except Exception:
                pass
            self._iface = None

        from pubsub import pub
        try:
            pub.unsubscribe(self._on_receive, "meshtastic.receive")
            pub.unsubscribe(self._on_connection, "meshtastic.connection.established")
            pub.unsubscribe(self._on_lost, "meshtastic.connection.lost")
        except Exception:
            pass

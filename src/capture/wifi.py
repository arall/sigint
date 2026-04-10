"""
WiFi Capture Source — owns the WiFi adapter in monitor mode and emits
raw 802.11 frames to registered parsers.

Emits (packet, channel) tuples where packet is a raw scapy Dot11 frame
and channel is the current WiFi channel number.

Requirements:
- WiFi adapter supporting monitor mode (e.g., Alfa AWUS036ACH)
- scapy: pip install scapy
- Root/sudo privileges for monitor mode and raw packet capture
- iw: for channel hopping and monitor mode setup
"""

import subprocess
import sys
import threading

from capture.base import BaseCaptureSource

# Default parameters
DEFAULT_HOP_INTERVAL = 0.3  # seconds per channel

# Channel → frequency (MHz) mapping for iw
# 2.4 GHz (Band 1)
_FREQ_24GHZ = {
    1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437,
    7: 2442, 8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467,
    13: 2472, 14: 2484,
}
# 5 GHz (Band 2) — UNII-1/2/2e/3
_FREQ_5GHZ = {
    36: 5180, 40: 5200, 44: 5220, 48: 5240,
    52: 5260, 56: 5280, 60: 5300, 64: 5320,
    100: 5500, 104: 5520, 108: 5540, 112: 5560,
    116: 5580, 120: 5600, 124: 5620, 128: 5640,
    132: 5660, 136: 5680, 140: 5700, 144: 5720,
    149: 5745, 153: 5765, 157: 5785, 161: 5805, 165: 5825,
}
# 6 GHz (Band 4) — Wi-Fi 6E
_FREQ_6GHZ = {ch: 5955 + (ch - 1) * 5 for ch in range(1, 234, 4)}

# Commonly used non-DFS channels per band
CHANNELS_24GHZ = [1, 6, 11]
CHANNELS_5GHZ_NON_DFS = [36, 40, 44, 48, 149, 153, 157, 161, 165]
CHANNELS_5GHZ_ALL = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112,
                     116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165]
CHANNELS_DEFAULT = CHANNELS_24GHZ + CHANNELS_5GHZ_NON_DFS


def channel_to_freq(ch):
    """Convert a WiFi channel number to frequency in MHz."""
    if ch in _FREQ_24GHZ:
        return _FREQ_24GHZ[ch]
    if ch in _FREQ_5GHZ:
        return _FREQ_5GHZ[ch]
    if ch in _FREQ_6GHZ:
        return _FREQ_6GHZ[ch]
    return None


def _run_cmd(cmd, check=True):
    """Run a shell command, return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.returncode, result.stdout.strip(), result.stderr.strip()


class WiFiCaptureSource(BaseCaptureSource):
    """Captures raw 802.11 frames via monitor mode and scapy."""

    def __init__(self, interface="wlan1", channels=None, hop_interval=DEFAULT_HOP_INTERVAL):
        super().__init__()
        self.interface = interface
        self.channels = channels or CHANNELS_DEFAULT
        self.hop_interval = hop_interval
        self.mon_interface = None
        self._current_channel = self.channels[0]

    @property
    def current_channel(self):
        return self._current_channel

    def start(self):
        """Enable monitor mode, start hopping, sniff frames. Blocks until stop()."""
        try:
            from scapy.all import sniff
        except ImportError:
            raise RuntimeError("scapy is required. Install with: pip install scapy")

        self._enable_monitor_mode()

        ch_24 = [c for c in self.channels if c in _FREQ_24GHZ]
        ch_5 = [c for c in self.channels if c in _FREQ_5GHZ]
        ch_6 = [c for c in self.channels if c in _FREQ_6GHZ]
        parts = []
        if ch_24:
            parts.append(f"2.4GHz:{ch_24}")
        if ch_5:
            parts.append(f"5GHz:{ch_5}")
        if ch_6:
            parts.append(f"6GHz:{ch_6}")
        print(f"[*] Channels: {' | '.join(parts)}  Hop interval: {self.hop_interval}s")
        print(f"[*] Sniffing on {self.mon_interface}... (Ctrl+C to stop)\n")

        hopper = threading.Thread(target=self._hop_channels, daemon=True)
        hopper.start()

        try:
            sniff(
                iface=self.mon_interface,
                prn=self._handle_packet,
                store=0,
                stop_filter=lambda _: self._stop_event.is_set(),
            )
        finally:
            self._disable_monitor_mode()

    def stop(self):
        """Signal the capture to stop."""
        self._stop_event.set()

    def _handle_packet(self, packet):
        """Wrap packet with current channel and emit to parsers."""
        self._emit((packet, self._current_channel))

    def _enable_monitor_mode(self):
        """Put the WiFi interface into monitor mode."""
        print(f"[*] Enabling monitor mode on {self.interface}...")

        _, out, _ = _run_cmd(["sudo", "iw", "dev", self.interface, "info"], check=False)
        if "type monitor" in out:
            self.mon_interface = self.interface
            print(f"[+] {self.interface} already in monitor mode")
            return

        _run_cmd(["sudo", "ip", "link", "set", self.interface, "down"])
        _run_cmd(["sudo", "iw", self.interface, "set", "type", "monitor"])
        _run_cmd(["sudo", "ip", "link", "set", self.interface, "up"])

        self.mon_interface = self.interface
        print(f"[+] Monitor mode enabled on {self.mon_interface}")

    def _disable_monitor_mode(self):
        """Restore the WiFi interface to managed mode."""
        if not self.mon_interface:
            return
        print(f"\n[*] Restoring {self.mon_interface} to managed mode...")
        _run_cmd(["sudo", "ip", "link", "set", self.mon_interface, "down"], check=False)
        _run_cmd(["sudo", "iw", self.mon_interface, "set", "type", "managed"], check=False)
        _run_cmd(["sudo", "ip", "link", "set", self.mon_interface, "up"], check=False)
        print(f"[+] {self.mon_interface} restored to managed mode")

    def _hop_channels(self):
        """Hop across WiFi channels in a background thread.

        Uses 'iw dev ... set freq <MHz>' instead of 'set channel' because
        channel numbers overlap between 2.4/5/6 GHz bands.
        """
        idx = 0
        while not self._stop_event.is_set():
            ch = self.channels[idx % len(self.channels)]
            freq = channel_to_freq(ch)
            try:
                if freq:
                    _run_cmd(
                        ["sudo", "iw", "dev", self.mon_interface,
                         "set", "freq", str(freq)],
                        check=False,
                    )
                else:
                    _run_cmd(
                        ["sudo", "iw", "dev", self.mon_interface,
                         "set", "channel", str(ch)],
                        check=False,
                    )
                self._current_channel = ch
            except Exception:
                pass
            idx += 1
            self._stop_event.wait(self.hop_interval)

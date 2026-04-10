"""
BLE Capture Source — owns the Bluetooth HCI adapter and emits raw
advertisement frames to registered parsers.

Emits tuples of (addr, addr_type, ad_bytes, rssi) for each BLE
advertisement received via hcitool/hcidump.

Requirements:
- bluez tools: hcitool, hcidump
- Root/sudo privileges for raw HCI access
"""

import os
import select
import struct
import subprocess
import sys
import time

from capture.base import BaseCaptureSource


class BLECaptureSource(BaseCaptureSource):
    """Captures BLE advertisements via HCI and emits raw AD frames."""

    def __init__(self, adapter="hci1"):
        super().__init__()
        self.adapter = adapter
        self._scan_proc = None
        self._dump_proc = None

    def start(self):
        """Start BLE capture. Blocks until stop() is called."""
        self._check_tools()
        self._reset_adapter()
        self._scan_proc = self._start_lescan()
        self._dump_proc = self._start_hcidump()

        print(f"[*] Scanning BLE on {self.adapter}... (Ctrl+C to stop)\n")

        try:
            self._parse_hcidump_stream()
        finally:
            self._cleanup()

    def stop(self):
        """Signal the capture to stop."""
        self._stop_event.set()

    def _check_tools(self):
        """Verify hcitool and hcidump are installed."""
        for tool in ("hcitool", "hcidump"):
            if not any(
                os.path.isfile(os.path.join(p, tool))
                for p in os.environ.get("PATH", "").split(":")
            ):
                raise RuntimeError(
                    f"{tool} not found. Install with: sudo apt install bluez bluez-hcidump")

    def _reset_adapter(self):
        """Reset adapter to clear stale state."""
        subprocess.run(["sudo", "hciconfig", self.adapter, "down"], capture_output=True)
        time.sleep(0.5)
        subprocess.run(["sudo", "hciconfig", self.adapter, "up"], capture_output=True)
        time.sleep(0.5)

    def _start_lescan(self):
        """Start hcitool lescan and verify it launched."""
        proc = subprocess.Popen(
            ["sudo", "hcitool", "-i", self.adapter, "lescan", "--duplicates"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        time.sleep(1.0)
        if proc.poll() is not None:
            err = proc.stderr.read().decode()
            raise RuntimeError(
                f"BLE scan failed: {err.strip()}. "
                f"Try: sudo hciconfig {self.adapter} down && "
                f"sudo hciconfig {self.adapter} up")
        return proc

    def _start_hcidump(self):
        """Start hcidump for raw HCI packets."""
        return subprocess.Popen(
            ["sudo", "hcidump", "-i", self.adapter, "--raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def _parse_hcidump_stream(self):
        """Parse raw HCI events from hcidump --raw output."""
        buf = bytearray()
        in_packet = False

        while not self._stop_event.is_set():
            ready, _, _ = select.select([self._dump_proc.stdout], [], [], 0.5)
            if not ready:
                continue

            line = self._dump_proc.stdout.readline()
            if not line:
                break
            line = line.decode("utf-8", errors="replace").rstrip()

            if line.startswith(">"):
                if in_packet and len(buf) >= 14:
                    self._process_hci_packet(bytes(buf))
                hex_str = line[1:].strip()
                try:
                    buf = bytearray.fromhex(hex_str.replace(" ", ""))
                except ValueError:
                    buf = bytearray()
                in_packet = True
            elif line.startswith("  ") and in_packet:
                try:
                    buf.extend(bytearray.fromhex(line.strip().replace(" ", "")))
                except ValueError:
                    pass
            elif line.startswith("<"):
                if in_packet and len(buf) >= 14:
                    self._process_hci_packet(bytes(buf))
                in_packet = False
                buf = bytearray()

        if in_packet and len(buf) >= 14:
            self._process_hci_packet(bytes(buf))

    def _process_hci_packet(self, data):
        """Parse HCI LE Advertising Report and emit (addr, addr_type, ad, rssi)."""
        if data[0] != 0x04 or data[1] != 0x3E:
            return
        if data[3] != 0x02:  # not advertising report
            return

        num = data[4]
        off = 5
        for _ in range(num):
            if off + 9 > len(data):
                break
            addr_type = data[off + 1]
            addr = ":".join(f"{b:02X}" for b in reversed(data[off + 2:off + 8]))
            dlen = data[off + 8]
            off += 9
            if off + dlen + 1 > len(data):
                break
            ad = data[off:off + dlen]
            off += dlen
            rssi = struct.unpack("b", bytes([data[off]]))[0]
            off += 1

            self._emit((addr, addr_type, ad, rssi))

    def _cleanup(self):
        """Terminate subprocesses."""
        if self._scan_proc:
            self._scan_proc.terminate()
            self._scan_proc.wait()
        if self._dump_proc:
            self._dump_proc.terminate()
            self._dump_proc.wait()

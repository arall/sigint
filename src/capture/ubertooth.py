"""Passive BLE advertisement capture through an Ubertooth One.

The Ubertooth command-line utility decodes BLE advertising PDUs and exposes
the same data contract as :mod:`capture.ble`: ``(mac, addr_type, ad, rssi)``.
That lets the existing BLE parsers run unchanged.  One Ubertooth monitors one
advertising channel at a time; the initial integration defaults to channel 37
for a stable continuous capture.
"""

import re
import select
import shutil
import subprocess

from capture.base import BaseCaptureSource


ADV_CHANNELS = (37, 38, 39)
_RSSI_RE = re.compile(r"\brssi=(-?\d+)")
_TYPE_RE = re.compile(r"^\s*Type:\s+(ADV_[A-Z_]+)")
_ADVA_RE = re.compile(r"^\s*AdvA:\s+([0-9a-f:]{17})\s+\((public|random)\)", re.I)
_DATA_RE = re.compile(r"^\s*AdvData:\s*([0-9a-f ]+)$", re.I)


class UbertoothCaptureSource(BaseCaptureSource):
    """Capture advertising PDUs using ``ubertooth-btle``.

    ``ubertooth-btle`` is deliberately used instead of duplicating its BLE
    PHY/CRC decoder.  Its human-readable output is parsed only at the small,
    stable AdvA/AdvData boundary and never treated as a shell command.
    """

    def __init__(self, device_index=0, channel=37,
                 binary="ubertooth-btle"):
        super().__init__()
        channel = int(channel)
        if channel not in ADV_CHANNELS:
            raise ValueError("Ubertooth channel must be 37, 38, or 39")
        self.device_index = int(device_index)
        self.channel = channel
        self.binary = binary
        self._proc = None
        self._rssi = None
        self._adv_type = None
        self._addr = None
        self._addr_type = None

    def start(self):
        """Capture until :meth:`stop` is called."""
        if not shutil.which(self.binary):
            raise RuntimeError(f"{self.binary} not found; install the Ubertooth host tools")

        try:
            self._start_channel(self.channel)
            while not self.stopped:
                self._read_once(0.25)
                if self._proc and self._proc.poll() is not None:
                    err = self._proc.stderr.read().decode(errors="replace") if self._proc.stderr else ""
                    raise RuntimeError(f"{self.binary} exited on channel {self.channel}: {err.strip()}")
        finally:
            self._stop_process()

    def stop(self):
        self._stop_event.set()
        self._stop_process()

    def _start_channel(self, channel):
        self._reset_frame()
        # stdbuf prevents libc from block-buffering the utility's stdout when
        # the server captures it through a pipe.
        cmd = ["stdbuf", "-oL", self.binary, "-n", f"-A{channel}", f"-U{self.device_index}"]
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=1,
        )

    def _read_once(self, timeout):
        if not self._proc or not self._proc.stdout:
            return
        ready, _, _ = select.select([self._proc.stdout], [], [], timeout)
        if ready:
            line = self._proc.stdout.readline().decode("utf-8", errors="replace").rstrip()
            if line:
                self._consume_line(line)

    def _consume_line(self, line):
        rssi = _RSSI_RE.search(line)
        if rssi:
            self._reset_frame()
            self._rssi = int(rssi.group(1))
            return
        kind = _TYPE_RE.match(line)
        if kind:
            self._adv_type = kind.group(1)
            return
        addr = _ADVA_RE.match(line)
        if addr:
            self._addr = addr.group(1).upper()
            self._addr_type = 1 if addr.group(2).lower() == "random" else 0
            return
        data = _DATA_RE.match(line)
        if data and self._adv_type in {"ADV_IND", "ADV_NONCONN_IND", "ADV_SCAN_IND"} and self._addr:
            try:
                ad = bytes.fromhex(data.group(1))
            except ValueError:
                return
            self._emit((self._addr, self._addr_type, ad, self._rssi))

    def _reset_frame(self):
        self._rssi = None
        self._adv_type = None
        self._addr = None
        self._addr_type = None

    def _stop_process(self):
        proc, self._proc = self._proc, None
        if not proc:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()

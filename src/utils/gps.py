#!/usr/bin/env python3
"""
GPS Reader Module
Reads NMEA sentences from a serial GPS (e.g. u-blox) and provides
current coordinates for signal detection logging.
"""

import json
import os
import re
import threading
import time
from typing import Callable, Optional, Tuple


# NMEA checksum validation
def _nmea_checksum(sentence: str) -> bool:
    """Validate NMEA sentence checksum."""
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body = sentence[1:sentence.index("*")]
    expected = sentence[sentence.index("*") + 1:].strip()
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return f"{calc:02X}" == expected.upper()


def _parse_nmea_coord(raw: str, direction: str) -> Optional[float]:
    """Parse NMEA lat/lon field (DDMM.MMMM or DDDMM.MMMM) to decimal degrees."""
    if not raw or not direction:
        return None
    try:
        # Find the decimal point, degrees are everything before the last 2 digits before it
        dot = raw.index(".")
        degrees = int(raw[:dot - 2])
        minutes = float(raw[dot - 2:])
        result = degrees + minutes / 60.0
        if direction in ("S", "W"):
            result = -result
        return round(result, 7)
    except (ValueError, IndexError):
        return None


class GPSReader:
    """
    Background thread that reads NMEA from a serial GPS device.
    Provides thread-safe access to the latest fix.
    """

    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate

        self._lat: Optional[float] = None
        self._lon: Optional[float] = None
        self._sats: int = 0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start reading GPS in background."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the GPS reader."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    @property
    def position(self) -> Tuple[Optional[float], Optional[float]]:
        """Return (latitude, longitude) or (None, None) if no fix."""
        with self._lock:
            return (self._lat, self._lon)

    @property
    def satellites(self) -> int:
        """Number of satellites in use (from GGA field 7). 0 if no fix."""
        with self._lock:
            return self._sats

    def _read_loop(self):
        """Read NMEA sentences from serial port."""
        try:
            import serial
            ser = serial.Serial(self.port, self.baudrate, timeout=1)
        except ImportError:
            # Fall back to raw file read if pyserial not available
            self._read_loop_raw()
            return
        except Exception as e:
            print(f"[GPS] Failed to open {self.port}: {e}")
            return

        try:
            while self._running:
                try:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if line:
                        self._parse_sentence(line)
                except Exception:
                    time.sleep(0.1)
        finally:
            ser.close()

    def _read_loop_raw(self):
        """Fallback: read GPS as a raw file descriptor (no pyserial)."""
        import termios
        try:
            fd = os.open(self.port, os.O_RDONLY | os.O_NOCTTY)
        except OSError as e:
            print(f"[GPS] Failed to open {self.port}: {e}")
            return

        # Configure serial: 9600 8N1
        try:
            attrs = termios.tcgetattr(fd)
            attrs[4] = termios.B9600  # ispeed
            attrs[5] = termios.B9600  # ospeed
            attrs[2] = termios.CS8 | termios.CLOCAL | termios.CREAD  # cflag
            attrs[0] = 0  # iflag
            attrs[1] = 0  # oflag
            attrs[3] = 0  # lflag
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 10  # 1 second timeout
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception:
            pass

        f = os.fdopen(fd, "r", errors="ignore")
        try:
            while self._running:
                try:
                    line = f.readline().strip()
                    if line:
                        self._parse_sentence(line)
                except Exception:
                    time.sleep(0.1)
        finally:
            f.close()

    def _parse_sentence(self, line: str):
        """Parse GGA or RMC sentences for position."""
        if not _nmea_checksum(line):
            return

        # $GPGGA or $GNGGA
        if ",GGA," in line or line.startswith(("$GPGGA", "$GNGGA")):
            fields = line.split(",")
            if len(fields) >= 10 and fields[6] != "0":  # fix quality != 0
                lat = _parse_nmea_coord(fields[2], fields[3])
                lon = _parse_nmea_coord(fields[4], fields[5])
                # field 7 = number of satellites in use
                try:
                    sats = int(fields[7]) if fields[7] else 0
                except ValueError:
                    sats = 0
                if lat is not None and lon is not None:
                    with self._lock:
                        self._lat = lat
                        self._lon = lon
                        self._sats = sats

        # $GPRMC or $GNRMC
        elif ",RMC," in line or line.startswith(("$GPRMC", "$GNRMC")):
            fields = line.split(",")
            if len(fields) >= 7 and fields[2] == "A":  # A = active fix
                lat = _parse_nmea_coord(fields[3], fields[4])
                lon = _parse_nmea_coord(fields[5], fields[6])
                if lat is not None and lon is not None:
                    with self._lock:
                        self._lat = lat
                        self._lon = lon


PositionProvider = Callable[[], Tuple[Optional[float], Optional[float], int]]


class MeshtasticGpsReader:
    """GPS reader backed by the local Meshtastic node's position field.

    Same surface as GPSReader (start/stop, position, satellites) but pulls
    `(lat, lon, sats)` from a provider callable instead of reading NMEA off
    a serial port. The agent passes a callable that wraps `MeshLink
    .get_local_position()` so the existing meshtastic serial connection
    is reused — no second port, no extra hardware.
    """

    def __init__(self, provider: PositionProvider, poll_interval: float = 5.0):
        self._provider = provider
        self._poll_interval = poll_interval
        self._lat: Optional[float] = None
        self._lon: Optional[float] = None
        self._sats: int = 0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def position(self) -> Tuple[Optional[float], Optional[float]]:
        with self._lock:
            return (self._lat, self._lon)

    @property
    def satellites(self) -> int:
        with self._lock:
            return self._sats

    def _loop(self):
        while not self._stop.is_set():
            try:
                lat, lon, sats = self._provider()
            except Exception:
                lat, lon, sats = None, None, 0
            with self._lock:
                self._lat = lat
                self._lon = lon
                self._sats = int(sats or 0)
            self._stop.wait(self._poll_interval)


def write_gps_sidecar(reader, path: str, interval: float = 30.0,
                      stop_event: Optional[threading.Event] = None) -> threading.Thread:
    """Periodically write `reader.position` + `reader.satellites` to `path`.

    The agent's `_stat_loop` reads this same path and uses the values for
    STAT messages and DET tagging — see agent.py:_stat_loop. Only writes
    when there's a fix; an unwritten/stale sidecar yields lat/lon=None
    on the consumer side, which is correct.

    Returns the daemon thread (already started). Pass a stop_event to
    halt it deterministically; otherwise it dies with the process.
    """
    stop = stop_event or threading.Event()

    def _loop():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        while not stop.is_set():
            lat, lon = reader.position
            if lat is not None and lon is not None:
                payload = {
                    "lat": lat,
                    "lon": lon,
                    "sats": reader.satellites,
                    "ts": time.time(),
                }
                tmp = path + ".tmp"
                try:
                    with open(tmp, "w") as f:
                        json.dump(payload, f)
                    os.replace(tmp, path)
                except OSError:
                    pass
            stop.wait(interval)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t

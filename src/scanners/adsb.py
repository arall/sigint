"""
ADS-B Scanner Module
Receives and decodes ADS-B (Automatic Dependent Surveillance-Broadcast) signals
from aircraft at 1090 MHz.

ADS-B transmits:
- ICAO 24-bit address (unique aircraft identifier)
- Callsign/flight number
- Altitude (barometric and geometric)
- Position (latitude/longitude via CPR encoding)
- Velocity (ground speed, heading, vertical rate)
- Squawk code

Technical details:
- Frequency: 1090 MHz
- Modulation: PPM (Pulse Position Modulation)
- Data rate: 1 Mbit/s
- Message types: Short (56 bits) and Extended Squitter (112 bits)

This scanner can either:
1. Use dump1090 for decoding (recommended, more accurate)
2. Perform native Python decoding (educational, less reliable)
"""

import sys
import os
import subprocess
import shutil
import json
import socket
import threading
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from collections import defaultdict

# Get project root (parent of src)
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.loader  # noqa: F401,E402 - Must be imported before rtlsdr

import numpy as np  # noqa: E402
from rtlsdr import RtlSdr  # noqa: E402

from utils.logger import SignalLogger  # noqa: E402


# ADS-B Constants
ADSB_FREQUENCY = 1090e6  # 1090 MHz
ADSB_SAMPLE_RATE = 2e6   # 2 MHz sample rate (2 samples per bit)
DEFAULT_GAIN = 40

# Mode S message types (Downlink Format)
DF_TYPES = {
    0: "Short air-air surveillance (ACAS)",
    4: "Surveillance altitude reply",
    5: "Surveillance identity reply",
    11: "All-call reply",
    16: "Long air-air surveillance (ACAS)",
    17: "Extended squitter (ADS-B)",
    18: "Extended squitter (TIS-B/ADS-R)",
    19: "Military extended squitter",
    20: "Comm-B altitude reply",
    21: "Comm-B identity reply",
    24: "Comm-D (ELM)",
}

# Type codes for DF17 (ADS-B) messages
TC_TYPES = {
    (1, 4): "Aircraft identification",
    (5, 8): "Surface position",
    (9, 18): "Airborne position (baro alt)",
    (19, 19): "Airborne velocity",
    (20, 22): "Airborne position (GNSS alt)",
    (23, 23): "Test message",
    (24, 24): "Surface system status",
    (25, 27): "Reserved",
    (28, 28): "Extended squitter status",
    (29, 29): "Target state and status",
    (31, 31): "Aircraft operational status",
}

# Character set for callsign decoding
CALLSIGN_CHARS = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######"


@dataclass
class Aircraft:
    """Tracked aircraft information."""
    icao: str  # 24-bit ICAO address as hex string
    callsign: Optional[str] = None
    altitude: Optional[int] = None  # feet
    ground_speed: Optional[float] = None  # knots
    heading: Optional[float] = None  # degrees
    vertical_rate: Optional[int] = None  # feet/min
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    squawk: Optional[str] = None
    on_ground: bool = False
    last_seen: datetime = field(default_factory=datetime.now)
    message_count: int = 0

    # For CPR position decoding
    _cpr_even_lat: Optional[float] = None
    _cpr_even_lon: Optional[float] = None
    _cpr_even_time: Optional[float] = None
    _cpr_odd_lat: Optional[float] = None
    _cpr_odd_lon: Optional[float] = None
    _cpr_odd_time: Optional[float] = None

    def update_position_cpr(self, lat_cpr: float, lon_cpr: float, odd: bool, t: float):
        """Update CPR position data for later decoding."""
        if odd:
            self._cpr_odd_lat = lat_cpr
            self._cpr_odd_lon = lon_cpr
            self._cpr_odd_time = t
        else:
            self._cpr_even_lat = lat_cpr
            self._cpr_even_lon = lon_cpr
            self._cpr_even_time = t

        # Try to decode position if we have both even and odd
        if self._can_decode_position():
            self._decode_position()

    def _can_decode_position(self) -> bool:
        """Check if we have enough data to decode position."""
        if None in (self._cpr_even_lat, self._cpr_even_lon,
                    self._cpr_odd_lat, self._cpr_odd_lon,
                    self._cpr_even_time, self._cpr_odd_time):
            return False
        # Messages must be within 10 seconds of each other
        return abs(self._cpr_even_time - self._cpr_odd_time) < 10.0

    def _decode_position(self):
        """Decode latitude/longitude from CPR encoded positions.
        See: https://mode-s.org/decode/content/ads-b/3-airborne-position.html
        """
        lat_even = self._cpr_even_lat
        lat_odd = self._cpr_odd_lat
        lon_even = self._cpr_even_lon
        lon_odd = self._cpr_odd_lon

        # Number of latitude zones (NZ = 15 for Mode S)
        nz = 15

        # Latitude index
        j = int(59 * lat_odd - 60 * lat_even + 0.5)

        # Latitude zone sizes
        dlat_even = 360.0 / (4 * nz)       # 6 degrees
        dlat_odd = 360.0 / (4 * nz - 1)    # ~6.1 degrees

        lat_even_decoded = dlat_even * ((j % (4 * nz)) + lat_even)
        lat_odd_decoded = dlat_odd * ((j % (4 * nz - 1)) + lat_odd)

        # Adjust for southern hemisphere
        if lat_even_decoded >= 270:
            lat_even_decoded -= 360
        if lat_odd_decoded >= 270:
            lat_odd_decoded -= 360

        # Check that both latitudes are in the same NL zone
        if self._nl(lat_even_decoded) != self._nl(lat_odd_decoded):
            return  # Ambiguous zone, wait for next pair

        # Use the most recent position
        if self._cpr_even_time > self._cpr_odd_time:
            # Even message is most recent
            lat = lat_even_decoded
            nl = self._nl(lat)
            ni = max(nl, 1)
            dlon = 360.0 / ni
            m = int(lon_even * (nl - 1) - lon_odd * nl + 0.5)
            lon = dlon * ((m % ni) + lon_even)
        else:
            # Odd message is most recent
            lat = lat_odd_decoded
            nl = self._nl(lat)
            ni = max(nl - 1, 1)
            dlon = 360.0 / ni
            m = int(lon_even * (nl - 1) - lon_odd * nl + 0.5)
            lon = dlon * ((m % ni) + lon_odd)

        # Adjust longitude
        if lon > 180:
            lon -= 360

        self.latitude = lat
        self.longitude = lon

    @staticmethod
    def _nl(lat: float) -> int:
        """Calculate number of longitude zones for a given latitude."""
        if abs(lat) >= 87:
            return 1

        import math
        nz = 15
        a = 1 - math.cos(math.pi / (2 * nz))
        b = math.cos(math.pi / 180 * abs(lat)) ** 2
        nl = math.floor(2 * math.pi / math.acos(1 - a / b))
        return nl


def check_tools_installed() -> Dict[str, bool]:
    """Check which ADS-B tools are available."""
    tools = {
        'dump1090': shutil.which('readsb') or shutil.which('dump1090') or shutil.which('dump1090-mutability') or shutil.which('dump1090-fa'),
        'rtl_adsb': shutil.which('rtl_adsb'),
    }
    return {k: v is not None for k, v in tools.items()}


def crc24(data: bytes) -> int:
    """Calculate CRC-24 checksum for Mode S messages."""
    # CRC-24 polynomial for Mode S
    poly = 0xFFF409
    crc = 0

    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            if crc & 0x800000:
                crc = (crc << 1) ^ poly
            else:
                crc <<= 1
            crc &= 0xFFFFFF

    return crc


def decode_callsign(data: bytes) -> str:
    """Decode 8-character callsign from ADS-B message."""
    # Callsign is encoded in 6-bit characters
    chars = []
    bits = int.from_bytes(data, 'big')

    for i in range(8):
        char_idx = (bits >> (42 - i * 6)) & 0x3F
        if char_idx < len(CALLSIGN_CHARS):
            chars.append(CALLSIGN_CHARS[char_idx])

    return ''.join(chars).strip()


def decode_altitude(alt_code: int, q_bit: bool) -> Optional[int]:
    """Decode altitude from 12-bit altitude code."""
    if alt_code == 0:
        return None

    if q_bit:
        # 25-foot resolution: remove Q-bit and reassemble
        n = ((alt_code >> 1) & 0x7F0) | (alt_code & 0x0F)
        return n * 25 - 1000
    else:
        # Gillham code (Gray code variant) for 100-foot resolution
        # Extract the C and A fields per ICAO Annex 10
        # Bit layout: C1 A1 C2 A2 C4 A4 _ B1 D1 B2 D2 B4 D4
        c1 = (alt_code >> 10) & 1
        a1 = (alt_code >> 9) & 1
        c2 = (alt_code >> 8) & 1
        a2 = (alt_code >> 7) & 1
        c4 = (alt_code >> 6) & 1
        a4 = (alt_code >> 5) & 1
        # bit 4 is the M-bit (skipped)
        b1 = (alt_code >> 3) & 1
        d1 = (alt_code >> 2) & 1
        b2 = (alt_code >> 1) & 1
        d2 = (alt_code >> 0) & 1
        # Note: b4 and d4 not always present in 12-bit code

        # Gray-to-binary conversion for 500ft increments (D1, D2, D4 -> 100ft)
        # and (A1, A2, A4, B1, B2, B4 -> 500ft via Gray code)
        gray_500 = (a1 << 2) | (a2 << 1) | a4
        gray_100 = (c1 << 2) | (c2 << 1) | c4

        # Convert Gray to binary
        n500 = gray_500
        mask = gray_500 >> 1
        while mask:
            n500 ^= mask
            mask >>= 1

        n100 = gray_100
        mask = gray_100 >> 1
        while mask:
            n100 ^= mask
            mask >>= 1

        # 100ft encoding: 1=100, 2=200, 3=300, 4=400, 5=500 (then wraps)
        if n100 == 0 or n100 == 5 or n100 == 6:
            return None  # Invalid
        if n100 == 7:
            n100 = 5

        alt = (n500 * 500 + n100 * 100) - 1300
        return alt if alt > -1300 else None


def decode_velocity(data: bytes) -> tuple:
    """Decode airborne velocity from ADS-B message."""
    subtype = (data[0] >> 3) & 0x07

    if subtype in (1, 2):  # Ground speed
        ew_dir = (data[1] >> 2) & 0x01
        ew_vel = ((data[1] & 0x03) << 8) | data[2]
        ns_dir = (data[3] >> 7) & 0x01
        ns_vel = ((data[3] & 0x7F) << 3) | ((data[4] >> 5) & 0x07)

        # Calculate ground speed and heading
        if ew_vel and ns_vel:
            ew = -ew_vel if ew_dir else ew_vel
            ns = -ns_vel if ns_dir else ns_vel

            speed = (ew**2 + ns**2) ** 0.5
            heading = (np.arctan2(ew, ns) * 180 / np.pi) % 360

            # Vertical rate
            vr_sign = (data[4] >> 3) & 0x01
            vr = ((data[4] & 0x07) << 6) | ((data[5] >> 2) & 0x3F)
            vr = (vr - 1) * 64 if vr else 0
            if vr_sign:
                vr = -vr

            return speed, heading, vr

    elif subtype in (3, 4):  # Airspeed
        heading_available = (data[1] >> 2) & 0x01
        if heading_available:
            heading = ((data[1] & 0x03) << 8 | data[2]) * 360 / 1024
        else:
            heading = None

        airspeed_type = (data[3] >> 7) & 0x01  # 0=IAS, 1=TAS
        airspeed = ((data[3] & 0x7F) << 3) | ((data[4] >> 5) & 0x07)

        # Vertical rate
        vr_sign = (data[4] >> 3) & 0x01
        vr = ((data[4] & 0x07) << 6) | ((data[5] >> 2) & 0x3F)
        vr = (vr - 1) * 64 if vr else 0
        if vr_sign:
            vr = -vr

        return airspeed, heading, vr

    return None, None, None


def decode_adsb_message(msg: bytes, aircraft_db: Dict[str, Aircraft]) -> Optional[Aircraft]:
    """
    Decode an ADS-B message and update aircraft database.

    Args:
        msg: Raw message bytes (7 or 14 bytes)
        aircraft_db: Dictionary of tracked aircraft

    Returns:
        Updated Aircraft object or None if decode failed
    """
    if len(msg) < 7:
        return None

    # Downlink format (first 5 bits)
    df = (msg[0] >> 3) & 0x1F

    # Only process DF17 (ADS-B) and DF18 (TIS-B) for now
    if df not in (17, 18):
        return None

    if len(msg) < 14:
        return None

    # Verify CRC
    crc = crc24(msg[:11])
    msg_crc = (msg[11] << 16) | (msg[12] << 8) | msg[13]
    if crc != msg_crc:
        return None

    # Extract ICAO address (bytes 1-3)
    icao = f"{msg[1]:02X}{msg[2]:02X}{msg[3]:02X}"

    # Get or create aircraft entry
    if icao not in aircraft_db:
        aircraft_db[icao] = Aircraft(icao=icao)

    ac = aircraft_db[icao]
    ac.last_seen = datetime.now()
    ac.message_count += 1

    # Type code (first 5 bits of ME field, byte 4)
    tc = (msg[4] >> 3) & 0x1F

    # Aircraft identification (TC 1-4)
    if 1 <= tc <= 4:
        ac.callsign = decode_callsign(msg[5:11])

    # Surface position (TC 5-8)
    elif 5 <= tc <= 8:
        ac.on_ground = True
        # Position decoding similar to airborne

    # Airborne position with baro altitude (TC 9-18)
    elif 9 <= tc <= 18:
        ac.on_ground = False

        # Altitude
        alt_code = ((msg[5] & 0xFF) << 4) | ((msg[6] >> 4) & 0x0F)
        q_bit = (msg[5] >> 0) & 0x01
        ac.altitude = decode_altitude(alt_code, q_bit)

        # CPR position data
        odd = (msg[6] >> 2) & 0x01
        lat_cpr = ((msg[6] & 0x03) << 15) | (
            (msg[7] & 0xFF) << 7) | ((msg[8] >> 1) & 0x7F)
        lon_cpr = ((msg[8] & 0x01) << 16) | (
            (msg[9] & 0xFF) << 8) | (msg[10] & 0xFF)

        lat_cpr /= 131072.0  # 2^17
        lon_cpr /= 131072.0

        ac.update_position_cpr(lat_cpr, lon_cpr, bool(odd), time.time())

    # Airborne velocity (TC 19)
    elif tc == 19:
        speed, heading, vr = decode_velocity(msg[5:11])
        if speed is not None:
            ac.ground_speed = speed
        if heading is not None:
            ac.heading = heading
        if vr is not None:
            ac.vertical_rate = vr

    # Airborne position with GNSS altitude (TC 20-22)
    elif 20 <= tc <= 22:
        ac.on_ground = False
        # Similar to TC 9-18 but with GNSS altitude

    return ac


def detect_preamble(samples: np.ndarray, threshold: float) -> List[int]:
    """
    Detect ADS-B preambles in sample data.

    ADS-B preamble pattern (8 µs):
    - Pulse at 0 µs
    - Pulse at 1 µs
    - Low at 2-3.5 µs
    - Pulse at 3.5 µs
    - Pulse at 4.5 µs
    - Low at 5-8 µs

    At 2 MHz sample rate: 1 µs = 2 samples
    """
    # Get magnitude
    mag = np.abs(samples)

    # Preamble detection using correlation
    # Pattern: high, high, low, low, low, low, low, high, high, low, low, low, low, low, low, low
    # At 2 samples per microsecond
    preamble_indices = []

    min_samples = 16 + 112 * 2  # Preamble + message

    for i in range(len(mag) - min_samples):
        # Check preamble pattern
        # Pulses at samples 0-1, 2-3, 7-8, 9-10
        # Low at 4-6, 11-15

        high_samples = [0, 1, 2, 3, 7, 8, 9, 10]
        low_samples = [4, 5, 6, 11, 12, 13, 14, 15]

        high_avg = np.mean(mag[i + np.array(high_samples)])
        low_avg = np.mean(mag[i + np.array(low_samples)])

        if high_avg > threshold and high_avg > 2 * low_avg:
            preamble_indices.append(i)
            # Skip ahead to avoid duplicate detections
            i += 16

    return preamble_indices


def demodulate_message(samples: np.ndarray, start_idx: int) -> Optional[bytes]:
    """
    Demodulate PPM encoded ADS-B message.

    Each bit is 1 µs (2 samples at 2 MHz):
    - '1' = high then low
    - '0' = low then high
    """
    mag = np.abs(samples)

    # Skip preamble (16 samples = 8 µs)
    bit_start = start_idx + 16

    # Extended squitter is 112 bits = 14 bytes
    bits = []

    for bit_num in range(112):
        idx = bit_start + bit_num * 2

        if idx + 1 >= len(mag):
            return None

        # Compare first and second half of bit period
        if mag[idx] > mag[idx + 1]:
            bits.append(1)
        else:
            bits.append(0)

    # Convert bits to bytes
    msg_bytes = []
    for i in range(0, 112, 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        msg_bytes.append(byte)

    return bytes(msg_bytes)


class Dump1090Client:
    """Client to receive decoded data from dump1090."""

    def __init__(self, host: str = "localhost", port: int = 30003):
        """
        Connect to dump1090 SBS output.

        Args:
            host: dump1090 host
            port: SBS output port (default 30003)
        """
        self.host = host
        self.port = port
        self.socket = None
        self.running = False
        self.aircraft_db: Dict[str, Aircraft] = {}
        self._thread = None

    def connect(self) -> bool:
        """Connect to dump1090."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(1.0)
            return True
        except Exception as e:
            print(f"Could not connect to dump1090: {e}")
            return False

    def start(self):
        """Start receiving in background thread."""
        self.running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop receiving."""
        self.running = False
        if self.socket:
            self.socket.close()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _receive_loop(self):
        """Background thread to receive SBS messages."""
        buffer = ""

        while self.running:
            try:
                data = self.socket.recv(4096).decode('ascii', errors='ignore')
                if not data:
                    break

                buffer += data

                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    self._parse_sbs_message(line.strip())

            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Receive error: {e}")
                break

    def _parse_sbs_message(self, line: str):
        """Parse SBS format message from dump1090."""
        # SBS format: MSG,type,session,aircraft,icao,flight,date,time,date,time,callsign,alt,speed,heading,lat,lon,vrate,...
        parts = line.split(',')

        if len(parts) < 11 or parts[0] != 'MSG':
            return

        try:
            icao = parts[4].strip()
            if not icao:
                return

            if icao not in self.aircraft_db:
                self.aircraft_db[icao] = Aircraft(icao=icao)

            ac = self.aircraft_db[icao]
            ac.last_seen = datetime.now()
            ac.message_count += 1

            # Parse available fields
            if len(parts) > 10 and parts[10].strip():
                ac.callsign = parts[10].strip()
            if len(parts) > 11 and parts[11].strip():
                ac.altitude = int(parts[11])
            if len(parts) > 12 and parts[12].strip():
                ac.ground_speed = float(parts[12])
            if len(parts) > 13 and parts[13].strip():
                ac.heading = float(parts[13])
            if len(parts) > 14 and parts[14].strip():
                ac.latitude = float(parts[14])
            if len(parts) > 15 and parts[15].strip():
                ac.longitude = float(parts[15])
            if len(parts) > 16 and parts[16].strip():
                ac.vertical_rate = int(parts[16])
            if len(parts) > 17 and parts[17].strip():
                ac.squawk = parts[17].strip()

        except (ValueError, IndexError):
            pass


class ADSBScanner:
    """
    ADS-B aircraft scanner using RTL-SDR.

    Can operate in two modes:
    1. dump1090 mode: Uses dump1090 for decoding (recommended)
    2. Native mode: Python-based decoding (educational)
    """

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        gain: int = DEFAULT_GAIN,
        use_dump1090: bool = True,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.output_dir = output_dir
        self.device_id = device_id
        self.device_index = device_index
        self.gain = gain
        self.use_dump1090 = use_dump1090
        self.sample_rate = ADSB_SAMPLE_RATE

        os.makedirs(output_dir, exist_ok=True)

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="adsb",
            device_id=device_id,
            min_snr_db=0,
        )

        self.sdr = None
        self.aircraft_db: Dict[str, Aircraft] = {}
        self.dump1090_process = None
        self.dump1090_client = None

        # Check available tools
        self.tools = check_tools_installed()

    def start_dump1090(self) -> bool:
        """Start dump1090 in the background."""
        dump1090_cmd = None

        for cmd in ['readsb', 'dump1090-fa', 'dump1090-mutability', 'dump1090']:
            if shutil.which(cmd):
                dump1090_cmd = cmd
                break

        if not dump1090_cmd:
            return False

        try:
            # Build command — readsb needs explicit port flags
            cmd_args = [dump1090_cmd, '--net', '--gain', str(self.gain)]
            if dump1090_cmd == 'readsb':
                cmd_args += ['--device-type', 'rtlsdr', '--net-sbs-port', '30003', '--no-interactive']
            else:
                cmd_args.append('--quiet')

            # Start dump1090/readsb with network output
            self.dump1090_process = subprocess.Popen(
                cmd_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for it to start
            time.sleep(2)

            # Connect client
            self.dump1090_client = Dump1090Client()
            if self.dump1090_client.connect():
                self.dump1090_client.start()
                return True

        except Exception as e:
            print(f"Error starting dump1090: {e}")

        return False

    def stop_dump1090(self):
        """Stop dump1090."""
        if self.dump1090_client:
            self.dump1090_client.stop()

        if self.dump1090_process:
            self.dump1090_process.terminate()
            self.dump1090_process.wait(timeout=5)

    def scan_native(self):
        """Scan using native Python decoding."""
        print("Using native Python ADS-B decoding...")
        print("Note: dump1090 provides better decoding accuracy.\n")

        try:
            self.sdr = RtlSdr(self.device_index)
            self.sdr.sample_rate = self.sample_rate
            self.sdr.center_freq = ADSB_FREQUENCY
            self.sdr.gain = self.gain

            print(f"Tuned to {ADSB_FREQUENCY/1e6:.1f} MHz")
            print(f"Sample rate: {self.sample_rate/1e6:.1f} MHz")
            print(f"Gain: {self.gain} dB\n")

            num_samples = 256 * 1024

            while True:
                # Read samples
                samples = self.sdr.read_samples(num_samples)

                # Calculate threshold
                mag = np.abs(samples)
                threshold = np.mean(mag) + 2 * np.std(mag)

                # Detect preambles
                preambles = detect_preamble(samples, threshold)

                # Decode messages
                for idx in preambles:
                    msg = demodulate_message(samples, idx)
                    if msg:
                        decode_adsb_message(msg, self.aircraft_db)

                # Display
                self._display_aircraft()
                time.sleep(0.5)

        except KeyboardInterrupt:
            print("\n\nStopping scan...")
        finally:
            if self.sdr:
                self.sdr.close()

    def scan_dump1090(self):
        """Scan using dump1090 for decoding."""
        print("Starting dump1090...")

        if not self.start_dump1090():
            print("Failed to start dump1090. Falling back to native decoding.")
            self.scan_native()
            return

        print("Connected to dump1090. Receiving aircraft data...\n")

        self._logged_aircraft = {}  # icao -> last logged message count

        try:
            while True:
                # Get aircraft from dump1090 client
                self.aircraft_db = self.dump1090_client.aircraft_db
                self._log_aircraft_updates()
                self._display_aircraft()
                time.sleep(1.0)

        except KeyboardInterrupt:
            print("\n\nStopping scan...")
        finally:
            self.stop_dump1090()

    def _log_aircraft_updates(self):
        """Log new/updated aircraft positions to the detection log and TAK."""
        import json
        for icao, ac in list(self.aircraft_db.items()):
            if ac.latitude is None or ac.longitude is None:
                continue
            last_count = self._logged_aircraft.get(icao, 0)
            if ac.message_count > last_count:
                meta = {
                    "icao": ac.icao,
                    "callsign": ac.callsign or "",
                    "altitude": ac.altitude,
                    "speed": ac.ground_speed,
                    "heading": ac.heading,
                    "squawk": ac.squawk or "",
                }
                self.logger.log_signal(
                    signal_type="ADS-B",
                    frequency_hz=ADSB_FREQUENCY,
                    power_db=0,
                    noise_floor_db=0,
                    channel=ac.icao,
                    latitude=ac.latitude,
                    longitude=ac.longitude,
                    metadata=json.dumps(meta),
                )
                self._logged_aircraft[icao] = ac.message_count

    def _display_aircraft(self):
        """Display tracked aircraft."""
        # Clear screen
        print("\033[H\033[J", end="")

        print("=" * 100)
        print("                           ADS-B Aircraft Tracker")
        print("=" * 100)

        # Remove stale aircraft (not seen in 60 seconds)
        now = datetime.now()
        stale_icao = [
            icao for icao, ac in list(self.aircraft_db.items())
            if (now - ac.last_seen).total_seconds() > 60
        ]
        for icao in stale_icao:
            del self.aircraft_db[icao]

        if not self.aircraft_db:
            print("\nNo aircraft detected yet. Waiting for signals...")
            print("\nMake sure you have a clear view of the sky.")
            print("Aircraft typically need to be within ~100 miles.")
        else:
            # Sort by altitude (highest first)
            sorted_aircraft = sorted(
                list(self.aircraft_db.values()),
                key=lambda x: x.altitude or 0,
                reverse=True
            )

            print(f"\n{'ICAO':<8} | {'Callsign':<10} | {'Alt(ft)':>8} | {'Spd(kt)':>7} | {'Hdg':>5} | {'VRate':>6} | {'Lat':>9} | {'Lon':>10} | {'Msgs':>5}")
            print("-" * 100)

            for ac in sorted_aircraft[:20]:  # Top 20
                callsign = ac.callsign or "--------"
                alt = f"{ac.altitude:>8}" if ac.altitude else "    ----"
                speed = f"{ac.ground_speed:>7.0f}" if ac.ground_speed else "   ----"
                hdg = f"{ac.heading:>5.0f}" if ac.heading else " ----"
                vrate = f"{ac.vertical_rate:>+6}" if ac.vertical_rate else "  ----"
                lat = f"{ac.latitude:>9.4f}" if ac.latitude else "   ------"
                lon = f"{ac.longitude:>10.4f}" if ac.longitude else "    ------"

                # Age indicator
                age = (now - ac.last_seen).total_seconds()
                if age < 5:
                    status = "🟢"
                elif age < 15:
                    status = "🟡"
                else:
                    status = "🔴"

                print(
                    f"{status} {ac.icao:<6} | {callsign:<10} | {alt} | {speed} | {hdg} | {vrate} | {lat} | {lon} | {ac.message_count:>5}")

        print("-" * 100)
        print(f"Aircraft tracked: {len(self.aircraft_db)}")
        print(f"Updated: {now.strftime('%H:%M:%S')}")
        print("\nPress Ctrl+C to exit")

    def scan(self):
        """Run the ADS-B scanner."""
        print("=" * 60)
        print("         ADS-B Aircraft Scanner")
        print("=" * 60)
        print(f"\nFrequency: {ADSB_FREQUENCY/1e6:.1f} MHz")
        print(f"Device: {self.device_id}")
        print(f"Gain: {self.gain} dB")

        print("\nChecking ADS-B tools:")
        for tool, available in self.tools.items():
            status = "✓ installed" if available else "✗ not found"
            print(f"  {tool}: {status}")

        print("-" * 60)

        # Start logging
        output_file = self.logger.start()
        print(f"Logging to: {output_file}")

        try:
            if self.use_dump1090 and self.tools.get('dump1090'):
                self.scan_dump1090()
            else:
                if self.use_dump1090:
                    print("\ndump1090/readsb not found. Install with:")
                    print("  macOS: brew install dump1090-mutability")
                    print("  Linux: apt install readsb")
                    print("\nUsing native Python decoder instead.\n")
                self.scan_native()

        finally:
            # Log final aircraft state
            for ac in list(self.aircraft_db.values()):
                self.logger.log_signal(
                    signal_type="ADS-B",
                    frequency_hz=ADSB_FREQUENCY,
                    power_db=0,
                    noise_floor_db=0,
                    channel=ac.icao,
                    audio_file=f"callsign:{ac.callsign or 'N/A'},alt:{ac.altitude or 0},lat:{ac.latitude or 0},lon:{ac.longitude or 0}",
                )

            total = self.logger.stop()
            print(f"\nTotal aircraft logged: {total}")


# Allow running directly for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ADS-B Aircraft Scanner")
    parser.add_argument("--gain", "-g", type=int, default=DEFAULT_GAIN,
                        help="RF gain")
    parser.add_argument("--native", action="store_true",
                        help="Use native Python decoder instead of dump1090")

    args = parser.parse_args()

    scanner = ADSBScanner(
        gain=args.gain,
        use_dump1090=not args.native,
    )
    scanner.scan()

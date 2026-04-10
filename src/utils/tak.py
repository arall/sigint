#!/usr/bin/env python3
"""
TAK Server integration — stream CoT (Cursor on Target) events over SSL.

Handles certificate enrollment and persistent streaming connection to TAK Server.
Each signal detection is sent as a CoT event, appearing as a marker on ATAK maps.
"""

import json
import os
import socket
import ssl
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


# CoT event type mapping per signal type
COT_TYPES = {
    "PMR446": "a-n-G-E-S",      # neutral ground electronic signals
    "keyfob": "a-n-G-E-S",      # neutral ground electronic signals
    "tpms": "a-n-G-E-V",        # neutral ground vehicle
    "gsm": "a-n-G-E-S",         # neutral ground electronic signals
    "lte": "a-n-G-E-S",         # neutral ground electronic signals
    "adsb": "a-n-A-C-F",        # neutral airborne civilian fixed-wing
    "ADS-B": "a-n-A-C-F",       # neutral airborne civilian fixed-wing
    "RemoteID": "a-n-A-C-F",    # neutral airborne civilian (drone)
    "RemoteID-operator": "a-f-G-E-S",  # friendly ground (drone operator)
    "DroneVideo": "a-n-A-C-F",      # neutral airborne (drone video link)
    "ais": "a-n-S-X",           # neutral surface vessel
    "pocsag": "a-n-G-E-S",      # neutral ground electronic signals
    "wifi": "a-n-G-E-S",        # neutral ground electronic signals
    "bluetooth": "a-n-G-E-S",   # neutral ground electronic signals
}

# How long a CoT marker stays on the map before going stale (seconds)
STALE_SECONDS = {
    "keyfob": 60,
    "tpms": 60,
    "adsb": 60,
    "ais": 120,
    "RemoteID": 30,
    "RemoteID-operator": 30,
    "DroneVideo": 60,
    "PMR446": 300,
    "gsm": 300,
    "lte": 300,
    "wifi": 120,
    "bluetooth": 120,
    "pocsag": 120,
}


def parse_tak_config(config_dir: str) -> dict:
    """Parse TAK connection info from enrollment data package config.pref."""
    config_pref = os.path.join(config_dir, "config.pref")
    if not os.path.exists(config_pref):
        raise FileNotFoundError(f"TAK config not found: {config_pref}")

    tree = ET.parse(config_pref)
    root = tree.getroot()

    config = {}
    for pref in root.findall("preference"):
        name = pref.get("name")
        if name == "cot_streams":
            for entry in pref.findall("entry"):
                key = entry.get("key")
                val = entry.text
                if key == "connectString0" and val:
                    parts = val.split(":")
                    config["host"] = parts[0]
                    config["port"] = int(parts[1])
                    config["protocol"] = parts[2] if len(parts) > 2 else "ssl"
                elif key == "caPassword0":
                    config["ca_password"] = val
        elif name == "com.atakmap.app_preferences":
            for entry in pref.findall("entry"):
                key = entry.get("key")
                val = entry.text
                if key == "apiCertEnrollmentPort":
                    config["enrollment_port"] = int(val)

    return config


def extract_ca_pem(p12_path: str, password: str, output_path: str) -> str:
    """Extract CA certificate from PKCS#12 to PEM format using openssl."""
    if os.path.exists(output_path):
        return output_path

    # Try standard openssl first, then with -legacy for OpenSSL 3.x
    for extra_args in [[], ["-legacy"]]:
        result = subprocess.run(
            ["openssl", "pkcs12", "-in", p12_path, "-out", output_path,
             "-nokeys", "-passin", f"pass:{password}"] + extra_args,
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return output_path

    raise RuntimeError(f"Failed to extract CA cert: {result.stderr}")


def enroll_client_cert(
    host: str,
    port: int,
    ca_pem: str,
    username: str,
    password: str,
    cert_dir: str,
    uid: str,
) -> tuple:
    """Enroll for a client certificate from TAK Server.

    Posts a CSR to the enrollment API with Basic auth.
    Returns (cert_pem_path, key_pem_path).
    """
    import base64
    import urllib.request

    cert_path = os.path.join(cert_dir, "client.pem")
    key_path = os.path.join(cert_dir, "client.key")

    if os.path.exists(cert_path) and os.path.exists(key_path):
        print(f"[TAK] Client cert already exists: {cert_path}")
        return cert_path, key_path

    csr_path = os.path.join(cert_dir, "client.csr")

    # Generate key pair + CSR
    subprocess.run(
        ["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
         "-keyout", key_path, "-out", csr_path, "-subj", f"/CN={uid}"],
        capture_output=True, check=True,
    )
    os.chmod(key_path, 0o600)

    with open(csr_path) as f:
        csr = f.read()

    # POST CSR to enrollment endpoint
    # Enrollment API uses the server's web cert (e.g., Let's Encrypt), not the TAK CA.
    # Use default system trust store; fall back to unverified if cert is expired/invalid.
    url = f"https://{host}:{port}/Marti/api/tls/signClient/v2?clientUID={uid}&version=3"
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()

    ctx = ssl.create_default_context()
    try:
        _test_sock = socket.create_connection((host, port), timeout=5)
        _test_ssl = ctx.wrap_socket(_test_sock, server_hostname=host)
        _test_ssl.close()
    except ssl.SSLError:
        print("[TAK] Server cert verification failed (expired?), proceeding unverified")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, data=csr.encode(), method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/pkcs10")

    try:
        response = urllib.request.urlopen(req, context=ctx)
    except Exception as e:
        # Clean up partial files on failure
        for f in (key_path, csr_path):
            if os.path.exists(f):
                os.remove(f)
        raise RuntimeError(f"Enrollment failed: {e}")

    # Response is PKCS#12 with the signed cert
    p12_tmp = os.path.join(cert_dir, "client.p12")
    with open(p12_tmp, "wb") as f:
        f.write(response.read())

    # Extract cert from returned p12 (try empty password, then atakatak)
    extracted = False
    for pwd in ["", "atakatak"]:
        for extra in [[], ["-legacy"]]:
            result = subprocess.run(
                ["openssl", "pkcs12", "-in", p12_tmp, "-out", cert_path,
                 "-nokeys", "-passin", f"pass:{pwd}"] + extra,
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                extracted = True
                break
        if extracted:
            break

    # Clean up temp files
    for f in (csr_path, p12_tmp):
        if os.path.exists(f):
            os.remove(f)

    if not extracted:
        raise RuntimeError("Failed to extract client cert from enrollment response")

    print(f"[TAK] Client cert enrolled: {cert_path}")
    return cert_path, key_path


def detection_to_cot(detection, callsign: str = "SDR") -> Optional[str]:
    """Convert a SignalDetection to CoT XML string.

    Returns None if the detection has no GPS coordinates.
    """
    lat = detection.latitude
    lon = detection.longitude
    if lat is None or lon is None:
        return None

    now = datetime.now(timezone.utc)
    stale_s = STALE_SECONDS.get(detection.signal_type) or STALE_SECONDS.get(detection.signal_type.lower(), 120)
    stale = now + timedelta(seconds=stale_s)
    time_fmt = "%Y-%m-%dT%H:%M:%SZ"

    cot_type = COT_TYPES.get(detection.signal_type) or COT_TYPES.get(detection.signal_type.lower(), "a-u-G")

    # UID groups detections by signal source
    freq_mhz = detection.frequency_hz / 1e6
    if detection.channel:
        uid = f"sdr-{detection.signal_type}-{detection.channel}"
    else:
        uid = f"sdr-{detection.signal_type}-{freq_mhz:.3f}"

    # Parse metadata for rich display
    meta = {}
    if detection.metadata:
        try:
            meta = json.loads(detection.metadata)
        except (json.JSONDecodeError, TypeError):
            pass

    # Contact callsign shown on ATAK map — use target name when available
    if detection.signal_type == "AIS":
        name = meta.get("name", "").strip()
        mmsi = meta.get("mmsi", detection.channel or "")
        contact = name if name else f"MMSI {mmsi}"
    elif detection.signal_type in ("adsb", "ADS-B"):
        callsign = meta.get("callsign", "").strip()
        contact = callsign if callsign else f"ICAO {detection.channel or freq_mhz:.3f}"
    elif detection.signal_type == "RemoteID":
        ua_type = meta.get("ua_type", "Drone")
        drone_id = meta.get("drone_id", detection.channel or "?")
        alt = meta.get("geodetic_alt_m")
        alt_str = f" {alt:.0f}m" if alt is not None else ""
        contact = f"{drone_id} {ua_type}{alt_str}"
    elif detection.signal_type == "RemoteID-operator":
        drone_id = meta.get("drone_id", detection.channel or "?")
        op_id = meta.get("operator_id", "")
        contact = f"Operator {op_id or drone_id}"
    else:
        contact = detection.signal_type
        if detection.channel:
            contact += f" {detection.channel}"
        contact += f" {freq_mhz:.3f}MHz"

    # Remarks with signal metadata
    remarks = f"SNR: {detection.snr_db:.1f} dB | Power: {detection.power_db:.1f} dBFS"
    for k, v in meta.items():
        if k not in ("transcription",):
            remarks += f" | {k}: {v}"

    return (
        f'<event version="2.0" uid="{uid}" type="{cot_type}" '
        f'time="{now.strftime(time_fmt)}" start="{now.strftime(time_fmt)}" '
        f'stale="{stale.strftime(time_fmt)}" how="m-g">'
        f'<point lat="{lat}" lon="{lon}" hae="0" ce="9999999" le="9999999"/>'
        f'<detail>'
        f'<contact callsign="{contact}"/>'
        f'<remarks>{remarks}</remarks>'
        f'</detail>'
        f'</event>'
    )


def trail_to_cot(device_uid: str, positions: list,
                 signal_type: str = "", stale_s: int = 300) -> Optional[str]:
    """Generate a CoT drawing shape (polyline) for a device movement trail.

    Args:
        device_uid: Unique device identifier (used as CoT UID)
        positions: List of (lat, lon, timestamp_str) tuples
        signal_type: Signal type for color coding
        stale_s: How long the trail stays on the map

    Returns:
        CoT XML string, or None if fewer than 2 positions
    """
    if len(positions) < 2:
        return None

    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=stale_s)
    time_fmt = "%Y-%m-%dT%H:%M:%SZ"

    uid = f"sdr-trail-{device_uid}"

    # Use centroid as the point
    avg_lat = sum(p[0] for p in positions) / len(positions)
    avg_lon = sum(p[1] for p in positions) / len(positions)

    # Build link line for ATAK drawing
    # ATAK uses <link> elements inside <detail> for polyline vertices
    links = ""
    for lat, lon, _ in positions:
        links += f'<link point="{lat},{lon},0"/>'

    # Color: red for voice, cyan for BLE, blue for WiFi, yellow for RF
    color_map = {
        "BLE-Adv": "ffff8800",   # orange
        "WiFi-Probe": "ff0088ff", # blue
        "tpms": "ff00ffff",      # cyan
        "keyfob": "ff00ff00",    # green
        "RemoteID": "ffff0000",  # red
    }
    color = color_map.get(signal_type, "ffffff00")  # yellow default

    return (
        f'<event version="2.0" uid="{uid}" type="u-d-f" '
        f'time="{now.strftime(time_fmt)}" start="{now.strftime(time_fmt)}" '
        f'stale="{stale.strftime(time_fmt)}" how="m-g">'
        f'<point lat="{avg_lat}" lon="{avg_lon}" hae="0" ce="9999999" le="9999999"/>'
        f'<detail>'
        f'<contact callsign="Trail: {device_uid[:20]}"/>'
        f'<shape><polyline closed="false">{links}</polyline></shape>'
        f'<strokeColor value="{color}"/>'
        f'<strokeWeight value="3"/>'
        f'<remarks>Trail: {len(positions)} points, {signal_type}</remarks>'
        f'</detail>'
        f'</event>'
    )


class TrailTracker:
    """Tracks device positions over time for movement trail visualization.

    Accumulates per-device position history from SignalDetections.
    Generates CoT trail polylines for ATAK when enough movement is detected.
    """

    MIN_POSITIONS = 3       # Minimum positions before generating a trail
    MIN_MOVEMENT_M = 10.0   # Minimum movement in meters to create trail
    MAX_POSITIONS = 100     # Ring buffer size per device

    def __init__(self, tak_client=None):
        self.tak_client = tak_client
        # device_uid → [(lat, lon, timestamp_str), ...]
        self._trails = {}

    def _device_uid(self, detection) -> Optional[str]:
        """Extract a stable device identifier from a detection."""
        sig = detection.signal_type
        try:
            meta = json.loads(detection.metadata) if detection.metadata else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}

        if sig == "BLE-Adv":
            return meta.get("persona_id") or detection.channel
        elif sig == "WiFi-Probe":
            return meta.get("persona_id") or detection.device_id
        elif sig == "tpms":
            return meta.get("sensor_id")
        elif sig == "RemoteID":
            return meta.get("serial_number")
        elif sig == "keyfob":
            return meta.get("data_hex")
        elif sig in ("ADS-B", "adsb"):
            return meta.get("icao") or detection.channel
        elif sig == "AIS":
            return meta.get("mmsi") or detection.channel
        return None

    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2):
        """Approximate distance in meters between two lat/lon points."""
        import math
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon/2)**2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def on_detection(self, detection):
        """Process a detection and update trails. Send CoT if trail is ready."""
        lat = detection.latitude
        lon = detection.longitude
        if lat is None or lon is None or (lat == 0 and lon == 0):
            return

        uid = self._device_uid(detection)
        if not uid:
            return

        # Add to trail
        if uid not in self._trails:
            self._trails[uid] = []
        trail = self._trails[uid]

        # Check for duplicate position (within 1m)
        if trail:
            last_lat, last_lon, _ = trail[-1]
            if self._haversine_m(lat, lon, last_lat, last_lon) < 1.0:
                return  # Same spot, skip

        trail.append((lat, lon, detection.timestamp))

        # Ring buffer
        if len(trail) > self.MAX_POSITIONS:
            self._trails[uid] = trail[-self.MAX_POSITIONS:]
            trail = self._trails[uid]

        # Check if trail meets criteria
        if len(trail) < self.MIN_POSITIONS:
            return

        # Total movement
        total_m = sum(
            self._haversine_m(trail[i][0], trail[i][1], trail[i+1][0], trail[i+1][1])
            for i in range(len(trail) - 1)
        )

        if total_m < self.MIN_MOVEMENT_M:
            return

        # Generate and send trail CoT
        if self.tak_client and self.tak_client.connected:
            cot = trail_to_cot(uid, trail, detection.signal_type)
            if cot:
                self.tak_client._send(cot)

    @property
    def active_trails(self) -> int:
        """Number of devices with active trails."""
        return sum(1 for t in self._trails.values() if len(t) >= self.MIN_POSITIONS)

    @property
    def trail_devices(self) -> list:
        """List of device UIDs with active trails."""
        return [uid for uid, t in self._trails.items() if len(t) >= self.MIN_POSITIONS]


def delete_cot(uid: str) -> str:
    """Build a CoT delete event for the given UID."""
    now = datetime.now(timezone.utc)
    time_fmt = "%Y-%m-%dT%H:%M:%SZ"
    stale = now + timedelta(seconds=120)
    return (
        f'<event version="2.0" uid="{uid}" type="t-x-d-d" '
        f'time="{now.strftime(time_fmt)}" start="{now.strftime(time_fmt)}" '
        f'stale="{stale.strftime(time_fmt)}" how="m-g">'
        f'<point lat="0" lon="0" hae="0" ce="9999999" le="9999999"/>'
        f'<detail><link uid="{uid}" relation="none" type="none"/></detail>'
        f'</event>'
    )


class TAKClient:
    """Streaming CoT client for TAK Server over SSL/TLS.

    Thread-safe. Automatically reconnects on connection loss.
    """

    RECONNECT_INTERVAL = 10  # seconds between reconnect attempts

    def __init__(
        self,
        host: str,
        port: int,
        certfile: str,
        keyfile: str,
        cafile: str,
        callsign: str = "SDR",
    ):
        self.host = host
        self.port = port
        self.certfile = certfile
        self.keyfile = keyfile
        self.cafile = cafile
        self.callsign = callsign

        self._sock = None
        self._ssl_sock = None
        self._lock = threading.Lock()
        self._connected = False
        self._closing = False

    def connect(self):
        """Establish SSL connection to TAK Server."""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)
        ctx.load_verify_locations(cafile=self.cafile)
        ctx.check_hostname = False  # TAK Server certs often use internal names
        ctx.verify_mode = ssl.CERT_REQUIRED

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        ssl_sock = ctx.wrap_socket(sock, server_hostname=self.host)
        ssl_sock.connect((self.host, self.port))

        with self._lock:
            self._sock = sock
            self._ssl_sock = ssl_sock
            self._connected = True

        print(f"[TAK] Connected to {self.host}:{self.port}")

    def send_detection(self, detection) -> bool:
        """Convert a SignalDetection to CoT and send it."""
        cot = detection_to_cot(detection, self.callsign)
        if cot is None:
            return False
        return self._send(cot)

    def _send(self, cot_xml: str) -> bool:
        """Send CoT XML. Returns False on failure (will reconnect on next call)."""
        with self._lock:
            if not self._connected:
                return False
            try:
                self._ssl_sock.sendall((cot_xml + "\n").encode("utf-8"))
                return True
            except (socket.error, ssl.SSLError, OSError) as e:
                print(f"[TAK] Send failed: {e}")
                self._connected = False
                # Attempt reconnect in background
                threading.Thread(
                    target=self._reconnect_loop, daemon=True
                ).start()
                return False

    def _reconnect_loop(self):
        """Try to reconnect until successful or client is closed."""
        while not self._closing and not self._connected:
            time.sleep(self.RECONNECT_INTERVAL)
            if self._closing:
                break
            try:
                self._close_sockets()
                self.connect()
                print("[TAK] Reconnected")
                return
            except Exception as e:
                print(f"[TAK] Reconnect failed: {e}")

    def _close_sockets(self):
        """Close underlying sockets."""
        for s in (self._ssl_sock, self._sock):
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        self._ssl_sock = None
        self._sock = None

    def close(self):
        """Close the connection."""
        self._closing = True
        with self._lock:
            self._connected = False
        self._close_sockets()

    @property
    def connected(self) -> bool:
        return self._connected


def _extract_p12_to_pem(p12_path: str, cert_out: str, key_out: str, password: str = "atakatak") -> bool:
    """Extract cert and key from a PKCS#12 file to PEM files."""
    if os.path.exists(cert_out) and os.path.exists(key_out):
        return True

    for extra in [[], ["-legacy"]]:
        r1 = subprocess.run(
            ["openssl", "pkcs12", "-in", p12_path, "-nokeys",
             "-passin", f"pass:{password}", "-out", cert_out] + extra,
            capture_output=True, text=True,
        )
        r2 = subprocess.run(
            ["openssl", "pkcs12", "-in", p12_path, "-nocerts", "-nodes",
             "-passin", f"pass:{password}", "-out", key_out] + extra,
            capture_output=True, text=True,
        )
        if r1.returncode == 0 and r2.returncode == 0:
            os.chmod(key_out, 0o600)
            return True

    return False


def setup_tak(config_dir: str, callsign: str = "SDR") -> Optional[TAKClient]:
    """Set up TAK client from certificate directory.

    Looks for client cert/key (PEM or P12) and CA cert, then connects.
    Falls back to config.pref for host/port if available, otherwise uses
    default TAK Server port 8089 with host from CA cert.
    Returns None if certs are missing.
    """
    # Parse config.pref if available, otherwise use defaults
    config_pref = os.path.join(config_dir, "config.pref")
    if os.path.exists(config_pref):
        config = parse_tak_config(config_dir)
        host = config["host"]
        port = config["port"]
        ca_password = config.get("ca_password", "atakatak")
    else:
        host = os.environ.get("TAK_HOST")
        port = int(os.environ.get("TAK_PORT", "8089"))
        ca_password = os.environ.get("TAK_CA_PASSWORD", "atakatak")
        if not host:
            print("[TAK] No config.pref found and TAK_HOST not set in .env")
            return None

    # Find or extract CA cert
    ca_pem = os.path.join(config_dir, "ca.pem")
    ca_trusted = os.path.join(config_dir, "ca-trusted.pem")
    ca_p12 = os.path.join(config_dir, "caCert.p12")

    if not os.path.exists(ca_pem):
        if os.path.exists(ca_trusted):
            ca_pem = ca_trusted
        elif os.path.exists(ca_p12):
            extract_ca_pem(ca_p12, ca_password, ca_pem)
        else:
            print("[TAK] No CA cert found in", config_dir)
            return None

    # Find or extract client cert + key
    cert_path = os.path.join(config_dir, "client.pem")
    key_path = os.path.join(config_dir, "client.key")

    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        # Try to extract from any .p12 that looks like a client cert
        import glob
        p12_files = glob.glob(os.path.join(config_dir, "*.p12"))
        # Exclude caCert.p12
        p12_files = [f for f in p12_files if "caCert" not in os.path.basename(f)]
        if p12_files:
            p12 = p12_files[0]
            print(f"[TAK] Extracting client cert from {os.path.basename(p12)}")
            if not _extract_p12_to_pem(p12, cert_path, key_path, ca_password):
                print("[TAK] Failed to extract client cert from p12")
                return None
        else:
            print("[TAK] No client cert found. Place a .p12 or client.pem + client.key in", config_dir)
            return None

    client = TAKClient(
        host=host,
        port=port,
        certfile=cert_path,
        keyfile=key_path,
        cafile=ca_pem,
        callsign=callsign,
    )

    try:
        client.connect()
    except Exception as e:
        print(f"[TAK] Connection failed: {e}")
        print("[TAK] Detections will be logged to CSV only.")
        return None

    return client

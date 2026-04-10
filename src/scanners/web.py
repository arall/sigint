"""
Standalone web UI for the SDR server dashboard.

Reads detection data from CSV files in the output directory and serves
a live dashboard via HTTP. Runs independently of the SDR server — works
while captures are running or for reviewing historical data.

Usage:
    python3 sdr.py web                    # serve output/ on :8080
    python3 sdr.py web -p 9090            # custom port
    python3 sdr.py web -d /path/to/output # custom output directory

Routes:
    GET /                  — HTML dashboard (tabs: overview, detections, activity)
    GET /api/state         — JSON dashboard summary
    GET /api/events        — SSE live updates (state JSON every 2s)
    GET /api/detections    — Individual detection list (newest first, filterable)
    GET /api/activity      — Per-minute detection counts
    GET /audio/<filename>  — Serve recorded WAV files
"""

import csv
import json
import os
import re
import signal
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')
_SAFE_FILENAME_RE = re.compile(r'^[a-zA-Z0-9_\-\.]+\.wav$')


def _get_system_stats():
    """Read CPU, memory, and disk stats from /proc and os (Linux)."""
    stats = {}
    try:
        # CPU usage from /proc/stat (compute between two reads)
        # Use load average instead — instantaneous and no state needed
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        stats["load"] = round(load1, 2)
        stats["cpu_pct"] = round(load1 / cpu_count * 100, 1)

        # Memory from /proc/meminfo
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(':')] = int(parts[1])
        total_kb = meminfo.get('MemTotal', 0)
        avail_kb = meminfo.get('MemAvailable', 0)
        used_kb = total_kb - avail_kb
        stats["mem_total_mb"] = round(total_kb / 1024)
        stats["mem_used_mb"] = round(used_kb / 1024)
        stats["mem_pct"] = round(used_kb / total_kb * 100, 1) if total_kb else 0

        # CPU temperature (Raspberry Pi)
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                stats["cpu_temp"] = round(int(f.read().strip()) / 1000, 1)
        except (FileNotFoundError, ValueError):
            pass

        # Disk usage for the partition containing the output dir
        st = os.statvfs('/')
        disk_total = st.f_blocks * st.f_frsize
        disk_free = st.f_bavail * st.f_frsize
        disk_used = disk_total - disk_free
        stats["disk_total_gb"] = round(disk_total / (1024**3), 1)
        stats["disk_used_gb"] = round(disk_used / (1024**3), 1)
        stats["disk_pct"] = round(disk_used / disk_total * 100, 1) if disk_total else 0

    except Exception:
        pass
    return stats


# ---------------------------------------------------------------------------
# Persona loader — reads persona JSON databases from the output directory
# ---------------------------------------------------------------------------

def _load_personas(output_dir, active_sigs=None):
    """Load and merge BLE + WiFi persona databases into a unified list.

    Args:
        output_dir: Path to the output directory containing persona JSON files.
        active_sigs: Optional dict of {dev_sig: {"rssi": float, "apple_device": str}}
                     from recent detections, used to mark active devices.
    """
    active_sigs = active_sigs or {}
    personas = []

    for filename, transport in [
        ("personas_bt.json", "BLE"),
        ("personas.json", "WiFi"),
    ]:
        path = os.path.join(output_dir, filename)
        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue

        for key, p in data.get("personas", {}).items():
            macs = p.get("macs_seen", [])
            names = p.get("ssids", [])
            dev_sig = p.get("dev_sig", key.split(":")[0])
            manufacturer = p.get("manufacturer") or ""
            randomized = p.get("randomized", False)

            # Active state from recent detections
            active_info = active_sigs.get(dev_sig, {})
            apple_device = active_info.get("apple_device", "")

            # Build best human-readable label
            label = ""
            if names:
                label = ", ".join(names[:3])
            elif apple_device:
                label = apple_device
            elif manufacturer:
                label = manufacturer
            elif macs and not randomized:
                label = macs[0]
            else:
                # Anonymous device — show short sig hash
                label = dev_sig[:8] if dev_sig else ""

            personas.append({
                "transport": transport,
                "dev_sig": dev_sig,
                "label": label,
                "manufacturer": manufacturer,
                "apple_device": apple_device,
                "names": names,
                "macs": macs,
                "mac_count": len(macs),
                "randomized": randomized,
                "sessions": p.get("sessions", 0),
                "total_probes": p.get("total_probes", 0),
                "first_session": p.get("first_session", ""),
                "last_session": p.get("last_session", ""),
                "active": bool(active_info),
                "last_rssi": active_info.get("rssi"),
            })

    # Sort: active first, then by last_session, then by probes
    personas.sort(key=lambda p: (
        p["active"],
        p["last_session"],
        p["total_probes"],
    ), reverse=True)
    return personas


# ---------------------------------------------------------------------------
# CSV tailer — watches the output directory for the latest CSV and tails it
# ---------------------------------------------------------------------------

class CSVTailer:
    """Watches the output directory, tails the latest CSV, builds live state."""

    def __init__(self, output_dir):
        self.output_dir = output_dir
        self._lock = threading.Lock()
        self._stop = threading.Event()

        # State
        self._detections = deque(maxlen=50000)
        self._type_counts = Counter()
        self._type_last_seen = {}
        self._type_last_snr = {}
        self._type_last_detail = {}
        self._type_uniques = {}
        self._recent_events = deque(maxlen=20)
        self._activity_minutes = {}
        self._csv_name = ""
        self._start_time = time.time()

        # File tracking
        self._loaded_csvs = set()   # fully-read CSV paths
        self._tailing_csv = None    # currently tailing (latest) CSV path
        self._file_handle = None
        self._file_pos = 0

    def start(self):
        """Start background thread that tails CSV files."""
        t = threading.Thread(target=self._run, daemon=True, name="csv-tailer")
        t.start()
        return t

    def stop(self):
        self._stop.set()
        try:
            if self._file_handle:
                self._file_handle.close()
        except Exception:
            pass

    def _find_all_csvs(self):
        """Find all CSV files in output_dir, sorted by mtime."""
        try:
            csvs = [
                os.path.join(self.output_dir, f)
                for f in os.listdir(self.output_dir)
                if f.endswith('.csv')
            ]
            return sorted(csvs, key=os.path.getmtime)
        except OSError:
            return []

    def _read_full_csv(self, path):
        """Read all rows from a CSV file."""
        try:
            with open(path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    self._process_row(row)
        except Exception:
            pass

    def _run(self):
        """Background loop: read all CSVs, tail the latest for new rows."""
        while not self._stop.is_set():
            all_csvs = self._find_all_csvs()

            # Read any new CSV files we haven't seen yet
            for csv_path in all_csvs:
                if csv_path in self._loaded_csvs:
                    continue
                # If we're already tailing a file, close it
                if self._file_handle:
                    self._file_handle.close()
                    self._file_handle = None

                self._read_full_csv(csv_path)
                self._loaded_csvs.add(csv_path)
                self._csv_name = os.path.basename(csv_path)

            # Tail the latest CSV for new rows
            latest = all_csvs[-1] if all_csvs else None
            if latest:
                if self._tailing_csv != latest or self._file_handle is None:
                    # (Re)open the file for tailing
                    if self._file_handle:
                        self._file_handle.close()
                    self._tailing_csv = latest
                    self._file_handle = open(latest, 'r', newline='')
                    self._file_handle.seek(0, 2)  # seek to end
                    self._file_pos = self._file_handle.tell()

                # Check for new lines
                self._file_handle.seek(self._file_pos)
                for line in self._file_handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        import io
                        rdr = csv.DictReader(
                            io.StringIO(line),
                            fieldnames=[
                                "timestamp", "signal_type", "frequency_hz",
                                "power_db", "noise_floor_db", "snr_db",
                                "channel", "latitude", "longitude",
                                "device_id", "audio_file", "metadata",
                            ],
                        )
                        row = next(rdr)
                        if row.get("timestamp") == "timestamp":
                            continue
                        self._process_row(row)
                    except Exception:
                        pass
                self._file_pos = self._file_handle.tell()

            self._stop.wait(1.0)

    def _process_row(self, row):
        """Process a single CSV row into internal state."""
        sig = row.get("signal_type", "")
        if not sig:
            return

        try:
            snr = float(row.get("snr_db", 0))
        except (ValueError, TypeError):
            snr = 0
        try:
            freq = float(row.get("frequency_hz", 0))
        except (ValueError, TypeError):
            freq = 0
        try:
            meta = json.loads(row.get("metadata", "")) if row.get("metadata") else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}

        ts = row.get("timestamp", "")
        ch = row.get("channel", "")
        audio_file = row.get("audio_file", "") or None
        detail = _extract_detail(sig, ch, meta)
        transcript = meta.get("transcript")

        with self._lock:
            self._type_counts[sig] += 1

            ts_short = ""
            if "T" in ts:
                ts_short = ts.split("T")[1].split(".")[0]
            self._type_last_seen[sig] = ts_short

            if snr > 0:
                self._type_last_snr[sig] = snr
            if detail:
                self._type_last_detail[sig] = detail

            # Track unique IDs
            uid = _extract_uid(sig, row, meta)
            if uid:
                if sig not in self._type_uniques:
                    self._type_uniques[sig] = set()
                self._type_uniques[sig].add(uid)

            # Detection buffer
            self._detections.append({
                "timestamp": ts,
                "signal_type": sig,
                "frequency_mhz": round(freq / 1e6, 4) if freq else 0,
                "channel": ch,
                "snr_db": round(snr, 1) if snr > 0 else None,
                "audio_file": audio_file if audio_file else None,
                "detail": detail,
                "transcript": transcript,
                "dev_sig": meta.get("dev_sig", ""),
                "apple_device": meta.get("apple_device", ""),
            })

            # Recent events feed
            freq_mhz = freq / 1e6 if freq else 0
            line = (
                f"{ts_short}  {sig:12s} {ch:6s}  "
                f"{freq_mhz:8.3f} MHz  {snr:5.1f} dB  {detail}"
            )
            self._recent_events.append((sig, line))

            # Activity per minute
            minute_key = ts[:16] if len(ts) >= 16 else ""
            if minute_key:
                if minute_key not in self._activity_minutes:
                    self._activity_minutes[minute_key] = Counter()
                    # Prune old entries
                    if len(self._activity_minutes) > 180:
                        cutoff = (datetime.now() - timedelta(hours=2)).strftime(
                            "%Y-%m-%dT%H:%M")
                        self._activity_minutes = {
                            k: v for k, v in self._activity_minutes.items()
                            if k >= cutoff
                        }
                self._activity_minutes[minute_key][sig] += 1

    def get_state(self):
        """Return dashboard summary state."""
        uptime = timedelta(seconds=int(time.time() - self._start_time))
        now = datetime.now().strftime("%H:%M:%S")

        type_order = [
            "PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS",
            "RemoteID", "DroneCtrl",
            "keyfob", "tpms", "lora", "ISM",
            "ADS-B",
            "GSM-UPLINK-GSM-900", "GSM-UPLINK-GSM-850",
            "pocsag",
            "BLE-Adv", "WiFi-Probe",
        ]

        with self._lock:
            seen = set(self._type_counts.keys())
            all_types = [t for t in type_order if t in seen]
            all_types += sorted(seen - set(type_order))

            signals = []
            for sig in all_types:
                signals.append({
                    "type": sig,
                    "count": self._type_counts.get(sig, 0),
                    "uniques": len(self._type_uniques.get(sig, set())),
                    "last_seen": self._type_last_seen.get(sig),
                    "snr": self._type_last_snr.get(sig),
                    "detail": self._type_last_detail.get(sig, ""),
                })

            recent = [
                {"type": sig, "line": line}
                for sig, line in self._recent_events
            ]

            total = sum(self._type_counts.values())

        return {
            "time": now,
            "uptime": str(uptime),
            "detection_count": total,
            "gps": None,
            "csv": self._csv_name,
            "captures": [],
            "signals": signals,
            "recent": recent,
            "system": _get_system_stats(),
        }

    def get_detections(self, limit=50, offset=0, signal_type=None):
        """Return recent detections, newest first."""
        with self._lock:
            buf = list(reversed(self._detections))
        if signal_type:
            buf = [d for d in buf if d["signal_type"] == signal_type]
        return buf[offset:offset + limit]

    def get_activity(self, minutes=60):
        """Return per-minute detection counts."""
        now = datetime.now()
        result = []
        with self._lock:
            for i in range(minutes - 1, -1, -1):
                t = now - timedelta(minutes=i)
                key = t.strftime("%Y-%m-%dT%H:%M")
                counts = self._activity_minutes.get(key, Counter())
                result.append({
                    "minute": key,
                    "counts": dict(counts),
                    "total": sum(counts.values()),
                })
        return result

    def get_active_sigs(self, minutes=5):
        """Return dict of dev_sig → info for devices seen in the last N minutes."""
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        active = {}
        with self._lock:
            for d in reversed(self._detections):
                if d["timestamp"] < cutoff:
                    break
                sig = d.get("dev_sig")
                if not sig:
                    continue
                if sig not in active:
                    active[sig] = {
                        "rssi": d.get("snr_db"),
                        "apple_device": d.get("apple_device", ""),
                    }
        return active


def _extract_detail(sig, channel, meta):
    """Extract a short detail string from metadata (mirrors server.py logic)."""
    if sig == "BLE-Adv":
        return meta.get("device_type", "") or meta.get("manufacturer", "") or ""
    elif sig == "WiFi-Probe":
        ssid = meta.get("ssid", "")
        if ssid and ssid != "(broadcast)":
            return ssid[:60]
        return (meta.get("manufacturer", "") or "")[:60]
    elif sig == "ADS-B":
        cs = meta.get("callsign", "").strip()
        alt = meta.get("altitude", "")
        parts = [cs] if cs else []
        if alt:
            try:
                alt = int(alt)
                parts.append(f"FL{alt // 100}" if alt >= 10000 else f"{alt}ft")
            except (ValueError, TypeError):
                pass
        return " ".join(parts)
    elif sig == "keyfob":
        return (meta.get("protocol", "") or "")[:60]
    elif sig == "tpms":
        sid = meta.get("sensor_id", "")
        return f"ID:{sid}" if sid else ""
    elif sig == "lora":
        bw = meta.get("bandwidth_khz", "")
        return f"BW:{bw}kHz" if bw else ""
    elif sig in ("PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS", "FM_voice"):
        t = meta.get("transcript", "")
        if t:
            return f'"{t[:60]}"'
        dur = meta.get("duration_s", "")
        return f"{channel} {dur}s" if dur else channel
    elif sig == "RemoteID":
        return meta.get("serial_number", "") or meta.get("ua_type", "")
    elif sig == "DroneCtrl":
        return meta.get("drone_type", "")
    return ""


def _extract_uid(sig, row, meta):
    """Extract unique device ID from a CSV row."""
    if sig == "BLE-Adv":
        return meta.get("persona_id") or row.get("channel", "")
    elif sig == "WiFi-Probe":
        return meta.get("persona_id") or row.get("device_id", "")
    elif sig == "ADS-B":
        return meta.get("icao") or row.get("channel", "")
    elif sig == "keyfob":
        return meta.get("data_hex")
    elif sig == "tpms":
        return meta.get("sensor_id")
    elif sig == "lora":
        try:
            return f'{float(row.get("frequency_hz", 0)):.0f}'
        except (ValueError, TypeError):
            return None
    elif sig in ("PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS"):
        return row.get("channel", "")
    return None


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------

class WebHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests for the web dashboard."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == '/':
            self._serve_html()
        elif path == '/api/state':
            self._serve_state()
        elif path == '/api/events':
            self._serve_sse()
        elif path == '/api/detections':
            self._serve_detections(qs)
        elif path == '/api/activity':
            self._serve_activity(qs)
        elif path == '/api/config':
            self._serve_config()
        elif path == '/api/personas':
            self._serve_personas(qs)
        elif path.startswith('/audio/'):
            self._serve_audio(path[7:])
        else:
            self.send_error(404)

    def _send_json(self, data):
        payload = json.dumps(data)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(payload.encode('utf-8'))

    def _serve_html(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(_HTML_PAGE.encode('utf-8'))

    def _serve_state(self):
        self._send_json(self.server.tailer.get_state())

    def _serve_sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        stop = self.server.stop_event
        try:
            while not stop.is_set():
                state = self.server.tailer.get_state()
                payload = json.dumps(state)
                self.wfile.write(f"data: {payload}\n\n".encode('utf-8'))
                self.wfile.flush()
                stop.wait(2.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _serve_detections(self, qs):
        limit = min(int(qs.get("limit", [50])[0]), 200)
        offset = int(qs.get("offset", [0])[0])
        sig_type = qs.get("type", [None])[0]
        self._send_json(
            self.server.tailer.get_detections(limit, offset, sig_type))

    def _serve_activity(self, qs):
        minutes = min(int(qs.get("minutes", [60])[0]), 180)
        self._send_json(self.server.tailer.get_activity(minutes))

    def _serve_config(self):
        info_path = os.path.join(self.server.output_dir, "server_info.json")
        try:
            with open(info_path, 'r') as f:
                self._send_json(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            self._send_json({"captures": []})

    def _serve_personas(self, qs):
        transport = qs.get("transport", [None])[0]
        active_sigs = self.server.tailer.get_active_sigs(minutes=5)
        personas = _load_personas(self.server.output_dir, active_sigs)
        if transport:
            personas = [p for p in personas if p["transport"] == transport]
        self._send_json(personas)

    def _serve_audio(self, filename):
        if not _SAFE_FILENAME_RE.match(filename):
            self.send_error(400, "Invalid filename")
            return

        audio_dir = os.path.join(self.server.output_dir, "audio")
        filepath = os.path.join(audio_dir, filename)

        try:
            real_path = os.path.realpath(filepath)
            real_dir = os.path.realpath(audio_dir)
            if not real_path.startswith(real_dir + os.sep):
                self.send_error(403)
                return
        except (OSError, ValueError):
            self.send_error(403)
            return

        if not os.path.isfile(filepath):
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Content-Length', str(os.path.getsize(filepath)))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)


def run_web_server(output_dir, port=8080):
    """Run the standalone web server (blocking)."""
    output_dir = str(output_dir)
    stop_event = threading.Event()

    tailer = CSVTailer(output_dir)
    tailer.start()

    server = ThreadingHTTPServer(('0.0.0.0', port), WebHandler)
    server.tailer = tailer
    server.output_dir = output_dir
    server.stop_event = stop_event

    def _shutdown(signum, frame):
        print("\n[WEB] Shutting down...")
        stop_event.set()
        tailer.stop()
        # Shutdown in a thread to avoid deadlock (signal handler can't block)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print(f"[WEB] Serving {output_dir} on http://0.0.0.0:{port}/")
    print(f"[WEB] Ctrl+C to stop")
    server.serve_forever()


def start_web_server_background(output_dir, port=8080):
    """Start web server in a background daemon thread (for embedding in server)."""
    output_dir = str(output_dir)
    stop_event = threading.Event()

    tailer = CSVTailer(output_dir)
    tailer.start()

    try:
        server = ThreadingHTTPServer(('0.0.0.0', port), WebHandler)
    except OSError as e:
        print(f"  [WARN] Web UI failed to start on port {port}: {e}")
        tailer.stop()
        return None

    server.tailer = tailer
    server.output_dir = output_dir
    server.stop_event = stop_event

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="web-ui",
    )
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# Type colors (matches _TYPE_COLOR in server.py)
# ---------------------------------------------------------------------------

_TYPE_COLORS = {
    "BLE-Adv": "#00bcd4",
    "WiFi-Probe": "#2196f3",
    "keyfob": "#ffeb3b",
    "tpms": "#ffeb3b",
    "ISM": "#ffeb3b",
    "ADS-B": "#4caf50",
    "PMR446": "#f44336",
    "dPMR": "#f44336",
    "70cm": "#f44336",
    "MarineVHF": "#f44336",
    "2m": "#f44336",
    "FRS": "#f44336",
    "FM_voice": "#f44336",
    "RemoteID": "#f44336",
    "DroneCtrl": "#f44336",
    "GSM-UPLINK-GSM-900": "#ccc",
    "GSM-UPLINK-GSM-850": "#ccc",
    "lora": "#ce93d8",
    "pocsag": "#ccc",
}

# ---------------------------------------------------------------------------
# Embedded HTML page
# ---------------------------------------------------------------------------

_HTML_PAGE = (
    '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<title>SDR Server</title>\n'
    '<style>\n'
    r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #1a1a2e; color: #e0e0e0;
  font-family: "SF Mono", "Cascadia Code", "Fira Code", "Consolas", monospace;
  font-size: 14px; line-height: 1.5;
  padding: 16px; max-width: 1200px; margin: 0 auto;
}
h1 { font-size: 18px; font-weight: 600; }

.header {
  display: flex; flex-wrap: wrap; gap: 12px 24px;
  align-items: baseline;
  padding: 12px 16px; margin-bottom: 12px;
  background: #16213e; border-radius: 8px; border: 1px solid #0f3460;
}
.header .label { color: #888; font-size: 12px; }
.header .value { color: #e0e0e0; font-weight: 600; }
.header .highlight { color: #4fc3f7; }

.tabs { display: flex; gap: 4px; margin-bottom: 12px; }
.tab-btn {
  background: #16213e; color: #888; border: 1px solid #0f3460;
  border-bottom: none; border-radius: 6px 6px 0 0;
  padding: 8px 16px; cursor: pointer;
  font-family: inherit; font-size: 13px;
}
.tab-btn.active { color: #e0e0e0; background: #1a1a2e; }
.tab-content { display: none; }
.tab-content.active { display: block; }

.section {
  background: #16213e; border-radius: 8px; border: 1px solid #0f3460;
  margin-bottom: 12px; overflow: hidden;
}
.section-title {
  padding: 8px 16px; font-size: 12px; font-weight: 600;
  color: #888; text-transform: uppercase; letter-spacing: 1px;
  border-bottom: 1px solid #0f3460;
  display: flex; justify-content: space-between; align-items: center;
}
.section-body { padding: 8px 16px; }

.capture-line { padding: 2px 0; color: #aaa; white-space: pre-wrap; }

table { width: 100%; border-collapse: collapse; }
th {
  text-align: left; padding: 6px 12px; font-size: 11px;
  color: #888; text-transform: uppercase; letter-spacing: 1px;
  border-bottom: 1px solid #0f3460;
}
td { padding: 6px 12px; border-bottom: 1px solid #0f3460; }
tr:last-child td { border-bottom: none; }
.sig-type { font-weight: 600; white-space: nowrap; }
.num { text-align: right; }
.detail {
  max-width: 400px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.transcript { color: #81c784; font-style: italic; }

.event-line {
  padding: 2px 0; font-size: 13px;
  white-space: pre-wrap; word-break: break-all;
}

.status-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; font-size: 12px; color: #888;
}
.status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #4caf50; display: inline-block;
}
.status-dot.off { background: #f44336; }

.empty { color: #555; font-style: italic; padding: 12px 0; }

.filter-bar { display: flex; gap: 8px; align-items: center; }
.filter-bar select, .filter-bar button {
  background: #1a1a2e; color: #e0e0e0; border: 1px solid #0f3460;
  padding: 4px 10px; font-family: inherit; font-size: 12px;
  border-radius: 4px; cursor: pointer;
}
.filter-bar button:hover { border-color: #4fc3f7; }

.play-btn {
  background: none; border: 1px solid #0f3460; color: #4fc3f7;
  cursor: pointer; padding: 2px 10px; border-radius: 4px;
  font-family: inherit; font-size: 13px;
}
.play-btn:hover { border-color: #4fc3f7; }
.play-btn.playing { color: #f44336; border-color: #f44336; }

.load-more { padding: 8px 16px; text-align: center; }
.load-more button {
  background: #16213e; color: #888; border: 1px solid #0f3460;
  padding: 6px 20px; border-radius: 4px; cursor: pointer;
  font-family: inherit; font-size: 12px;
}
.load-more button:hover { color: #e0e0e0; border-color: #4fc3f7; }

.chart-container { padding: 16px; }
.activity-summary {
  padding: 8px 16px; font-size: 12px;
  display: flex; flex-wrap: wrap; gap: 8px 16px;
}

@media (max-width: 700px) {
  body { font-size: 12px; padding: 8px; }
  td, th { padding: 4px 6px; }
  .detail { max-width: 160px; }
  .tab-btn { padding: 6px 10px; font-size: 11px; }
}
"""
    '\n</style>\n</head>\n<body>\n'
    r"""
<!-- Header -->
<div class="header" id="header">
  <h1>SDR SERVER</h1>
  <div><span class="label">Time </span><span class="value" id="h-time">-</span></div>
  <div><span class="label">Up </span><span class="value" id="h-uptime">-</span></div>
  <div><span class="label">Detections </span><span class="value highlight" id="h-count">0</span></div>
  <div><span class="label">GPS </span><span class="value" id="h-gps">no fix</span></div>
  <div><span class="label">CSV </span><span class="value" id="h-csv" style="color:#888">-</span></div>
</div>

<!-- System stats bar -->
<div class="header" style="font-size:12px; gap: 8px 20px; padding: 8px 16px;">
  <div><span class="label">CPU </span><span class="value" id="s-cpu">-</span></div>
  <div><span class="label">Temp </span><span class="value" id="s-temp">-</span></div>
  <div><span class="label">Mem </span><span class="value" id="s-mem">-</span></div>
  <div><span class="label">Disk </span><span class="value" id="s-disk">-</span></div>
</div>

<!-- Tabs -->
<div class="tabs">
  <button class="tab-btn active" data-tab="overview">Overview</button>
  <button class="tab-btn" data-tab="detections">Detections</button>
  <button class="tab-btn" data-tab="devices">Devices</button>
  <button class="tab-btn" data-tab="captures">Captures</button>
  <button class="tab-btn" data-tab="activity">Activity</button>
</div>

<!-- Tab: Overview -->
<div id="tab-overview" class="tab-content active">
  <div class="section">
    <div class="section-title">Signals</div>
    <table>
      <thead><tr>
        <th>Signal</th><th class="num">Count</th><th class="num">Uniq</th>
        <th>Last</th><th class="num">SNR</th><th>Details</th>
      </tr></thead>
      <tbody id="signals">
        <tr><td colspan="6" class="empty">waiting for detections...</td></tr>
      </tbody>
    </table>
  </div>

  <div class="section">
    <div class="section-title">Recent</div>
    <div class="section-body" id="recent"><div class="empty">...</div></div>
  </div>
</div>

<!-- Tab: Detections -->
<div id="tab-detections" class="tab-content">
  <div class="section">
    <div class="section-title">
      <span>Detections</span>
      <div class="filter-bar">
        <select id="det-filter"><option value="">All Types</option></select>
        <button onclick="loadDetections()">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Time</th><th>Type</th><th>Ch</th><th>Freq (MHz)</th>
        <th class="num">SNR</th><th>Details</th><th></th>
      </tr></thead>
      <tbody id="det-body">
        <tr><td colspan="7" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
    <div class="load-more">
      <button id="det-more" onclick="loadDetections(true)">Load More</button>
    </div>
  </div>
</div>

<!-- Tab: Devices -->
<div id="tab-devices" class="tab-content">
  <!-- Summary cards -->
  <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap" id="dev-stats"></div>

  <div class="section">
    <div class="section-title">
      <span>Known Devices</span>
      <div class="filter-bar">
        <select id="dev-transport">
          <option value="">All</option>
          <option value="BLE">BLE</option>
          <option value="WiFi">WiFi</option>
        </select>
        <label style="font-size:11px;color:#888;display:flex;align-items:center;gap:4px;text-transform:none;letter-spacing:0">
          <input type="checkbox" id="dev-active-only"> Active only
        </label>
        <select id="dev-sort">
          <option value="default">Sort: Active + Recent</option>
          <option value="sessions">Sort: Sessions</option>
          <option value="probes">Sort: Probes</option>
          <option value="name">Sort: Name</option>
        </select>
        <button onclick="loadPersonas()">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th style="width:20px"></th><th>Type</th><th>Device</th><th>Manufacturer</th>
        <th class="num">MACs</th><th class="num">Sessions</th>
        <th class="num">Probes</th><th>Last Seen</th>
      </tr></thead>
      <tbody id="dev-body">
        <tr><td colspan="8" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab: Captures -->
<div id="tab-captures" class="tab-content">
  <div class="section">
    <div class="section-title">Capture Configuration</div>
    <div class="section-body" id="captures"><div class="empty">loading...</div></div>
  </div>
</div>

<!-- Tab: Activity -->
<div id="tab-activity" class="tab-content">
  <div class="section">
    <div class="section-title">Activity (last 60 minutes)</div>
    <div class="chart-container" id="activity-chart">
      <div class="empty">loading...</div>
    </div>
    <div class="activity-summary" id="activity-summary"></div>
  </div>
</div>

<!-- Status -->
<div class="status-bar">
  <span class="status-dot" id="status-dot"></span>
  <span id="status-text">connecting...</span>
</div>

<!-- Hidden audio element -->
<audio id="audio-player" style="display:none"></audio>

<script>
"""
    + 'const TYPE_COLORS = ' + json.dumps(_TYPE_COLORS) + ';\n'
    + r"""
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// --- Config / Captures ---
let configLoaded = false;

async function loadConfig() {
  if (configLoaded) return;
  const capEl = document.getElementById('captures');
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    if (!cfg.captures || !cfg.captures.length) {
      capEl.innerHTML = '<div class="empty">no server_info.json found (server not running?)</div>';
      configLoaded = true;
      return;
    }
    let html = '';
    cfg.captures.forEach(cap => {
      const t = cap.type;
      let line = '<div style="margin-bottom:8px">';
      line += '<div><span style="color:#4fc3f7;font-weight:600">' + esc(cap.name) + '</span>';
      line += ' <span style="color:#888">' + esc(cap.device || '') + '</span></div>';

      const tags = [];
      if (t === 'hackrf') {
        tags.push(cap.center_freq_mhz + ' MHz');
        tags.push(cap.sample_rate_mhz + ' MS/s');
        if (cap.lna_gain != null) tags.push('LNA ' + cap.lna_gain);
        if (cap.vga_gain != null) tags.push('VGA ' + cap.vga_gain);
        if (cap.transcribe) tags.push('\u2705 transcribe');
        if (cap.whisper_model && cap.whisper_model !== 'base') tags.push('whisper: ' + cap.whisper_model);
        if (cap.language) tags.push('lang: ' + cap.language);
      } else if (t === 'rtlsdr') {
        tags.push(cap.center_freq_mhz + ' MHz');
        if (cap.parsers) tags.push(cap.parsers.join(', '));
      } else if (t === 'rtlsdr_sweep') {
        tags.push(cap.band_start_mhz + '-' + cap.band_end_mhz + ' MHz');
        tags.push('\u{1F500} hopping');
        if (cap.parsers) tags.push(cap.parsers.join(', '));
      } else if (t === 'ble') {
        tags.push('Bluetooth LE');
        if (cap.parsers) tags.push(cap.parsers.join(', '));
      } else if (t === 'wifi') {
        tags.push('WiFi monitor');
        if (cap.channels && cap.channels.length) tags.push('ch ' + cap.channels.join(','));
        if (cap.parsers) tags.push(cap.parsers.join(', '));
      } else if (t === 'standalone') {
        tags.push(esc(cap.scanner_type || ''));
        if (cap.args && cap.args.length) tags.push(cap.args.join(' '));
      }
      if (tags.length) {
        line += '<div style="font-size:12px;color:#aaa;margin-left:12px">' + tags.map(t => '<span style="background:#0f3460;padding:1px 6px;border-radius:3px;margin-right:4px;display:inline-block;margin-top:2px">' + esc(t) + '</span>').join('') + '</div>';
      }

      // Show channels for HackRF
      if (t === 'hackrf' && cap.channels && cap.channels.length) {
        cap.channels.forEach(ch => {
          const chTags = [];
          if (ch.band) chTags.push(ch.band);
          chTags.push(ch.freq_mhz + ' MHz');
          if (ch.bandwidth_mhz) chTags.push(ch.bandwidth_mhz + ' MHz BW');
          if (ch.parsers) chTags.push(ch.parsers.join(', '));
          if (ch.transcribe) chTags.push('\u2705 transcribe');
          line += '<div style="font-size:11px;color:#888;margin-left:24px;margin-top:2px">\u2514 ' + chTags.join(' \u00b7 ') + '</div>';
        });
      }
      line += '</div>';
      html += line;
    });
    if (cfg.started) {
      html += '<div style="font-size:11px;color:#555;margin-top:4px">Started: ' + esc(cfg.started.replace('T', ' ').split('.')[0]) + '</div>';
    }
    capEl.innerHTML = html;
    configLoaded = true;
  } catch(e) {
    capEl.innerHTML = '<div class="empty">could not load config</div>';
  }
}

// --- Overview Tab ---
function updateOverview(state) {
  document.getElementById('h-time').textContent = state.time || '-';
  document.getElementById('h-uptime').textContent = state.uptime || '-';
  document.getElementById('h-count').textContent = state.detection_count || 0;
  document.getElementById('h-csv').textContent = state.csv || '-';

  const gps = state.gps;
  const gpsEl = document.getElementById('h-gps');
  if (gps && gps.lat != null) {
    gpsEl.textContent = gps.lat.toFixed(4) + ', ' + gps.lon.toFixed(4);
    gpsEl.style.color = '#4fc3f7';
  } else {
    gpsEl.textContent = 'no fix';
    gpsEl.style.color = '#888';
  }

  // System stats
  const sys = state.system || {};
  const cpuEl = document.getElementById('s-cpu');
  if (sys.cpu_pct != null) {
    cpuEl.textContent = sys.cpu_pct + '%';
    cpuEl.style.color = sys.cpu_pct > 80 ? '#f44336' : sys.cpu_pct > 50 ? '#ffeb3b' : '#4caf50';
  }
  const tempEl = document.getElementById('s-temp');
  if (sys.cpu_temp != null) {
    tempEl.textContent = sys.cpu_temp + '\u00b0C';
    tempEl.style.color = sys.cpu_temp > 75 ? '#f44336' : sys.cpu_temp > 60 ? '#ffeb3b' : '#4caf50';
  }
  const memEl = document.getElementById('s-mem');
  if (sys.mem_used_mb != null) {
    memEl.textContent = sys.mem_used_mb + ' / ' + sys.mem_total_mb + ' MB (' + sys.mem_pct + '%)';
    memEl.style.color = sys.mem_pct > 85 ? '#f44336' : sys.mem_pct > 70 ? '#ffeb3b' : '#e0e0e0';
  }
  const diskEl = document.getElementById('s-disk');
  if (sys.disk_used_gb != null) {
    diskEl.textContent = sys.disk_used_gb + ' / ' + sys.disk_total_gb + ' GB (' + sys.disk_pct + '%)';
    diskEl.style.color = sys.disk_pct > 90 ? '#f44336' : sys.disk_pct > 75 ? '#ffeb3b' : '#e0e0e0';
  }

  // (Captures are in their own tab now)

  // Signals table
  const tbody = document.getElementById('signals');
  if (state.signals && state.signals.length) {
    tbody.innerHTML = state.signals.map(s => {
      const color = TYPE_COLORS[s.type] || '#ccc';
      const isTx = s.detail && s.detail.startsWith('"');
      const cls = 'detail' + (isTx ? ' transcript' : '');
      return '<tr>'
        + '<td class="sig-type" style="color:'+color+'">'+esc(s.type)+'</td>'
        + '<td class="num">'+s.count+'</td>'
        + '<td class="num">'+(s.uniques>1?'('+s.uniques+')':'')+'</td>'
        + '<td>'+(s.last_seen||'-')+'</td>'
        + '<td class="num">'+(s.snr!=null?s.snr.toFixed(1)+' dB':'-')+'</td>'
        + '<td class="'+cls+'">'+esc(s.detail||'')+'</td></tr>';
    }).join('');
  } else {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">waiting for detections...</td></tr>';
  }

  // Recent events
  const recEl = document.getElementById('recent');
  if (state.recent && state.recent.length) {
    recEl.innerHTML = state.recent.map(ev => {
      const color = TYPE_COLORS[ev.type] || '#ccc';
      const line = esc(ev.line);
      const typed = esc(ev.type);
      const colored = line.replace(typed,
        '<span style="color:'+color+';font-weight:600">'+typed+'</span>');
      return '<div class="event-line">' + colored + '</div>';
    }).join('');
  } else {
    recEl.innerHTML = '<div class="empty">...</div>';
  }

  // Populate filter dropdown
  populateFilter(state.signals);
}

// --- Detections Tab ---
let detOffset = 0;
let detectionsLoaded = false;
let filterPopulated = false;

function populateFilter(signals) {
  if (filterPopulated || !signals || !signals.length) return;
  const sel = document.getElementById('det-filter');
  signals.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.type;
    opt.textContent = s.type + ' (' + s.count + ')';
    sel.appendChild(opt);
  });
  filterPopulated = true;
}

async function loadDetections(append) {
  if (!append) detOffset = 0;
  const filter = document.getElementById('det-filter').value;
  const url = '/api/detections?limit=50&offset=' + detOffset
    + (filter ? '&type=' + encodeURIComponent(filter) : '');
  try {
    const r = await fetch(url);
    const data = await r.json();
    const tbody = document.getElementById('det-body');
    if (!append) tbody.innerHTML = '';

    data.forEach(d => {
      const tr = document.createElement('tr');
      const ts = d.timestamp ? d.timestamp.split('T')[1].split('.')[0] : '-';
      const color = TYPE_COLORS[d.signal_type] || '#ccc';
      const hasTx = !!d.transcript;
      const detailText = hasTx ? '\u201c' + d.transcript + '\u201d' : (d.detail || '');
      const audioBtn = d.audio_file
        ? '<button class="play-btn" onclick="playAudio(this,\''+esc(d.audio_file)+'\')">&#9654;</button>'
        : '';
      tr.innerHTML =
        '<td>'+ts+'</td>'
        + '<td class="sig-type" style="color:'+color+'">'+esc(d.signal_type)+'</td>'
        + '<td>'+esc(d.channel)+'</td>'
        + '<td>'+d.frequency_mhz.toFixed(3)+'</td>'
        + '<td class="num">'+(d.snr_db!=null?d.snr_db+' dB':'-')+'</td>'
        + '<td class="detail'+(hasTx?' transcript':'')+'">'+esc(detailText)+'</td>'
        + '<td>'+audioBtn+'</td>';
      tbody.appendChild(tr);
    });

    detOffset += data.length;
    detectionsLoaded = true;
    document.getElementById('det-more').style.display = data.length < 50 ? 'none' : '';
  } catch(e) {}
}

document.getElementById('det-filter').addEventListener('change', () => loadDetections());

// --- Audio Playback ---
const audioEl = document.getElementById('audio-player');

function playAudio(btn, filename) {
  if (audioEl.dataset.file === filename && !audioEl.paused) {
    audioEl.pause();
    btn.innerHTML = '&#9654;';
    btn.classList.remove('playing');
    return;
  }
  document.querySelectorAll('.play-btn.playing').forEach(b => {
    b.innerHTML = '&#9654;'; b.classList.remove('playing');
  });
  audioEl.src = '/audio/' + encodeURIComponent(filename);
  audioEl.dataset.file = filename;
  audioEl.play();
  btn.innerHTML = '&#9724;';
  btn.classList.add('playing');
  audioEl.onended = () => {
    btn.innerHTML = '&#9654;'; btn.classList.remove('playing');
  };
}

// --- Devices Tab ---
let _personaCache = [];

async function loadPersonas() {
  const transport = document.getElementById('dev-transport').value;
  const url = '/api/personas' + (transport ? '?transport=' + transport : '');
  try {
    const r = await fetch(url);
    _personaCache = await r.json();
    renderPersonas();
  } catch(e) {}
}

function renderPersonas() {
  const data = _personaCache;
  const activeOnly = document.getElementById('dev-active-only').checked;
  const sortBy = document.getElementById('dev-sort').value;

  let filtered = activeOnly ? data.filter(p => p.active) : data;

  if (sortBy === 'sessions') filtered.sort((a,b) => b.sessions - a.sessions);
  else if (sortBy === 'probes') filtered.sort((a,b) => b.total_probes - a.total_probes);
  else if (sortBy === 'name') filtered.sort((a,b) => (a.label||'zzz').localeCompare(b.label||'zzz'));
  // default sort is from server (active + recent)

  // Summary cards
  const totalBle = data.filter(p => p.transport === 'BLE').length;
  const totalWifi = data.filter(p => p.transport === 'WiFi').length;
  const activeCount = data.filter(p => p.active).length;
  const returning = data.filter(p => p.sessions >= 5).length;
  const cardStyle = 'background:#16213e;border:1px solid #0f3460;border-radius:6px;padding:8px 14px;font-size:12px;text-align:center;min-width:80px';
  document.getElementById('dev-stats').innerHTML =
    '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#e0e0e0">'+data.length+'</div>Total</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#4caf50">'+activeCount+'</div>Active</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#00bcd4">'+totalBle+'</div>BLE</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#2196f3">'+totalWifi+'</div>WiFi</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#ffeb3b">'+returning+'</div>Returning</div>';

  // Table
  const tbody = document.getElementById('dev-body');
  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">no devices found</td></tr>';
    return;
  }
  tbody.innerHTML = filtered.map(p => {
    const tColor = p.transport === 'BLE' ? '#00bcd4' : '#2196f3';
    const lastSeen = p.last_session ? p.last_session.split('T')[0].slice(5) + ' ' + p.last_session.split('T')[1].split('.')[0] : '-';
    const sessColor = p.sessions >= 20 ? '#f44336' : p.sessions >= 5 ? '#ffeb3b' : '#e0e0e0';
    const macList = p.macs.map(m => esc(m)).join('\n');

    // Build label cell
    let labelHtml = '';
    if (p.label) {
      labelHtml = '<span style="color:#e0e0e0">' + esc(p.label) + '</span>';
    } else {
      labelHtml = '<span style="color:#555">unknown</span>';
    }
    // Badges
    const badges = [];
    if (p.apple_device) badges.push('<span style="background:#333;color:#aaa;padding:0 5px;border-radius:3px;font-size:10px">' + esc(p.apple_device) + '</span>');
    if (p.randomized) badges.push('<span style="background:#333;color:#888;padding:0 5px;border-radius:3px;font-size:10px">rand</span>');
    if (badges.length) labelHtml += ' ' + badges.join(' ');

    // Active dot
    const dot = p.active
      ? '<span class="status-dot" title="Active now"></span>'
      : '<span class="status-dot off" style="opacity:0.2"></span>';

    // Row style
    const rowStyle = p.sessions <= 1 ? 'opacity:0.5' : '';
    const borderStyle = p.active ? 'border-left:3px solid #4caf50' : '';

    return '<tr style="'+rowStyle+';'+borderStyle+'">'
      + '<td>'+dot+'</td>'
      + '<td style="color:'+tColor+';font-size:11px;white-space:nowrap">'+esc(p.transport)+'</td>'
      + '<td>'+labelHtml+'</td>'
      + '<td style="color:#888;font-size:12px">'+esc(p.manufacturer || '')+'</td>'
      + '<td class="num" title="'+esc(macList)+'" style="cursor:help">'+p.mac_count+'</td>'
      + '<td class="num" style="color:'+sessColor+'">'+p.sessions+'</td>'
      + '<td class="num">'+p.total_probes.toLocaleString()+'</td>'
      + '<td style="font-size:12px;white-space:nowrap">'+lastSeen+'</td>'
      + '</tr>';
  }).join('');
}

document.getElementById('dev-transport').addEventListener('change', () => loadPersonas());
document.getElementById('dev-active-only').addEventListener('change', () => renderPersonas());
document.getElementById('dev-sort').addEventListener('change', () => renderPersonas());

// --- Activity Tab ---
async function loadActivity() {
  try {
    const r = await fetch('/api/activity?minutes=60');
    const data = await r.json();

    const allTypes = new Set();
    data.forEach(m => Object.keys(m.counts).forEach(t => allTypes.add(t)));
    const types = Array.from(allTypes);

    const maxTotal = Math.max(1, ...data.map(m => m.total));

    const W = 800, H = 200, PAD = 40;
    const barW = Math.max(1, (W - PAD * 2) / data.length);

    let svg = '<svg viewBox="0 0 '+W+' '+(H+30)+'" style="width:100%;height:auto">';

    // Gridlines
    for (let g = 0; g <= 4; g++) {
      const gy = PAD + (H - PAD) * (1 - g/4);
      svg += '<line x1="'+PAD+'" y1="'+gy+'" x2="'+(W-10)+'" y2="'+gy+'" stroke="#0f3460" stroke-width="0.5"/>';
      svg += '<text x="'+(PAD-4)+'" y="'+(gy+3)+'" fill="#888" font-size="9" text-anchor="end" font-family="monospace">'+Math.round(maxTotal*g/4)+'</text>';
    }

    data.forEach((m, i) => {
      const x = PAD + i * barW;
      let y = H;
      types.forEach(t => {
        const count = m.counts[t] || 0;
        if (!count) return;
        const barH = (count / maxTotal) * (H - PAD);
        y -= barH;
        const color = TYPE_COLORS[t] || '#ccc';
        svg += '<rect x="'+x+'" y="'+y+'" width="'+Math.max(1,barW-1)+'" height="'+barH+'" fill="'+color+'" opacity="0.8">'
             + '<title>'+m.minute.slice(11)+' '+t+': '+count+'</title></rect>';
      });
      if (i % 10 === 0) {
        svg += '<text x="'+(x+barW/2)+'" y="'+(H+15)+'" fill="#888" font-size="9" text-anchor="middle" font-family="monospace">'+m.minute.slice(11)+'</text>';
      }
    });

    svg += '</svg>';
    document.getElementById('activity-chart').innerHTML = svg;

    // Summary
    const totals = {};
    data.forEach(m => Object.entries(m.counts).forEach(([t,c]) => totals[t]=(totals[t]||0)+c));
    document.getElementById('activity-summary').innerHTML = Object.entries(totals)
      .sort((a,b) => b[1]-a[1])
      .map(([t,c]) => '<span style="color:'+(TYPE_COLORS[t]||'#ccc')+'">'+esc(t)+'</span>: '+c)
      .join('&nbsp;&nbsp;&nbsp;');
  } catch(e) {}
}

// --- Tab Navigation ---
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => {
      c.classList.remove('active'); c.style.display = 'none';
    });
    btn.classList.add('active');
    const panel = document.getElementById('tab-' + btn.dataset.tab);
    panel.classList.add('active');
    panel.style.display = 'block';
    location.hash = btn.dataset.tab;
    if (btn.dataset.tab === 'detections') loadDetections();
    if (btn.dataset.tab === 'devices') loadPersonas();
    if (btn.dataset.tab === 'captures') loadConfig();
    if (btn.dataset.tab === 'activity') loadActivity();
  });
});
if (location.hash) {
  const btn = document.querySelector('.tab-btn[data-tab="'+location.hash.slice(1)+'"]');
  if (btn) btn.click();
}

// --- SSE Connection ---
let errorCount = 0;
let polling = false;

function connectSSE() {
  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('status-text');
  const es = new EventSource('/api/events');

  es.onopen = () => {
    errorCount = 0;
    dot.className = 'status-dot';
    txt.textContent = 'live';
  };

  es.onmessage = (ev) => {
    try {
      const state = JSON.parse(ev.data);
      updateOverview(state);
      if (document.getElementById('tab-detections').classList.contains('active')) {
        loadDetections();
      }
    } catch(e) {}
  };

  es.onerror = () => {
    es.close();
    errorCount++;
    dot.className = 'status-dot off';
    txt.textContent = 'reconnecting...';
    if (errorCount >= 3 && !polling) {
      polling = true;
      txt.textContent = 'polling';
      startPolling();
    } else if (!polling) {
      setTimeout(connectSSE, 2000);
    }
  };
}

function startPolling() {
  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('status-text');
  setInterval(async () => {
    try {
      const r = await fetch('/api/state');
      const state = await r.json();
      updateOverview(state);
      dot.className = 'status-dot';
      txt.textContent = 'polling';
    } catch(e) {
      dot.className = 'status-dot off';
      txt.textContent = 'disconnected';
    }
  }, 3000);
}

// Refresh activity chart every 60s if active
setInterval(() => {
  if (document.getElementById('tab-activity').classList.contains('active')) {
    loadActivity();
  }
}, 60000);

connectSSE();
</script>
</body>
</html>
"""
)

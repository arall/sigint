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
        self._detections = deque(maxlen=500)
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
        self._current_csv = None
        self._file_handle = None
        self._reader = None
        self._file_pos = 0

    def start(self):
        """Start background thread that tails CSV files."""
        t = threading.Thread(target=self._run, daemon=True, name="csv-tailer")
        t.start()
        return t

    def stop(self):
        self._stop.set()
        if self._file_handle:
            self._file_handle.close()

    def _find_latest_csv(self):
        """Find the most recently modified CSV in output_dir."""
        try:
            csvs = [
                os.path.join(self.output_dir, f)
                for f in os.listdir(self.output_dir)
                if f.endswith('.csv')
            ]
            if not csvs:
                return None
            return max(csvs, key=os.path.getmtime)
        except OSError:
            return None

    def _run(self):
        """Background loop: find CSV, tail new rows."""
        while not self._stop.is_set():
            latest = self._find_latest_csv()

            # Switch to new CSV if it changed
            if latest and latest != self._current_csv:
                if self._file_handle:
                    self._file_handle.close()
                self._current_csv = latest
                self._csv_name = os.path.basename(latest)
                self._file_handle = open(latest, 'r', newline='')
                # Read existing content
                reader = csv.DictReader(self._file_handle)
                for row in reader:
                    self._process_row(row)
                self._file_pos = self._file_handle.tell()

            # Tail for new lines
            if self._file_handle:
                self._file_handle.seek(self._file_pos)
                for line in self._file_handle:
                    line = line.strip()
                    if not line:
                        continue
                    # Parse CSV line using the known headers
                    try:
                        # Re-parse with DictReader on single line
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
                        # Skip if it looks like a header row
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
        server.shutdown()

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

<!-- Tabs -->
<div class="tabs">
  <button class="tab-btn active" data-tab="overview">Overview</button>
  <button class="tab-btn" data-tab="detections">Detections</button>
  <button class="tab-btn" data-tab="activity">Activity</button>
</div>

<!-- Tab: Overview -->
<div id="tab-overview" class="tab-content active">
  <div class="section" id="captures-section" style="display:none">
    <div class="section-title">Listening</div>
    <div class="section-body" id="captures"></div>
  </div>

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

  // Captures (only show if server provides them)
  const capSec = document.getElementById('captures-section');
  const capEl = document.getElementById('captures');
  if (state.captures && state.captures.length) {
    capSec.style.display = '';
    capEl.innerHTML = state.captures
      .map(c => '<div class="capture-line">' + esc(c) + '</div>').join('');
  } else {
    capSec.style.display = 'none';
  }

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

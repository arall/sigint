"""
Web dashboard HTTP server.

Serves:
  /                    → static/index.html
  /static/style.css    → static/style.css
  /static/app.js       → static/app.js
  /api/state           → DBTailer.get_state() snapshot
  /api/events          → SSE stream of state updates (2s cadence)
  /api/detections      → DBTailer.get_detections() window
  /api/activity        → per-minute activity histogram
  /api/config          → passthrough for server_info.json
  /api/devices         → WiFi APs + WiFi Clients + BLE grouped
  /api/cat/<name>      → domain-shaped rows for a category tab
  /audio/<filename>    → WAV playback for voice transmissions

Two public entry points:
  run_web_server(output_dir, port)            — standalone, blocking
  start_web_server_background(output_dir, port) — threaded, returns thread
"""

import json
import os
import re
import signal
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .categories import CATEGORY_LABELS
from .fetch import fetch_detections_for_category, fetch_detections_for_category_all
from .loaders import (
    CATEGORY_LOADERS,
    _load_ble_devices,
    _load_wifi_aps,
    _load_wifi_clients,
)
from .sessions import list_sessions, resolve_session_path
from .tailer import DBTailer


_SAFE_FILENAME_RE = re.compile(r'^[a-zA-Z0-9_\-\.]+\.wav$')
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Whitelist of static assets — only these are served, protecting against
# path traversal and arbitrary disk read.
_STATIC_WHITELIST = {
    "index.html":  "text/html; charset=utf-8",
    "style.css":   "text/css; charset=utf-8",
    "app.js":      "application/javascript; charset=utf-8",
    "leaflet.js":  "application/javascript; charset=utf-8",
    "leaflet.css": "text/css; charset=utf-8",
}


def _read_static(filename):
    """Return (content_bytes, content_type) for a whitelisted static file,
    or (None, None) if filename is not allowed / missing."""
    ct = _STATIC_WHITELIST.get(filename)
    if ct is None:
        return None, None
    path = os.path.join(_STATIC_DIR, filename)
    try:
        with open(path, 'rb') as f:
            return f.read(), ct
    except OSError:
        return None, None


class WebHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests for the web dashboard."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == '/':
            self._serve_static('index.html')
        elif path.startswith('/static/'):
            self._serve_static(path[len('/static/'):])
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
        elif path == '/api/devices':
            self._serve_devices(qs)
        elif path == '/api/sessions':
            self._serve_sessions()
        elif path.startswith('/api/cat/'):
            self._serve_category(path[len('/api/cat/'):], qs)
        elif path.startswith('/audio/'):
            self._serve_audio(path[7:])
        else:
            self.send_error(404)

    # --- helpers ---

    def _send_json(self, data):
        payload = json.dumps(data)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(payload.encode('utf-8'))

    def _serve_static(self, filename):
        body, ct = _read_static(filename)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- API endpoints ---

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

    def _serve_category(self, name, qs):
        loader = CATEGORY_LOADERS.get(name)
        if loader is None:
            self.send_error(404, f"Unknown category: {name}")
            return

        tailer = self.server.tailer

        # Time window for SQL fetch, in hours; default 6h, capped at 168 (1wk).
        try:
            window_hours = float(qs.get("window", [6])[0])
        except (ValueError, TypeError):
            window_hours = 6
        window_hours = max(0.1, min(window_hours, 168))
        window_seconds = int(window_hours * 3600)

        # Session override: ?session=<filename> picks a single historical
        # .db. Default is LIVE mode, which unions every .db in the output
        # directory — because standalone scanners (sdr.py pmr, adsb, ais,
        # ...) write to their own files separate from the server .db, so
        # a single-file scope would miss them.
        session_name = qs.get("session", [None])[0]
        session_resolved = None
        detections = None

        if session_name:
            db_path = resolve_session_path(self.server.output_dir, session_name)
            if db_path is None:
                self.send_error(400, f"Unknown session: {session_name}")
                return
            session_resolved = session_name
            try:
                detections = fetch_detections_for_category(
                    db_path, name,
                    window_seconds=window_seconds,
                )
            except Exception:
                detections = None
        else:
            try:
                detections = fetch_detections_for_category_all(
                    self.server.output_dir, name,
                    window_seconds=window_seconds,
                )
            except Exception:
                detections = None

        source = "db"
        if detections is None:
            source = "deque"
            with tailer._lock:
                detections = list(tailer._detections)

        rows = loader(detections)
        self._send_json({
            "category": name,
            "label": CATEGORY_LABELS.get(name, name),
            "rows": rows,
            "total": len(rows),
            "source": source,
            "session": session_resolved,
            "window_hours": window_hours,
        })

    def _serve_sessions(self):
        sessions = list_sessions(self.server.output_dir)
        self._send_json({"sessions": sessions})

    def _serve_devices(self, qs):
        tailer = self.server.tailer
        active_sigs = tailer.get_active_sigs(minutes=5)
        active_bssids = tailer.get_active_bssids(minutes=5)
        out_dir = self.server.output_dir
        wifi_aps = _load_wifi_aps(out_dir, active_bssids)
        wifi_clients = _load_wifi_clients(out_dir, active_sigs)
        ble = _load_ble_devices(out_dir, active_sigs)
        summary = {
            "wifi_aps": len(wifi_aps),
            "wifi_clients": len(wifi_clients),
            "ble": len(ble),
            "active": sum(1 for x in wifi_aps + wifi_clients + ble if x.get("active")),
        }
        self._send_json({
            "wifi_aps": wifi_aps,
            "wifi_clients": wifi_clients,
            "ble": ble,
            "summary": summary,
        })

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


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run_web_server(output_dir, port=8080):
    """Run the standalone web server (blocking)."""
    output_dir = str(output_dir)
    stop_event = threading.Event()

    tailer = DBTailer(output_dir)
    tailer.start()

    server = ThreadingHTTPServer(('0.0.0.0', port), WebHandler)
    server.tailer = tailer
    server.output_dir = output_dir
    server.stop_event = stop_event

    def _shutdown(signum, frame):
        print("\n[WEB] Shutting down...")
        stop_event.set()
        tailer.stop()
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

    tailer = DBTailer(output_dir)
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

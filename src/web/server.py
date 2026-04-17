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
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from .categories import CATEGORY_LABELS
from .fetch import (
    fetch_active_bssids,
    fetch_active_dev_sigs,
    fetch_activity_histogram,
    fetch_agent_detections,
    fetch_correlations,
    fetch_detections_for_category,
    fetch_detections_for_category_all,
    fetch_recent_detections,
)
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
        elif path == '/api/correlations':
            self._serve_correlations()
        elif path.startswith('/api/cat/'):
            self._serve_category(path[len('/api/cat/'):], qs)
        elif path == '/api/agents':
            self._serve_agents()
        elif path == '/api/agents/detections':
            self._serve_agent_detections(qs)
        elif path == '/api/fpv/frame':
            self._serve_fpv_frame()
        elif path == '/api/fpv/stream':
            self._serve_fpv_stream()
        elif path.startswith('/audio/'):
            self._serve_audio(path[7:])
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length else ''
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_error(400, "bad json")
            return

        if path == '/api/agents/approve':
            self._agents_approve(data)
        elif path == '/api/agents/cmd':
            self._agents_cmd(data)
        elif path == '/api/agents/cfg':
            self._agents_cfg(data)
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
        self._send_json(fetch_recent_detections(
            self.server.output_dir,
            limit=limit,
            offset=offset,
            signal_type=sig_type,
        ))

    def _serve_activity(self, qs):
        minutes = min(int(qs.get("minutes", [60])[0]), 180)
        self._send_json(fetch_activity_histogram(
            self.server.output_dir, minutes=minutes,
        ))

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

        # Time window for SQL fetch, in hours. Default: no window (rely on
        # the row LIMIT). Pass ?window=N to restrict to the last N hours.
        window_seconds = None
        raw = qs.get("window", [None])[0]
        if raw is not None:
            try:
                window_hours = max(0.1, min(float(raw), 168))
                window_seconds = int(window_hours * 3600)
            except (ValueError, TypeError):
                window_seconds = None

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
                detections = []
        else:
            try:
                detections = fetch_detections_for_category_all(
                    self.server.output_dir, name,
                    window_seconds=window_seconds,
                )
            except Exception:
                detections = []

        rows = loader(detections or [])
        self._send_json({
            "category": name,
            "label": CATEGORY_LABELS.get(name, name),
            "rows": rows,
            "total": len(rows),
            "session": session_resolved,
            "window_hours": (window_seconds / 3600) if window_seconds else None,
        })

    def _serve_sessions(self):
        sessions = list_sessions(self.server.output_dir)
        self._send_json({"sessions": sessions})

    def _serve_correlations(self):
        """Compute correlations on demand from every session .db in the
        output dir. See web/fetch.py::fetch_correlations for rationale
        (cross-session pairs, stateless across server restart, no
        sidecar JSON to sync)."""
        qs = parse_qs(urlparse(self.path).query)
        try:
            window_s = float(qs.get("window", [30])[0])
        except (ValueError, TypeError):
            window_s = 30.0
        try:
            threshold = float(qs.get("threshold", [0.5])[0])
        except (ValueError, TypeError):
            threshold = 0.5
        window_s = max(1.0, min(window_s, 3600.0))
        threshold = max(0.0, min(threshold, 1.0))

        try:
            result = fetch_correlations(
                self.server.output_dir,
                window_s=window_s,
                threshold=threshold,
            )
        except Exception as e:
            result = {
                "correlated_pairs": [],
                "clusters": [],
                "total_devices": 0,
                "timestamp": None,
                "error": f"{type(e).__name__}: {e}",
            }
        self._send_json(result)

    def _serve_devices(self, qs):
        out_dir = self.server.output_dir
        active_sigs = fetch_active_dev_sigs(out_dir, minutes=5)
        active_bssids_map = fetch_active_bssids(out_dir, minutes=5)
        wifi_aps = _load_wifi_aps(out_dir, active_bssids_map)
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

    def _serve_fpv_frame(self):
        """Serve the latest FPV video frame as PNG."""
        fpv_path = os.path.join(self.server.output_dir, "fpv_latest.png")
        if not os.path.isfile(fpv_path):
            self.send_error(404, "No FPV frame available")
            return
        try:
            with open(fpv_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(500)

    def _serve_fpv_stream(self):
        """Serve FPV video as MJPEG-style stream (multipart PNG frames)."""
        fpv_path = os.path.join(self.server.output_dir, "fpv_latest.png")
        self.send_response(200)
        self.send_header('Content-Type',
                         'multipart/x-mixed-replace; boundary=--frame')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        last_mtime = 0
        try:
            while not self.server.stop_event.is_set():
                try:
                    if not os.path.isfile(fpv_path):
                        time.sleep(0.5)
                        continue
                    mtime = os.path.getmtime(fpv_path)
                    if mtime == last_mtime:
                        time.sleep(0.2)
                        continue
                    last_mtime = mtime
                    with open(fpv_path, 'rb') as f:
                        data = f.read()
                    if len(data) < 50:
                        continue
                    self.wfile.write(b'--frame\r\n')
                    self.wfile.write(b'Content-Type: image/png\r\n')
                    self.wfile.write(
                        f'Content-Length: {len(data)}\r\n\r\n'.encode())
                    self.wfile.write(data)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                except OSError:
                    time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_agents(self):
        """Serve agent status (approved, pending, info)."""
        mgr = getattr(self.server, 'agent_manager', None)
        if not mgr:
            self._send_json({"approved": {}, "pending": {}, "info": {}})
            return
        approved = mgr.approved()
        self._send_json({
            "approved": approved,
            "pending": mgr.pending(),
            "info": {aid: mgr.agent_info(aid) for aid in approved},
        })

    def _serve_agent_detections(self, qs):
        """Serve recent detections forwarded from mesh agents."""
        try:
            limit = int(qs.get('limit', ['200'])[0])
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(limit, 1000))
        rows = fetch_agent_detections(self.server.output_dir, limit=limit)
        self._send_json({"detections": rows, "total": len(rows)})

    def _agents_approve(self, data):
        """Approve a pending agent."""
        mgr = getattr(self.server, 'agent_manager', None)
        if not mgr:
            self.send_error(503, "no agent manager")
            return
        aid = data.get('agent_id')
        if not aid:
            self.send_error(400, "agent_id required")
            return
        mgr.approve(aid)
        self._send_json({"ok": True})

    def _agents_cmd(self, data):
        """Send a command to an agent."""
        mgr = getattr(self.server, 'agent_manager', None)
        if not mgr:
            self.send_error(503, "no agent manager")
            return
        aid = data.get('agent_id')
        verb = data.get('verb')
        args = data.get('args') or []
        if not aid or not verb:
            self.send_error(400, "agent_id and verb required")
            return
        mgr.send_cmd(aid, verb, args)
        self._send_json({"ok": True})

    def _agents_cfg(self, data):
        """Send a config parameter to an agent."""
        mgr = getattr(self.server, 'agent_manager', None)
        if not mgr:
            self.send_error(503, "no agent manager")
            return
        aid = data.get('agent_id')
        key = data.get('key')
        value = data.get('value')
        if not (aid and key):
            self.send_error(400, "agent_id and key required")
            return
        mgr.send_cfg(aid, key, str(value))
        self._send_json({"ok": True})


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


def start_web_server_background(output_dir, port=8080, agent_manager=None):
    """Start web server in a background daemon thread (for embedding in server).

    Args:
        output_dir: Directory to serve dashboard data from
        port: HTTP port to listen on
        agent_manager: Optional AgentManager instance to expose via /api/agents
    """
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
    server.agent_manager = agent_manager

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="web-ui",
    )
    thread.start()
    return thread

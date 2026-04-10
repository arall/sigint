"""
Web Dashboard — lightweight HTTP server for viewing signal detections.

Serves a single-page dashboard that reads CSV detection logs and audio
files from the output directory. Auto-refreshes to show live data when
running alongside the server.

Two entry points:
- run_web_server(output_dir, port)           — standalone, blocking
- start_web_server_background(output_dir, port) — daemon thread for server embedding

No external dependencies — uses only Python stdlib (http.server, json, csv).
"""

import csv
import json
import os
import threading
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse


def _read_detections(output_dir, limit=200, signal_type=None):
    """Read recent detections from all CSV files in output_dir."""
    detections = []
    csv_files = sorted(
        [f for f in os.listdir(output_dir) if f.endswith('.csv')],
        reverse=True,
    )
    for csv_file in csv_files:
        csv_path = os.path.join(output_dir, csv_file)
        try:
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if signal_type and row.get('signal_type') != signal_type:
                        continue
                    detections.append(row)
        except Exception:
            continue
    # Sort by timestamp descending, limit
    detections.sort(key=lambda d: d.get('timestamp', ''), reverse=True)
    return detections[:limit]


def _read_server_info(output_dir):
    """Read server_info.json if present."""
    info_path = os.path.join(output_dir, 'server_info.json')
    if os.path.exists(info_path):
        try:
            with open(info_path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _get_signal_types(output_dir):
    """Get unique signal types from CSV files."""
    types = set()
    for csv_file in os.listdir(output_dir):
        if not csv_file.endswith('.csv'):
            continue
        try:
            with open(os.path.join(output_dir, csv_file), 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('signal_type'):
                        types.add(row['signal_type'])
        except Exception:
            continue
    return sorted(types)


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SIGINT Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, 'Segoe UI', Roboto, monospace;
    background: #0a0a0a; color: #e0e0e0;
    padding: 16px; font-size: 14px;
  }
  h1 { color: #4fc3f7; margin-bottom: 4px; font-size: 20px; }
  .subtitle { color: #666; font-size: 12px; margin-bottom: 16px; }
  .controls {
    display: flex; gap: 12px; align-items: center;
    margin-bottom: 16px; flex-wrap: wrap;
  }
  .controls label { color: #888; font-size: 12px; }
  .controls select, .controls button {
    background: #1a1a1a; color: #e0e0e0; border: 1px solid #333;
    padding: 4px 8px; border-radius: 4px; font-size: 13px;
  }
  .controls button { cursor: pointer; }
  .controls button:hover { border-color: #4fc3f7; }
  .auto-refresh { color: #4caf50; font-size: 12px; }
  .auto-refresh.paused { color: #f44336; }

  .info-bar {
    background: #111; border: 1px solid #222; border-radius: 6px;
    padding: 10px 14px; margin-bottom: 16px; font-size: 12px;
  }
  .info-bar .label { color: #666; }
  .info-bar .value { color: #4fc3f7; }

  .stats {
    display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap;
  }
  .stat {
    background: #111; border: 1px solid #222; border-radius: 6px;
    padding: 10px 14px; min-width: 120px;
  }
  .stat .n { font-size: 24px; color: #4fc3f7; font-weight: bold; }
  .stat .label { font-size: 11px; color: #666; }

  table { width: 100%; border-collapse: collapse; }
  th {
    text-align: left; padding: 8px 10px; background: #111;
    color: #888; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; border-bottom: 1px solid #222;
    position: sticky; top: 0;
  }
  td {
    padding: 6px 10px; border-bottom: 1px solid #1a1a1a;
    font-size: 13px; white-space: nowrap;
  }
  tr:hover { background: #111; }
  .freq { color: #ff9800; }
  .snr { color: #4caf50; }
  .snr.low { color: #f44336; }
  .channel { color: #ce93d8; }
  .type { color: #4fc3f7; }
  .time { color: #666; }
  .audio-btn {
    background: #1b5e20; color: #a5d6a7; border: none;
    padding: 2px 8px; border-radius: 3px; cursor: pointer;
    font-size: 11px;
  }
  .audio-btn:hover { background: #2e7d32; }
  .audio-btn.playing { background: #c62828; color: #ffcdd2; }
  .meta { color: #555; max-width: 300px; overflow: hidden; text-overflow: ellipsis; }
  .empty { text-align: center; padding: 40px; color: #444; }
</style>
</head>
<body>

<h1>SIGINT Dashboard</h1>
<div class="subtitle" id="server-info">Loading...</div>

<div class="controls">
  <label>Filter: </label>
  <select id="type-filter"><option value="">All types</option></select>
  <button onclick="refresh()">Refresh</button>
  <span class="auto-refresh" id="auto-status">Auto-refresh: 5s</span>
</div>

<div class="stats" id="stats"></div>

<table>
  <thead>
    <tr>
      <th>Time</th>
      <th>Type</th>
      <th>Channel</th>
      <th>Frequency</th>
      <th>SNR</th>
      <th>Power</th>
      <th>Audio</th>
      <th>Info</th>
    </tr>
  </thead>
  <tbody id="detections"></tbody>
</table>
<div class="empty" id="empty" style="display:none">No detections yet</div>

<script>
let currentAudio = null;
let currentBtn = null;
const typeFilter = document.getElementById('type-filter');

function formatFreq(hz) {
  const f = parseFloat(hz);
  if (f >= 1e9) return (f/1e9).toFixed(3) + ' GHz';
  if (f >= 1e6) return (f/1e6).toFixed(3) + ' MHz';
  if (f >= 1e3) return (f/1e3).toFixed(1) + ' kHz';
  return f.toFixed(0) + ' Hz';
}

function formatTime(ts) {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString();
  } catch(e) { return ts; }
}

function parseMeta(s) {
  try { return JSON.parse(s); } catch(e) { return null; }
}

function playAudio(btn, file) {
  if (currentAudio && currentBtn === btn) {
    currentAudio.pause();
    currentAudio = null;
    btn.textContent = 'Play';
    btn.classList.remove('playing');
    currentBtn = null;
    return;
  }
  if (currentAudio) {
    currentAudio.pause();
    if (currentBtn) { currentBtn.textContent = 'Play'; currentBtn.classList.remove('playing'); }
  }
  currentAudio = new Audio('/audio/' + file);
  currentBtn = btn;
  btn.textContent = 'Stop';
  btn.classList.add('playing');
  currentAudio.onended = () => { btn.textContent = 'Play'; btn.classList.remove('playing'); currentAudio = null; currentBtn = null; };
  currentAudio.play();
}

async function refresh() {
  const filter = typeFilter.value;
  const params = filter ? '?signal_type=' + filter : '';
  try {
    const [detResp, infoResp] = await Promise.all([
      fetch('/api/detections' + params),
      fetch('/api/info'),
    ]);
    const data = await detResp.json();
    const info = await infoResp.json();

    // Server info
    const infoEl = document.getElementById('server-info');
    if (info.started) {
      const captures = (info.captures || []).map(c => c.name || c.type).join(', ');
      infoEl.textContent = 'Started: ' + new Date(info.started).toLocaleString() + (captures ? ' | Captures: ' + captures : '');
    } else {
      infoEl.textContent = 'Standalone mode (reading from output directory)';
    }

    // Type filter options
    if (data.signal_types) {
      const current = typeFilter.value;
      typeFilter.innerHTML = '<option value="">All types</option>';
      data.signal_types.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t; opt.textContent = t;
        if (t === current) opt.selected = true;
        typeFilter.appendChild(opt);
      });
    }

    // Stats
    const stats = document.getElementById('stats');
    const counts = {};
    (data.detections || []).forEach(d => {
      counts[d.signal_type] = (counts[d.signal_type] || 0) + 1;
    });
    stats.innerHTML = '<div class="stat"><div class="n">' + (data.detections || []).length + '</div><div class="label">Total</div></div>';
    Object.entries(counts).sort((a,b) => b[1]-a[1]).forEach(([t, n]) => {
      stats.innerHTML += '<div class="stat"><div class="n">' + n + '</div><div class="label">' + t + '</div></div>';
    });

    // Detections table
    const tbody = document.getElementById('detections');
    const empty = document.getElementById('empty');
    const rows = data.detections || [];
    if (rows.length === 0) {
      tbody.innerHTML = '';
      empty.style.display = 'block';
      return;
    }
    empty.style.display = 'none';
    tbody.innerHTML = rows.map(d => {
      const snr = parseFloat(d.snr_db) || 0;
      const snrClass = snr < 10 ? 'snr low' : 'snr';
      const meta = parseMeta(d.metadata);
      let metaStr = '';
      if (meta) {
        if (meta.transcript) metaStr = meta.transcript;
        else if (meta.duration_s) metaStr = meta.duration_s + 's';
        if (meta.band && !metaStr.includes(meta.band)) metaStr = (metaStr ? metaStr + ' | ' : '') + meta.band;
      }
      const audioBtn = d.audio_file
        ? '<button class="audio-btn" onclick="playAudio(this,\'' + d.audio_file.replace(/'/g, "\\'") + '\')">Play</button>'
        : '';
      return '<tr>' +
        '<td class="time">' + formatTime(d.timestamp) + '</td>' +
        '<td class="type">' + (d.signal_type || '') + '</td>' +
        '<td class="channel">' + (d.channel || '') + '</td>' +
        '<td class="freq">' + formatFreq(d.frequency_hz) + '</td>' +
        '<td class="' + snrClass + '">' + snr.toFixed(1) + ' dB</td>' +
        '<td>' + (parseFloat(d.power_db) || 0).toFixed(1) + ' dB</td>' +
        '<td>' + audioBtn + '</td>' +
        '<td class="meta">' + metaStr + '</td>' +
        '</tr>';
    }).join('');
  } catch(e) {
    console.error('Refresh failed:', e);
  }
}

typeFilter.onchange = refresh;
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler for the SIGINT web dashboard."""

    output_dir = "output"

    def log_message(self, format, *args):
        """Suppress default access logs."""
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/' or path == '/index.html':
            self._serve_html()
        elif path == '/api/detections':
            self._serve_detections(parsed.query)
        elif path == '/api/info':
            self._serve_info()
        elif path.startswith('/audio/'):
            self._serve_audio(path[7:])  # strip '/audio/'
        else:
            self.send_error(404)

    def _serve_html(self):
        content = DASHBOARD_HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_detections(self, query_string):
        params = parse_qs(query_string)
        signal_type = params.get('signal_type', [None])[0]
        if signal_type == '':
            signal_type = None
        detections = _read_detections(
            self.output_dir, limit=200, signal_type=signal_type)
        signal_types = _get_signal_types(self.output_dir)
        data = json.dumps({
            'detections': detections,
            'signal_types': signal_types,
        })
        content = data.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_info(self):
        info = _read_server_info(self.output_dir) or {}
        content = json.dumps(info).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_audio(self, filename):
        # Sanitize: no path traversal
        filename = os.path.basename(filename)
        audio_dir = os.path.join(self.output_dir, 'audio')
        filepath = os.path.join(audio_dir, filename)
        if not os.path.isfile(filepath):
            self.send_error(404)
            return
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_error(500)


def run_web_server(output_dir, port=8080):
    """Run the web dashboard server (blocking)."""
    output_dir = os.path.abspath(output_dir)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    DashboardHandler.output_dir = output_dir
    server = HTTPServer(('0.0.0.0', port), DashboardHandler)
    print(f"[WEB] Dashboard: http://0.0.0.0:{port}/")
    print(f"[WEB] Serving detections from: {output_dir}")
    print(f"[WEB] Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WEB] Stopped")
    finally:
        server.server_close()


def start_web_server_background(output_dir, port=8080):
    """Start the web dashboard in a daemon thread (non-blocking)."""
    output_dir = os.path.abspath(output_dir)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    DashboardHandler.output_dir = output_dir
    server = HTTPServer(('0.0.0.0', port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

"""
Web dashboard package — standalone or embedded HTTP server that tails the
current SQLite detection log and serves a category-grouped UI.

Split into:
  categories.py  — signal-type → real-world category mapping
  loaders.py     — pure functions that shape deque rows for the Devices
                   tab and the per-category tabs
  tailer.py      — DBTailer (polls the newest .db file by rowid) and
                   system stats + detail extractors
  server.py      — HTTP handler, static file serving, public entry points
  static/        — index.html, style.css, app.js
"""

from .server import run_web_server, start_web_server_background

__all__ = ["run_web_server", "start_web_server_background"]

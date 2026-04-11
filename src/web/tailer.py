"""
DBTailer — tracks which SQLite detection file is currently "live" and
keeps a refreshed Live-tab state snapshot for the SSE broadcaster.

After the SQL-first migration, the tailer is no longer a detection
state machine (it used to keep a 50k in-memory deque + per-type
counters + activity histogram + recent events + BSSID map, all
reconstructed by replaying every row). Those are all computed on
demand by `web/fetch.py` from SQL now — so the tailer is a thin
watcher plus a state cache:

  - `_tailing_db` / `_db_name`   — newest .db in the output dir, for
                                    the header "DB" display
  - `_cached_state`              — result of `fetch_live_state(...)`,
                                    refreshed on a background thread
                                    every ~2s so SSE + /api/state are
                                    sub-millisecond reads despite the
                                    underlying query being ~200ms

Transcripts now live in each session's `.db` (`transcripts` table),
read directly by `web/fetch.py` at query time — no sidecar poll here.

Also hosts two stateless helpers used by `web/fetch.py`:

  _extract_detail — per-signal-type one-line summary for Log/Live
  _extract_uid    — per-signal-type unique identifier for uniques
                    counting (SQL query in fetch._UNIQUES_SQL has
                    to stay in sync with this)
"""

import os
import threading
import time
from datetime import datetime, timedelta


STATE_REFRESH_INTERVAL_S = 2.0   # matches SSE cadence


def _get_system_stats():
    """Read CPU, memory, and disk stats from /proc and os (Linux)."""
    stats = {}
    try:
        load1, _, _ = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        stats["load"] = round(load1, 2)
        stats["cpu_pct"] = round(load1 / cpu_count * 100, 1)

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

        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                stats["cpu_temp"] = round(int(f.read().strip()) / 1000, 1)
        except (FileNotFoundError, ValueError):
            pass

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


class DBTailer:
    """Thin watcher for the output directory + Live-tab state cache."""

    def __init__(self, output_dir):
        self.output_dir = output_dir
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._start_time = time.time()

        # Current session tracking — used for the header "DB" display
        # and (indirectly) to decide which file to tail.
        self._tailing_db = None
        self._db_name = ""

        # Cached Live-tab state, refreshed by the background thread.
        self._cached_state = {
            "detection_count": 0,
            "signals": [],
            "categories": [],
            "recent": [],
        }

        # Read-error deduplication (one warning per path)
        self._read_errors = set()

    def start(self):
        """Start the background state-refresh thread."""
        t = threading.Thread(target=self._run, daemon=True, name="db-tailer")
        t.start()
        return t

    def stop(self):
        self._stop.set()

    def _find_all_dbs(self):
        """Return all session .db files in output_dir sorted by mtime.
        Excludes support DBs like devices.db (persona store)."""
        from .sessions import is_session_db_name
        try:
            dbs = [
                os.path.join(self.output_dir, f)
                for f in os.listdir(self.output_dir)
                if is_session_db_name(f)
            ]
            return sorted(dbs, key=os.path.getmtime)
        except OSError:
            return []

    def _update_tailing_db(self):
        """Pick the newest .db file and expose its basename."""
        all_dbs = self._find_all_dbs()
        latest = all_dbs[-1] if all_dbs else None
        with self._lock:
            if latest != self._tailing_db:
                self._tailing_db = latest
                self._db_name = os.path.basename(latest) if latest else ""

    def _refresh_state(self):
        """Recompute the cached Live-tab state from SQL. Cheap enough at
        ~200ms on 10k-row DBs to run every 2s on the background thread."""
        from .fetch import fetch_live_state
        try:
            new_state = fetch_live_state(self.output_dir)
        except Exception as e:
            self._warn_read_error("<live_state>", e)
            return
        with self._lock:
            self._cached_state = new_state

    def _run(self):
        """Background loop: pick latest .db, refresh cached state."""
        while not self._stop.is_set():
            self._update_tailing_db()
            self._refresh_state()
            self._stop.wait(STATE_REFRESH_INTERVAL_S)

    def _warn_read_error(self, path, err):
        """Print a single warning per read failure key. Dedup so we don't
        flood the log."""
        if path in self._read_errors:
            return
        self._read_errors.add(path)
        print(f"[WEB] read error ({path}): {err}")
        if isinstance(path, str) and path.endswith(".db"):
            print(f"[WEB]   usual cause: output dir not writable by the web user "
                  "(SQLite WAL needs to create sidecar files)")
            print(f"[WEB]   fix: sudo chmod 777 {os.path.dirname(path) or '.'}  "
                  "or restart the server so it re-applies the umask patch")

    # --- public API ---

    def get_state(self):
        """Return the cached dashboard state merged with live counters
        (time, uptime, db filename, /proc snapshot). Sub-millisecond
        because everything is in-memory; the real work happens on the
        background refresh thread."""
        uptime = timedelta(seconds=int(time.time() - self._start_time))
        with self._lock:
            state = dict(self._cached_state)
            db_name = self._db_name
        state["time"] = datetime.now().strftime("%H:%M:%S")
        state["uptime"] = str(uptime)
        state["gps"] = None
        state["db"] = db_name
        state["captures"] = []
        state["system"] = _get_system_stats()
        return state


def _extract_detail(sig, channel, meta):
    """Extract a short detail string from metadata (mirrors server.py logic)."""
    if sig == "BLE-Adv":
        parts = []
        pid = meta.get("persona_id")
        if pid:
            parts.append(pid)
        name = meta.get("name")
        if name:
            parts.append(f'"{name[:24]}"')
        apple = meta.get("apple_device")
        mfr = meta.get("manufacturer")
        if apple:
            parts.append(f"[{apple}]")
        elif mfr:
            parts.append(f"[{mfr[:18]}]")
        mac = meta.get("mac")
        if mac:
            parts.append(mac)
        if meta.get("randomized"):
            parts.append("rand")
        prior = meta.get("prior_sessions", 0)
        if prior:
            parts.append(f"seen {prior}x")
        return " ".join(parts)
    elif sig == "WiFi-Probe":
        parts = []
        pid = meta.get("persona_id")
        if pid:
            parts.append(pid)
        ssids = meta.get("ssids") or []
        if isinstance(ssids, list) and ssids:
            s = ", ".join(ssids[:3])
            if len(ssids) > 3:
                s += f" +{len(ssids) - 3}"
            parts.append(f'"{s[:40]}"')
        else:
            ssid = meta.get("ssid")
            if ssid:
                parts.append(f'"{ssid[:24]}"')
        mfr = meta.get("manufacturer")
        device = meta.get("device")
        if device and device != mfr:
            parts.append(f"[{device[:18]}]")
        elif mfr:
            parts.append(f"[{mfr[:18]}]")
        mac = meta.get("mac")
        if mac:
            parts.append(mac)
        if meta.get("randomized"):
            parts.append("rand")
        prior = meta.get("prior_sessions", 0)
        if prior:
            parts.append(f"seen {prior}x")
        return " ".join(parts)
    elif sig == "WiFi-AP":
        ssid = meta.get("ssid") or "(hidden)"
        crypto = meta.get("crypto", "")
        mfr = meta.get("manufacturer", "")
        bssid = meta.get("bssid", "")
        parts = [ssid[:28]]
        if bssid:
            parts.append(bssid)
        if crypto:
            parts.append(crypto)
        if mfr:
            parts.append(f"[{mfr[:20]}]")
        return " ".join(parts)
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
    """Extract unique device ID from a detection row.

    NOTE: kept in sync with `fetch._UNIQUES_SQL`. If you change the
    keys here, update the CASE expression there (or vice versa) so the
    Live tab's per-type unique counts stay consistent with the Log tab's.
    """
    if sig == "BLE-Adv":
        return meta.get("persona_id") or row.get("channel", "")
    elif sig == "WiFi-Probe":
        return meta.get("persona_id") or row.get("device_id", "")
    elif sig == "WiFi-AP":
        return meta.get("bssid") or row.get("device_id", "")
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

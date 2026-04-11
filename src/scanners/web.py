"""
Standalone web UI for the SDR server dashboard.

Reads detection data from SQLite DB files in the output directory and
serves a live dashboard via HTTP. Runs independently of the SDR server —
works while captures are running or for reviewing historical data.

Usage:
    python3 sdr.py web                    # serve output/ on :8080
    python3 sdr.py web -p 9090            # custom port
    python3 sdr.py web -d /path/to/output # custom output directory

Routes:
    GET /                  — HTML dashboard (tabs: live, log, personas, config, timeline)
    GET /api/state         — JSON dashboard summary
    GET /api/events        — SSE live updates (state JSON every 2s)
    GET /api/detections    — Individual detection list (newest first, filterable)
    GET /api/activity      — Per-minute detection counts
    GET /audio/<filename>  — Serve recorded WAV files
"""

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
# Category map — groups signal types into real-world domains so the
# dashboard can show dedicated tabs (Voice / Drones / Aircraft / Vessels /
# Vehicles / Cellular / Devices / Other) instead of one flat firehose.
# Anything not listed falls into "other".
# ---------------------------------------------------------------------------

CATEGORIES = {
    "voice": [
        "PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS", "FM_voice",
    ],
    "drones": [
        "RemoteID", "RemoteID-operator", "DroneCtrl", "DroneVideo",
    ],
    "aircraft": ["ADS-B"],
    "vessels":  ["AIS"],
    "vehicles": ["tpms", "keyfob"],
    "cellular": [
        "GSM-UPLINK-GSM-900", "GSM-UPLINK-GSM-850", "LTE-UPLINK",
    ],
    "devices": [
        "BLE-Adv", "WiFi-Probe", "WiFi-AP",
    ],
    "other": [
        "ISM", "lora", "pocsag",
    ],
}

CATEGORY_LABELS = {
    "voice":    "Voice",
    "drones":   "Drones",
    "aircraft": "Aircraft",
    "vessels":  "Vessels",
    "vehicles": "Vehicles",
    "cellular": "Cellular",
    "devices":  "Devices",
    "other":    "Other",
}

CATEGORY_ORDER = [
    "voice", "drones", "aircraft", "vessels",
    "vehicles", "cellular", "devices", "other",
]

TYPE_TO_CATEGORY = {sig: cat for cat, sigs in CATEGORIES.items() for sig in sigs}


def _category_of(signal_type):
    """Map a raw signal_type string to a category id. Handles wildcards
    (e.g. GSM-UPLINK-* → cellular) so new-subtypes don't fall through."""
    if signal_type in TYPE_TO_CATEGORY:
        return TYPE_TO_CATEGORY[signal_type]
    if signal_type.startswith("GSM-UPLINK") or signal_type.startswith("LTE-UPLINK"):
        return "cellular"
    return "other"


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
# Device loaders — read persona / AP JSON databases and shape them for the
# Devices tab. Three categories: WiFi APs, WiFi Clients, BLE.
# ---------------------------------------------------------------------------

def _load_wifi_clients(output_dir, active_sigs=None):
    """Read personas.json and return WiFi client device records.

    A WiFi client is a phone/laptop that emits probe requests. The label is
    manufacturer+fingerprint (NOT the SSID — that's what the client is probing
    FOR, not its identity).
    """
    active_sigs = active_sigs or {}
    path = os.path.join(output_dir, "personas.json")
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    clients = []
    for key, p in data.get("personas", {}).items():
        dev_sig = p.get("dev_sig", key.split(":")[0])
        persona_key = key
        macs = p.get("macs_seen", []) or []
        ssids = p.get("ssids", []) or []
        manufacturer = p.get("manufacturer") or ""
        randomized = p.get("randomized", False)

        active_info = active_sigs.get(dev_sig, {})

        if manufacturer:
            label = manufacturer
        elif macs and not randomized:
            label = macs[0]
        else:
            label = f"anon:{dev_sig[:8]}" if dev_sig else "anon"

        clients.append({
            "persona_key": persona_key,
            "dev_sig": dev_sig,
            "label": label,
            "manufacturer": manufacturer,
            "randomized": randomized,
            "macs": macs,
            "mac_count": len(macs),
            "ssids": ssids,
            "ssid_count": len(ssids),
            "sessions": p.get("sessions", 0),
            "total_probes": p.get("total_probes", 0),
            "first_session": p.get("first_session", ""),
            "last_session": p.get("last_session", ""),
            "active": bool(active_info),
            "last_rssi": active_info.get("rssi"),
        })

    clients.sort(key=lambda c: (
        c["active"], c["last_session"], c["total_probes"],
    ), reverse=True)
    return clients


def _load_ble_devices(output_dir, active_sigs=None):
    """Read personas_bt.json and return BLE device records."""
    active_sigs = active_sigs or {}
    path = os.path.join(output_dir, "personas_bt.json")
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    devices = []
    for key, p in data.get("personas", {}).items():
        dev_sig = p.get("dev_sig", key.split(":")[0])
        persona_key = key
        macs = p.get("macs_seen", []) or []
        names = p.get("ssids", []) or []  # BLE advertised names reuse "ssids"
        manufacturer = p.get("manufacturer") or ""
        randomized = p.get("randomized", False)

        active_info = active_sigs.get(dev_sig, {})
        # Prefer the persisted apple_device (survives restart); fall back to
        # the value captured from recent live detections.
        apple_device = p.get("apple_device") or active_info.get("apple_device", "")

        if apple_device:
            label = apple_device
        elif names:
            label = names[0]
        elif manufacturer:
            label = manufacturer
        elif macs and not randomized:
            label = macs[0]
        else:
            label = f"anon:{dev_sig[:8]}" if dev_sig else "anon"

        devices.append({
            "persona_key": persona_key,
            "dev_sig": dev_sig,
            "label": label,
            "manufacturer": manufacturer,
            "apple_device": apple_device,
            "randomized": randomized,
            "macs": macs,
            "mac_count": len(macs),
            "names": names,
            "sessions": p.get("sessions", 0),
            "total_probes": p.get("total_probes", 0),
            "first_session": p.get("first_session", ""),
            "last_session": p.get("last_session", ""),
            "active": bool(active_info),
            "last_rssi": active_info.get("rssi"),
        })

    devices.sort(key=lambda d: (
        d["active"], d["last_session"], d["total_probes"],
    ), reverse=True)
    return devices


def _load_wifi_aps(output_dir, active_bssids=None):
    """Read aps.json and return WiFi AP records grouped by physical AP.

    Conservative grouping heuristic: two BSSIDs are merged into the same
    physical AP row if they share a non-empty SSID AND their first 5 MAC
    octets match (covers the common 2.4/5 GHz radio pattern where vendors
    increment only the last octet). Anything else stays ungrouped.
    """
    active_bssids = active_bssids or {}
    path = os.path.join(output_dir, "aps.json")
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    ap_map = data.get("aps", {})
    groups = []  # list of dicts with {"group_key", "bssids": [...]}

    def group_key(rec):
        ssids = rec.get("ssids", []) or []
        bssid = (rec.get("bssid") or "").lower()
        if not ssids or not bssid or rec.get("hidden"):
            return ("bssid", bssid)
        prefix = ":".join(bssid.split(":")[:5])
        primary_ssid = ssids[0]
        return ("grp", primary_ssid, prefix)

    buckets = {}
    for bssid, rec in ap_map.items():
        rec = dict(rec)
        rec["bssid"] = bssid
        active = active_bssids.get(bssid, {})
        rec["active"] = bool(active)
        if active.get("rssi") is not None:
            rec["last_rssi"] = active["rssi"]
        k = group_key(rec)
        buckets.setdefault(k, []).append(rec)

    for k, members in buckets.items():
        members.sort(key=lambda r: r.get("bssid", ""))
        ssids_union = []
        channels_union = []
        clients_union = set()
        for m in members:
            for s in m.get("ssids", []) or []:
                if s not in ssids_union:
                    ssids_union.append(s)
            for c in m.get("channels", []) or []:
                if c not in channels_union:
                    channels_union.append(c)
            for cl in m.get("clients", []) or []:
                clients_union.add(cl)
        channels_union.sort()

        any_24 = any(c <= 14 for c in channels_union)
        any_5 = any(c >= 32 for c in channels_union)
        bands = []
        if any_24:
            bands.append("2.4")
        if any_5:
            bands.append("5")

        label = ssids_union[0] if ssids_union else "(hidden)"
        manufacturers = [m.get("manufacturer") for m in members if m.get("manufacturer")]
        manufacturer = manufacturers[0] if manufacturers else ""
        crypto = next((m.get("crypto") for m in members if m.get("crypto")), "")
        total_beacons = sum(int(m.get("total_beacons", 0)) for m in members)
        sessions = max(int(m.get("sessions", 0)) for m in members)
        rssis = [m.get("last_rssi") for m in members if m.get("last_rssi") is not None]
        last_rssi = max(rssis) if rssis else None
        first_seen = min((m.get("first_seen", "") for m in members if m.get("first_seen")), default="")
        last_seen = max((m.get("last_seen", "") for m in members if m.get("last_seen")), default="")
        hidden = all(m.get("hidden") for m in members)
        active = any(m.get("active") for m in members)

        groups.append({
            "group_key": "|".join(str(x) for x in k),
            "label": label,
            "ssids": ssids_union,
            "bssids": members,
            "bssid_count": len(members),
            "channels": channels_union,
            "bands": bands,
            "crypto": crypto,
            "manufacturer": manufacturer,
            "hidden": hidden,
            "total_beacons": total_beacons,
            "sessions": sessions,
            "last_rssi": last_rssi,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "active": active,
            "clients": sorted(clients_union),
            "client_count": len(clients_union),
        })

    groups.sort(key=lambda g: (
        g["active"], g["last_seen"], g["total_beacons"],
    ), reverse=True)
    return groups


# ---------------------------------------------------------------------------
# DB tailer — watches the output directory for the latest .db and tails it
# ---------------------------------------------------------------------------

class DBTailer:
    """Watches the output directory for .db files, tails the latest by
    rowid, and builds the live dashboard state."""

    def __init__(self, output_dir):
        self.output_dir = output_dir
        self._lock = threading.Lock()
        self._stop = threading.Event()

        # State
        self._detections = deque(maxlen=50000)
        self._recent_bssids = {}  # bssid -> {"rssi": float, "last_seen": iso}
        self._type_counts = Counter()
        self._type_last_seen = {}
        self._type_last_snr = {}
        self._type_last_detail = {}
        self._type_uniques = {}
        self._recent_events = deque(maxlen=20)
        self._activity_minutes = {}
        self._db_name = ""
        self._start_time = time.time()

        # DB tracking — which files we've already fully loaded, and the
        # rowid cursor for the currently tailing file.
        self._loaded_dbs = set()
        self._tailing_db = None
        self._tail_last_id = 0

        # Transcript sidecar — lets detections appear immediately and get
        # text back-filled later when the async transcriber finishes.
        self._transcripts = {}      # basename(audio_file) -> transcript text
        self._transcripts_mtime = 0

    def start(self):
        """Start background thread that tails DB files."""
        t = threading.Thread(target=self._run, daemon=True, name="db-tailer")
        t.start()
        return t

    def stop(self):
        self._stop.set()

    def _find_all_dbs(self):
        """Find all .db files in output_dir, sorted by mtime."""
        try:
            dbs = [
                os.path.join(self.output_dir, f)
                for f in os.listdir(self.output_dir)
                if f.endswith('.db') and not f.endswith('-wal') and not f.endswith('-shm')
            ]
            return sorted(dbs, key=os.path.getmtime)
        except OSError:
            return []

    def _read_full_db(self, path):
        """Read every row from a historical DB file once."""
        try:
            from utils import db as _db
            conn = _db.connect(path, readonly=True)
        except Exception:
            return
        try:
            for row in _db.iter_detections(conn):
                self._process_row(_db.row_to_dict(row))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _tail_db(self, path):
        """Poll the latest DB for rows with id > last seen and feed them."""
        try:
            from utils import db as _db
            conn = _db.connect(path, readonly=True)
        except Exception:
            return
        try:
            rows = list(_db.iter_detections(conn, since_rowid=self._tail_last_id))
            for row in rows:
                self._process_row(_db.row_to_dict(row))
                if row["id"] > self._tail_last_id:
                    self._tail_last_id = row["id"]
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _run(self):
        """Background loop: read any new DB files, tail the latest for new rows."""
        # Preload existing transcripts so the first replay sees them
        self._poll_transcripts()
        while not self._stop.is_set():
            all_dbs = self._find_all_dbs()

            # Read any historical DB files we haven't seen yet, EXCEPT the
            # latest one (which we'll tail instead to pick up live writes).
            latest = all_dbs[-1] if all_dbs else None
            for db_path in all_dbs:
                if db_path in self._loaded_dbs:
                    continue
                if db_path == latest:
                    continue  # will tail from rowid 0 below
                self._read_full_db(db_path)
                self._loaded_dbs.add(db_path)

            # Tail the latest DB for new rows
            if latest:
                if self._tailing_db != latest:
                    self._tailing_db = latest
                    self._tail_last_id = 0  # start from beginning of the new file
                    self._db_name = os.path.basename(latest)
                self._tail_db(latest)

            self._poll_transcripts()
            self._stop.wait(1.0)

    def _poll_transcripts(self):
        """Reload transcripts.json if it changed and back-fill detections."""
        path = os.path.join(self.output_dir, "transcripts.json")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        if mtime == self._transcripts_mtime:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
        except (OSError, json.JSONDecodeError):
            return
        self._transcripts_mtime = mtime

        # Figure out which keys are new relative to last time
        new_keys = {k: v for k, v in data.items() if self._transcripts.get(k) != v}
        self._transcripts = data
        if not new_keys:
            return

        # Back-fill already-seen detections whose audio file now has a transcript
        with self._lock:
            for d in self._detections:
                af = d.get("audio_file")
                if not af:
                    continue
                t = new_keys.get(af)
                if t and d.get("transcript") != t:
                    d["transcript"] = t
                    # Refresh detail string for the Log tab
                    sig = d.get("signal_type", "")
                    if sig in ("PMR446", "dPMR", "70cm", "MarineVHF",
                               "2m", "FRS", "FM_voice"):
                        d["detail"] = f'"{t[:60]}"'
                        self._type_last_detail[sig] = d["detail"]

    def _process_row(self, row):
        """Process a single detection row into internal state."""
        sig = row.get("signal_type", "")
        if not sig:
            return

        try:
            snr = float(row.get("snr_db", 0))
        except (ValueError, TypeError):
            snr = 0
        try:
            power_db = float(row.get("power_db", 0))
        except (ValueError, TypeError):
            power_db = 0
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
        transcript = meta.get("transcript")
        # Overlay any already-known sidecar transcript
        if audio_file and not transcript:
            sidecar = self._transcripts.get(audio_file)
            if sidecar:
                transcript = sidecar
                meta["transcript"] = sidecar
        detail = _extract_detail(sig, ch, meta)

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

            # Track active WiFi APs by BSSID
            if sig == "WiFi-AP":
                bssid = meta.get("bssid") or row.get("device_id", "")
                if bssid:
                    self._recent_bssids[bssid] = {
                        "rssi": power_db if power_db else None,
                        "last_seen": ts,
                    }

            # Track unique IDs
            uid = _extract_uid(sig, row, meta)
            if uid:
                if sig not in self._type_uniques:
                    self._type_uniques[sig] = set()
                self._type_uniques[sig].add(uid)

            # Detection buffer
            try:
                lat = float(row.get("latitude") or 0) or None
            except (ValueError, TypeError):
                lat = None
            try:
                lon = float(row.get("longitude") or 0) or None
            except (ValueError, TypeError):
                lon = None
            self._detections.append({
                "timestamp": ts,
                "signal_type": sig,
                "category": _category_of(sig),
                "frequency_mhz": round(freq / 1e6, 4) if freq else 0,
                "channel": ch,
                "snr_db": round(snr, 1) if snr > 0 else None,
                "power_db": power_db if power_db else None,
                "audio_file": audio_file if audio_file else None,
                "detail": detail,
                "transcript": transcript,
                "dev_sig": meta.get("dev_sig", ""),
                "apple_device": meta.get("apple_device", ""),
                "device_id": row.get("device_id", "") or meta.get("bssid", ""),
                "latitude": lat,
                "longitude": lon,
                "meta": meta,
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
                    "category": _category_of(sig),
                    "count": self._type_counts.get(sig, 0),
                    "uniques": len(self._type_uniques.get(sig, set())),
                    "last_seen": self._type_last_seen.get(sig),
                    "snr": self._type_last_snr.get(sig),
                    "detail": self._type_last_detail.get(sig, ""),
                })

            # Roll signals up into category summary rows for the Live tab
            cat_counts = Counter()
            cat_uniques = {}
            cat_last_seen = {}
            cat_types = {}
            for s in signals:
                c = s["category"]
                cat_counts[c] += s["count"]
                cat_uniques.setdefault(c, 0)
                cat_uniques[c] += s["uniques"]
                prev_ls = cat_last_seen.get(c, "")
                if s["last_seen"] and s["last_seen"] > prev_ls:
                    cat_last_seen[c] = s["last_seen"]
                cat_types.setdefault(c, []).append(s["type"])
            categories = []
            for c in CATEGORY_ORDER:
                if cat_counts.get(c, 0) == 0:
                    continue
                categories.append({
                    "id": c,
                    "label": CATEGORY_LABELS[c],
                    "count": cat_counts.get(c, 0),
                    "uniques": cat_uniques.get(c, 0),
                    "last_seen": cat_last_seen.get(c, ""),
                    "types": cat_types.get(c, []),
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
            "db": self._db_name,
            "captures": [],
            "signals": signals,
            "categories": categories,
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

    def get_active_bssids(self, minutes=5):
        """Return dict of bssid → info for APs seen in the last N minutes."""
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        active = {}
        with self._lock:
            for bssid, info in self._recent_bssids.items():
                if info.get("last_seen", "") >= cutoff:
                    active[bssid] = dict(info)
        return active

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
    """Extract unique device ID from a detection row."""
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


# ---------------------------------------------------------------------------
# Category loaders — each builds a shaped, domain-specific row list from
# the tailer's in-memory detection deque. Called by /api/cat/<name>.
# ---------------------------------------------------------------------------

def _fmt_ts_short(ts):
    """Format an ISO timestamp as 'MM-DD HH:MM:SS' for table rendering."""
    if not ts:
        return "-"
    parts = ts.split("T")
    if len(parts) < 2:
        return ts
    return parts[0][5:] + " " + parts[1].split(".")[0]


def _load_voice(detections):
    """Each voice detection already represents one finalized transmission —
    one row per detection, newest first."""
    rows = []
    voice_types = set(CATEGORIES["voice"])
    for d in reversed(detections):
        if d["signal_type"] not in voice_types:
            continue
        meta = d.get("meta") or {}
        rows.append({
            "timestamp": d["timestamp"],
            "signal_type": d["signal_type"],
            "channel": d["channel"],
            "frequency_mhz": d["frequency_mhz"],
            "duration_s": meta.get("duration_s"),
            "snr_db": d["snr_db"],
            "audio_file": d["audio_file"],
            "transcript": d["transcript"] or meta.get("transcript") or "",
            "language": meta.get("language", ""),
        })
        if len(rows) >= 200:
            break
    return rows


def _load_drones(detections):
    """Group drone detections into one row per unique drone.

    Key by serial number (RemoteID) where available, otherwise by
    device_id or frequency for DroneCtrl / DroneVideo. Aggregate
    the latest position, altitude, speed, and operator GPS.
    """
    drones = {}
    drone_types = set(CATEGORIES["drones"])
    for d in detections:
        sig = d["signal_type"]
        if sig not in drone_types:
            continue
        meta = d.get("meta") or {}
        if sig == "RemoteID":
            key = meta.get("serial_number") or d["device_id"] or f"rid:{d['channel']}"
        elif sig == "RemoteID-operator":
            key = (meta.get("serial_number") or d["device_id"] or "") + ":op"
        elif sig == "DroneCtrl":
            key = f"ctrl:{meta.get('protocol','')}:{d['frequency_mhz']:.3f}"
        elif sig == "DroneVideo":
            key = f"video:{d['frequency_mhz']:.3f}"
        else:
            continue
        rec = drones.get(key)
        if rec is None:
            rec = {
                "key": key,
                "signal_type": sig,
                "serial": meta.get("serial_number", ""),
                "ua_type": meta.get("ua_type", ""),
                "operator_id": meta.get("operator_id", ""),
                "protocol": meta.get("protocol", ""),
                "frequency_mhz": d["frequency_mhz"],
                "count": 0,
                "first_seen": d["timestamp"],
                "last_seen": d["timestamp"],
                "last_lat": None,
                "last_lon": None,
                "altitude_m": None,
                "speed_ms": None,
                "op_lat": None,
                "op_lon": None,
            }
            drones[key] = rec
        rec["count"] += 1
        if d["timestamp"] > rec["last_seen"]:
            rec["last_seen"] = d["timestamp"]
        if d["timestamp"] < rec["first_seen"]:
            rec["first_seen"] = d["timestamp"]
        # RemoteID detections carry drone position in metadata
        if sig == "RemoteID":
            if meta.get("latitude") is not None:
                try:
                    rec["last_lat"] = float(meta["latitude"])
                    rec["last_lon"] = float(meta["longitude"])
                except (ValueError, TypeError):
                    pass
            if meta.get("altitude") is not None:
                try:
                    rec["altitude_m"] = float(meta["altitude"])
                except (ValueError, TypeError):
                    pass
            if meta.get("speed") is not None:
                try:
                    rec["speed_ms"] = float(meta["speed"])
                except (ValueError, TypeError):
                    pass
        elif sig == "RemoteID-operator":
            if meta.get("latitude") is not None:
                try:
                    rec["op_lat"] = float(meta["latitude"])
                    rec["op_lon"] = float(meta["longitude"])
                except (ValueError, TypeError):
                    pass
    out = list(drones.values())
    out.sort(key=lambda r: r["last_seen"], reverse=True)
    return out


def _load_aircraft(detections):
    """One row per aircraft, keyed by ICAO. Shows latest callsign,
    altitude, speed, heading, and position."""
    aircraft = {}
    for d in detections:
        if d["signal_type"] != "ADS-B":
            continue
        meta = d.get("meta") or {}
        icao = meta.get("icao") or d["device_id"] or d["channel"]
        if not icao:
            continue
        rec = aircraft.get(icao)
        if rec is None:
            rec = {
                "icao": icao,
                "callsign": "",
                "altitude_ft": None,
                "speed_kt": None,
                "heading": None,
                "latitude": None,
                "longitude": None,
                "count": 0,
                "first_seen": d["timestamp"],
                "last_seen": d["timestamp"],
            }
            aircraft[icao] = rec
        rec["count"] += 1
        if d["timestamp"] > rec["last_seen"]:
            rec["last_seen"] = d["timestamp"]
        cs = (meta.get("callsign") or "").strip()
        if cs:
            rec["callsign"] = cs
        for k_out, k_meta, cast in (
            ("altitude_ft", "altitude", _try_int),
            ("speed_kt",    "speed",    _try_float),
            ("heading",     "heading",  _try_float),
        ):
            v = meta.get(k_meta)
            if v not in (None, ""):
                c = cast(v)
                if c is not None:
                    rec[k_out] = c
        if d.get("latitude") is not None:
            rec["latitude"] = d["latitude"]
            rec["longitude"] = d["longitude"]
        elif meta.get("latitude") not in (None, ""):
            rec["latitude"] = _try_float(meta["latitude"])
            rec["longitude"] = _try_float(meta["longitude"])
    out = list(aircraft.values())
    out.sort(key=lambda r: r["last_seen"], reverse=True)
    return out


def _load_vessels(detections):
    """One row per vessel, keyed by MMSI."""
    vessels = {}
    for d in detections:
        if d["signal_type"] != "AIS":
            continue
        meta = d.get("meta") or {}
        mmsi = meta.get("mmsi") or d["device_id"] or d["channel"]
        if not mmsi:
            continue
        rec = vessels.get(mmsi)
        if rec is None:
            rec = {
                "mmsi": mmsi,
                "name": "",
                "ship_type": "",
                "nav_status": "",
                "speed_kn": None,
                "course": None,
                "latitude": None,
                "longitude": None,
                "count": 0,
                "first_seen": d["timestamp"],
                "last_seen": d["timestamp"],
            }
            vessels[mmsi] = rec
        rec["count"] += 1
        if d["timestamp"] > rec["last_seen"]:
            rec["last_seen"] = d["timestamp"]
        if meta.get("name"):
            rec["name"] = meta["name"]
        if meta.get("ship_type"):
            rec["ship_type"] = meta["ship_type"]
        if meta.get("nav_status"):
            rec["nav_status"] = meta["nav_status"]
        rec["speed_kn"] = _try_float(meta.get("speed")) or rec["speed_kn"]
        rec["course"]   = _try_float(meta.get("course")) or rec["course"]
        if d.get("latitude") is not None:
            rec["latitude"] = d["latitude"]
            rec["longitude"] = d["longitude"]
    out = list(vessels.values())
    out.sort(key=lambda r: r["last_seen"], reverse=True)
    return out


def _load_vehicles(detections):
    """TPMS sensors and keyfob bursts. One row per unique sensor / burst
    pattern. Groups TPMS by sensor_id, keyfob by data_hex."""
    items = {}
    for d in detections:
        sig = d["signal_type"]
        meta = d.get("meta") or {}
        if sig == "tpms":
            sid = meta.get("sensor_id")
            if not sid:
                continue
            key = f"tpms:{sid}"
            rec = items.get(key) or {
                "kind": "TPMS",
                "id": sid,
                "first_seen": d["timestamp"],
                "last_seen":  d["timestamp"],
                "count": 0,
                "protocol": meta.get("protocol", ""),
                "pressure_kpa": None,
                "temperature_c": None,
                "frequency_mhz": d["frequency_mhz"],
            }
            rec["count"] += 1
            if d["timestamp"] > rec["last_seen"]:
                rec["last_seen"] = d["timestamp"]
            rec["pressure_kpa"]  = _try_float(meta.get("pressure_kpa"))  or rec["pressure_kpa"]
            rec["temperature_c"] = _try_float(meta.get("temperature_c")) or rec["temperature_c"]
            items[key] = rec
        elif sig == "keyfob":
            dhex = meta.get("data_hex", "")
            key = f"kf:{dhex or d['frequency_mhz']}"
            rec = items.get(key) or {
                "kind": "Keyfob",
                "id": dhex or f"{d['frequency_mhz']} MHz",
                "first_seen": d["timestamp"],
                "last_seen":  d["timestamp"],
                "count": 0,
                "protocol": meta.get("protocol", ""),
                "frequency_mhz": d["frequency_mhz"],
                "pressure_kpa": None,
                "temperature_c": None,
            }
            rec["count"] += 1
            if d["timestamp"] > rec["last_seen"]:
                rec["last_seen"] = d["timestamp"]
            items[key] = rec
    out = list(items.values())
    out.sort(key=lambda r: r["last_seen"], reverse=True)
    return out


def _load_cellular(detections):
    """Aggregate cellular uplink detections per channel / frequency."""
    chans = {}
    for d in detections:
        sig = d["signal_type"]
        if not (sig.startswith("GSM-UPLINK") or sig.startswith("LTE-UPLINK")):
            continue
        key = f"{sig}:{d['frequency_mhz']:.3f}"
        rec = chans.get(key) or {
            "technology": "GSM" if sig.startswith("GSM") else "LTE",
            "band": sig,
            "channel": d["channel"],
            "frequency_mhz": d["frequency_mhz"],
            "first_seen": d["timestamp"],
            "last_seen":  d["timestamp"],
            "count": 0,
            "last_snr": d["snr_db"],
        }
        rec["count"] += 1
        if d["timestamp"] > rec["last_seen"]:
            rec["last_seen"] = d["timestamp"]
            rec["last_snr"] = d["snr_db"]
        chans[key] = rec
    out = list(chans.values())
    out.sort(key=lambda r: r["last_seen"], reverse=True)
    return out


def _load_other(detections):
    """Catch-all for ISM / LoRa / POCSAG and anything uncategorized."""
    rows = []
    for d in reversed(detections):
        if d["category"] != "other":
            continue
        meta = d.get("meta") or {}
        rows.append({
            "timestamp": d["timestamp"],
            "signal_type": d["signal_type"],
            "channel": d["channel"],
            "frequency_mhz": d["frequency_mhz"],
            "snr_db": d["snr_db"],
            "detail": d["detail"],
            "model": meta.get("model", ""),
            "protocol": meta.get("protocol", ""),
        })
        if len(rows) >= 200:
            break
    return rows


def _try_int(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _try_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


CATEGORY_LOADERS = {
    "voice":    _load_voice,
    "drones":   _load_drones,
    "aircraft": _load_aircraft,
    "vessels":  _load_vessels,
    "vehicles": _load_vehicles,
    "cellular": _load_cellular,
    "other":    _load_other,
}


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
        elif path == '/api/devices':
            self._serve_devices(qs)
        elif path.startswith('/api/cat/'):
            self._serve_category(path[len('/api/cat/'):], qs)
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

    def _serve_category(self, name, qs):
        loader = CATEGORY_LOADERS.get(name)
        if loader is None:
            self.send_error(404, f"Unknown category: {name}")
            return
        tailer = self.server.tailer
        with tailer._lock:
            detections = list(tailer._detections)
        rows = loader(detections)
        self._send_json({
            "category": name,
            "label": CATEGORY_LABELS.get(name, name),
            "rows": rows,
            "total": len(rows),
        })

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


# ---------------------------------------------------------------------------
# Type colors (matches _TYPE_COLOR in server.py)
# ---------------------------------------------------------------------------

_TYPE_COLORS = {
    "BLE-Adv": "#00bcd4",
    "WiFi-Probe": "#2196f3",
    "WiFi-AP": "#64b5f6",
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
.dev-subtab-btn {
  background: #0f1930; color: #888; border: 1px solid #0f3460;
  border-radius: 4px; padding: 6px 14px; cursor: pointer;
  font-family: inherit; font-size: 12px;
}
.dev-subtab-btn.active { color: #e0e0e0; background: #1a2a4e; border-color: #4fc3f7; }
th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: #4fc3f7; }
th.sortable.sort-asc::after { content: " \25b2"; color: #4fc3f7; font-size: 9px; }
th.sortable.sort-desc::after { content: " \25bc"; color: #4fc3f7; font-size: 9px; }
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
  <div><span class="label">DB </span><span class="value" id="h-db" style="color:#888">-</span></div>
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
  <button class="tab-btn active" data-tab="live">Live</button>
  <button class="tab-btn" data-tab="voice">Voice</button>
  <button class="tab-btn" data-tab="drones">Drones</button>
  <button class="tab-btn" data-tab="aircraft">Aircraft</button>
  <button class="tab-btn" data-tab="vessels">Vessels</button>
  <button class="tab-btn" data-tab="vehicles">Vehicles</button>
  <button class="tab-btn" data-tab="cellular">Cellular</button>
  <button class="tab-btn" data-tab="devices">Devices</button>
  <button class="tab-btn" data-tab="other">Other</button>
  <button class="tab-btn" data-tab="log">Log</button>
  <button class="tab-btn" data-tab="config">Config</button>
  <button class="tab-btn" data-tab="timeline">Timeline</button>
</div>

<!-- Tab: Live -->
<div id="tab-live" class="tab-content active">
  <div class="section">
    <div class="section-title">Categories</div>
    <table>
      <thead><tr>
        <th>Category</th><th class="num">Count</th><th class="num">Unique</th>
        <th>Last</th><th>Signal Types</th>
      </tr></thead>
      <tbody id="categories">
        <tr><td colspan="5" class="empty">waiting for detections...</td></tr>
      </tbody>
    </table>
  </div>

  <div class="section">
    <div class="section-title">Recent</div>
    <div class="section-body" id="recent"><div class="empty">...</div></div>
  </div>
</div>

<!-- Tab: Voice -->
<div id="tab-voice" class="tab-content">
  <div class="section">
    <div class="section-title">
      <span>Voice Transmissions</span>
      <div class="filter-bar">
        <button onclick="loadCategory('voice')">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Time</th><th>Type</th><th>Channel</th><th class="num">Freq (MHz)</th>
        <th class="num">Dur</th><th class="num">SNR</th><th>Transcript</th><th></th>
      </tr></thead>
      <tbody id="voice-body">
        <tr><td colspan="8" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab: Drones -->
<div id="tab-drones" class="tab-content">
  <div class="section">
    <div class="section-title">
      <span>Drones</span>
      <div class="filter-bar">
        <button onclick="loadCategory('drones')">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Type</th><th>Serial / ID</th><th>UA Type</th><th>Protocol</th>
        <th>Position</th><th class="num">Alt</th><th class="num">Speed</th>
        <th>Operator</th><th>Last Seen</th>
      </tr></thead>
      <tbody id="drones-body">
        <tr><td colspan="9" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab: Aircraft -->
<div id="tab-aircraft" class="tab-content">
  <div class="section">
    <div class="section-title">
      <span>Aircraft (ADS-B)</span>
      <div class="filter-bar">
        <button onclick="loadCategory('aircraft')">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>ICAO</th><th>Callsign</th><th class="num">Altitude</th>
        <th class="num">Speed</th><th class="num">Heading</th>
        <th>Position</th><th class="num">Msgs</th><th>Last Seen</th>
      </tr></thead>
      <tbody id="aircraft-body">
        <tr><td colspan="8" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab: Vessels -->
<div id="tab-vessels" class="tab-content">
  <div class="section">
    <div class="section-title">
      <span>Vessels (AIS)</span>
      <div class="filter-bar">
        <button onclick="loadCategory('vessels')">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>MMSI</th><th>Name</th><th>Type</th><th>Nav Status</th>
        <th class="num">Speed</th><th class="num">Course</th>
        <th>Position</th><th class="num">Msgs</th><th>Last Seen</th>
      </tr></thead>
      <tbody id="vessels-body">
        <tr><td colspan="9" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab: Vehicles -->
<div id="tab-vehicles" class="tab-content">
  <div class="section">
    <div class="section-title">
      <span>Vehicles (TPMS + Keyfobs)</span>
      <div class="filter-bar">
        <button onclick="loadCategory('vehicles')">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Kind</th><th>ID</th><th>Protocol</th><th class="num">Freq</th>
        <th class="num">Pressure</th><th class="num">Temp</th>
        <th class="num">Count</th><th>Last Seen</th>
      </tr></thead>
      <tbody id="vehicles-body">
        <tr><td colspan="8" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab: Cellular -->
<div id="tab-cellular" class="tab-content">
  <div class="section">
    <div class="section-title">
      <span>Cellular Uplink Activity</span>
      <div class="filter-bar">
        <button onclick="loadCategory('cellular')">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Technology</th><th>Band</th><th>Channel</th><th class="num">Freq (MHz)</th>
        <th class="num">Hits</th><th class="num">Last SNR</th><th>Last Seen</th>
      </tr></thead>
      <tbody id="cellular-body">
        <tr><td colspan="7" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab: Other -->
<div id="tab-other" class="tab-content">
  <div class="section">
    <div class="section-title">
      <span>Other (ISM, LoRa, POCSAG)</span>
      <div class="filter-bar">
        <button onclick="loadCategory('other')">Refresh</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Time</th><th>Type</th><th>Channel</th><th class="num">Freq (MHz)</th>
        <th class="num">SNR</th><th>Model / Protocol</th><th>Detail</th>
      </tr></thead>
      <tbody id="other-body">
        <tr><td colspan="7" class="empty">select tab to load...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Tab: Log -->
<div id="tab-log" class="tab-content">
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

  <!-- Sub-tabs -->
  <div class="tabs" style="margin-bottom:8px">
    <button class="dev-subtab-btn active" data-sub="wifi_aps">WiFi APs</button>
    <button class="dev-subtab-btn" data-sub="wifi_clients">WiFi Clients</button>
    <button class="dev-subtab-btn" data-sub="ble">BLE</button>
    <label style="font-size:11px;color:#888;display:flex;align-items:center;gap:4px;text-transform:none;letter-spacing:0;margin-left:auto;padding-right:12px">
      <input type="checkbox" id="dev-active-only"> Active only
    </label>
    <button onclick="loadDevices()" style="margin-right:8px">Refresh</button>
  </div>

  <!-- WiFi APs sub-pane -->
  <div class="dev-subpane" data-sub="wifi_aps">
    <div class="section">
      <table>
        <thead><tr>
          <th style="width:20px"></th>
          <th class="sortable" data-sub="wifi_aps" data-key="label">SSID</th>
          <th class="sortable" data-sub="wifi_aps" data-key="bssid_count">BSSID(s)</th>
          <th class="sortable" data-sub="wifi_aps" data-key="channel">Band / Ch</th>
          <th class="sortable" data-sub="wifi_aps" data-key="crypto">Crypto</th>
          <th class="sortable" data-sub="wifi_aps" data-key="manufacturer">Vendor</th>
          <th class="sortable num" data-sub="wifi_aps" data-key="last_rssi">RSSI</th>
          <th class="sortable num" data-sub="wifi_aps" data-key="client_count" title="Distinct client MACs seen communicating with this AP. Only populated while the scanner is tuned to the AP's channel, so counts grow slowly with channel hopping.">Clients</th>
          <th class="sortable" data-sub="wifi_aps" data-key="first_seen">First Seen</th>
          <th class="sortable" data-sub="wifi_aps" data-key="last_seen">Last Seen</th>
        </tr></thead>
        <tbody id="ap-body">
          <tr><td colspan="10" class="empty">select tab to load...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- WiFi Clients sub-pane -->
  <div class="dev-subpane" data-sub="wifi_clients" style="display:none">
    <div class="section">
      <table>
        <thead><tr>
          <th style="width:20px"></th>
          <th class="sortable" data-sub="wifi_clients" data-key="label">Device</th>
          <th class="sortable" data-sub="wifi_clients" data-key="manufacturer">Vendor</th>
          <th class="sortable num" data-sub="wifi_clients" data-key="mac_count">MACs</th>
          <th class="sortable num" data-sub="wifi_clients" data-key="ssid_count">SSIDs</th>
          <th class="sortable num" data-sub="wifi_clients" data-key="sessions">Sessions</th>
          <th class="sortable num" data-sub="wifi_clients" data-key="total_probes">Probes</th>
          <th class="sortable" data-sub="wifi_clients" data-key="last_session">Last Seen</th>
        </tr></thead>
        <tbody id="wc-body">
          <tr><td colspan="8" class="empty">select tab to load...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- BLE sub-pane -->
  <div class="dev-subpane" data-sub="ble" style="display:none">
    <div class="section">
      <table>
        <thead><tr>
          <th style="width:20px"></th>
          <th class="sortable" data-sub="ble" data-key="label">Device</th>
          <th class="sortable" data-sub="ble" data-key="manufacturer">Vendor</th>
          <th class="sortable" data-sub="ble" data-key="apple_device">Apple</th>
          <th class="sortable num" data-sub="ble" data-key="mac_count">MACs</th>
          <th class="sortable num" data-sub="ble" data-key="sessions">Sessions</th>
          <th class="sortable num" data-sub="ble" data-key="total_probes">Probes</th>
          <th class="sortable" data-sub="ble" data-key="last_session">Last Seen</th>
        </tr></thead>
        <tbody id="ble-body">
          <tr><td colspan="8" class="empty">select tab to load...</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- Tab: Config -->
<div id="tab-config" class="tab-content">
  <div class="section">
    <div class="section-title">Capture Configuration</div>
    <div class="section-body" id="captures"><div class="empty">loading...</div></div>
  </div>
</div>

<!-- Tab: Timeline -->
<div id="tab-timeline" class="tab-content">
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

// Central tooltip dictionary — human-readable explanations shown on hover
// for every short tag/badge in the UI. Lookups are case-insensitive and fall
// back to prefix matches so dynamic values (e.g. "LNA 24") resolve.
const TAG_TIPS = {
  // Device flags
  'rand':        'Device advertises with rotating random MAC addresses. Modern phones/watches/earbuds use this as a privacy feature to prevent tracking — the fingerprint groups all rotated MACs back into one device.',
  // Capture status
  'running':     'Capture source is running and producing samples.',
  'pending':     'Capture source has not started yet.',
  'degraded':    'Capture is running but the pipeline cannot keep up — samples are being dropped. Consider lowering sample rate or gain.',
  'failed':      'Capture source exited with an error. Check the status message or server logs for details.',
  // Bands
  '2.4 ghz':     'AP observed broadcasting on the 2.4 GHz band (channels 1-14).',
  '5 ghz':       'AP observed broadcasting on the 5 GHz band (channels 32+).',
  '6 ghz':       'AP observed broadcasting on the 6 GHz band (Wi-Fi 6E).',
  // Config/capture tags
  'transcribe':  'Audio is transcribed to text using Whisper (local model or OpenAI API).',
  'digital':     'Digital voice modes enabled (dPMR/DMR detection on PMR446).',
  'no audio':    'Audio recording is disabled — only detection events are logged.',
  // Crypto (shown as plain cell text but good to cover)
  'wpa2-psk':    'WPA2 Personal — pre-shared key authentication (standard home network).',
  'wpa3-sae':    'WPA3 Personal — SAE (Simultaneous Authentication of Equals), more secure than WPA2-PSK.',
  'wpa2-eap':    'WPA2 Enterprise — 802.1X authentication (corporate networks).',
  'owe':         'Opportunistic Wireless Encryption — encrypted but unauthenticated (open networks with WPA3 encryption).',
  'open':        'No encryption — plaintext network.',
  'wep':         'WEP — legacy, broken encryption. Treat as open.',
};
const TAG_TIP_PREFIXES = [
  ['lna ',     'HackRF LNA (Low-Noise Amplifier) gain in dB. Boosts RF signal at the front end; too high causes overload.'],
  ['vga ',     'HackRF VGA (Variable-Gain Amplifier) baseband gain in dB. Applied after downconversion.'],
  ['lang: ',   'Forced Whisper transcription language (ISO 639-1 code). Otherwise auto-detected.'],
  ['whisper: ','Whisper model used for transcription. Larger = more accurate but slower.'],
  ['ppm ',     'RTL-SDR / HackRF crystal frequency correction in parts-per-million. Corrects cheap SDR clock drift.'],
  ['probing: ','Network name(s) this client device is searching for. Clients reveal saved networks in their probe requests.'],
];

function tipFor(tag) {
  if (!tag) return '';
  const k = String(tag).toLowerCase().trim();
  if (TAG_TIPS[k]) return TAG_TIPS[k];
  for (const [prefix, tip] of TAG_TIP_PREFIXES) {
    if (k.startsWith(prefix)) return tip;
  }
  return '';
}

function tipAttr(tag) {
  const t = tipFor(tag);
  return t ? ' title="' + esc(t) + '"' : '';
}

// --- Config / Captures ---
async function loadConfig() {
  const capEl = document.getElementById('captures');
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    if (!cfg.captures || !cfg.captures.length) {
      capEl.innerHTML = '<div class="empty">no server_info.json found (server not running?)</div>';
      return;
    }
    const STATUS_COLORS = {
      running: '#4caf50',
      pending: '#888',
      degraded: '#ff9800',
      failed: '#f44336',
    };
    let html = '';
    cfg.captures.forEach(cap => {
      const t = cap.type;
      const status = cap.status || 'pending';
      const statusColor = STATUS_COLORS[status] || '#888';
      let line = '<div style="margin-bottom:8px;border-left:3px solid ' + statusColor + ';padding-left:8px">';
      line += '<div><span style="color:#4fc3f7;font-weight:600">' + esc(cap.name) + '</span>';
      line += ' <span' + tipAttr(status) + ' style="background:' + statusColor + ';color:#000;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;margin-left:6px;cursor:help">' + esc(status.toUpperCase()) + '</span>';
      line += ' <span style="color:#888">' + esc(cap.device || '') + '</span></div>';
      if (cap.status_message) {
        line += '<div style="font-size:11px;color:' + statusColor + ';margin-left:12px">\u26a0 ' + esc(cap.status_message) + '</div>';
      }

      // Coverage line: frequency range + hopping/continuous/passive mode
      const modeIcon = {
        continuous: '\u25cf',   // filled dot — continuous
        hopping:    '\u{1F500}', // shuffle — hopping
        passive:    '\u{1F442}', // ear — passive listen
      };
      if (cap.coverage || cap.mode) {
        const icon = modeIcon[cap.mode] || '';
        line += '<div style="font-size:11px;color:#9ecbff;margin-left:12px;margin-top:2px">'
             + (icon ? icon + ' ' : '')
             + esc(cap.coverage || '')
             + (cap.mode ? ' <span style="color:#666">\u00b7 ' + esc(cap.mode) + '</span>' : '')
             + '</div>';
      }

      // --- Tag row: only orthogonal info, no duplication of the coverage line ---
      const tags = [];
      if (t === 'hackrf') {
        if (cap.lna_gain != null) tags.push('LNA ' + cap.lna_gain);
        if (cap.vga_gain != null) tags.push('VGA ' + cap.vga_gain);
        if (cap.transcribe) tags.push('\u2705 transcribe');
        if (cap.whisper_model && cap.whisper_model !== 'base') tags.push('whisper: ' + cap.whisper_model);
        if (cap.language) tags.push('lang: ' + cap.language);
      } else if (t === 'rtlsdr' || t === 'rtlsdr_sweep') {
        if (cap.parsers && cap.parsers.length) tags.push(cap.parsers.join(' \u00b7 '));
      } else if (t === 'ble') {
        if (cap.parsers && cap.parsers.length) tags.push(cap.parsers.join(' \u00b7 '));
      } else if (t === 'wifi') {
        if (cap.parsers && cap.parsers.length) tags.push(cap.parsers.join(' \u00b7 '));
      } else if (t === 'standalone') {
        if (cap.scanner_label || cap.scanner_type) {
          tags.push(cap.scanner_label || cap.scanner_type);
        }
        // Pretty-print common args (mirrors HackRF flag rendering)
        const args = cap.args || [];
        if (args.includes('--transcribe')) tags.push('\u2705 transcribe');
        if (args.includes('--digital')) tags.push('\u2705 digital');
        if (args.includes('--no-audio')) tags.push('no audio');
        const flagValue = (flag) => {
          const i = args.indexOf(flag);
          return (i >= 0 && i + 1 < args.length) ? args[i + 1] : null;
        };
        const lang = flagValue('--language');
        if (lang) tags.push('lang: ' + lang);
        const wm = flagValue('--whisper-model');
        if (wm && wm !== 'base') tags.push('whisper: ' + wm);
        const ppm = flagValue('--ppm');
        if (ppm) tags.push('ppm ' + ppm);
        // Anything else (positional band names, custom flags) — show as-is
        const known = new Set([
          '--transcribe', '--digital', '--no-audio',
          '--language', '--whisper-model', '--ppm',
        ]);
        const skipNext = new Set(['--language', '--whisper-model', '--ppm']);
        const extras = [];
        for (let i = 0; i < args.length; i++) {
          const a = args[i];
          if (known.has(a)) {
            if (skipNext.has(a)) i++;
            continue;
          }
          extras.push(a);
        }
        if (extras.length) tags.push(extras.join(' '));
      }
      if (tags.length) {
        line += '<div style="font-size:12px;color:#aaa;margin-left:12px">' + tags.map(t => {
          const tip = tipFor(t);
          const cur = tip ? ';cursor:help' : '';
          const attr = tip ? ' title="' + esc(tip) + '"' : '';
          return '<span' + attr + ' style="background:#0f3460;padding:1px 6px;border-radius:3px;margin-right:4px;display:inline-block;margin-top:2px' + cur + '">' + esc(t) + '</span>';
        }).join('') + '</div>';
      }

      // --- Sub-channel list (HackRF + WiFi use the same tree-style rendering) ---
      const fmtFreq = (mhz) => {
        if (mhz == null) return '';
        if (mhz >= 1000) return (mhz / 1000).toFixed(3) + ' GHz';
        return Number(mhz).toFixed(4).replace(/0+$/, '').replace(/\.$/, '') + ' MHz';
      };

      if (t === 'hackrf' && cap.channels && cap.channels.length) {
        cap.channels.forEach(ch => {
          const chTags = [];
          if (ch.band) chTags.push(ch.band);
          if (ch.name) chTags.push(ch.name);
          chTags.push(fmtFreq(ch.freq_mhz));
          if (ch.bandwidth_mhz) chTags.push(ch.bandwidth_mhz + ' MHz BW');
          if (ch.parsers && ch.parsers.length) chTags.push(ch.parsers.join(' \u00b7 '));
          if (ch.transcribe) chTags.push('\u2705 transcribe');
          line += '<div style="font-size:11px;color:#888;margin-left:24px;margin-top:2px">\u2514 ' + chTags.join(' \u00b7 ') + '</div>';
        });
      }

      if (t === 'wifi' && cap.channel_list && cap.channel_list.length) {
        const chList = cap.channel_list;
        // Compact form for long lists: show first 6 + count
        const shown = chList.length > 8 ? chList.slice(0, 6) : chList;
        shown.forEach(ch => {
          line += '<div style="font-size:11px;color:#888;margin-left:24px;margin-top:2px">'
               + '\u2514 CH' + esc(ch.name) + ' \u00b7 ' + esc(fmtFreq(ch.freq_mhz)) + '</div>';
        });
        if (chList.length > shown.length) {
          line += '<div style="font-size:11px;color:#666;margin-left:24px;margin-top:2px">'
               + '\u2514 \u2026 +' + (chList.length - shown.length) + ' more</div>';
        }
      }

      line += '</div>';
      html += line;
    });
    if (cfg.started) {
      html += '<div style="font-size:11px;color:#555;margin-top:4px">Started: ' + esc(cfg.started.replace('T', ' ').split('.')[0]) + '</div>';
    }
    capEl.innerHTML = html;
  } catch(e) {
    capEl.innerHTML = '<div class="empty">could not load config</div>';
  }
}

// --- Live Tab ---
function updateOverview(state) {
  document.getElementById('h-time').textContent = state.time || '-';
  document.getElementById('h-uptime').textContent = state.uptime || '-';
  document.getElementById('h-count').textContent = state.detection_count || 0;
  document.getElementById('h-db').textContent = state.db || '-';

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

  // (Config is in its own tab)

  // Categories table (Live tab overview)
  const tbody = document.getElementById('categories');
  if (state.categories && state.categories.length) {
    tbody.innerHTML = state.categories.map(c => {
      const typesStr = c.types.map(t => {
        const col = TYPE_COLORS[t] || '#ccc';
        return '<span style="color:'+col+';margin-right:8px">'+esc(t)+'</span>';
      }).join('');
      return '<tr style="cursor:pointer" onclick="goToTab(\''+esc(c.id)+'\')">'
        + '<td style="font-weight:600;color:#e0e0e0">'+esc(c.label)+'</td>'
        + '<td class="num">'+c.count+'</td>'
        + '<td class="num">'+(c.uniques>0?c.uniques:'-')+'</td>'
        + '<td>'+(c.last_seen||'-')+'</td>'
        + '<td style="font-size:11px">'+typesStr+'</td>'
        + '</tr>';
    }).join('');
  } else {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">waiting for detections...</td></tr>';
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

// --- Log Tab ---
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
let _devCache = { wifi_aps: [], wifi_clients: [], ble: [], summary: {} };
let _devSubtab = 'wifi_aps';
let _devExpanded = { wifi_aps: new Set(), wifi_clients: new Set(), ble: new Set() };
// null = server-default sort; otherwise {key, dir: 'asc'|'desc'}
let _devSort = { wifi_aps: null, wifi_clients: null, ble: null };

function _devSortValue(row, key) {
  if (key === 'channel') {
    const chs = row.channels || [];
    return chs.length ? chs[0] : 0;
  }
  const v = row[key];
  if (v == null) return '';
  return v;
}

function _devApplySort(sub, rows) {
  const s = _devSort[sub];
  if (!s) return rows;
  const dir = s.dir === 'asc' ? 1 : -1;
  const out = rows.slice();
  out.sort((a, b) => {
    const av = _devSortValue(a, s.key);
    const bv = _devSortValue(b, s.key);
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
  return out;
}

function _devUpdateSortIndicators() {
  document.querySelectorAll('th.sortable').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    const sub = th.dataset.sub;
    const s = _devSort[sub];
    if (s && s.key === th.dataset.key) {
      th.classList.add(s.dir === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

function devSortBy(sub, key) {
  const s = _devSort[sub];
  if (s && s.key === key) {
    if (s.dir === 'desc') _devSort[sub] = { key, dir: 'asc' };
    else _devSort[sub] = null;  // third click clears → server default
  } else {
    _devSort[sub] = { key, dir: 'desc' };
  }
  _devUpdateSortIndicators();
  renderDevices();
}

async function loadDevices() {
  try {
    const r = await fetch('/api/devices');
    _devCache = await r.json();
    renderDevices();
  } catch(e) {}
}

function fmtTs(ts) {
  if (!ts) return '-';
  const parts = ts.split('T');
  if (parts.length < 2) return ts;
  return parts[0].slice(5) + ' ' + parts[1].split('.')[0];
}

function activeDot(active) {
  return active
    ? '<span class="status-dot" title="Active now"></span>'
    : '<span class="status-dot off" style="opacity:0.2"></span>';
}

function renderDevices() {
  const activeOnly = document.getElementById('dev-active-only').checked;
  const s = _devCache.summary || {};

  const cardStyle = 'background:#16213e;border:1px solid #0f3460;border-radius:6px;padding:8px 14px;font-size:12px;text-align:center;min-width:80px';
  document.getElementById('dev-stats').innerHTML =
    '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#2196f3">'+(s.wifi_aps||0)+'</div>WiFi APs</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#64b5f6">'+(s.wifi_clients||0)+'</div>WiFi Clients</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#00bcd4">'+(s.ble||0)+'</div>BLE</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#4caf50">'+(s.active||0)+'</div>Active</div>';

  renderWifiAps(activeOnly);
  renderWifiClients(activeOnly);
  renderBle(activeOnly);
}

function renderWifiAps(activeOnly) {
  const aps = _devApplySort('wifi_aps',
    (_devCache.wifi_aps || []).filter(a => !activeOnly || a.active));
  const tbody = document.getElementById('ap-body');
  if (!aps.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">no APs found — run sdr.py server to collect beacon data</td></tr>';
    return;
  }
  const rows = [];
  aps.forEach((a, i) => {
    const key = a.group_key || i;
    const isExp = _devExpanded.wifi_aps.has(String(key));
    const label = a.hidden ? '<span style="color:#888">(hidden)</span>' : esc(a.label || '');
    const bssidCell = a.bssid_count > 1
      ? '<span style="color:#4fc3f7">'+a.bssid_count+' radios</span>'
      : (a.bssids[0] ? esc(a.bssids[0].bssid) : '-');
    const bands = (a.bands || []).map(b => '<span title="'+esc(tipFor(b+' GHz'))+'" style="background:#0f3460;color:#9ecbff;padding:0 5px;border-radius:3px;font-size:10px;margin-right:2px;cursor:help">'+b+' GHz</span>').join('');
    const chs = (a.channels || []).join(',');
    const rssi = (a.last_rssi != null) ? a.last_rssi.toFixed(0)+' dBm' : '-';
    const borderStyle = a.active ? 'border-left:3px solid #4caf50' : '';
    const clientCount = a.client_count || 0;
    const noClientsTip = 'No associated clients observed yet. Client detection requires capturing data/mgmt frames while tuned to the AP channel — with channel hopping this can be slow. Dwelling longer on a channel surfaces more clients.';
    const clientCell = clientCount > 0
      ? '<span style="color:#4fc3f7;cursor:help" title="'+esc((a.clients||[]).join('\n'))+'">'+clientCount+'</span>'
      : '<span style="color:#555;cursor:help" title="'+esc(noClientsTip)+'">\u2014</span>';
    rows.push(
      '<tr style="cursor:pointer;'+borderStyle+'" onclick="toggleDevRow(\'wifi_aps\',\''+encodeURIComponent(String(key))+'\')">'
      + '<td>'+activeDot(a.active)+'</td>'
      + '<td>'+label+'</td>'
      + '<td style="font-family:monospace;font-size:11px">'+bssidCell+'</td>'
      + '<td>'+bands+' <span style="color:#888;font-size:11px">'+esc(chs)+'</span></td>'
      + '<td'+tipAttr(a.crypto)+' style="font-size:11px'+(tipFor(a.crypto)?';cursor:help':'')+'">'+esc(a.crypto||'')+'</td>'
      + '<td style="color:#888;font-size:11px">'+esc(a.manufacturer||'')+'</td>'
      + '<td class="num">'+rssi+'</td>'
      + '<td class="num">'+clientCell+'</td>'
      + '<td style="font-size:11px;white-space:nowrap">'+fmtTs(a.first_seen)+'</td>'
      + '<td style="font-size:11px;white-space:nowrap">'+fmtTs(a.last_seen)+'</td>'
      + '</tr>'
    );
    if (isExp) {
      let detail = '<div style="padding:8px 12px;background:#0a1020;font-size:11px">';
      detail += '<div style="color:#888;margin-bottom:4px">SSIDs: ' + (a.ssids||[]).map(esc).join(', ') + '</div>';
      detail += '<table style="width:100%;margin-top:4px"><thead><tr>'
        + '<th>BSSID</th><th>SSID</th><th class="num">Ch</th><th>Crypto</th><th>Vendor</th>'
        + '<th class="num">RSSI</th><th class="num">Clients</th><th class="num">Beacons</th><th>Last Seen</th>'
        + '</tr></thead><tbody>';
      (a.bssids||[]).forEach(b => {
        detail += '<tr><td style="font-family:monospace">'+esc(b.bssid)+'</td>'
          + '<td>'+esc((b.ssids||[]).join(',')||'(hidden)')+'</td>'
          + '<td class="num">'+esc((b.channels||[]).join(','))+'</td>'
          + '<td>'+esc(b.crypto||'')+'</td>'
          + '<td style="color:#888">'+esc(b.manufacturer||'')+'</td>'
          + '<td class="num">'+(b.last_rssi!=null?b.last_rssi.toFixed(0):'-')+'</td>'
          + '<td class="num">'+((b.client_count||0) > 0 ? b.client_count : '<span style="color:#555">\u2014</span>')+'</td>'
          + '<td class="num">'+(b.total_beacons||0)+'</td>'
          + '<td style="font-size:11px">'+fmtTs(b.last_seen)+'</td></tr>';
      });
      detail += '</tbody></table>';
      if ((a.clients||[]).length) {
        detail += '<div style="margin-top:8px"><div style="color:#4fc3f7;margin-bottom:2px">Associated clients ('+a.client_count+')</div>'
          + '<div style="font-family:monospace;color:#ccc;column-count:3">'
          + a.clients.map(esc).join('<br>')
          + '</div></div>';
      }
      detail += '</div>';
      rows.push('<tr><td colspan="10" style="padding:0">'+detail+'</td></tr>');
    }
  });
  tbody.innerHTML = rows.join('');
}

function renderWifiClients(activeOnly) {
  const items = _devApplySort('wifi_clients',
    (_devCache.wifi_clients || []).filter(c => !activeOnly || c.active));
  const tbody = document.getElementById('wc-body');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">no clients found</td></tr>';
    return;
  }
  const rows = [];
  items.forEach((c, i) => {
    const key = c.persona_key || c.dev_sig || String(i);
    const isExp = _devExpanded.wifi_clients.has(key);
    const sessColor = c.sessions >= 20 ? '#f44336' : c.sessions >= 5 ? '#ffeb3b' : '#e0e0e0';
    const borderStyle = c.active ? 'border-left:3px solid #4caf50' : '';
    const rowStyle = c.sessions <= 1 ? 'opacity:0.5' : '';

    let labelHtml = '<span style="color:#e0e0e0">' + esc(c.label || 'unknown') + '</span>';
    if (c.randomized) labelHtml += ' <span title="'+esc(tipFor('rand'))+'" style="background:#333;color:#888;padding:0 5px;border-radius:3px;font-size:10px;cursor:help">rand</span>';
    if (c.ssids && c.ssids.length) {
      labelHtml += ' <span style="background:#1a1a2e;color:#9ecbff;padding:0 5px;border-radius:3px;font-size:10px;cursor:help" title="'+esc(tipFor('probing: x'))+'\n\n'+esc(c.ssids.join(', '))+'">probing: '+esc(c.ssids[0])+(c.ssids.length>1?' +'+(c.ssids.length-1):'')+'</span>';
    }

    rows.push(
      '<tr style="cursor:pointer;'+rowStyle+';'+borderStyle+'" onclick="toggleDevRow(\'wifi_clients\',\''+encodeURIComponent(key)+'\')">'
      + '<td>'+activeDot(c.active)+'</td>'
      + '<td>'+labelHtml+'</td>'
      + '<td style="color:#888;font-size:12px">'+esc(c.manufacturer||'')+'</td>'
      + '<td class="num">'+c.mac_count+'</td>'
      + '<td class="num">'+c.ssid_count+'</td>'
      + '<td class="num" style="color:'+sessColor+'">'+c.sessions+'</td>'
      + '<td class="num">'+(c.total_probes||0).toLocaleString()+'</td>'
      + '<td style="font-size:11px;white-space:nowrap">'+fmtTs(c.last_session)+'</td>'
      + '</tr>'
    );
    if (isExp) {
      let detail = '<div style="padding:8px 12px;background:#0a1020;font-size:11px;display:flex;gap:24px;flex-wrap:wrap">';
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">MACs ('+c.mac_count+')</div><div style="font-family:monospace;color:#ccc">'+(c.macs||[]).map(esc).join('<br>')+'</div></div>';
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">Probed SSIDs ('+c.ssid_count+')</div><div style="color:#9ecbff">'+(c.ssids||[]).map(esc).join('<br>')+'</div></div>';
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">Fingerprint</div><div style="font-family:monospace;color:#888">'+esc(c.dev_sig||'')+'</div></div>';
      detail += '</div>';
      rows.push('<tr><td colspan="8" style="padding:0">'+detail+'</td></tr>');
    }
  });
  tbody.innerHTML = rows.join('');
}

function renderBle(activeOnly) {
  const items = _devApplySort('ble',
    (_devCache.ble || []).filter(d => !activeOnly || d.active));
  const tbody = document.getElementById('ble-body');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">no BLE devices found</td></tr>';
    return;
  }
  const rows = [];
  items.forEach((d, i) => {
    const key = d.persona_key || d.dev_sig || String(i);
    const isExp = _devExpanded.ble.has(key);
    const sessColor = d.sessions >= 20 ? '#f44336' : d.sessions >= 5 ? '#ffeb3b' : '#e0e0e0';
    const borderStyle = d.active ? 'border-left:3px solid #4caf50' : '';
    const rowStyle = d.sessions <= 1 ? 'opacity:0.5' : '';

    let labelHtml = '<span style="color:#e0e0e0">' + esc(d.label || 'unknown') + '</span>';
    if (d.randomized) labelHtml += ' <span title="'+esc(tipFor('rand'))+'" style="background:#333;color:#888;padding:0 5px;border-radius:3px;font-size:10px;cursor:help">rand</span>';

    rows.push(
      '<tr style="cursor:pointer;'+rowStyle+';'+borderStyle+'" onclick="toggleDevRow(\'ble\',\''+encodeURIComponent(key)+'\')">'
      + '<td>'+activeDot(d.active)+'</td>'
      + '<td>'+labelHtml+'</td>'
      + '<td style="color:#888;font-size:12px">'+esc(d.manufacturer||'')+'</td>'
      + '<td style="color:#aaa;font-size:11px">'+esc(d.apple_device||'')+'</td>'
      + '<td class="num">'+d.mac_count+'</td>'
      + '<td class="num" style="color:'+sessColor+'">'+d.sessions+'</td>'
      + '<td class="num">'+(d.total_probes||0).toLocaleString()+'</td>'
      + '<td style="font-size:11px;white-space:nowrap">'+fmtTs(d.last_session)+'</td>'
      + '</tr>'
    );
    if (isExp) {
      let detail = '<div style="padding:8px 12px;background:#0a1020;font-size:11px;display:flex;gap:24px;flex-wrap:wrap">';
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">MACs ('+d.mac_count+')</div><div style="font-family:monospace;color:#ccc">'+(d.macs||[]).map(esc).join('<br>')+'</div></div>';
      if (d.names && d.names.length) {
        detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">Names</div><div style="color:#9ecbff">'+(d.names||[]).map(esc).join('<br>')+'</div></div>';
      }
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">Fingerprint</div><div style="font-family:monospace;color:#888">'+esc(d.dev_sig||'')+'</div></div>';
      detail += '</div>';
      rows.push('<tr><td colspan="8" style="padding:0">'+detail+'</td></tr>');
    }
  });
  tbody.innerHTML = rows.join('');
}

function toggleDevRow(sub, encKey) {
  const key = decodeURIComponent(encKey);
  const s = _devExpanded[sub];
  if (s.has(key)) s.delete(key); else s.add(key);
  renderDevices();
}

function switchDevSubtab(name) {
  _devSubtab = name;
  document.querySelectorAll('.dev-subtab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.sub === name);
  });
  document.querySelectorAll('.dev-subpane').forEach(p => {
    p.style.display = p.dataset.sub === name ? 'block' : 'none';
  });
}

document.querySelectorAll('.dev-subtab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchDevSubtab(btn.dataset.sub));
});
document.querySelectorAll('th.sortable').forEach(th => {
  th.addEventListener('click', () => devSortBy(th.dataset.sub, th.dataset.key));
});
document.getElementById('dev-active-only').addEventListener('change', () => renderDevices());

// --- Category Tabs (Voice / Drones / Aircraft / Vessels / Vehicles / Cellular / Other) ---
async function loadCategory(name) {
  try {
    const r = await fetch('/api/cat/' + encodeURIComponent(name));
    const data = await r.json();
    const rows = data.rows || [];
    const fn = _CATEGORY_RENDERERS[name];
    if (fn) fn(rows);
  } catch(e) {}
}

function _emptyRow(bodyId, cols, msg) {
  const tbody = document.getElementById(bodyId);
  if (tbody) tbody.innerHTML = '<tr><td colspan="'+cols+'" class="empty">'+esc(msg)+'</td></tr>';
}

function _fmtCoord(lat, lon) {
  if (lat == null || lon == null) return '-';
  return lat.toFixed(4) + ', ' + lon.toFixed(4);
}

function renderVoice(rows) {
  const tbody = document.getElementById('voice-body');
  if (!rows.length) { _emptyRow('voice-body', 8, 'no voice transmissions yet'); return; }
  tbody.innerHTML = rows.map(r => {
    const ts = r.timestamp ? r.timestamp.split('T')[1].split('.')[0] : '-';
    const color = TYPE_COLORS[r.signal_type] || '#ccc';
    const dur = r.duration_s != null ? (+r.duration_s).toFixed(1)+'s' : '-';
    const tx = r.transcript || '';
    const audio = r.audio_file
      ? '<button class="play-btn" onclick="playAudio(this,\''+esc(r.audio_file)+'\')">&#9654;</button>'
      : '';
    return '<tr>'
      + '<td>'+ts+'</td>'
      + '<td class="sig-type" style="color:'+color+'">'+esc(r.signal_type)+'</td>'
      + '<td>'+esc(r.channel||'-')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+dur+'</td>'
      + '<td class="num">'+(r.snr_db != null ? r.snr_db+' dB' : '-')+'</td>'
      + '<td class="detail'+(tx?' transcript':'')+'">'+esc(tx?('\u201c'+tx+'\u201d'):'')+'</td>'
      + '<td>'+audio+'</td>'
      + '</tr>';
  }).join('');
}

function renderDrones(rows) {
  const tbody = document.getElementById('drones-body');
  if (!rows.length) { _emptyRow('drones-body', 9, 'no drones detected — RemoteID / DroneCtrl / DroneVideo not seen yet'); return; }
  tbody.innerHTML = rows.map(r => {
    const color = TYPE_COLORS[r.signal_type] || '#ccc';
    const pos = _fmtCoord(r.last_lat, r.last_lon);
    const alt = r.altitude_m != null ? r.altitude_m.toFixed(0)+' m' : '-';
    const spd = r.speed_ms != null ? r.speed_ms.toFixed(1)+' m/s' : '-';
    const op  = _fmtCoord(r.op_lat, r.op_lon);
    return '<tr>'
      + '<td class="sig-type" style="color:'+color+'">'+esc(r.signal_type)+'</td>'
      + '<td style="font-family:monospace">'+esc(r.serial||r.key||'-')+'</td>'
      + '<td>'+esc(r.ua_type||'')+'</td>'
      + '<td>'+esc(r.protocol||'')+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '<td class="num">'+alt+'</td>'
      + '<td class="num">'+spd+'</td>'
      + '<td style="font-size:11px">'+op+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderAircraft(rows) {
  const tbody = document.getElementById('aircraft-body');
  if (!rows.length) { _emptyRow('aircraft-body', 8, 'no aircraft detected — ADS-B capture not running'); return; }
  tbody.innerHTML = rows.map(r => {
    const alt = r.altitude_ft != null ? r.altitude_ft+' ft' : '-';
    const spd = r.speed_kt != null ? r.speed_kt.toFixed(0)+' kt' : '-';
    const hdg = r.heading != null ? r.heading.toFixed(0)+'\u00b0' : '-';
    const pos = _fmtCoord(r.latitude, r.longitude);
    return '<tr>'
      + '<td style="font-family:monospace">'+esc(r.icao)+'</td>'
      + '<td style="font-weight:600">'+esc(r.callsign||'-')+'</td>'
      + '<td class="num">'+alt+'</td>'
      + '<td class="num">'+spd+'</td>'
      + '<td class="num">'+hdg+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderVessels(rows) {
  const tbody = document.getElementById('vessels-body');
  if (!rows.length) { _emptyRow('vessels-body', 9, 'no vessels detected — AIS capture not running'); return; }
  tbody.innerHTML = rows.map(r => {
    const spd = r.speed_kn != null ? r.speed_kn.toFixed(1)+' kn' : '-';
    const crs = r.course != null ? r.course.toFixed(0)+'\u00b0' : '-';
    const pos = _fmtCoord(r.latitude, r.longitude);
    return '<tr>'
      + '<td style="font-family:monospace">'+esc(r.mmsi)+'</td>'
      + '<td style="font-weight:600">'+esc(r.name||'-')+'</td>'
      + '<td>'+esc(r.ship_type||'')+'</td>'
      + '<td>'+esc(r.nav_status||'')+'</td>'
      + '<td class="num">'+spd+'</td>'
      + '<td class="num">'+crs+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderVehicles(rows) {
  const tbody = document.getElementById('vehicles-body');
  if (!rows.length) { _emptyRow('vehicles-body', 8, 'no TPMS / keyfob detections yet'); return; }
  tbody.innerHTML = rows.map(r => {
    const pressure = r.pressure_kpa != null ? r.pressure_kpa.toFixed(0)+' kPa' : '-';
    const temp     = r.temperature_c != null ? r.temperature_c.toFixed(0)+' \u00b0C' : '-';
    const kindCol  = r.kind === 'TPMS' ? '#4fc3f7' : '#ffb74d';
    return '<tr>'
      + '<td style="color:'+kindCol+';font-weight:600">'+esc(r.kind)+'</td>'
      + '<td style="font-family:monospace">'+esc(r.id)+'</td>'
      + '<td>'+esc(r.protocol||'')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+pressure+'</td>'
      + '<td class="num">'+temp+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderCellular(rows) {
  const tbody = document.getElementById('cellular-body');
  if (!rows.length) { _emptyRow('cellular-body', 7, 'no cellular uplink activity detected'); return; }
  tbody.innerHTML = rows.map(r => {
    return '<tr>'
      + '<td style="font-weight:600;color:#ff7043">'+esc(r.technology)+'</td>'
      + '<td style="font-size:11px">'+esc(r.band)+'</td>'
      + '<td>'+esc(r.channel||'-')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td class="num">'+(r.last_snr != null ? r.last_snr+' dB' : '-')+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderOther(rows) {
  const tbody = document.getElementById('other-body');
  if (!rows.length) { _emptyRow('other-body', 7, 'no other detections'); return; }
  tbody.innerHTML = rows.map(r => {
    const ts = r.timestamp ? r.timestamp.split('T')[1].split('.')[0] : '-';
    const color = TYPE_COLORS[r.signal_type] || '#ccc';
    const info = [r.model, r.protocol].filter(Boolean).join(' / ');
    return '<tr>'
      + '<td>'+ts+'</td>'
      + '<td class="sig-type" style="color:'+color+'">'+esc(r.signal_type)+'</td>'
      + '<td>'+esc(r.channel||'-')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+(r.snr_db != null ? r.snr_db+' dB' : '-')+'</td>'
      + '<td>'+esc(info)+'</td>'
      + '<td class="detail">'+esc(r.detail||'')+'</td>'
      + '</tr>';
  }).join('');
}

const _CATEGORY_RENDERERS = {
  voice:    renderVoice,
  drones:   renderDrones,
  aircraft: renderAircraft,
  vessels:  renderVessels,
  vehicles: renderVehicles,
  cellular: renderCellular,
  other:    renderOther,
};

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
    if (btn.dataset.tab === 'log') loadDetections();
    if (btn.dataset.tab === 'devices') loadDevices();
    if (btn.dataset.tab === 'config') loadConfig();
    if (btn.dataset.tab === 'timeline') loadActivity();
    if (['voice','drones','aircraft','vessels','vehicles','cellular','other']
        .includes(btn.dataset.tab)) loadCategory(btn.dataset.tab);
  });
});

function goToTab(name) {
  const btn = document.querySelector('.tab-btn[data-tab="'+name+'"]');
  if (btn) btn.click();
}

// Auto-refresh Config tab every 3s so status badges stay live
setInterval(() => {
  const cfgTab = document.getElementById('tab-config');
  if (cfgTab && cfgTab.classList.contains('active')) loadConfig();
}, 3000);
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

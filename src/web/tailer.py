"""
DBTailer — background thread that watches the output directory for SQLite
detection files, bulk-reads historical ones once, and tails the newest by
rowid in read-only WAL mode. Each new row is fed through _process_row into
per-type counters, a 50k detection ring buffer, a live "recent events"
feed, and a per-minute activity histogram for the Timeline tab.

Also hosts:
  _get_system_stats — /proc-based CPU/mem/temp/disk snapshot for the header
  _extract_detail   — per-signal-type one-line summary string for the Log tab
  _extract_uid      — per-signal-type unique identifier for dedup counting
"""

import json
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta

from .categories import CATEGORY_LABELS, CATEGORY_ORDER, category_of


def _get_system_stats():
    """Read CPU, memory, and disk stats from /proc and os (Linux)."""
    stats = {}
    try:
        # CPU load average (instantaneous, no state)
        load1, _, _ = os.getloadavg()
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

        # Disk usage for root partition
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
                    self._tail_last_id = 0
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

        new_keys = {k: v for k, v in data.items() if self._transcripts.get(k) != v}
        self._transcripts = data
        if not new_keys:
            return

        with self._lock:
            for d in self._detections:
                af = d.get("audio_file")
                if not af:
                    continue
                t = new_keys.get(af)
                if t and d.get("transcript") != t:
                    d["transcript"] = t
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

            if sig == "WiFi-AP":
                bssid = meta.get("bssid") or row.get("device_id", "")
                if bssid:
                    self._recent_bssids[bssid] = {
                        "rssi": power_db if power_db else None,
                        "last_seen": ts,
                    }

            uid = _extract_uid(sig, row, meta)
            if uid:
                if sig not in self._type_uniques:
                    self._type_uniques[sig] = set()
                self._type_uniques[sig].add(uid)

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
                "category": category_of(sig),
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

            freq_mhz = freq / 1e6 if freq else 0
            line = (
                f"{ts_short}  {sig:12s} {ch:6s}  "
                f"{freq_mhz:8.3f} MHz  {snr:5.1f} dB  {detail}"
            )
            self._recent_events.append((sig, line))

            minute_key = ts[:16] if len(ts) >= 16 else ""
            if minute_key:
                if minute_key not in self._activity_minutes:
                    self._activity_minutes[minute_key] = Counter()
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
                    "category": category_of(sig),
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
        """Return dict of dev_sig → info for devices seen in the last N minutes.

        `rssi` is the real dBm RSSI from power_db (BLE HCI, WiFi scapy),
        not snr_db — for BLE the noise floor is a nominal -100 dB so
        snr_db = rssi + 100, which is not what the UI wants to show.
        """
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
                        "rssi": d.get("power_db"),
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

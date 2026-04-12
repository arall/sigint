"""
Device + category loaders for the web dashboard.

Two groups of pure functions, consumed by the HTTP endpoints:

Device loaders (read the persistent devices.db tables):
  _load_wifi_clients / _load_wifi_aps / _load_ble_devices
    → feed the Devices tab's three sub-sections.

Category loaders (operate on an in-memory detection deque snapshot):
  _load_voice / _load_drones / _load_aircraft / _load_vessels /
  _load_vehicles / _load_cellular / _load_other
    → feed each category tab (/api/cat/<name>).

CATEGORY_LOADERS at the bottom is the dispatch table used by the HTTP
handler to resolve a category id to its loader function.
"""

import json
import os
import sqlite3

from .categories import CATEGORIES


def _open_devices_db(output_dir):
    """Open output/devices.db read-only. Returns None when the file
    doesn't exist yet (the parsers haven't written anything) or when
    even the readonly open fails. Each call opens a fresh connection
    so we never share state across threads or requests.
    """
    path = os.path.join(output_dir, "devices.db")
    if not os.path.isfile(path):
        return None
    abs_path = os.path.abspath(path)
    try:
        conn = sqlite3.connect(
            f"file:{abs_path}?mode=ro", uri=True, timeout=2.0,
            isolation_level=None, check_same_thread=False,
        )
    except sqlite3.OperationalError:
        try:
            conn = sqlite3.connect(
                f"file:{abs_path}?mode=ro&immutable=1", uri=True, timeout=2.0,
                isolation_level=None, check_same_thread=False,
            )
        except sqlite3.OperationalError:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _iter_persona_rows(output_dir, table):
    """Yield rows from a persona table (personas_wifi or personas_bt)
    in the devices.db. Silently returns nothing when the DB is absent
    or the table hasn't been created yet."""
    conn = _open_devices_db(output_dir)
    if conn is None:
        return
    try:
        for r in conn.execute(
            f"SELECT persona_key, dev_sig, ssids, macs_seen, manufacturer, "
            f"apple_device, randomized, sessions, first_session, "
            f"last_session, total_probes FROM {table}"
        ).fetchall():
            yield r
    except sqlite3.OperationalError:
        return
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _iter_ap_rows(output_dir):
    """Yield wifi_aps rows from the devices.db."""
    conn = _open_devices_db(output_dir)
    if conn is None:
        return
    try:
        for r in conn.execute(
            "SELECT bssid, ssids, channels, crypto, manufacturer, hidden, "
            "beacon_interval, last_rssi, first_seen, last_seen, sessions, "
            "total_beacons, clients, client_count FROM wifi_aps"
        ).fetchall():
            yield r
    except sqlite3.OperationalError:
        return
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Type colors — referenced by the JS frontend; injected at /api/colors or
# baked into the static app.js. Kept here so the category + device
# domains share one source of truth.
# ---------------------------------------------------------------------------

TYPE_COLORS = {
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
# Device loaders — read persona / AP JSON databases from the output dir
# ---------------------------------------------------------------------------

def _load_wifi_clients(output_dir, active_sigs=None):
    """Read the personas_wifi table from devices.db and shape WiFi client
    device records for the Devices tab.

    A WiFi client is a phone/laptop that emits probe requests. The label
    is manufacturer+fingerprint (NOT the SSID — that's what the client is
    probing FOR, not its identity).
    """
    active_sigs = active_sigs or {}
    clients = []
    for r in _iter_persona_rows(output_dir, "personas_wifi"):
        persona_key = r["persona_key"]
        dev_sig = r["dev_sig"] or persona_key.split(":")[0]
        macs = json.loads(r["macs_seen"] or "[]")
        ssids = json.loads(r["ssids"] or "[]")
        manufacturer = r["manufacturer"] or ""
        randomized = bool(r["randomized"])

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
            "sessions": int(r["sessions"] or 0),
            "total_probes": int(r["total_probes"] or 0),
            "first_session": r["first_session"] or "",
            "last_session": r["last_session"] or "",
            "active": bool(active_info),
            "last_rssi": active_info.get("rssi"),
        })

    clients.sort(key=lambda c: (
        c["active"], c["last_session"], c["total_probes"],
    ), reverse=True)
    return clients


def _load_ble_devices(output_dir, active_sigs=None):
    """Read the personas_bt table from devices.db and shape BLE records."""
    active_sigs = active_sigs or {}
    devices = []
    for r in _iter_persona_rows(output_dir, "personas_bt"):
        persona_key = r["persona_key"]
        dev_sig = r["dev_sig"] or persona_key.split(":")[0]
        macs = json.loads(r["macs_seen"] or "[]")
        names = json.loads(r["ssids"] or "[]")  # BLE names reuse "ssids"
        manufacturer = r["manufacturer"] or ""
        randomized = bool(r["randomized"])

        active_info = active_sigs.get(dev_sig, {})
        # Prefer the persisted apple_device (survives restart); fall back to
        # the value captured from recent live detections.
        apple_device = r["apple_device"] or active_info.get("apple_device", "")

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
            "sessions": int(r["sessions"] or 0),
            "total_probes": int(r["total_probes"] or 0),
            "first_session": r["first_session"] or "",
            "last_session": r["last_session"] or "",
            "active": bool(active_info),
            "last_rssi": active_info.get("rssi"),
        })

    devices.sort(key=lambda d: (
        d["active"], d["last_session"], d["total_probes"],
    ), reverse=True)
    return devices


def _load_wifi_aps(output_dir, active_bssids=None):
    """Read the wifi_aps table from devices.db and return records
    grouped by physical AP.

    Conservative grouping heuristic: two BSSIDs are merged into the same
    physical AP row if they share a non-empty SSID AND their first 5 MAC
    octets match (covers the common 2.4/5 GHz radio pattern where vendors
    increment only the last octet). Anything else stays ungrouped.
    """
    active_bssids = active_bssids or {}
    ap_map = {}
    for r in _iter_ap_rows(output_dir):
        bssid = r["bssid"]
        ap_map[bssid] = {
            "bssid": bssid,
            "ssids": json.loads(r["ssids"] or "[]"),
            "channels": json.loads(r["channels"] or "[]"),
            "crypto": r["crypto"] or "",
            "manufacturer": r["manufacturer"] or "",
            "hidden": bool(r["hidden"]),
            "beacon_interval": r["beacon_interval"],
            "last_rssi": r["last_rssi"],
            "first_seen": r["first_seen"] or "",
            "last_seen": r["last_seen"] or "",
            "sessions": int(r["sessions"] or 0),
            "total_beacons": int(r["total_beacons"] or 0),
            "clients": json.loads(r["clients"] or "[]"),
            "client_count": int(r["client_count"] or 0),
        }
    groups = []

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
# Category loaders — operate on an in-memory detection deque snapshot
# ---------------------------------------------------------------------------

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


def _psi_to_kpa(psi):
    """Convert PSI to kPa, or None if not a number."""
    v = _try_float(psi)
    return round(v * 6.89476, 1) if v is not None else None


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
                "vertical_rate": None,
                "squawk": "",
                "category": "",
                "on_ground": False,
                "emergency": "",
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
            ("altitude_ft",   "altitude",      _try_int),
            ("speed_kt",      "speed",         _try_float),
            ("heading",       "heading",       _try_float),
            ("vertical_rate", "vertical_rate", _try_int),
        ):
            v = meta.get(k_meta)
            if v not in (None, ""):
                c = cast(v)
                if c is not None:
                    rec[k_out] = c
        for k in ("squawk", "category", "emergency"):
            v = (meta.get(k) or "").strip()
            if v:
                rec[k] = v
        if meta.get("on_ground"):
            rec["on_ground"] = True
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
                "callsign": "",
                "imo": "",
                "ship_type": "",
                "nav_status": "",
                "speed_kn": None,
                "course": None,
                "heading": None,
                "rot": None,
                "destination": "",
                "draught": None,
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
        for k in ("name", "callsign", "imo", "ship_type", "nav_status", "destination"):
            v = (meta.get(k) or meta.get({"ship_type": "type", "nav_status": "status"}.get(k, "")) or "").strip()
            if v:
                rec[k] = v
        for k_out, k_meta in (("speed_kn", "speed_kn"), ("course", "course"),
                              ("heading", "heading"), ("rot", "rot"), ("draught", "draught")):
            v = _try_float(meta.get(k_meta) if meta.get(k_meta) is not None else meta.get({"speed_kn": "sog", "course": "cog"}.get(k_out, "")))
            if v is not None:
                rec[k_out] = v
        if d.get("latitude") is not None:
            rec["latitude"] = d["latitude"]
            rec["longitude"] = d["longitude"]
    out = list(vessels.values())
    out.sort(key=lambda r: r["last_seen"], reverse=True)
    return out


def _load_keyfobs(detections):
    """Keyfob bursts from native parser and ISM/rtl_433. Groups by device ID."""
    items = {}
    for d in detections:
        sig = d["signal_type"]
        meta = d.get("meta") or {}
        # Native keyfob parser
        if sig == "keyfob":
            dhex = meta.get("data_hex", "")
            key = f"kf:{dhex or d['frequency_mhz']}"
            dev_id = dhex or f"{d['frequency_mhz']} MHz"
            protocol = meta.get("protocol", "")
        # ISM keyfob (HCS200, FSK, etc.)
        elif sig.startswith("ISM:"):
            dev_id = d.get("channel") or meta.get("encrypted", "") or sig
            key = f"ism:{dev_id}"
            protocol = sig.replace("ISM:", "")
        else:
            continue
        rec = items.get(key) or {
            "id": dev_id,
            "first_seen": d["timestamp"],
            "last_seen":  d["timestamp"],
            "count": 0,
            "protocol": protocol,
            "frequency_mhz": d["frequency_mhz"],
            "snr_db": d.get("snr_db"),
        }
        rec["count"] += 1
        if d["timestamp"] > rec["last_seen"]:
            rec["last_seen"] = d["timestamp"]
            rec["snr_db"] = d.get("snr_db")
        items[key] = rec
    out = list(items.values())
    out.sort(key=lambda r: r["last_seen"], reverse=True)
    return out


def _load_tpms(detections):
    """TPMS sensors from native parser and ISM/rtl_433. One row per unique sensor_id."""
    items = {}
    for d in detections:
        meta = d.get("meta") or {}
        sig = d["signal_type"]
        # Native TPMS parser
        if sig == "tpms":
            sid = meta.get("sensor_id")
        # ISM TPMS (rtl_433 decoded, e.g. ISM:Ford)
        elif sig.startswith("ISM:") and meta.get("type") == "TPMS":
            sid = d.get("channel") or meta.get("code", "")
            meta.setdefault("pressure_kpa", _psi_to_kpa(meta.get("pressure_PSI")))
            meta.setdefault("temperature_c", meta.get("temperature_C"))
            meta.setdefault("protocol", sig.replace("ISM:", ""))
        else:
            continue
        if not sid:
            continue
        key = f"tpms:{sid}"
        rec = items.get(key) or {
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


def _load_generic_signals(detections, category):
    """Generic loader for signal categories — returns timestamped rows."""
    rows = []
    for d in reversed(detections):
        if d.get("category") != category:
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


def _load_ism(detections):
    """ISM band devices (rtl_433 decoded + native FSK/OOK)."""
    return _load_generic_signals(detections, "ism")


def _load_lora(detections):
    """LoRa / Meshtastic chirp detections."""
    return _load_generic_signals(detections, "lora")


def _load_pagers(detections):
    """POCSAG pager messages."""
    return _load_generic_signals(detections, "pagers")


CATEGORY_LOADERS = {
    "voice":    _load_voice,
    "drones":   _load_drones,
    "aircraft": _load_aircraft,
    "vessels":  _load_vessels,
    "keyfobs":  _load_keyfobs,
    "tpms":     _load_tpms,
    "cellular": _load_cellular,
    "ism":      _load_ism,
    "lora":     _load_lora,
    "pagers":   _load_pagers,
}

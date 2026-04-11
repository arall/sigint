"""
Device + category loaders for the web dashboard.

Two groups of pure functions, consumed by the HTTP endpoints:

Device loaders (read persisted JSON sidecars in the output directory):
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

from .categories import CATEGORIES


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
    """Read personas.json and return WiFi client device records.

    A WiFi client is a phone/laptop that emits probe requests. The label
    is manufacturer+fingerprint (NOT the SSID — that's what the client is
    probing FOR, not its identity).
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


CATEGORY_LOADERS = {
    "voice":    _load_voice,
    "drones":   _load_drones,
    "aircraft": _load_aircraft,
    "vessels":  _load_vessels,
    "vehicles": _load_vehicles,
    "cellular": _load_cellular,
    "other":    _load_other,
}

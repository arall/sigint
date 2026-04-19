"""
Reference-emitter extractors for opportunistic RSSI calibration.

Each extractor turns a stream of stored detections into `cal_samples` rows by
matching them against emitters whose position and TX power are known. The
expected RSSI is computed from free-space path loss; the offset = measured −
expected. `calibration.solve_node_offsets` later fits the robust central
tendency of these offsets per band.

Two kinds of sources are supported today:

  surveyed-*   user-maintained registry (WiFi BSSIDs, FM stations, cell sites)
               at known lat/lon with declared EIRP. This is the path that works
               with the current scanners — wifi/beacon logs real radiotap dBm,
               fm logs FFT peak power.

  adsb / ais   the framework is present but the current adsb.py / ais.py
               scanners log power_db=0 (RSSI not captured). These extractors
               match the pattern but produce no samples until those scanners
               are enhanced to record signal level. No-op-safe.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from typing import Iterable, Iterator, Optional

from utils import calibration as _cal


# Default EIRP in dBm for aircraft ADS-B by category. Class A1 (small fixed-
# wing) is ~125 W = +51 dBm. Larger airliners are similar (~125-250 W). Light
# general aviation transponders are ~70 W = +49 dBm. These are priors; the
# Huber fit handles real-world variation.
ADSB_EIRP_BY_CATEGORY = {
    "Light":       49.0,
    "Small":       51.0,
    "Large":       51.0,
    "High vortex": 51.0,
    "Heavy":       53.0,
    "High performance": 51.0,
    "Rotorcraft":  49.0,
    "Glider":      44.0,
    "UAV":         44.0,
}
ADSB_EIRP_DEFAULT = 51.0
ADSB_EIRP_STDERR = 3.0  # uncertainty prior used for weighting

# AIS class-based EIRP — class A transponders are ~12.5 W (+41 dBm) typical,
# class B are ~2 W (+33 dBm). MMSI range doesn't reliably identify class;
# message type 18/19 is class B, type 1/2/3/5 is class A.
AIS_EIRP_CLASS_A = 41.0
AIS_EIRP_CLASS_B = 33.0


# --- earth geometry helpers --------------------------------------------------
EARTH_R_M = 6371000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return EARTH_R_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _slant_and_elevation(node_lat: float, node_lon: float, node_alt_m: float,
                         tgt_lat: float, tgt_lon: float, tgt_alt_m: float
                         ) -> tuple[float, float]:
    """3-D slant range (m) and elevation angle (deg) from node to target."""
    ground = _haversine_m(node_lat, node_lon, tgt_lat, tgt_lon)
    dz = float(tgt_alt_m) - float(node_alt_m)
    slant = math.sqrt(ground * ground + dz * dz)
    if slant <= 0:
        return 0.0, 0.0
    elev = math.degrees(math.atan2(dz, ground)) if ground > 0 else 90.0
    return slant, elev


# --- reference emitter registry ---------------------------------------------
def empty_registry() -> dict:
    return {"wifi": {}, "fm": {}, "cell": {}, "adsb_eirp": {}}


def load_reference_emitters(path: str) -> dict:
    """Load configs/calibration_emitters.json.

    Shape:
      {
        "wifi": {"<BSSID lowercase>": {"lat":.., "lon":.., "eirp_dbm":.., "eirp_stderr":..}},
        "fm":   {"<label>": {"freq_hz":.., "lat":.., "lon":.., "eirp_dbm":..}},
        "cell": {"<CGI>": {"freq_hz":.., "lat":.., "lon":.., "eirp_dbm":..}},
        "adsb_eirp": {"<category>": <dbm>}   # optional overrides
      }
    Missing sections default to empty; file not found → empty registry.
    """
    if not path or not os.path.exists(path):
        return empty_registry()
    with open(path) as f:
        raw = json.load(f)
    reg = empty_registry()
    for section in ("wifi", "fm", "cell", "adsb_eirp"):
        if section in raw and isinstance(raw[section], dict):
            reg[section] = raw[section]
    # Normalize WiFi BSSIDs to lower-case with colons.
    reg["wifi"] = {_norm_mac(k): v for k, v in reg["wifi"].items()}
    return reg


def _norm_mac(mac: str) -> str:
    if not mac:
        return ""
    return mac.strip().lower().replace("-", ":")


# --- detection parsing helpers ----------------------------------------------
def _iter_raw_detections(det_conn: sqlite3.Connection,
                         since_epoch: Optional[float] = None
                         ) -> Iterator[sqlite3.Row]:
    sql = "SELECT id, timestamp, ts_epoch, signal_type, frequency_hz, " \
          "power_db, noise_floor_db, snr_db, channel, latitude, longitude, " \
          "device_id, audio_file, metadata FROM detections"
    params: list = []
    if since_epoch is not None:
        sql += " WHERE ts_epoch >= ?"
        params.append(since_epoch)
    sql += " ORDER BY id"
    yield from det_conn.execute(sql, params)


def _parse_meta(s) -> dict:
    if not s:
        return {}
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# --- primary entrypoint -----------------------------------------------------
def extract_samples(
    *,
    det_conn: sqlite3.Connection,
    db_file: str,
    node_id: str,
    node_lat: float,
    node_lon: float,
    node_alt: float,
    emitters: dict,
    source_filter: Optional[set] = None,
    since_epoch: Optional[float] = None,
    skip_rowids: Optional[set] = None,
) -> Iterator[dict]:
    """Iterate over detections and emit calibration samples for matched ones."""
    skip_rowids = skip_rowids or set()

    for row in _iter_raw_detections(det_conn, since_epoch=since_epoch):
        rowid = int(row["id"])
        if rowid in skip_rowids:
            continue
        meta = _parse_meta(row["metadata"])
        sig_type = (row["signal_type"] or "").lower()

        sample = None
        if sig_type in ("adsb", "ads-b"):
            if _source_enabled("adsb", source_filter):
                sample = _try_adsb(row, meta, node_id, node_lat, node_lon,
                                   node_alt, emitters, db_file, rowid)
        elif sig_type == "ais":
            if _source_enabled("ais", source_filter):
                sample = _try_ais(row, meta, node_id, node_lat, node_lon,
                                  node_alt, emitters, db_file, rowid)
        elif sig_type in ("wifi-ap", "wifi_ap", "wifi-probe", "wifi_probe", "wifi"):
            if _source_enabled("surveyed", source_filter):
                sample = _try_surveyed_wifi(row, meta, node_id, node_lat,
                                            node_lon, node_alt, emitters,
                                            db_file, rowid)
        elif sig_type.startswith("fm") or sig_type in ("broadcast-fm", "fm-broadcast"):
            if _source_enabled("surveyed", source_filter):
                sample = _try_surveyed_fm(row, meta, node_id, node_lat,
                                          node_lon, node_alt, emitters,
                                          db_file, rowid)
        elif sig_type in ("gsm", "lte"):
            if _source_enabled("surveyed", source_filter):
                sample = _try_surveyed_cell(row, meta, node_id, node_lat,
                                            node_lon, node_alt, emitters,
                                            db_file, rowid)

        if sample is not None:
            yield sample


def _source_enabled(name: str, source_filter: Optional[set]) -> bool:
    if not source_filter:
        return True
    return name in source_filter or "all" in source_filter


# --- ADS-B -----------------------------------------------------------------
def _try_adsb(row, meta, node_id, node_lat, node_lon, node_alt,
              emitters, db_file, rowid) -> Optional[dict]:
    """ADS-B: aircraft self-reports lat/lon/alt; EIRP from category table.

    NOTE: current adsb.py logs power_db=0 which will make residuals useless.
    We still emit the sample (with weight computed) so a scanner enhancement
    that populates power_db lights this up instantly; analysts can filter
    `WHERE power_db != 0` until that lands.
    """
    try:
        power_db = float(row["power_db"] or 0.0)
    except (TypeError, ValueError):
        return None
    if power_db == 0.0:
        # Today's adsb.py logs power_db=0 — unpopulated default. Skip until
        # the scanner is enhanced to record per-message signal level.
        return None

    # Aircraft position: adsb.py writes it into the detection row's lat/lon.
    tgt_lat = _maybe_float(row["latitude"])
    tgt_lon = _maybe_float(row["longitude"])
    tgt_alt_ft = meta.get("altitude")
    if tgt_lat is None or tgt_lon is None or tgt_alt_ft in (None, "", 0):
        return None
    tgt_alt_m = float(tgt_alt_ft) * 0.3048

    distance_m, elev_deg = _slant_and_elevation(
        node_lat, node_lon, node_alt, tgt_lat, tgt_lon, tgt_alt_m)

    # Reject low-elevation and far-horizon returns.
    if elev_deg < 5.0 or distance_m > 400_000 or distance_m < 500:
        return None

    freq_hz = float(row["frequency_hz"] or 1090e6)
    band = _cal.band_for(freq_hz) or "UHF"
    category = meta.get("category") or ""
    eirp_overrides = emitters.get("adsb_eirp", {}) if emitters else {}
    eirp_dbm = float(eirp_overrides.get(category, ADSB_EIRP_BY_CATEGORY.get(category, ADSB_EIRP_DEFAULT)))

    expected = _cal.expected_rssi_fspl(eirp_dbm, distance_m, freq_hz)
    offset = power_db - expected

    # Weight: favour close, high-elevation, high-SNR samples.
    snr = max(float(row["snr_db"] or 0.0), 1.0)
    geom = math.sin(math.radians(elev_deg))
    weight = (snr * geom) / (1.0 + distance_m / 10_000.0) / (ADSB_EIRP_STDERR + 1.0)

    return {
        "ts_epoch": float(row["ts_epoch"] or 0.0),
        "device_id": node_id,
        "band": band,
        "frequency_hz": freq_hz,
        "source": "adsb",
        "ref_id": str(meta.get("icao") or row["channel"] or ""),
        "power_db": power_db,
        "expected_db": expected,
        "offset_db": offset,
        "distance_m": distance_m,
        "elevation_deg": elev_deg,
        "weight": weight,
        "session_db": db_file,
        "det_rowid": rowid,
    }


# --- AIS -------------------------------------------------------------------
def _try_ais(row, meta, node_id, node_lat, node_lon, node_alt,
             emitters, db_file, rowid) -> Optional[dict]:
    try:
        power_db = float(row["power_db"] or 0.0)
    except (TypeError, ValueError):
        return None
    if power_db == 0.0:
        return None  # current ais.py does not populate power_db
    tgt_lat = _maybe_float(meta.get("latitude") or row["latitude"])
    tgt_lon = _maybe_float(meta.get("longitude") or row["longitude"])
    if tgt_lat is None or tgt_lon is None:
        return None

    distance_m = _haversine_m(node_lat, node_lon, tgt_lat, tgt_lon)
    if distance_m < 500 or distance_m > 200_000:
        return None

    # Class A vs B based on message type (AIS parser sets "msg_type").
    msg_type = meta.get("msg_type") or meta.get("type")
    if msg_type in (18, 19, "18", "19", "B", "b", "class_b"):
        eirp_dbm = AIS_EIRP_CLASS_B
    else:
        eirp_dbm = AIS_EIRP_CLASS_A

    freq_hz = float(row["frequency_hz"] or 162e6)
    band = _cal.band_for(freq_hz) or "VHF-high"
    expected = _cal.expected_rssi_fspl(eirp_dbm, distance_m, freq_hz)
    offset = power_db - expected
    snr = max(float(row["snr_db"] or 0.0), 1.0)
    weight = snr / (1.0 + distance_m / 10_000.0)

    return {
        "ts_epoch": float(row["ts_epoch"] or 0.0),
        "device_id": node_id,
        "band": band,
        "frequency_hz": freq_hz,
        "source": "ais",
        "ref_id": str(meta.get("mmsi") or row["channel"] or ""),
        "power_db": power_db,
        "expected_db": expected,
        "offset_db": offset,
        "distance_m": distance_m,
        "elevation_deg": None,
        "weight": weight,
        "session_db": db_file,
        "det_rowid": rowid,
    }


# --- surveyed WiFi ---------------------------------------------------------
def _try_surveyed_wifi(row, meta, node_id, node_lat, node_lon, node_alt,
                       emitters, db_file, rowid) -> Optional[dict]:
    try:
        power_db = float(row["power_db"] or 0.0)
    except (TypeError, ValueError):
        return None
    if power_db == 0.0:
        return None  # likely an unpopulated default, not a real measurement

    bssid = _norm_mac(meta.get("bssid") or meta.get("mac") or row["device_id"] or "")
    if not bssid:
        return None
    reg = (emitters or {}).get("wifi", {})
    ref = reg.get(bssid)
    if ref is None:
        return None

    try:
        tgt_lat = float(ref["lat"])
        tgt_lon = float(ref["lon"])
        eirp_dbm = float(ref.get("eirp_dbm", 20.0))
    except (KeyError, TypeError, ValueError):
        return None
    eirp_stderr = float(ref.get("eirp_stderr", 3.0))

    distance_m = _haversine_m(node_lat, node_lon, tgt_lat, tgt_lon)
    if distance_m < 5 or distance_m > 2000:
        return None  # NLOS / beyond WiFi realistic range

    freq_hz = float(row["frequency_hz"] or 2.437e9)
    band = _cal.band_for(freq_hz) or ("5G" if freq_hz > 5e9 else "2G4")
    expected = _cal.expected_rssi_fspl(eirp_dbm, distance_m, freq_hz)
    offset = power_db - expected
    snr = max(float(row["snr_db"] or 0.0), 1.0)
    weight = snr / (eirp_stderr + 1.0) / (1.0 + distance_m / 200.0)

    return {
        "ts_epoch": float(row["ts_epoch"] or 0.0),
        "device_id": node_id,
        "band": band,
        "frequency_hz": freq_hz,
        "source": "surveyed-wifi",
        "ref_id": bssid,
        "power_db": power_db,
        "expected_db": expected,
        "offset_db": offset,
        "distance_m": distance_m,
        "elevation_deg": None,
        "weight": weight,
        "session_db": db_file,
        "det_rowid": rowid,
    }


# --- surveyed FM broadcast --------------------------------------------------
def _try_surveyed_fm(row, meta, node_id, node_lat, node_lon, node_alt,
                     emitters, db_file, rowid) -> Optional[dict]:
    try:
        power_db = float(row["power_db"] or 0.0)
    except (TypeError, ValueError):
        return None
    if power_db == 0.0:
        return None

    freq_hz = float(row["frequency_hz"] or 0.0)
    if freq_hz <= 0:
        return None

    reg = (emitters or {}).get("fm", {})
    ref = _match_by_frequency(reg, freq_hz, tol_hz=100_000)
    if ref is None:
        return None
    try:
        tgt_lat = float(ref["lat"])
        tgt_lon = float(ref["lon"])
        eirp_dbm = float(ref["eirp_dbm"])
    except (KeyError, TypeError, ValueError):
        return None
    eirp_stderr = float(ref.get("eirp_stderr", 3.0))

    distance_m = _haversine_m(node_lat, node_lon, tgt_lat, tgt_lon)
    if distance_m < 500 or distance_m > 150_000:
        return None

    band = _cal.band_for(freq_hz) or "VHF-high"
    expected = _cal.expected_rssi_fspl(eirp_dbm, distance_m, freq_hz)
    offset = power_db - expected
    snr = max(float(row["snr_db"] or 0.0), 1.0)
    weight = snr / (eirp_stderr + 1.0) / (1.0 + distance_m / 20_000.0)

    return {
        "ts_epoch": float(row["ts_epoch"] or 0.0),
        "device_id": node_id,
        "band": band,
        "frequency_hz": freq_hz,
        "source": "surveyed-fm",
        "ref_id": ref.get("_key", f"{freq_hz / 1e6:.1f}MHz"),
        "power_db": power_db,
        "expected_db": expected,
        "offset_db": offset,
        "distance_m": distance_m,
        "elevation_deg": None,
        "weight": weight,
        "session_db": db_file,
        "det_rowid": rowid,
    }


# --- surveyed cell towers ---------------------------------------------------
def _try_surveyed_cell(row, meta, node_id, node_lat, node_lon, node_alt,
                       emitters, db_file, rowid) -> Optional[dict]:
    """Dormant until scanners identify specific cells (cgi, enb, pci).

    Matching key in metadata: "cgi" (MCC-MNC-LAC-CID) or similar. Today's
    gsm/lte scanners log aggregate band activity only, so this stays inert.
    """
    cgi = meta.get("cgi") or meta.get("cell_id")
    if not cgi:
        return None
    try:
        power_db = float(row["power_db"] or 0.0)
    except (TypeError, ValueError):
        return None
    if power_db == 0.0:
        return None

    reg = (emitters or {}).get("cell", {})
    ref = reg.get(str(cgi))
    if ref is None:
        return None

    try:
        tgt_lat = float(ref["lat"])
        tgt_lon = float(ref["lon"])
        eirp_dbm = float(ref["eirp_dbm"])
        freq_hz = float(ref.get("freq_hz") or row["frequency_hz"])
    except (KeyError, TypeError, ValueError):
        return None

    distance_m = _haversine_m(node_lat, node_lon, tgt_lat, tgt_lon)
    if distance_m < 100 or distance_m > 30_000:
        return None

    band = _cal.band_for(freq_hz) or "UHF"
    expected = _cal.expected_rssi_fspl(eirp_dbm, distance_m, freq_hz)
    offset = power_db - expected
    snr = max(float(row["snr_db"] or 0.0), 1.0)
    weight = snr / (1.0 + distance_m / 5_000.0)

    return {
        "ts_epoch": float(row["ts_epoch"] or 0.0),
        "device_id": node_id,
        "band": band,
        "frequency_hz": freq_hz,
        "source": "surveyed-cell",
        "ref_id": str(cgi),
        "power_db": power_db,
        "expected_db": expected,
        "offset_db": offset,
        "distance_m": distance_m,
        "elevation_deg": None,
        "weight": weight,
        "session_db": db_file,
        "det_rowid": rowid,
    }


# --- misc helpers ----------------------------------------------------------
def _match_by_frequency(reg: dict, freq_hz: float, tol_hz: float) -> Optional[dict]:
    best = None
    best_delta = tol_hz
    for key, entry in reg.items():
        try:
            f = float(entry.get("freq_hz"))
        except (TypeError, ValueError):
            continue
        delta = abs(f - freq_hz)
        if delta < best_delta:
            best = dict(entry, _key=key)
            best_delta = delta
    return best


def _maybe_float(x) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

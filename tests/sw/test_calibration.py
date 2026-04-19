"""
Calibration math + DB + sources regression tests.

Covers the mechanics that the opportunistic calibration pipeline depends on:
FSPL arithmetic, band bucketing, robust offset fitting, Calibration.get()
band interpolation + stderr fallback, sample ingestion shape, and the
surveyed-WiFi extractor happy path.

Run:
    python3 tests/sw/test_calibration.py
"""

import json
import math
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


# --- math -------------------------------------------------------------------
def test_fspl_at_1090mhz():
    """FSPL at 10 km, 1090 MHz ≈ 113.2 dB."""
    from utils.calibration import expected_rssi_fspl
    # At EIRP=0 dBm, RSSI = -FSPL
    rssi = expected_rssi_fspl(eirp_dbm=0.0, distance_m=10_000.0, freq_hz=1090e6)
    fspl = -rssi
    assert 112.5 < fspl < 113.5, f"FSPL {fspl:.2f} dB not ~113.2"


def test_fspl_at_2450mhz_100m():
    """Common WiFi sanity: 2.45 GHz, 100 m → ~80.2 dB path loss."""
    from utils.calibration import expected_rssi_fspl
    rssi = expected_rssi_fspl(eirp_dbm=20.0, distance_m=100.0, freq_hz=2.45e9)
    # expected: 20 - 80.2 = -60.2 dBm
    assert -61.0 < rssi < -59.0, f"Expected ~-60.2 dBm, got {rssi:.2f}"


def test_band_for_picks_narrowest():
    """900 MHz should land in '900' not 'UHF' (overlap → narrower wins)."""
    from utils.calibration import band_for
    assert band_for(2.437e9) == "2G4"
    assert band_for(915e6) == "900"
    assert band_for(1090e6) == "UHF"
    # FM broadcast (88-108 MHz) falls in VHF-low by our split at 144 MHz.
    assert band_for(98.5e6) == "VHF-low"
    assert band_for(162.025e6) == "VHF-high"
    assert band_for(14e6) == "HF"
    assert band_for(3.5e9) is None
    assert band_for(0) is None
    assert band_for(-1) is None


def test_huber_recovers_offset_with_outliers():
    """Generate 200 residuals around a true offset, inject 5% outliers."""
    from utils.calibration import fit_offset_huber
    rng = random.Random(42)
    true_offset = -17.4
    residuals = []
    weights = []
    for i in range(200):
        if i < 10:
            residuals.append(true_offset + rng.uniform(-25, 25))  # outlier
        else:
            residuals.append(true_offset + rng.gauss(0, 2.0))
        weights.append(1.0)
    fit = fit_offset_huber(residuals, weights)
    assert abs(fit.offset_db - true_offset) < 0.6, (
        f"Huber recovered {fit.offset_db:.2f}, expected ~{true_offset}")
    assert fit.n_samples >= 150  # most samples retained


def test_mean_falls_back_without_scipy():
    from utils.calibration import fit_offset_mean
    fit = fit_offset_mean([1.0, 2.0, 3.0], [1.0, 1.0, 1.0])
    assert abs(fit.offset_db - 2.0) < 1e-9
    assert fit.method == "mean"


def test_empty_fit_returns_empty():
    from utils.calibration import fit_offset_huber, fit_offset_mean
    assert fit_offset_huber([], []).n_samples == 0
    assert fit_offset_mean([], []).n_samples == 0


# --- Calibration lookup -----------------------------------------------------
def test_calibration_get_exact_band():
    from utils.calibration import Calibration
    cal = Calibration(offsets={("n01", "UHF"): (-18.0, 0.5)})
    offset, applied = cal.get("n01", 1090e6)
    assert applied and abs(offset - (-18.0)) < 1e-9


def test_calibration_get_unknown_node_returns_zero():
    from utils.calibration import Calibration
    cal = Calibration(offsets={("n01", "UHF"): (-18.0, 0.5)})
    offset, applied = cal.get("n02", 1090e6)
    assert offset == 0.0 and not applied


def test_calibration_interpolates_neighbor_bands():
    """No UHF offset, but VHF-high and 2G4 → lookup at 433 MHz should interpolate."""
    from utils.calibration import Calibration
    cal = Calibration(offsets={
        ("n01", "VHF-high"): (-10.0, 0.5),
        ("n01", "2G4"):      (-20.0, 0.5),
    })
    # 433 MHz: no UHF offset; neighbors are VHF-high (mid 222 MHz) and 2G4 (2.4 GHz).
    # Linear interp t = (433 − 222)/(2400 − 222) ≈ 0.097 → offset ≈ -10.97
    off, applied = cal.get("n01", 433e6)
    assert applied
    assert -14.0 < off < -9.0, f"Unexpected interpolated offset {off}"


def test_calibration_high_stderr_exact_still_returns():
    """Wide stderr is used if no better neighbour exists."""
    from utils.calibration import Calibration
    cal = Calibration(offsets={("n01", "UHF"): (-18.0, 5.0)})
    off, applied = cal.get("n01", 1090e6)
    assert applied and abs(off - (-18.0)) < 1e-9


def test_apply_offset_subtracts():
    """corrected = measured − offset."""
    from utils.calibration import Calibration, apply_offset
    cal = Calibration(offsets={("n01", "UHF"): (-18.0, 0.1)})
    corrected, applied = apply_offset(power_db=-80.0, device_id="n01",
                                      freq_hz=1090e6, cal=cal)
    assert applied
    # offset is -18 → corrected = -80 − (-18) = -62
    assert abs(corrected - (-62.0)) < 1e-9


# --- Calibration DB ---------------------------------------------------------
def test_db_schema_and_upsert():
    from utils import calibration_db as _cdb
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cal.db")
    conn = _cdb.connect(path)

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"cal_samples", "cal_offsets", "cal_meta"}.issubset(tables)

    _cdb.upsert_offset(conn, "n01", "UHF", -18.2, 0.5, 120, "huber")
    _cdb.upsert_offset(conn, "n01", "UHF", -18.4, 0.4, 130, "huber")
    rows = _cdb.get_offsets(conn, device_id="n01")
    assert len(rows) == 1
    assert abs(rows[0]["offset_db"] - (-18.4)) < 1e-9
    assert rows[0]["n_samples"] == 130


def test_db_insert_and_iter_samples():
    from utils import calibration_db as _cdb
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cal.db")
    conn = _cdb.connect(path)

    sample = {
        "ts_epoch": 1700000000.0, "device_id": "n01", "band": "UHF",
        "frequency_hz": 1090e6, "source": "surveyed-fm", "ref_id": "test",
        "power_db": -55.2, "expected_db": -40.0, "offset_db": -15.2,
        "distance_m": 5000, "elevation_deg": 12.0, "weight": 1.5,
        "session_db": "a.db", "det_rowid": 42,
    }
    _cdb.insert_sample(conn, sample)
    rows = list(_cdb.iter_samples(conn, device_id="n01"))
    assert len(rows) == 1
    assert rows[0]["det_rowid"] == 42

    # seen_detection_ids makes ingest idempotent across re-runs
    seen = _cdb.seen_detection_ids(conn, "a.db")
    assert 42 in seen


def test_db_meta_roundtrip():
    from utils import calibration_db as _cdb
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cal.db")
    conn = _cdb.connect(path)
    _cdb.set_meta(conn, "node_lat:n01", "42.5098")
    _cdb.set_meta(conn, "node_lat:n01", "42.5099")  # overwrite
    assert _cdb.get_meta(conn, "node_lat:n01") == "42.5099"
    assert _cdb.get_meta(conn, "missing", "fallback") == "fallback"


# --- Reference emitter registry + extractor --------------------------------
def test_load_reference_emitters_missing_file():
    from utils import calibration_sources as _src
    reg = _src.load_reference_emitters("/nonexistent/path.json")
    assert reg == _src.empty_registry()


def test_load_reference_emitters_normalizes_mac():
    from utils import calibration_sources as _src
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "emitters.json")
    with open(path, "w") as f:
        json.dump({
            "wifi": {"AA-BB-CC-11-22-33": {"lat": 1, "lon": 2, "eirp_dbm": 20}}
        }, f)
    reg = _src.load_reference_emitters(path)
    assert "aa:bb:cc:11:22:33" in reg["wifi"]


def test_surveyed_wifi_extract_happy_path():
    """End-to-end: write a WiFi-AP detection to a real sqlite .db and extract."""
    from utils import db as _db
    from utils import calibration_sources as _src
    from utils.logger import SignalDetection

    tmp = tempfile.mkdtemp()
    det_path = os.path.join(tmp, "wifi.db")
    conn = _db.connect(det_path)
    bssid = "aa:bb:cc:11:22:33"
    # Node at (42.5098, 1.5361), AP 150 m NE (roughly).
    det = SignalDetection.create(
        signal_type="WiFi-AP",
        frequency_hz=2.437e9, power_db=-55.0, noise_floor_db=-95.0,
        channel="CH6",
        latitude=42.5098, longitude=1.5361,
        device_id=bssid,
        metadata=json.dumps({"bssid": bssid, "ssid": "test"}),
    )
    _db.insert_detection(conn, det)
    conn.close()

    emitters = {"wifi": {bssid: {"lat": 42.5108, "lon": 1.5373,
                                  "eirp_dbm": 20, "eirp_stderr": 2}},
                "fm": {}, "cell": {}, "adsb_eirp": {}}

    det_conn = _db.connect(det_path, readonly=True)
    samples = list(_src.extract_samples(
        det_conn=det_conn, db_file=det_path,
        node_id="n01", node_lat=42.5098, node_lon=1.5361, node_alt=0.0,
        emitters=emitters, source_filter={"surveyed"},
    ))
    det_conn.close()
    assert len(samples) == 1
    s = samples[0]
    assert s["source"] == "surveyed-wifi"
    assert s["band"] == "2G4"
    assert s["ref_id"] == bssid
    # 150 m ballpark — haversine between the two points.
    assert 100 < s["distance_m"] < 200
    # power_db=-55, expected ≈ 20 − 20*log10(150) − 20*log10(2.437e9) + 147.55
    #        ≈ 20 − 43.52 − 187.73 + 147.55 ≈ -63.7 dBm
    # offset = -55 − (-63.7) = +8.7
    assert 5 < s["offset_db"] < 15


def test_adsb_extractor_rejects_zero_power():
    """ADS-B scanner currently logs power_db=0; extractor must skip it."""
    from utils import db as _db
    from utils import calibration_sources as _src
    from utils.logger import SignalDetection

    tmp = tempfile.mkdtemp()
    det_path = os.path.join(tmp, "adsb.db")
    conn = _db.connect(det_path)
    det = SignalDetection.create(
        signal_type="ADS-B",
        frequency_hz=1090e6, power_db=0.0, noise_floor_db=0.0,
        channel="ABC123",
        latitude=42.6, longitude=1.55,  # aircraft lat/lon
        metadata=json.dumps({"icao": "ABC123", "altitude": 30000,
                             "category": "Heavy"}),
    )
    _db.insert_detection(conn, det)
    conn.close()

    det_conn = _db.connect(det_path, readonly=True)
    samples = list(_src.extract_samples(
        det_conn=det_conn, db_file=det_path,
        node_id="n01", node_lat=42.5098, node_lon=1.5361, node_alt=1000.0,
        emitters=_src.empty_registry(),
    ))
    det_conn.close()
    # SignalLogger drops rows below min_snr_db by default (5.0) and
    # snr_db = power_db - noise_floor_db = 0 - 0 = 0, so the row is
    # filtered at log time. If it did land, extractor would skip it.
    # Either way: no calibration samples produced.
    assert len(samples) == 0


def test_adsb_extractor_happy_path_with_rssi():
    """Once scanner populates RSSI (dBFS), the extractor emits a sample."""
    from utils import db as _db
    from utils import calibration_sources as _src
    from utils.logger import SignalDetection

    tmp = tempfile.mkdtemp()
    det_path = os.path.join(tmp, "adsb.db")
    conn = _db.connect(det_path)
    det = SignalDetection.create(
        signal_type="ADS-B",
        frequency_hz=1090e6, power_db=-20.0, noise_floor_db=-60.0,
        channel="ABC123",
        latitude=42.6, longitude=1.55,  # aircraft ≈ 10 km N, 9 km up
        metadata=json.dumps({"icao": "ABC123", "altitude": 30000,
                             "category": "Heavy", "rssi_dbfs": -20.0}),
    )
    _db.insert_detection(conn, det)
    conn.close()

    det_conn = _db.connect(det_path, readonly=True)
    samples = list(_src.extract_samples(
        det_conn=det_conn, db_file=det_path,
        node_id="n01", node_lat=42.5098, node_lon=1.5361, node_alt=1000.0,
        emitters=_src.empty_registry(),
    ))
    det_conn.close()
    assert len(samples) == 1
    s = samples[0]
    assert s["source"] == "adsb"
    assert s["band"] == "UHF"
    assert s["ref_id"] == "ABC123"
    # Slant ~13 km at 1090 MHz, EIRP 53 dBm (Heavy override) → expected ≈
    # 53 - 20·log10(13000) - 20·log10(1.09e9) + 147.55 ≈ 53 - 82.3 - 180.74 + 147.55 = -62.5 dBm
    # offset = measured(-20) - expected(-62.5) = +42.5 — realistic dBFS→dBm bias
    assert 30.0 < s["offset_db"] < 55.0, f"Unexpected offset {s['offset_db']:.1f}"
    assert s["elevation_deg"] > 5.0


def test_aircraft_dataclass_has_rssi_field():
    """Regression: adsb.py Aircraft must carry an rssi slot for the poller."""
    from scanners.adsb import Aircraft
    ac = Aircraft(icao="ABC123")
    assert hasattr(ac, "rssi")
    assert ac.rssi is None
    ac.rssi = -18.7
    assert ac.rssi == -18.7


def test_aircraft_json_poller_updates_rssi(tmp_path=None):
    """Poller reads aircraft.json and copies rssi into the shared aircraft_db."""
    from scanners.adsb import AircraftJsonPoller, Aircraft

    tmp = tempfile.mkdtemp()
    json_path = os.path.join(tmp, "aircraft.json")
    # Pre-seed the db so the poller updates an existing aircraft (covers
    # the common case where SBS saw the aircraft first).
    db = {"ABC123": Aircraft(icao="ABC123")}
    with open(json_path, "w") as f:
        json.dump({
            "now": 1700000000,
            "aircraft": [
                {"hex": "abc123", "rssi": -22.3, "alt_baro": 34000},
                {"hex": "def456", "rssi": -35.5},
            ],
        }, f)

    poller = AircraftJsonPoller(json_dir=tmp, aircraft_db=db, interval_s=0.05)
    poller.start()
    # Give the background thread a couple of tick intervals.
    import time as _time
    for _ in range(40):
        if db["ABC123"].rssi is not None and "DEF456" in db:
            break
        _time.sleep(0.05)
    poller.stop()

    assert db["ABC123"].rssi == -22.3, f"ABC123 rssi={db['ABC123'].rssi}"
    # Poller creates unseen entries so RSSI isn't lost before SBS catches up.
    assert "DEF456" in db and db["DEF456"].rssi == -35.5


# --- solve_node_offsets pipeline --------------------------------------------
def test_solve_node_offsets_end_to_end():
    from utils import calibration_db as _cdb
    from utils.calibration import solve_node_offsets

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cal.db")
    conn = _cdb.connect(path)

    import time as _time
    now = _time.time()
    rng = random.Random(7)
    true_offset = -15.0
    for i in range(30):
        resid_noise = rng.gauss(0, 1.5)
        _cdb.insert_sample(conn, {
            "ts_epoch": now - i * 60,
            "device_id": "n01", "band": "UHF",
            "frequency_hz": 1090e6, "source": "adsb", "ref_id": f"a{i}",
            "power_db": -60.0 + resid_noise,
            "expected_db": -60.0 - true_offset,
            "offset_db": (true_offset + resid_noise),
            "distance_m": 20000, "elevation_deg": 15.0, "weight": 1.0,
            "session_db": "x.db", "det_rowid": i,
        })

    fits = solve_node_offsets(conn, "n01")
    assert "UHF" in fits
    fit = fits["UHF"]
    assert abs(fit.offset_db - true_offset) < 1.0, (
        f"Recovered {fit.offset_db:.2f}, expected ~{true_offset}")
    assert fit.n_samples >= 20

    # And it should have been persisted to cal_offsets.
    rows = _cdb.get_offsets(conn, device_id="n01")
    assert len(rows) == 1 and rows[0]["band"] == "UHF"


# --- web/fetch.py integration ----------------------------------------------
def test_row_for_map_applies_calibration():
    """fetch._row_for_map enriches rows with calibrated power when cal exists."""
    from web.fetch import _row_for_map
    from utils.calibration import Calibration

    cal = Calibration(offsets={("N01", "UHF"): (-18.0, 0.4)})
    # Fake a sqlite3.Row-like object (dict suffices because code uses r[key])
    row = {
        "timestamp": "2026-04-19T10:00:00",
        "ts_epoch": 1700000000.0,
        "signal_type": "keyfob",
        "frequency_hz": 433.92e6,
        "power_db": -72.0,
        "snr_db": 18.0,
        "channel": "CH1",
        "device_id": "N01",
    }
    shaped = _row_for_map(row, cal=cal)
    assert shaped["cal_applied"] is True
    # corrected = -72 − (−18) = −54
    assert abs(shaped["power_db_cal"] - (-54.0)) < 1e-6
    assert shaped["power_db"] == -72.0   # raw preserved
    assert shaped["snr_db"] == 18.0


def test_row_for_map_without_calibration_leaves_power_cal_null():
    from web.fetch import _row_for_map
    from utils.calibration import Calibration

    row = {
        "timestamp": "", "ts_epoch": 0, "signal_type": "BLE-Adv",
        "frequency_hz": 2.45e9, "power_db": -80, "snr_db": 12,
        "channel": "", "device_id": "unknown_node",
    }
    shaped = _row_for_map(row, cal=Calibration.empty())
    assert shaped["cal_applied"] is False
    assert shaped["power_db_cal"] is None
    assert shaped["power_db"] == -80


def test_row_for_map_handles_wifi_bssid_device_id():
    """WiFi-AP beacons carry BSSID in device_id; lookup silently misses."""
    from web.fetch import _row_for_map
    from utils.calibration import Calibration

    cal = Calibration(offsets={("N01", "2G4"): (-25.0, 0.5)})
    row = {
        "timestamp": "", "ts_epoch": 0, "signal_type": "WiFi-AP",
        "frequency_hz": 2.437e9, "power_db": -55, "snr_db": 40,
        "channel": "CH6", "device_id": "aa:bb:cc:11:22:33",
    }
    shaped = _row_for_map(row, cal=cal)
    assert shaped["cal_applied"] is False
    assert shaped["power_db_cal"] is None


def test_get_calibration_caches_by_mtime():
    """_get_calibration reuses the cached view while the DB file is stable."""
    from web import fetch as _f
    from utils import calibration_db as _cdb

    tmp = tempfile.mkdtemp()
    # First call: no cal DB yet → empty view, cache path set.
    _f._CAL_CACHE["path"] = None
    _f._CAL_CACHE["mtime"] = None
    _f._CAL_CACHE["cal"] = None
    cal1 = _f._get_calibration(tmp)
    assert cal1.offsets == {}

    # Create a cal DB with one offset and re-fetch.
    conn = _cdb.connect(_cdb.default_path(tmp))
    _cdb.upsert_offset(conn, "N01", "UHF", -18.0, 0.5, 50, "huber")
    conn.close()
    cal2 = _f._get_calibration(tmp)
    assert ("N01", "UHF") in cal2.offsets

    # Same mtime → same object (cache hit).
    cal3 = _f._get_calibration(tmp)
    assert cal3 is cal2


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"  ERR  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(0 if failures == 0 else 1)

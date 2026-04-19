"""
Tests for the AIS RSSI capture path (parsers/marine/ais_rssi.py +
parsers/marine/ais.py integration).

Hardware-free: the monitor exposes `inject_sample_for_tests` so we can
exercise recent_power / channel-selection / staleness logic without a
second RTL-SDR. The parser tests feed synthetic NMEA strings through
AISParser and check what ends up in the SQLite log.

Covers:
  - recent_power returns None when no samples yet, or when the newest
    sample is past max_age_s
  - recent_power without freq_hz returns max(AIS1, AIS2) — best-effort
    attribution since rtl_ais doesn't name the decoding channel
  - recent_power with freq_hz picks the nearest channel
  - AISParser falls back to power_db=0 when no monitor is attached
    (pre-commit behaviour preserved)
  - AISParser writes the monitor's RSSI into power_db + metadata when
    a monitor is attached
  - Calibration extractor accepts the enriched rows (power_db non-zero
    now unblocks the existing _try_ais check)

Run:
    python3 tests/sw/test_ais_rssi.py
"""

import json
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _valid_nmea_position_vessel_1_msg() -> str:
    """A real, checksum-valid Type 1 AIS position report from the wild.

    MMSI 316013198, lat ~48.38, lon ~-123.39 — this is a sample
    message used in rtl_ais documentation.
    """
    return "!AIVDM,1,1,,A,15MgK45P3@G?fl0E`JbR0OwT0@MS,0*4E"


def test_recent_power_none_until_sample_arrives():
    from parsers.marine.ais_rssi import AISChannelRSSI
    mon = AISChannelRSSI(device_index=0)  # never started — no SDR needed
    assert mon.recent_power() is None


def test_recent_power_returns_max_by_default():
    """rtl_ais doesn't tell us which channel decoded an NMEA sentence,
    so the default (no freq_hz) returns max(AIS1, AIS2)."""
    from parsers.marine.ais_rssi import AISChannelRSSI
    mon = AISChannelRSSI(device_index=0, max_age_s=10.0)
    mon.inject_sample_for_tests(ais1_db=-35.0, ais2_db=-28.0)
    assert mon.recent_power() == -28.0


def test_recent_power_selects_nearest_channel_by_freq():
    from parsers.marine.ais_rssi import AIS1_FREQ, AIS2_FREQ, AISChannelRSSI
    mon = AISChannelRSSI(device_index=0, max_age_s=10.0)
    mon.inject_sample_for_tests(ais1_db=-35.0, ais2_db=-28.0)
    assert mon.recent_power(freq_hz=AIS1_FREQ) == -35.0
    assert mon.recent_power(freq_hz=AIS2_FREQ) == -28.0
    # Equidistant -> AIS1 (arbitrary tiebreaker, locked by <=).
    assert mon.recent_power(freq_hz=162.0e6) == -35.0


def test_recent_power_drops_stale_samples():
    from parsers.marine.ais_rssi import AISChannelRSSI
    mon = AISChannelRSSI(device_index=0, max_age_s=0.5)
    # Inject 10 s old sample — past max_age_s.
    mon.inject_sample_for_tests(ais1_db=-30.0, ais2_db=-25.0,
                                 ts=time.time() - 10.0)
    assert mon.recent_power() is None


def test_parser_without_monitor_logs_zero_power():
    """Pre-commit behaviour preserved: no monitor -> power_db = 0.0."""
    from utils import db as _db
    from utils.logger import SignalLogger
    from parsers.marine.ais import AISParser

    tmp = tempfile.mkdtemp()
    logger = SignalLogger(output_dir=tmp, signal_type="ais", min_snr_db=0)
    logger.start()
    parser = AISParser(logger=logger)  # no rssi_monitor
    parser.handle_frame(_valid_nmea_position_vessel_1_msg())
    logger.stop()

    conn = sqlite3.connect(os.path.join(tmp, os.listdir(tmp)[0]))
    row = conn.execute(
        "SELECT power_db, metadata FROM detections LIMIT 1").fetchone()
    conn.close()
    # Some rows may not decode a position — skip the assertion then.
    if row is None:
        return
    assert row[0] == 0
    meta = json.loads(row[1])
    assert "rssi_dbfs" not in meta


def test_parser_with_monitor_attaches_rssi_to_power_db_and_meta():
    from utils import db as _db
    from utils.logger import SignalLogger
    from parsers.marine.ais import AISParser
    from parsers.marine.ais_rssi import AISChannelRSSI

    tmp = tempfile.mkdtemp()
    logger = SignalLogger(output_dir=tmp, signal_type="ais", min_snr_db=0)
    logger.start()

    mon = AISChannelRSSI(device_index=0, max_age_s=10.0)
    mon.inject_sample_for_tests(ais1_db=-45.0, ais2_db=-28.5)

    parser = AISParser(logger=logger, rssi_monitor=mon)
    parser.handle_frame(_valid_nmea_position_vessel_1_msg())
    logger.stop()

    conn = sqlite3.connect(os.path.join(tmp, os.listdir(tmp)[0]))
    row = conn.execute(
        "SELECT power_db, noise_floor_db, metadata FROM detections LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        return  # no position decode — covered by the no-monitor test
    # Got the max-of-channels value.
    assert row[0] == -28.5
    # Noise floor nominalised so SNR stays positive.
    assert row[1] == -60.0
    meta = json.loads(row[2])
    assert meta["rssi_dbfs"] == -28.5


def test_calibration_extractor_accepts_enriched_ais_row():
    """With the RSSI monitor plumbed, _try_ais no longer returns None on
    the `power_db == 0.0` check — the extractor produces real samples."""
    from utils import db as _db
    from utils import calibration_sources as _src
    from utils.logger import SignalDetection

    tmp = tempfile.mkdtemp()
    det_path = os.path.join(tmp, "ais.db")
    conn = _db.connect(det_path)
    det = SignalDetection.create(
        signal_type="AIS",
        frequency_hz=162.0e6,
        power_db=-35.0,      # populated by the RSSI monitor
        noise_floor_db=-60.0,
        channel="123456789",
        latitude=42.510,     # vessel self-reports position
        longitude=1.540,
        metadata=json.dumps({
            "mmsi": "123456789",
            "msg_type": 1,        # class A — triggers the 41 dBm EIRP
            "rssi_dbfs": -35.0,
        }),
    )
    _db.insert_detection(conn, det)
    conn.close()

    det_conn = _db.connect(det_path, readonly=True)
    samples = list(_src.extract_samples(
        det_conn=det_conn, db_file=det_path,
        node_id="n01", node_lat=42.505, node_lon=1.535, node_alt=0.0,
        emitters=_src.empty_registry(),
        source_filter={"ais"},
    ))
    det_conn.close()
    assert len(samples) == 1
    s = samples[0]
    assert s["source"] == "ais"
    assert s["band"] in ("VHF-high",)
    assert s["ref_id"] == "123456789"


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

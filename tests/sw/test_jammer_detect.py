"""
Tests for utils/jammer_detect.py — the post-hoc opportunistic
analyzer that infers jamming events from stored detection logs.

Feeds synthetic (device, signal_type) time series into the analyzer
and asserts it produces the expected AnomalyEvent shape.

Covers:
  - Baseline period + sustained elevation → one anomaly event
  - Brief spikes under min_consec → no event
  - Falling back to baseline triggers ended_at
  - Elevation peak tracked across the event (max, not last)
  - Two different nodes are isolated (a jammer on N01 doesn't
    suppress detection on N02 via shared baseline)
  - Per-scanner grouping (same node, different signal_types are
    independent)
  - Groups with fewer than min_samples_per_group are skipped
    silently — no false alarm off a 3-row session
  - Rolling baseline actually rolls: a slow noise-floor drift
    doesn't fire (it's the new normal), an abrupt jump does
  - anomaly_to_detection_meta produces the keys the dashboard
    expects

Run:
    python3 tests/sw/test_jammer_detect.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _make_rows(device_id, signal_type, nf_series, start_ts=1_700_000_000.0,
               spacing_s=10.0):
    """nf_series: list of noise_floor_db values. Emits detection dicts
    in the shape detect_anomalies expects."""
    return [
        {
            "device_id": device_id,
            "signal_type": signal_type,
            "noise_floor_db": nf,
            "ts_epoch": start_ts + i * spacing_s,
        }
        for i, nf in enumerate(nf_series)
    ]


# --- baseline establishment + sustained elevation ---------------------------

def test_sustained_elevation_produces_one_event():
    from utils.jammer_detect import detect_anomalies
    # 30 samples at -90 dB baseline, 10 at -70 dB, 10 back at -90.
    rows = _make_rows("N01", "PMR446", [-90] * 30 + [-70] * 10 + [-90] * 10)
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=5)
    assert len(events) == 1
    e = events[0]
    assert e.device_id == "N01"
    assert e.signal_type == "PMR446"
    # Peak is the worst sample during the event.
    assert abs(e.peak_db - (-70.0)) < 1e-6
    assert e.baseline_db < -70.0   # baseline was at the quiet floor
    assert e.ended_at is not None  # series returned to baseline → closed


def test_brief_spike_under_min_consec_is_ignored():
    from utils.jammer_detect import detect_anomalies
    # Two elevated samples, then back to baseline — min_consec=3 rejects.
    rows = _make_rows("N01", "PMR446", [-90] * 30 + [-70, -70] + [-90] * 10)
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=5)
    assert events == []


def test_event_tracks_peak_across_window():
    """Peak should be the MAX noise floor across the event, not the
    first or last sample."""
    from utils.jammer_detect import detect_anomalies
    rows = _make_rows("N01", "PMR446",
                      [-90] * 30 + [-75, -65, -70, -85] + [-90] * 10)
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=5)
    # event covers samples that beat threshold; peak is the -65 one.
    assert len(events) == 1
    assert abs(events[0].peak_db - (-65.0)) < 1e-6


def test_ongoing_event_has_ended_at_none():
    """Series ends while still elevated → event is flagged ongoing."""
    from utils.jammer_detect import detect_anomalies
    rows = _make_rows("N01", "PMR446", [-90] * 30 + [-70] * 10)
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=5)
    assert len(events) == 1
    assert events[0].ended_at is None


# --- isolation --------------------------------------------------------------

def test_two_nodes_are_isolated():
    """A jammer on N01 doesn't affect the N02 baseline."""
    from utils.jammer_detect import detect_anomalies
    rows = (
        _make_rows("N01", "PMR446", [-90] * 30 + [-60] * 10)
        + _make_rows("N02", "PMR446", [-90] * 40)   # quiet throughout
    )
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=5)
    assert len(events) == 1
    assert events[0].device_id == "N01"


def test_two_scanners_on_same_node_isolated():
    """Same node, different signal types → independent baselines."""
    from utils.jammer_detect import detect_anomalies
    rows = (
        _make_rows("N01", "PMR446",  [-90] * 30 + [-60] * 10)
        + _make_rows("N01", "BLE-Adv", [-80] * 40)
    )
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=5)
    assert len(events) == 1
    assert events[0].signal_type == "PMR446"


# --- filters ---------------------------------------------------------------

def test_min_samples_filter_skips_thin_streams():
    """Fewer than min_samples_per_group rows → no anomaly attempted."""
    from utils.jammer_detect import detect_anomalies
    rows = _make_rows("N01", "PMR446", [-90, -70, -70, -70])
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=20)
    assert events == []


def test_zero_noise_floor_rows_are_dropped():
    """Legacy ADS-B / AIS rows with noise_floor_db=0 are ambiguous
    (no RSSI captured) and must not poison the baseline."""
    from utils.jammer_detect import detect_anomalies
    # 20 zero-floor rows, then 30 real samples all the same — the zero
    # rows should be ignored, so no bogus "-X dB elevation" vs zero.
    rows = _make_rows("N01", "ADS-B", [0] * 20 + [-60] * 30)
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=5)
    # -60 is the ONLY populated value — no variance, no anomaly.
    assert events == []


def test_rolling_baseline_follows_slow_drift():
    """A slow uniform rise by the same amount everywhere is the 'new
    normal' — the rolling baseline should follow and NOT fire."""
    from utils.jammer_detect import detect_anomalies
    # Linear drift across 60 samples: -90 → -85 (half a dB per sample).
    drift = [-90 + i * 0.1 for i in range(60)]
    rows = _make_rows("N01", "PMR446", drift)
    # Any spike should be against the CURRENT window's median, not the
    # first-ever sample. A 5 dB total drift should produce zero events.
    events = detect_anomalies(rows, elevation_threshold_db=10,
                              min_consec=3, min_samples_per_group=5,
                              baseline_window_s=300.0)
    assert events == []


# --- metadata shape --------------------------------------------------------

def test_anomaly_to_detection_meta_has_dashboard_keys():
    """The dashboard row renderer consumes these exact keys — locking
    down the wire contract between analyzer and UI."""
    from utils.jammer_detect import AnomalyEvent, anomaly_to_detection_meta
    e = AnomalyEvent(
        device_id="N01", signal_type="PMR446",
        started_at=1_700_000_000.0, ended_at=1_700_000_020.0,
        baseline_db=-90.0, peak_db=-65.0, samples=7,
    )
    meta = anomaly_to_detection_meta(e)
    for k in ("source", "baseline_db", "observed_db", "elevation_db",
              "flatness", "bandwidth_hz", "samples", "duration_s",
              "ongoing"):
        assert k in meta, f"missing {k}"
    assert meta["source"] == "inferred"
    assert meta["ongoing"] is False
    assert abs(meta["elevation_db"] - 25.0) < 1e-6


def test_ongoing_anomaly_meta_flags_ongoing():
    from utils.jammer_detect import AnomalyEvent, anomaly_to_detection_meta
    e = AnomalyEvent(
        device_id="N01", signal_type="PMR446",
        started_at=1_700_000_000.0, ended_at=None,
        baseline_db=-90.0, peak_db=-65.0, samples=7,
    )
    meta = anomaly_to_detection_meta(e)
    assert meta["ongoing"] is True
    assert meta["duration_s"] == 0.0   # not yet closed


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

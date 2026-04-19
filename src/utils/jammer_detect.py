"""
Opportunistic jammer / broadband-interference detection from stored
detection logs.

Counterpart to `sdr.py jammer`, which needs a dedicated SDR to hop
bands and sample noise directly. This module works *without* any
extra hardware: it looks at `noise_floor_db` values already written
by every scanner (PMR, ADS-B, WiFi, …) and flags time segments
where a given (node, signal_type)'s noise floor spikes above its
own rolling baseline.

Trade-offs vs the live scanner:

- **No flatness.** The live scanner uses spectral flatness to reject
  narrowband peaks. We only have the pre-reduced `noise_floor_db`
  column, so the analyzer has to trust the scanner's own median /
  Welch estimate. False positives from genuinely-elevated noise
  (e.g. a new nearby emitter) are possible; they'll look like
  sustained elevation without flatness context to rule them out.
- **Only covers bands with active scanners.** If nobody's running
  `sdr.py wifi`, there's no 2.4 GHz noise-floor series to analyze.
  Complements the live scanner rather than replacing it.
- **Batch / delayed, not live.** Intended to run periodically over
  accumulated logs, not to alert in real time. Easy to drive from
  cron or on-demand from the CLI.

Reuses `dsp.jammer.decide` so the fire/clear semantics — consecutive
elevated samples, hysteresis exit — match the live scanner exactly.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional

from dsp.jammer import DetectionState, BandSample, decide


# Minimum distinct detections per group before we'll even try to
# baseline it. Below this, the rolling baseline is too noisy to
# distinguish "normal variance" from "sustained elevation".
DEFAULT_MIN_SAMPLES_PER_GROUP = 20

# Lookback window for the rolling baseline, in seconds. 1 h is long
# enough to smooth out burst traffic but short enough that a jammer
# which came on 20 min ago still shows up against its pre-jam history.
DEFAULT_BASELINE_WINDOW_S = 3600.0


@dataclass
class AnomalyEvent:
    """A detected stretch of elevated noise floor on a (node, type) stream.

    Times are epoch seconds. `baseline_db` is the rolling median at
    entry; `peak_db` is the max observed noise floor across the event.
    `samples` is how many consecutive detections were above threshold.
    """
    device_id: str
    signal_type: str
    started_at: float
    ended_at: Optional[float]
    baseline_db: float
    peak_db: float
    samples: int


def _group_key(row) -> tuple:
    """(device_id, signal_type) — the right granularity for baselining.

    noise_floor_db is not normalised across scanners (PMR's FFT
    estimate ≠ BLE's radiotap value), and nodes have different RF
    paths / dongle offsets. So baselines only make sense within a
    single node's view of a single scanner.
    """
    return (row.get("device_id") or "", row.get("signal_type") or "")


def _rolling_baseline(
    prior: List[float],
    window_s: float,
    ts_now: float,
    ts_history: List[float],
) -> Optional[float]:
    """Median of prior noise-floor values inside [ts_now - window, ts_now).

    Returns None until we have at least 5 samples in the window — we
    don't want to chase the first-few-samples jitter into a false
    alarm. Baseline is re-computed every sample; cheap because we only
    keep the sliding window's values.
    """
    if not prior:
        return None
    cutoff = ts_now - window_s
    vals = [v for v, t in zip(prior, ts_history) if t >= cutoff]
    if len(vals) < 5:
        return None
    vals = sorted(vals)
    return vals[len(vals) // 2]


def detect_anomalies(
    detections: Iterable[dict],
    baseline_window_s: float = DEFAULT_BASELINE_WINDOW_S,
    elevation_threshold_db: float = 10.0,
    min_consec: int = 3,
    hysteresis_db: float = 3.0,
    min_samples_per_group: int = DEFAULT_MIN_SAMPLES_PER_GROUP,
) -> List[AnomalyEvent]:
    """Walk detection rows and emit one AnomalyEvent per sustained
    elevation stretch.

    Rows must carry at least `device_id`, `signal_type`,
    `noise_floor_db`, `ts_epoch`. Extra fields are ignored. Rows are
    sorted internally per group so caller order doesn't matter.
    """
    by_group: dict = defaultdict(list)
    for r in detections:
        try:
            nf = float(r.get("noise_floor_db"))
            ts = float(r.get("ts_epoch"))
        except (TypeError, ValueError):
            continue
        # Skip rows where the scanner explicitly logged no signal floor
        # (e.g. self-locating ADS-B/AIS before the RSSI work landed).
        if nf == 0.0:
            continue
        by_group[_group_key(r)].append((ts, nf))

    events: List[AnomalyEvent] = []
    for (device, sig), series in by_group.items():
        if len(series) < min_samples_per_group:
            continue
        series.sort(key=lambda x: x[0])
        events.extend(_detect_in_series(
            device, sig, series,
            baseline_window_s=baseline_window_s,
            elevation_threshold_db=elevation_threshold_db,
            min_consec=min_consec,
            hysteresis_db=hysteresis_db,
        ))
    # Newest first so the CLI / UI show the freshest anomaly top of list.
    events.sort(key=lambda e: e.started_at, reverse=True)
    return events


def _detect_in_series(
    device: str,
    sig: str,
    series: List[tuple],
    baseline_window_s: float,
    elevation_threshold_db: float,
    min_consec: int,
    hysteresis_db: float,
) -> List[AnomalyEvent]:
    """Run the decide state machine over a single group's time series."""
    events: List[AnomalyEvent] = []
    state = DetectionState()
    # Rolling history for baseline recomputation. Only the last N hours
    # of samples matter; we prune on each iteration to keep this flat.
    hist_vals: List[float] = []
    hist_ts: List[float] = []

    current: Optional[dict] = None
    # Peak tracker for the samples that triggered firing. An elevation
    # stretch crosses min_consec via the 3rd hit, but the 1st and 2nd
    # hits might have higher noise floor — carry the running max so
    # the event's peak_db reflects the worst sample in the stretch,
    # not just the one that flipped the state machine.
    candidate_peak: Optional[float] = None

    for ts, nf in series:
        # Roll the baseline forward. Before we have enough history to
        # baseline, we still append to history so the window fills.
        baseline = _rolling_baseline(hist_vals, baseline_window_s, ts, hist_ts)
        hist_vals.append(nf)
        hist_ts.append(ts)
        # Trim history outside the window — keeps memory bounded on
        # long captures.
        cutoff = ts - baseline_window_s
        while hist_ts and hist_ts[0] < cutoff:
            hist_ts.pop(0)
            hist_vals.pop(0)

        if baseline is None:
            continue

        # Seed the state's baseline the first time we have enough history.
        if state.baseline_db is None:
            state.baseline_db = baseline
            continue

        # Keep the state's baseline tracking the rolling window, but
        # only when we're NOT currently firing — a jammer that just
        # came on shouldn't pull its own baseline upward and suppress
        # detection.
        if not state.firing:
            state.baseline_db = baseline

        # Track the candidate peak across the elevated run before
        # decide fires. Resets whenever we see a non-elevated sample,
        # matching decide's own consec-counter reset rule.
        elevated_now = (nf - state.baseline_db) >= elevation_threshold_db
        if elevated_now and not state.firing:
            candidate_peak = (nf if candidate_peak is None
                              else max(candidate_peak, nf))
        elif not elevated_now and not state.firing:
            candidate_peak = None

        # No flatness available from stored rows; pass 1.0 so the
        # flatness test never rejects. The scanner's median-based
        # noise_floor_db is already "broadband-ish" by construction
        # (peaks don't pull the median), so we inherit that filter.
        sample = BandSample(
            noise_floor_db=nf, peak_db=nf, flatness=1.0, bins=0,
        )
        fired, transition_off = decide(
            sample, state,
            elevation_threshold_db=elevation_threshold_db,
            flatness_threshold=0.0,
            min_consec=min_consec,
            hysteresis_db=hysteresis_db,
        )

        if fired and current is None:
            current = {
                # Back-date started_at by (min_consec - 1) intervals so
                # the event timestamp corresponds to the *first*
                # triggering sample, not the one that closed the
                # min_consec window. That peak we already tracked via
                # candidate_peak; use it as the event's initial peak.
                "started_at": ts,
                "baseline_db": state.baseline_db,
                "peak_db": candidate_peak if candidate_peak is not None else nf,
                "samples": min_consec,
            }
        elif fired and current is not None:
            current["samples"] += 1
            current["peak_db"] = max(current["peak_db"], nf)
        elif transition_off and current is not None:
            events.append(AnomalyEvent(
                device_id=device, signal_type=sig,
                started_at=current["started_at"], ended_at=ts,
                baseline_db=current["baseline_db"],
                peak_db=current["peak_db"],
                samples=current["samples"],
            ))
            current = None
            candidate_peak = None

    # If the stream ends mid-event, emit an open-ended anomaly — the
    # dashboard can render it as "ongoing" with ended_at=None.
    if current is not None:
        events.append(AnomalyEvent(
            device_id=device, signal_type=sig,
            started_at=current["started_at"], ended_at=None,
            baseline_db=current["baseline_db"],
            peak_db=current["peak_db"],
            samples=current["samples"],
        ))
    return events


def anomaly_to_detection_meta(event: AnomalyEvent) -> dict:
    """Shape an AnomalyEvent as the metadata dict we log alongside
    each synthetic `signal_type="jamming-inferred"` detection.

    Mirrors the keys the live jammer scanner writes so the dashboard's
    row renderer can treat inferred + live rows uniformly.
    """
    elevation = event.peak_db - event.baseline_db
    return {
        "source": "inferred",
        "baseline_db": round(event.baseline_db, 2),
        "observed_db": round(event.peak_db, 2),
        "elevation_db": round(elevation, 2),
        "flatness": None,      # not available from stored rows
        "bandwidth_hz": 0,     # the analyzer doesn't know which band width
                                # the scanner used; the scanner's own type
                                # label carries that implicitly.
        "samples": event.samples,
        "duration_s": round((event.ended_at or event.started_at)
                            - event.started_at, 1),
        "ongoing": event.ended_at is None,
    }

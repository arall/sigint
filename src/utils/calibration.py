"""
Opportunistic RSSI calibration — math core and CLI runner.

Each RTL-SDR dongle's `power_db` is dB relative to ADC full-scale, not absolute
dBm, and every dongle has a different gain offset that varies by frequency.
Two nodes reading the same signal can disagree by 10–20 dB. For triangulation
that error is dominant.

This module solves per-(node, band) offsets by:

  1. Matching captured detections against emitters whose position and TX power
     are known (see calibration_sources.py).
  2. Computing expected RSSI from FSPL.
  3. Fitting offset = measured − expected via robust (Huber) regression.

`triangulate.py` calls `load_calibration()` + `apply_offset()` transparently.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

from utils import calibration_db as _cdb


# --- band table -------------------------------------------------------------
# Overlapping bands by design: narrower entries win. `band_for` picks the
# smallest matching band so a 900 MHz ISM signal ends up in `900` even though
# it's inside the UHF range.
BANDS: list[tuple[str, float, float]] = [
    ("HF",       3e6,    30e6),
    ("VHF-low",  30e6,   144e6),
    ("VHF-high", 144e6,  300e6),
    # UHF by ITU spans 300 MHz–3 GHz. We keep it wide so 1090 MHz (ADS-B)
    # and 1.2 GHz GPS fall in here; narrower sub-bands (900, 2G4) win via
    # the "narrowest match" rule in band_for.
    ("UHF",      300e6,  3e9),
    ("900",      860e6,  960e6),
    ("2G4",      2.3e9,  2.5e9),
    ("5G",       5.1e9,  5.9e9),
]

BAND_NAMES = {b[0] for b in BANDS}


def band_for(freq_hz: float) -> Optional[str]:
    """Return the narrowest band containing freq_hz, or None if uncovered."""
    if freq_hz is None or freq_hz <= 0:
        return None
    candidates = [(name, hi - lo) for name, lo, hi in BANDS if lo <= freq_hz < hi]
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


def _band_midpoint(name: str) -> float:
    for n, lo, hi in BANDS:
        if n == name:
            return 0.5 * (lo + hi)
    return 0.0


# --- free-space path loss ---------------------------------------------------
def expected_rssi_fspl(eirp_dbm: float, distance_m: float, freq_hz: float,
                       atm_loss_db: float = 0.0) -> float:
    """Predict received power (dBm) under free-space path loss.

    FSPL = 20 log10(d) + 20 log10(f) − 147.55  (with d in m and f in Hz)

    Short distances and valid frequencies only — callers should have
    already rejected 0 / near-zero distances.
    """
    if distance_m <= 0 or freq_hz <= 0:
        return eirp_dbm
    fspl_db = 20.0 * math.log10(distance_m) + 20.0 * math.log10(freq_hz) - 147.55
    return eirp_dbm - fspl_db - atm_loss_db


# --- robust offset fit ------------------------------------------------------
@dataclass
class OffsetFit:
    offset_db: float
    stderr_db: float
    n_samples: int
    method: str


def _weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights), key=lambda p: p[0])
    total = sum(w for _, w in pairs)
    if total <= 0:
        return 0.0
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= total / 2:
            return v
    return pairs[-1][0]


def _mad(values: list[float], median: float) -> float:
    if not values:
        return 0.0
    deviations = sorted(abs(v - median) for v in values)
    return deviations[len(deviations) // 2]


def fit_offset_huber(residuals: list[float], weights: list[float],
                     max_iter: int = 20) -> OffsetFit:
    """Fit a scalar offset by iteratively-reweighted Huber regression.

    `residuals` are measured_db − expected_db for each matched sample.
    The offset is the robust central tendency of the residuals (a shift of
    measured onto expected). Huber weights down-weight outliers without
    discarding them entirely.
    """
    if not residuals or len(residuals) != len(weights):
        return OffsetFit(0.0, 0.0, 0, "empty")
    n = len(residuals)
    if n < 2:
        return OffsetFit(residuals[0], float("inf"), n, "single")

    # First-pass outlier trim: drop |r - median| > 4 * MAD before fitting.
    median = _weighted_median(residuals, weights)
    mad = _mad(residuals, median)
    scale = max(1.4826 * mad, 0.5)
    kept = [(r, w) for r, w in zip(residuals, weights) if abs(r - median) <= 4 * scale]
    if len(kept) < max(5, n // 4):
        kept = list(zip(residuals, weights))

    r = [p[0] for p in kept]
    w = [p[1] for p in kept]
    mu = sum(ri * wi for ri, wi in zip(r, w)) / sum(w)

    # Huber IRLS
    k = 1.345 * max(scale, 0.5)
    for _ in range(max_iter):
        resid = [ri - mu for ri in r]
        huber_w = [
            wi if abs(d) <= k else wi * k / max(abs(d), 1e-9)
            for wi, d in zip(w, resid)
        ]
        new_mu = sum(ri * hwi for ri, hwi in zip(r, huber_w)) / max(sum(huber_w), 1e-9)
        if abs(new_mu - mu) < 1e-4:
            mu = new_mu
            break
        mu = new_mu

    residuals_final = [ri - mu for ri in r]
    stderr = 1.4826 * _mad(residuals_final, 0.0) / math.sqrt(max(len(r), 1))
    return OffsetFit(mu, stderr, len(r), "huber")


def fit_offset_mean(residuals: list[float], weights: list[float]) -> OffsetFit:
    """Weighted-mean fallback when robust fit isn't wanted."""
    if not residuals:
        return OffsetFit(0.0, 0.0, 0, "empty")
    total_w = sum(weights)
    if total_w <= 0:
        return OffsetFit(0.0, 0.0, 0, "empty")
    mu = sum(r * w for r, w in zip(residuals, weights)) / total_w
    var = sum(w * (r - mu) ** 2 for r, w in zip(residuals, weights)) / total_w
    stderr = math.sqrt(max(var, 0.0)) / math.sqrt(max(len(residuals), 1))
    return OffsetFit(mu, stderr, len(residuals), "mean")


# --- calibration object used at application time ----------------------------
@dataclass
class Calibration:
    """In-memory view of cal_offsets used at triangulate time."""
    offsets: dict[tuple[str, str], tuple[float, float]]   # (device, band) -> (offset, stderr)

    @classmethod
    def empty(cls) -> "Calibration":
        return cls(offsets={})

    def get(self, device_id: str, freq_hz: float,
            max_stderr: float = 1.5) -> tuple[float, bool]:
        """Return (offset_db, applied). offset=0, applied=False means "unknown"."""
        band = band_for(freq_hz)
        if band is None or not device_id:
            return 0.0, False
        exact = self.offsets.get((device_id, band))
        if exact is not None and exact[1] <= max_stderr:
            return exact[0], True

        # Interpolate between adjacent bands if both are precise enough.
        neighbors = self._nearest(device_id, band, max_stderr)
        if not neighbors:
            if exact is not None:
                return exact[0], True  # wide stderr but still our best guess
            return 0.0, False
        if len(neighbors) == 1:
            return neighbors[0][1], True
        (b1, o1), (b2, o2) = neighbors[:2]
        f1, f2 = _band_midpoint(b1), _band_midpoint(b2)
        if f1 == f2:
            return 0.5 * (o1 + o2), True
        t = (freq_hz - f1) / (f2 - f1)
        t = max(0.0, min(1.0, t))
        return o1 + t * (o2 - o1), True

    def _nearest(self, device_id: str, target_band: str,
                 max_stderr: float) -> list[tuple[str, float]]:
        target_f = _band_midpoint(target_band)
        cands = []
        for (dev, band), (off, se) in self.offsets.items():
            if dev != device_id or band == target_band or se > max_stderr:
                continue
            cands.append((band, off, abs(_band_midpoint(band) - target_f)))
        cands.sort(key=lambda x: x[2])
        return [(b, o) for b, o, _ in cands]


def load_calibration(path: Optional[str]) -> Calibration:
    """Load cal_offsets from `path` (default output/calibration.db)."""
    if path is None:
        path = _cdb.default_path()
    if not os.path.exists(path):
        return Calibration.empty()
    try:
        conn = _cdb.connect(path, readonly=True)
    except Exception:
        return Calibration.empty()
    try:
        rows = conn.execute(
            "SELECT device_id, band, offset_db, stderr_db FROM cal_offsets"
        ).fetchall()
    except Exception:
        conn.close()
        return Calibration.empty()
    conn.close()
    offsets = {(r["device_id"], r["band"]): (float(r["offset_db"]), float(r["stderr_db"]))
               for r in rows}
    return Calibration(offsets=offsets)


def apply_offset(power_db: float, device_id: str, freq_hz: float,
                 cal: Calibration) -> tuple[float, bool]:
    """Subtract the learnt offset from a raw power reading.

    offset = measured − expected, so corrected = measured − offset.
    Returns (corrected_db, applied). When `applied` is False the caller
    should fall back to the raw reading (and probably surface that in
    diagnostics).
    """
    if cal is None or not device_id or power_db is None:
        return power_db, False
    offset, applied = cal.get(device_id, freq_hz)
    if not applied:
        return power_db, False
    return power_db - offset, True


# --- ingestion + fit pipeline ------------------------------------------------
def solve_node_offsets(conn, device_id: str, method: str = "huber",
                        max_age_days: float = 7.0, min_samples: int = 20,
                        min_weight: float = 0.1) -> dict[str, OffsetFit]:
    """Recompute cal_offsets for a single node from cal_samples."""
    since = time.time() - max_age_days * 86400
    results: dict[str, OffsetFit] = {}
    by_band: dict[str, list[tuple[float, float]]] = {}  # band -> [(residual, weight)]
    for row in _cdb.iter_samples(conn, device_id=device_id,
                                  since_epoch=since, min_weight=min_weight):
        band = row["band"]
        resid = float(row["power_db"]) - float(row["expected_db"])
        w = float(row["weight"])
        by_band.setdefault(band, []).append((resid, w))

    for band, pairs in by_band.items():
        if len(pairs) < min_samples:
            continue
        residuals = [p[0] for p in pairs]
        weights = [p[1] for p in pairs]
        fit = (fit_offset_huber(residuals, weights) if method == "huber"
               else fit_offset_mean(residuals, weights))
        results[band] = fit
        _cdb.upsert_offset(conn, device_id, band,
                           fit.offset_db, fit.stderr_db, fit.n_samples,
                           fit.method)
    return results


# --- CLI --------------------------------------------------------------------
def run_calibration(args) -> int:
    """Dispatch for `sdr.py calibrate <subcommand>`. Returns an exit code."""
    sub = getattr(args, "calibrate_cmd", None)
    if sub == "ingest":
        return _cli_ingest(args)
    if sub == "show":
        return _cli_show(args)
    if sub == "recompute":
        return _cli_recompute(args)
    if sub == "set-position":
        return _cli_set_position(args)
    if sub == "watch":
        return _cli_watch(args)
    print("Error: missing calibrate subcommand (ingest/show/recompute/set-position/watch)",
          file=sys.stderr)
    return 2


def _cli_ingest(args) -> int:
    from utils import calibration_sources as _src
    from utils import db as _detdb

    db_path = args.db or _cdb.default_path(args.output)
    emitters_path = args.emitters
    source_filter = set(args.source) if args.source else None
    since_hours = args.since_hours
    since_epoch = (time.time() - since_hours * 3600) if since_hours else None
    node_id = args.node_id
    if not node_id:
        print("Error: --node-id is required (identifies which physical node "
              "these .db files came from)", file=sys.stderr)
        return 2

    cal_conn = _cdb.connect(db_path)
    node_pos = _resolve_node_position(cal_conn, args)
    if node_pos is None:
        print(f"[calibrate] no node position set for {node_id!r}. "
              f"Run `sdr.py calibrate set-position --node-id {node_id} "
              f"--lat Y --lon X` or pass --lat/--lon now.", file=sys.stderr)
        cal_conn.close()
        return 2

    emitters = _src.load_reference_emitters(emitters_path) if emitters_path else _src.empty_registry()
    node_alt = float(args.node_alt) if args.node_alt is not None else 0.0

    total_files = 0
    total_samples = 0
    per_source: dict[str, int] = {}
    per_band: dict[str, int] = {}
    for db_file in args.files:
        if not os.path.exists(db_file):
            print(f"  skip {db_file}: not found", file=sys.stderr)
            continue
        total_files += 1
        try:
            det_conn = _detdb.connect(db_file, readonly=True)
        except Exception as e:
            print(f"  skip {db_file}: {e}", file=sys.stderr)
            continue
        try:
            already = _cdb.seen_detection_ids(cal_conn, db_file)
            samples = list(_src.extract_samples(
                det_conn=det_conn,
                db_file=db_file,
                node_id=node_id,
                node_lat=node_pos[0],
                node_lon=node_pos[1],
                node_alt=node_alt,
                emitters=emitters,
                source_filter=source_filter,
                since_epoch=since_epoch,
                skip_rowids=already,
            ))
        finally:
            det_conn.close()

        for s in samples:
            per_source[s["source"]] = per_source.get(s["source"], 0) + 1
            per_band[s["band"]] = per_band.get(s["band"], 0) + 1
        total_samples += len(samples)

        if args.dry_run:
            continue
        _cdb.insert_samples(cal_conn, samples)

    _cdb.set_meta(cal_conn, "last_ingest_epoch", str(time.time()))

    print(f"\nIngested from {total_files} file(s): {total_samples} new sample(s)")
    if per_source:
        print("  by source:", ", ".join(f"{k}={v}" for k, v in sorted(per_source.items())))
    if per_band:
        print("  by band:  ", ", ".join(f"{k}={v}" for k, v in sorted(per_band.items())))

    if args.dry_run:
        cal_conn.close()
        return 0

    # Refit.
    fits = solve_node_offsets(cal_conn, node_id,
                              method=args.method or "huber",
                              max_age_days=args.max_age_days or 7.0)
    if fits:
        print("\nSolved offsets:")
        for band, fit in sorted(fits.items()):
            print(f"  {node_id} | {band:<8} offset={fit.offset_db:+7.2f} dB "
                  f"± {fit.stderr_db:.2f}  n={fit.n_samples}  ({fit.method})")
    else:
        print("\nNo bands with enough samples to fit yet (need 20+ per band).")
    cal_conn.close()
    return 0


def _cli_show(args) -> int:
    db_path = args.db or _cdb.default_path(args.output)
    node_filter = getattr(args, "cal_node_filter", None)
    if not os.path.exists(db_path):
        print(f"No calibration DB at {db_path}")
        return 0
    conn = _cdb.connect(db_path, readonly=True)
    try:
        rows = _cdb.get_offsets(conn, device_id=node_filter)
        if getattr(args, "as_json", False):
            out = [{
                "device_id": r["device_id"], "band": r["band"],
                "offset_db": r["offset_db"], "stderr_db": r["stderr_db"],
                "n_samples": r["n_samples"],
                "ts_updated": r["ts_updated"], "method": r["method"],
            } for r in rows]
            print(json.dumps(out, indent=2))
            return 0

        if not rows:
            print("No offsets solved yet. Run `sdr.py calibrate ingest <files>` first.")
            return 0
        # Count samples per (device,band) for context
        counts = {}
        for r in conn.execute(
                "SELECT device_id, band, COUNT(*) AS n FROM cal_samples "
                "GROUP BY device_id, band").fetchall():
            counts[(r["device_id"], r["band"])] = r["n"]

        print(f"{'Node':<12} | {'Band':<8} | {'Offset':>9} | {'StdErr':>7} | {'n_fit':>6} | {'total':>6} | {'Updated':<20}")
        print("-" * 85)
        for r in rows:
            key = (r["device_id"], r["band"])
            total = counts.get(key, r["n_samples"])
            ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["ts_updated"]))
            print(f"{r['device_id']:<12} | {r['band']:<8} | "
                  f"{r['offset_db']:+7.2f}dB | {r['stderr_db']:6.2f}  | "
                  f"{r['n_samples']:>6} | {total:>6} | {ts}")

        # Report bands with samples but no offset (not enough data).
        have_offset = {(r["device_id"], r["band"]) for r in rows}
        missing = [k for k in counts if k not in have_offset and counts[k] > 0]
        if missing:
            print("\nBands with samples but no offset yet:")
            for dev, band in sorted(missing):
                print(f"  {dev} | {band}: {counts[(dev, band)]} sample(s) (need 20)")
    finally:
        conn.close()
    return 0


def _cli_recompute(args) -> int:
    db_path = args.db or _cdb.default_path(args.output)
    if not os.path.exists(db_path):
        print(f"No calibration DB at {db_path}")
        return 1
    conn = _cdb.connect(db_path)
    try:
        node_filter = getattr(args, "cal_node_filter", None)
        devices = [node_filter] if node_filter else _cdb.distinct_device_ids(conn)
        if not devices:
            print("No samples in DB.")
            return 0
        for dev in devices:
            fits = solve_node_offsets(conn, dev,
                                      method=args.method or "huber",
                                      max_age_days=args.max_age_days or 7.0)
            print(f"{dev}: {len(fits)} band(s) fit")
            for band, fit in sorted(fits.items()):
                print(f"  {band:<8} offset={fit.offset_db:+7.2f}dB "
                      f"± {fit.stderr_db:.2f}  n={fit.n_samples}")
    finally:
        conn.close()
    return 0


def _cli_set_position(args) -> int:
    if args.lat is None or args.lon is None:
        print("Error: --lat and --lon are required", file=sys.stderr)
        return 2
    if not args.node_id:
        print("Error: --node-id is required", file=sys.stderr)
        return 2
    db_path = args.db or _cdb.default_path(args.output)
    conn = _cdb.connect(db_path)
    try:
        _cdb.set_meta(conn, f"node_lat:{args.node_id}", f"{args.lat:.7f}")
        _cdb.set_meta(conn, f"node_lon:{args.node_id}", f"{args.lon:.7f}")
        if args.alt is not None:
            _cdb.set_meta(conn, f"node_alt:{args.node_id}", f"{float(args.alt):.1f}")
        if args.mobile:
            _cdb.set_meta(conn, f"mobile:{args.node_id}", "1")
        elif args.mobile is False:
            _cdb.set_meta(conn, f"mobile:{args.node_id}", "0")
    finally:
        conn.close()
    print(f"Set position for {args.node_id}: {args.lat:.6f}, {args.lon:.6f}")
    return 0


def _cli_watch(args) -> int:
    """Tail every .db in output/ matching the filter and re-ingest periodically."""
    import glob
    pattern = os.path.join(args.output, "*.db")
    interval = max(1, int(args.interval or 10))
    print(f"Watching {pattern} every {interval}s (Ctrl+C to stop).")
    try:
        while True:
            files = sorted(glob.glob(pattern))
            args.files = [f for f in files if "calibration" not in os.path.basename(f)]
            if args.files:
                _cli_ingest(args)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def _resolve_node_position(conn, args) -> Optional[tuple[float, float]]:
    """Find the node's lat/lon from (CLI flags) or cal_meta.

    CLI flags override anything stored; that lets the user do a one-shot
    ingest from a different location without having to `set-position` first.
    """
    if args.lat is not None and args.lon is not None:
        return (float(args.lat), float(args.lon))
    lat_s = _cdb.get_meta(conn, f"node_lat:{args.node_id}")
    lon_s = _cdb.get_meta(conn, f"node_lon:{args.node_id}")
    if lat_s and lon_s:
        try:
            return (float(lat_s), float(lon_s))
        except ValueError:
            return None
    return None

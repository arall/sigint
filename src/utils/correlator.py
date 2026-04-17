"""
Device Relationship Correlator

Analyzes detection logs to find co-occurring devices across signal types.
Identifies clusters of devices that consistently appear together (e.g.,
a phone's WiFi probe + BLE advertisement + TPMS from the same vehicle).

Usage:
    python -m utils.correlator output/server_*.db
    python -m utils.correlator output/server_*.db --window 30 --threshold 0.7
"""

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from utils import db as _db


# Default co-occurrence time window (seconds)
DEFAULT_WINDOW_S = 30.0

# Minimum co-occurrence ratio to consider devices related
DEFAULT_THRESHOLD = 0.5

# Minimum total observations per device before correlation is meaningful
MIN_OBSERVATIONS = 3

# Signal type → preferred unique ID extraction
UID_EXTRACTORS = {
    "BLE-Adv":     lambda r, m: m.get("persona_id") or r.get("channel", ""),
    "WiFi-Probe":  lambda r, m: m.get("persona_id") or r.get("device_id", ""),
    "ADS-B":       lambda r, m: m.get("icao") or r.get("channel", ""),
    "keyfob":      lambda r, m: m.get("data_hex", ""),
    "tpms":        lambda r, m: m.get("sensor_id", ""),
    "RemoteID":    lambda r, m: m.get("serial_number", ""),
    "lora":        lambda r, m: f'{float(r.get("frequency_hz", 0)):.0f}',
    "ISM":         lambda r, m: m.get("model", "") or m.get("id", ""),
}


def _extract_uid(row: dict) -> Optional[str]:
    """Extract a unique device identifier from a detection row dict."""
    sig = row.get("signal_type", "")
    try:
        meta = json.loads(row.get("metadata", "{}") or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}

    extractor = UID_EXTRACTORS.get(sig)
    if extractor:
        uid = extractor(row, meta)
        if uid:
            return f"{sig}:{uid}"

    # Fallback: use channel or frequency
    ch = row.get("channel", "")
    if ch:
        return f"{sig}:ch:{ch}"
    freq = row.get("frequency_hz", "")
    if freq:
        return f"{sig}:f:{freq}"

    return None


def _parse_timestamp(ts: str) -> Optional[float]:
    """Parse ISO timestamp to epoch seconds."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).timestamp()
        except ValueError:
            continue
    return None


class DeviceCorrelator:
    """Finds co-occurring devices from detection logs."""

    def __init__(self, window_s: float = DEFAULT_WINDOW_S,
                 threshold: float = DEFAULT_THRESHOLD):
        self.window_s = window_s
        self.threshold = threshold

        # device_id → list of (timestamp_epoch, lat, lon, signal_type)
        self._observations: Dict[str, List[Tuple[float, Optional[float], Optional[float], str]]] = defaultdict(list)

    def load_db(self, path: str, since_epoch: Optional[float] = None):
        """Load detections from a .db file."""
        conn = _db.connect(path, readonly=True)
        try:
            for r in _db.iter_detections(conn, since_epoch=since_epoch):
                row = _db.row_to_dict(r)
                uid = _extract_uid(row)
                if not uid:
                    continue

                ts = _parse_timestamp(row.get("timestamp", ""))
                if ts is None:
                    continue

                lat = row.get("latitude", "")
                lon = row.get("longitude", "")
                try:
                    lat = float(lat) if lat not in ("", None, "None") else None
                    lon = float(lon) if lon not in ("", None, "None") else None
                except (ValueError, TypeError):
                    lat, lon = None, None

                self._observations[uid].append((ts, lat, lon, row.get("signal_type", "")))
        finally:
            conn.close()

    def add_detection(self, detection):
        """Add a SignalDetection object (for real-time use)."""
        try:
            meta = json.loads(detection.metadata or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}

        row = {
            "signal_type": detection.signal_type,
            "channel": detection.channel or "",
            "device_id": detection.device_id or "",
            "frequency_hz": str(detection.frequency_hz),
            "metadata": detection.metadata or "{}",
        }
        uid = _extract_uid(row)
        if not uid:
            return

        ts = _parse_timestamp(detection.timestamp)
        if ts is None:
            return

        self._observations[uid].append(
            (ts, detection.latitude, detection.longitude, detection.signal_type))

    @property
    def device_count(self) -> int:
        return len(self._observations)

    def correlate(self) -> List[dict]:
        """Find co-occurring device pairs.

        Returns list of dicts:
            {
                "device_a": str,
                "device_b": str,
                "co_occurrences": int,
                "total_a": int,
                "total_b": int,
                "ratio": float,  # co_occurrences / min(total_a, total_b)
                "cross_transport": bool,  # different signal types
            }
        """
        devices = {uid: obs for uid, obs in self._observations.items()
                   if len(obs) >= MIN_OBSERVATIONS}

        if len(devices) < 2:
            return []

        # Build time-binned presence: for each device, set of time bins it appears in
        device_bins: Dict[str, Set[int]] = {}
        for uid, obs in devices.items():
            bins = set()
            for ts, _, _, _ in obs:
                bins.add(int(ts / self.window_s))
            device_bins[uid] = bins

        # Pairwise co-occurrence
        results = []
        uids = list(devices.keys())
        for i in range(len(uids)):
            for j in range(i + 1, len(uids)):
                uid_a, uid_b = uids[i], uids[j]
                bins_a = device_bins[uid_a]
                bins_b = device_bins[uid_b]

                overlap = len(bins_a & bins_b)
                if overlap < 2:
                    continue

                min_total = min(len(bins_a), len(bins_b))
                ratio = overlap / min_total if min_total > 0 else 0

                if ratio < self.threshold:
                    continue

                # Determine if cross-transport
                types_a = set(obs[3] for obs in devices[uid_a])
                types_b = set(obs[3] for obs in devices[uid_b])
                cross = bool(types_a != types_b)

                results.append({
                    "device_a": uid_a,
                    "device_b": uid_b,
                    "co_occurrences": overlap,
                    "total_a": len(bins_a),
                    "total_b": len(bins_b),
                    "ratio": round(ratio, 3),
                    "cross_transport": cross,
                })

        results.sort(key=lambda x: x["ratio"], reverse=True)
        return results

    def find_clusters(self) -> List[List[str]]:
        """Group correlated devices into clusters using union-find.

        Returns list of clusters, each a list of device UIDs.
        """
        pairs = self.correlate()
        if not pairs:
            return []

        # Union-find
        parent = {}

        def find(x):
            if x not in parent:
                parent[x] = x
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for pair in pairs:
            union(pair["device_a"], pair["device_b"])

        # Group by root
        clusters_map = defaultdict(set)
        for pair in pairs:
            root = find(pair["device_a"])
            clusters_map[root].add(pair["device_a"])
            clusters_map[root].add(pair["device_b"])

        # Filter to clusters with 2+ members
        clusters = [sorted(members) for members in clusters_map.values() if len(members) >= 2]
        clusters.sort(key=len, reverse=True)
        return clusters

    def export_json(self, path: str):
        """Export correlation results to JSON."""
        pairs = self.correlate()
        clusters = self.find_clusters()

        result = {
            "timestamp": datetime.now().isoformat(),
            "window_s": self.window_s,
            "threshold": self.threshold,
            "total_devices": self.device_count,
            "correlated_pairs": pairs,
            "clusters": clusters,
        }

        with open(path, 'w') as f:
            json.dump(result, f, indent=2)

        print(f"[correlator] Exported: {path} ({len(pairs)} pairs, "
              f"{len(clusters)} clusters from {self.device_count} devices)")
        return path

    def print_report(self):
        """Print a human-readable correlation report."""
        pairs = self.correlate()
        clusters = self.find_clusters()

        print(f"\n{'=' * 70}")
        print(f"  Device Correlation Report")
        print(f"  Window: {self.window_s}s | Threshold: {self.threshold} | "
              f"Devices: {self.device_count}")
        print(f"{'=' * 70}")

        if clusters:
            print(f"\n  Clusters ({len(clusters)}):")
            print(f"  {'─' * 66}")
            for i, cluster in enumerate(clusters, 1):
                print(f"  Cluster {i} ({len(cluster)} devices):")
                for uid in cluster:
                    obs_count = len(self._observations.get(uid, []))
                    print(f"    - {uid} ({obs_count} obs)")
                print()
        else:
            print("\n  No device clusters found.")

        if pairs:
            print(f"  Correlated Pairs ({len(pairs)}):")
            print(f"  {'─' * 66}")
            print(f"  {'Device A':<30s} {'Device B':<30s} {'Ratio':>5s} {'Xport'}")
            print(f"  {'─' * 30} {'─' * 30} {'─' * 5} {'─' * 5}")
            for p in pairs[:20]:
                a = p["device_a"][:30]
                b = p["device_b"][:30]
                cross = "YES" if p["cross_transport"] else ""
                print(f"  {a:<30s} {b:<30s} {p['ratio']:>5.1%} {cross}")
            if len(pairs) > 20:
                print(f"  ... and {len(pairs) - 20} more")

        print(f"\n{'=' * 70}")


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Device correlation analysis")
    parser.add_argument("db_files", nargs="+", help="Detection .db files")
    parser.add_argument("--window", type=float, default=DEFAULT_WINDOW_S,
                        help=f"Co-occurrence time window in seconds (default: {DEFAULT_WINDOW_S})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Minimum co-occurrence ratio (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--json", type=str, default=None,
                        help="Export results to JSON file")

    args = parser.parse_args()

    correlator = DeviceCorrelator(window_s=args.window, threshold=args.threshold)
    for path in args.db_files:
        print(f"Loading: {path}")
        correlator.load_db(path)

    correlator.print_report()

    if args.json:
        correlator.export_json(args.json)

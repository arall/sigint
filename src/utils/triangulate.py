"""
RSSI Triangulation Module

Post-hoc multilateration from multi-node CSV detection logs.
Takes 2+ CSV files from sensor nodes at known GPS positions, correlates
detections of the same emitter by device ID or frequency, and estimates
emitter position using log-distance path loss model.
"""

import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Optional


# Log-distance path loss defaults: (exponent n, RSSI at 1m in dB)
# These are starting points — real-world calibration improves accuracy.
PATH_LOSS_DEFAULTS = {
    "keyfob":    (2.7, -30),
    "tpms":      (2.5, -35),
    "BLE-Adv":   (2.5, -40),
    "wifi":      (2.7, -30),
    "PMR446":    (2.2, -20),
    "gsm":       (3.0, -20),
    "lte":       (3.0, -20),
    "lora":      (2.3, -30),
    "LoRa":      (2.3, -30),
    "ISM":       (2.7, -30),
    "pocsag":    (2.7, -30),
}

# Correlation strategy per signal type
MATCH_STRATEGIES = {
    "keyfob":  "channel",
    "tpms":    "metadata_id",
    "BLE-Adv": "metadata_id",
    "wifi":    "metadata_id",
    "PMR446":  "channel",
    "gsm":     "frequency",
    "lte":     "frequency",
    "lora":    "frequency",
    "LoRa":    "frequency",
    "ISM":     "frequency",
    "pocsag":  "channel",
}

# Signal types that self-report position (not candidates for triangulation)
SELF_LOCATING = {"ADS-B", "adsb", "AIS", "ais"}


def haversine(lat1, lon1, lat2, lon2):
    """Distance in meters between two WGS84 points."""
    R = 6371000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def offset_position(lat, lon, north_m, east_m):
    """Offset a lat/lon by meters north and east. Returns (lat, lon)."""
    R = 6371000
    dlat = north_m / R
    dlon = east_m / (R * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def load_detections(csv_path):
    """Load and parse a CSV detection log. Returns list of dicts."""
    detections = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse timestamp
            try:
                row["_ts"] = datetime.fromisoformat(row["timestamp"])
            except (ValueError, KeyError):
                continue

            # Parse coordinates
            try:
                lat = row.get("latitude", "")
                lon = row.get("longitude", "")
                if not lat or not lon:
                    continue
                row["_lat"] = float(lat)
                row["_lon"] = float(lon)
            except (ValueError, TypeError):
                continue

            # Parse power
            try:
                row["_power"] = float(row.get("power_db", 0))
                row["_noise"] = float(row.get("noise_floor_db", 0))
            except (ValueError, TypeError):
                continue

            # Parse metadata
            try:
                row["_meta"] = json.loads(row.get("metadata", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                row["_meta"] = {}

            row["_source_file"] = csv_path
            detections.append(row)
    return detections


def _get_match_key(det, strategy):
    """Extract the correlation key from a detection."""
    if strategy == "channel":
        return det.get("channel", "")
    elif strategy == "frequency":
        try:
            freq = float(det.get("frequency_hz", 0))
            # Round to nearest kHz for matching
            return f"{round(freq / 1000)}"
        except (ValueError, TypeError):
            return ""
    elif strategy == "metadata_id":
        meta = det.get("_meta", {})
        # Try various ID fields in order of specificity
        for key in ("persona_id", "dev_sig", "mac", "sensor_id", "id", "code"):
            if key in meta and meta[key]:
                return str(meta[key])
        # Fall back to channel
        return det.get("channel", "")
    return ""


def correlate(file_detections, time_window_s=5.0, strategy="auto"):
    """Find correlated detections across sensor nodes.

    Args:
        file_detections: list of (detections_list, device_id) per file
        time_window_s: max seconds between correlated detections
        strategy: "auto", "channel", "frequency", or "metadata_id"

    Returns:
        list of groups, where each group is a list of detections
        from different nodes that correspond to the same emitter.
    """
    if not file_detections:
        return []

    # Auto-detect strategy from signal type
    if strategy == "auto":
        for dets, _ in file_detections:
            if dets:
                sig_type = dets[0].get("signal_type", "")
                strategy = MATCH_STRATEGIES.get(sig_type, "channel")
                break

    # Index all detections by match key, tagged with their node
    keyed = defaultdict(list)
    for dets, node_id in file_detections:
        for det in dets:
            key = _get_match_key(det, strategy)
            if key:
                keyed[key].append((det, node_id))

    groups = []
    for key, entries in keyed.items():
        # Need detections from at least 2 different nodes
        nodes = set(nid for _, nid in entries)
        if len(nodes) < 2:
            continue

        # Sort by timestamp
        entries.sort(key=lambda x: x[0]["_ts"])

        # Sliding window clustering
        i = 0
        while i < len(entries):
            cluster = [entries[i]]
            cluster_nodes = {entries[i][1]}
            j = i + 1
            while j < len(entries):
                dt = (entries[j][0]["_ts"] - entries[i][0]["_ts"]).total_seconds()
                if dt > time_window_s:
                    break
                if entries[j][1] not in cluster_nodes:
                    cluster.append(entries[j])
                    cluster_nodes.add(entries[j][1])
                j += 1

            if len(cluster_nodes) >= 2:
                groups.append({
                    "key": key,
                    "signal_type": cluster[0][0].get("signal_type", "unknown"),
                    "frequency_hz": float(cluster[0][0].get("frequency_hz", 0)),
                    "observations": [
                        {
                            "node": nid,
                            "lat": det["_lat"],
                            "lon": det["_lon"],
                            "power_db": det["_power"],
                            "noise_floor_db": det["_noise"],
                            "timestamp": det["timestamp"],
                            "meta": det.get("_meta", {}),
                        }
                        for det, nid in cluster
                    ],
                })
                i = j  # Skip past this cluster
            else:
                i += 1

    return groups


def rssi_to_distance(rssi_db, rssi_ref, n):
    """Estimate distance from RSSI using log-distance path loss model.

    d = 10^((rssi_ref - rssi) / (10 * n))
    """
    if n <= 0:
        return 1.0
    exponent = (rssi_ref - rssi_db) / (10.0 * n)
    # Clamp to reasonable range (0.1m to 50km)
    exponent = max(-1, min(exponent, 4.7))
    return 10.0 ** exponent


def estimate_position(observations, path_loss_n=None, rssi_ref=None,
                      signal_type=None, use_snr=False):
    """Estimate emitter position from RSSI observations at known locations.

    Args:
        observations: list of dicts with lat, lon, power_db, noise_floor_db
        path_loss_n: path loss exponent (auto from signal_type if None)
        rssi_ref: RSSI at 1m reference (auto from signal_type if None)
        signal_type: for auto parameter selection
        use_snr: use SNR instead of raw power (better when gains differ)

    Returns:
        dict with lat, lon, error_radius_m, num_nodes, distances
    """
    # Select path loss parameters
    defaults = PATH_LOSS_DEFAULTS.get(signal_type, (2.7, -30))
    if path_loss_n is None:
        path_loss_n = defaults[0]
    if rssi_ref is None:
        rssi_ref = defaults[1]

    # Compute estimated distances
    for obs in observations:
        if use_snr:
            rssi = obs["power_db"] - obs["noise_floor_db"]
            ref = rssi_ref - obs["noise_floor_db"]
        else:
            rssi = obs["power_db"]
            ref = rssi_ref
        obs["_dist_m"] = rssi_to_distance(rssi, ref, path_loss_n)

    if len(observations) == 2:
        return _estimate_2node(observations)
    else:
        return _estimate_multinode(observations)


def _estimate_2node(observations):
    """2-node estimation: weighted midpoint biased toward stronger signal."""
    o1, o2 = observations[0], observations[1]
    d1, d2 = o1["_dist_m"], o2["_dist_m"]

    # Weight inversely by distance (closer node is more reliable)
    w1 = 1.0 / max(d1, 0.1)
    w2 = 1.0 / max(d2, 0.1)
    total_w = w1 + w2

    lat = (o1["lat"] * w1 + o2["lat"] * w2) / total_w
    lon = (o1["lon"] * w1 + o2["lon"] * w2) / total_w

    # Error: distance between the two nodes as upper bound
    node_dist = haversine(o1["lat"], o1["lon"], o2["lat"], o2["lon"])
    error_m = node_dist * 0.5  # Ambiguous with 2 nodes

    return {
        "lat": lat,
        "lon": lon,
        "error_radius_m": error_m,
        "num_nodes": 2,
        "method": "weighted-midpoint",
        "distances": [(o["node"], o["_dist_m"]) for o in observations],
    }


def _estimate_multinode(observations):
    """3+ node estimation: least-squares minimization.

    Minimizes weighted sum of (estimated_distance - model_distance)^2.
    Uses scipy if available, falls back to iterative grid search.
    """
    try:
        from scipy.optimize import minimize as scipy_minimize
        return _estimate_scipy(observations, scipy_minimize)
    except ImportError:
        return _estimate_grid(observations)


def _estimate_scipy(observations, scipy_minimize):
    """Least-squares multilateration using scipy."""
    # Initial guess: centroid of sensor positions
    lat0 = sum(o["lat"] for o in observations) / len(observations)
    lon0 = sum(o["lon"] for o in observations) / len(observations)

    def cost(params):
        lat, lon = params
        total = 0
        for obs in observations:
            actual_dist = haversine(lat, lon, obs["lat"], obs["lon"])
            est_dist = obs["_dist_m"]
            # Weight by inverse distance (closer = more reliable RSSI)
            weight = 1.0 / max(est_dist, 1.0)
            total += weight * (actual_dist - est_dist) ** 2
        return total

    result = scipy_minimize(cost, [lat0, lon0], method="Nelder-Mead",
                            options={"xatol": 1e-7, "fatol": 0.1})

    lat, lon = result.x

    # Error estimate from residuals
    residuals = []
    for obs in observations:
        d_actual = haversine(lat, lon, obs["lat"], obs["lon"])
        residuals.append(abs(d_actual - obs["_dist_m"]))
    error_m = sum(residuals) / len(residuals)

    return {
        "lat": lat,
        "lon": lon,
        "error_radius_m": error_m,
        "num_nodes": len(observations),
        "method": "least-squares",
        "distances": [(o["node"], o["_dist_m"]) for o in observations],
    }


def _estimate_grid(observations):
    """Fallback grid search when scipy is not available."""
    # Start with centroid
    lat0 = sum(o["lat"] for o in observations) / len(observations)
    lon0 = sum(o["lon"] for o in observations) / len(observations)

    best_lat, best_lon = lat0, lon0
    best_cost = float("inf")

    # Progressive grid refinement
    for step_m in [500, 100, 20, 5, 1]:
        for di in range(-10, 11):
            for dj in range(-10, 11):
                lat, lon = offset_position(best_lat, best_lon,
                                           di * step_m, dj * step_m)
                cost = 0
                for obs in observations:
                    d = haversine(lat, lon, obs["lat"], obs["lon"])
                    weight = 1.0 / max(obs["_dist_m"], 1.0)
                    cost += weight * (d - obs["_dist_m"]) ** 2
                if cost < best_cost:
                    best_cost = cost
                    best_lat, best_lon = lat, lon

    residuals = []
    for obs in observations:
        d = haversine(best_lat, best_lon, obs["lat"], obs["lon"])
        residuals.append(abs(d - obs["_dist_m"]))

    return {
        "lat": best_lat,
        "lon": best_lon,
        "error_radius_m": sum(residuals) / len(residuals),
        "num_nodes": len(observations),
        "method": "grid-search",
        "distances": [(o["node"], o["_dist_m"]) for o in observations],
    }


def format_result(group, position):
    """Format a triangulation result for stdout."""
    lines = []
    sig = group["signal_type"]
    key = group["key"]
    freq_mhz = group["frequency_hz"] / 1e6 if group["frequency_hz"] else 0

    lines.append(f"Signal: {sig} | Key: {key} | Freq: {freq_mhz:.3f} MHz")

    for obs in group["observations"]:
        dist_str = ""
        for node, dist in position["distances"]:
            if node == obs["node"]:
                dist_str = f"  Est. distance: {dist:.1f} m"
                break
        lines.append(
            f"  Node {obs['node']:15s} @ {obs['lat']:.6f}, {obs['lon']:.6f}"
            f"  RSSI: {obs['power_db']:.1f} dB{dist_str}"
        )

    lines.append(
        f"  >> Estimated position: {position['lat']:.6f}, {position['lon']:.6f}"
        f"  (error: ~{position['error_radius_m']:.0f} m, "
        f"{position['num_nodes']}-node {position['method']})"
    )
    return "\n".join(lines)


def result_to_cot(group, position):
    """Build a CoT XML event for a triangulated position."""
    from datetime import timedelta, timezone

    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=300)
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    sig = group["signal_type"]
    key = group["key"]
    uid = f"sdr-tri-{sig}-{key}"

    freq_mhz = group["frequency_hz"] / 1e6 if group["frequency_hz"] else 0
    contact = f"TRI {sig} {key}"
    if freq_mhz:
        contact += f" {freq_mhz:.3f}MHz"

    n = position["num_nodes"]
    err = position["error_radius_m"]
    remarks = (
        f"Triangulated from {n} nodes ({position['method']}) | "
        f"Error: ~{err:.0f} m"
    )
    for node, dist in position["distances"]:
        remarks += f" | {node}: {dist:.0f}m"

    return (
        f'<event version="2.0" uid="{uid}" type="a-u-G" '
        f'time="{now.strftime(fmt)}" start="{now.strftime(fmt)}" '
        f'stale="{stale.strftime(fmt)}" how="m-g">'
        f'<point lat="{position["lat"]}" lon="{position["lon"]}" '
        f'hae="0" ce="{err:.0f}" le="9999999"/>'
        f'<detail>'
        f'<contact callsign="{contact}"/>'
        f'<remarks>{remarks}</remarks>'
        f'</detail>'
        f'</event>'
    )


def run_triangulation(args, tak_client=None):
    """Entry point called from sdr.py dispatch."""
    files = args.files
    if len(files) < 2:
        print("Error: need at least 2 CSV files from different nodes")
        return

    # Load all files
    print(f"Loading {len(files)} CSV files...")
    file_data = []
    for path in files:
        dets = load_detections(path)
        if not dets:
            print(f"  {path}: no valid detections (missing GPS?)")
            continue

        # Determine node ID from the first detection's device_id
        node_id = dets[0].get("device_id", path)
        sig_type = dets[0].get("signal_type", "unknown")

        # Warn about self-locating signal types
        if sig_type in SELF_LOCATING:
            print(f"  Warning: {path} contains {sig_type} data — these targets"
                  " self-report position, triangulation not needed")

        print(f"  {path}: {len(dets)} detections, node={node_id}, type={sig_type}")
        file_data.append((dets, node_id))

    if len(file_data) < 2:
        print("Error: need valid detections from at least 2 nodes")
        return

    # Check for duplicate node IDs
    node_ids = [nid for _, nid in file_data]
    if len(set(node_ids)) < len(node_ids):
        print("Warning: duplicate node IDs detected — are these from different positions?")

    # Correlate
    strategy = getattr(args, "strategy", "auto")
    time_window = getattr(args, "time_window", 5.0)
    print(f"\nCorrelating detections (window={time_window}s, strategy={strategy})...")

    groups = correlate(file_data, time_window_s=time_window, strategy=strategy)

    if not groups:
        print("No correlated detections found across nodes.")
        print("Tips: increase --time-window, check that CSVs have overlapping signals")
        return

    print(f"Found {len(groups)} correlated signal(s)\n")
    print("=" * 70)
    print("  TRIANGULATION RESULTS")
    print("=" * 70)

    # Estimate positions
    n_exp = getattr(args, "path_loss_exp", None)
    rssi_ref = getattr(args, "rssi_ref", None)
    use_snr = getattr(args, "use_snr", False)

    results = []
    for group in groups:
        pos = estimate_position(
            group["observations"],
            path_loss_n=n_exp,
            rssi_ref=rssi_ref,
            signal_type=group["signal_type"],
            use_snr=use_snr,
        )
        results.append((group, pos))
        print(f"\n{format_result(group, pos)}")

        if tak_client:
            cot = result_to_cot(group, pos)
            if tak_client._send(cot):
                print("  >> Sent to ATAK")

    print(f"\n{'=' * 70}")
    print(f"Total: {len(results)} emitter(s) triangulated from {len(file_data)} nodes")

    # CSV output
    csv_out = getattr(args, "csv_out", None)
    if csv_out:
        _write_results_csv(csv_out, results)
        print(f"Results written to: {csv_out}")

    if tak_client:
        tak_client.close()


def _write_results_csv(path, results):
    """Write triangulation results to CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "signal_type", "match_key", "frequency_hz",
            "estimated_lat", "estimated_lon", "error_radius_m",
            "num_nodes", "method", "node_details",
        ])
        for group, pos in results:
            writer.writerow([
                group["signal_type"],
                group["key"],
                group["frequency_hz"],
                f"{pos['lat']:.8f}",
                f"{pos['lon']:.8f}",
                f"{pos['error_radius_m']:.1f}",
                pos["num_nodes"],
                pos["method"],
                json.dumps(pos["distances"]),
            ])

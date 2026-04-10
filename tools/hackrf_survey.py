#!/usr/bin/env python3
"""
HackRF wideband spectrum survey.

Runs hackrf_sweep continuously and logs peak signals per band.
Outputs a summary CSV and prints periodic activity reports.

Usage:
    python3 tools/hackrf_survey.py                    # 1 hour, 24-1800 MHz
    python3 tools/hackrf_survey.py --duration 3600    # 1 hour
    python3 tools/hackrf_survey.py --duration 300     # 5 minutes
    python3 tools/hackrf_survey.py --freq-min 400 --freq-max 500  # UHF only
"""

import argparse
import csv
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime

KNOWN_BANDS = [
    (26.9, 27.5, "CB radio"),
    (87.5, 108.0, "FM broadcast"),
    (108.0, 137.0, "Airband"),
    (144.0, 148.0, "2m amateur"),
    (151.0, 155.0, "MURS/VHF"),
    (156.0, 157.5, "Marine VHF"),
    (157.5, 160.6, "Land mobile"),
    (160.6, 162.0, "Marine VHF"),
    (162.0, 163.0, "AIS"),
    (174.0, 230.0, "DAB/TV VHF"),
    (380.0, 400.0, "TETRA"),
    (410.0, 430.0, "TETRA private"),
    (430.0, 440.0, "70cm amateur"),
    (433.0, 434.0, "ISM 433"),
    (440.0, 450.0, "PMR446/UHF"),
    (462.0, 468.0, "FRS/GMRS"),
    (470.0, 790.0, "TV/DVB-T"),
    (791.0, 821.0, "LTE 800 DL"),
    (821.0, 832.0, "LTE 800 guard"),
    (832.0, 862.0, "LTE 800 UL"),
    (880.0, 915.0, "GSM 900 UL"),
    (925.0, 960.0, "GSM 900 DL"),
    (960.0, 1164.0, "Aeronautical/DME"),
    (1164.0, 1215.0, "GNSS L5/Galileo"),
    (1215.0, 1300.0, "GNSS L2/Radar"),
    (1300.0, 1400.0, "Radar/Aero"),
    (1452.0, 1492.0, "DAB L-band"),
    (1525.0, 1559.0, "Inmarsat/Sat DL"),
    (1559.0, 1610.0, "GNSS L1"),
    (1610.0, 1626.5, "Iridium"),
    (1710.0, 1785.0, "LTE 1800 UL"),
    (1805.0, 1880.0, "LTE 1800 DL"),
    (1920.0, 1980.0, "UMTS UL"),
    (2110.0, 2170.0, "UMTS DL"),
]


def identify_band(freq_mhz):
    for low, high, name in KNOWN_BANDS:
        if low <= freq_mhz <= high:
            return name
    return ""


def run_survey(freq_min, freq_max, duration, lna_gain, vga_gain, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_csv = os.path.join(output_dir, f"survey_raw_{timestamp}.csv")
    summary_csv = os.path.join(output_dir, f"survey_summary_{timestamp}.csv")

    # Track peak power per frequency bin across the entire run
    peak_power = {}
    # Track activity counts per band (how many sweeps had signal > threshold)
    band_activity = defaultdict(int)
    sweep_count = 0
    threshold_db = -30

    cmd = [
        "hackrf_sweep",
        "-f", f"{freq_min}:{freq_max}",
        "-w", "500000",
        "-l", str(lna_gain),
        "-g", str(vga_gain),
    ]

    print(f"Starting HackRF survey: {freq_min}-{freq_max} MHz for {duration}s")
    print(f"LNA gain: {lna_gain}, VGA gain: {vga_gain}")
    print(f"Raw data: {raw_csv}")
    print(f"Summary:  {summary_csv}")
    print()

    start_time = time.time()
    last_report = start_time

    # Write raw CSV header
    with open(raw_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "freq_mhz", "power_db", "band"])

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    try:
        raw_rows = []
        for line in proc.stdout:
            elapsed = time.time() - start_time
            if elapsed >= duration:
                break

            parts = line.strip().split(",")
            if len(parts) < 7:
                continue

            try:
                ts = parts[0].strip() + " " + parts[1].strip()
                freq_low = int(parts[2].strip())
                bin_width = float(parts[4].strip())
                powers = [float(p.strip()) for p in parts[6:]]
            except (ValueError, IndexError):
                continue

            sweep_count += 1
            active_bands_this_sweep = set()

            for i, p in enumerate(powers):
                freq_mhz = (freq_low + i * bin_width) / 1e6

                # Track peaks
                if freq_mhz not in peak_power or p > peak_power[freq_mhz]:
                    peak_power[freq_mhz] = p

                # Track activity
                if p > threshold_db:
                    band = identify_band(freq_mhz)
                    if band:
                        active_bands_this_sweep.add(band)

                    raw_rows.append([ts, f"{freq_mhz:.2f}", f"{p:.1f}", band])

            for band in active_bands_this_sweep:
                band_activity[band] += 1

            # Flush raw data periodically
            if len(raw_rows) >= 1000:
                with open(raw_csv, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerows(raw_rows)
                raw_rows = []

            # Print periodic report every 60 seconds
            now = time.time()
            if now - last_report >= 60:
                last_report = now
                remaining = max(0, duration - elapsed)
                print(f"\n--- {int(elapsed)}s elapsed, {int(remaining)}s remaining, {sweep_count} sweeps ---")
                if band_activity:
                    sorted_bands = sorted(band_activity.items(), key=lambda x: -x[1])
                    for band, count in sorted_bands[:10]:
                        print(f"  {band:20s}  {count:5d} detections")
                else:
                    print("  No activity above threshold")

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        proc.terminate()
        proc.wait()

    # Flush remaining raw data
    if raw_rows:
        with open(raw_csv, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(raw_rows)

    # Write summary
    peaks = [(f, p) for f, p in peak_power.items() if p > threshold_db]
    peaks.sort(key=lambda x: -x[1])

    with open(summary_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["freq_mhz", "peak_power_db", "band"])
        for freq, power in peaks:
            writer.writerow([f"{freq:.2f}", f"{power:.1f}", identify_band(freq)])

    # Final report
    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"Survey complete: {int(elapsed)}s, {sweep_count} sweeps")
    print(f"{'=' * 60}")
    print(f"\nTop 30 strongest signals:")
    print(f"{'Frequency':>12}  {'Peak Power':>10}  Band")
    print("-" * 55)
    for freq, power in peaks[:30]:
        band = identify_band(freq)
        print(f"{freq:>10.2f} MHz  {power:>8.1f} dB  {band}")

    print(f"\nBand activity (sweeps with signal > {threshold_db} dB):")
    print(f"{'Band':>20}  {'Detections':>10}  {'% of sweeps':>11}")
    print("-" * 50)
    if band_activity:
        sorted_bands = sorted(band_activity.items(), key=lambda x: -x[1])
        for band, count in sorted_bands:
            pct = count / max(sweep_count, 1) * 100
            print(f"{band:>20}  {count:>10}  {pct:>10.1f}%")

    print(f"\nFiles saved:")
    print(f"  Raw:     {raw_csv}")
    print(f"  Summary: {summary_csv}")


def main():
    parser = argparse.ArgumentParser(description="HackRF wideband spectrum survey")
    parser.add_argument("--duration", type=int, default=3600,
                        help="Survey duration in seconds (default: 3600 = 1 hour)")
    parser.add_argument("--freq-min", type=int, default=24,
                        help="Start frequency in MHz (default: 24)")
    parser.add_argument("--freq-max", type=int, default=1800,
                        help="End frequency in MHz (default: 1800)")
    parser.add_argument("--lna-gain", type=int, default=32,
                        help="LNA gain 0-40 dB (default: 32)")
    parser.add_argument("--vga-gain", type=int, default=32,
                        help="VGA gain 0-62 dB (default: 32)")
    parser.add_argument("--output", default=None,
                        help="Output directory (default: output/surveys/)")
    args = parser.parse_args()

    output_dir = args.output or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output", "surveys"
    )

    run_survey(args.freq_min, args.freq_max, args.duration,
               args.lna_gain, args.vga_gain, output_dir)


if __name__ == "__main__":
    main()

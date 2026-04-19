#!/usr/bin/env python3
"""
SDR Signal Scanner
Main entry point for signal detection and logging.

Usage:
    python sdr.py pmr        # Scan PMR446 channels
    python sdr.py keyfob     # Scan keyfobs/garage door openers
    python sdr.py gsm        # Detect phone activity (GSM uplink)
    python sdr.py lte        # Detect phone presence (LTE uplink power)
    python sdr.py adsb       # Track aircraft (ADS-B)
    python sdr.py ais        # Track vessels (AIS)
    python sdr.py pocsag     # Decode pager messages (POCSAG)
    python sdr.py record     # Record IQ samples to file
    python sdr.py replay     # Analyze recorded signals
    python sdr.py wifi       # Scan WiFi (coming soon)
    python sdr.py bluetooth  # Scan Bluetooth (coming soon)
"""

import argparse
import os
import sys

# Project root directory (parent of src)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT = os.path.join(PROJECT_ROOT, "output")

# Load .env file if present
_env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                os.environ.setdefault(_key.strip(), _val.strip())


def main():
    parser = argparse.ArgumentParser(
        description="SDR Signal Scanner - Detect and log radio signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sdr.py pmr                    Scan PMR446 channels
  python sdr.py keyfob                 Scan keyfobs at 433.92 MHz
  python sdr.py keyfob -f 315          Scan keyfobs at 315 MHz (US)
  python sdr.py pmr --gain 30          Scan with custom gain
  python sdr.py pmr --output ./logs    Save logs to custom directory
        """,
    )

    # Global options
    parser.add_argument(
        "--gps",
        action="store_true",
        help="Enable GPS for real-time coordinates in detections",
    )
    parser.add_argument(
        "--gps-port",
        default="/dev/ttyACM0",
        metavar="PORT",
        help="GPS serial port (default: /dev/ttyACM0)",
    )
    parser.add_argument(
        "--output", "-o",
        default=DEFAULT_OUTPUT,
        help=f"Output directory for signal logs (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Delete all output data (DBs, audio, personas, logs) before starting",
    )
    parser.add_argument(
        "--device-id", "-d",
        default="rtlsdr-001",
        help="Device identifier for this SDR (default: rtlsdr-001)",
    )
    parser.add_argument(
        "--device-index",
        type=int,
        default=0,
        help="RTL-SDR device index for multi-dongle setups (default: 0)",
    )
    parser.add_argument(
        "--min-snr",
        type=float,
        default=5.0,
        help="Minimum SNR (dB) to log a detection (default: 5.0)",
    )
    parser.add_argument(
        "--tak",
        action="store_true",
        help="Stream detections to TAK Server as CoT events",
    )
    parser.add_argument(
        "--tak-dir",
        default=os.path.join(PROJECT_ROOT, "atak"),
        metavar="DIR",
        help="TAK certificate directory (default: atak/)",
    )

    # Subcommands for different signal types
    subparsers = parser.add_subparsers(
        dest="command",
        title="scanners",
        description="Available signal scanners",
    )

    # PMR scanner
    pmr_parser = subparsers.add_parser(
        "pmr",
        help="Scan PMR446 channels (446 MHz)",
    )
    pmr_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    pmr_parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Disable audio recording",
    )
    pmr_parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Transcribe audio to text using Whisper",
    )
    pmr_parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: base)",
    )
    pmr_parser.add_argument(
        "--language",
        default=None,
        help="Language code for transcription (e.g. en, es). Auto-detect if omitted",
    )
    pmr_parser.add_argument(
        "--digital",
        action="store_true",
        help="Enable digital PMR (dPMR/DMR) energy detection on channels D1-D16",
    )
    pmr_parser.add_argument(
        "--ppm",
        type=int,
        default=0,
        help="RTL-SDR frequency correction in ppm (e.g. -28, default: 0)",
    )

    # Keyfob scanner
    keyfob_parser = subparsers.add_parser(
        "keyfob",
        help="Scan keyfobs/garage door openers (315/433 MHz)",
    )
    keyfob_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    keyfob_parser.add_argument(
        "--frequency", "-f",
        type=float,
        default=433.92,
        help="Frequency in MHz (default: 433.92, US: 315)",
    )

    # TPMS scanner
    tpms_parser = subparsers.add_parser(
        "tpms",
        help="Scan TPMS tire pressure sensors (315/433 MHz)",
    )
    tpms_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    tpms_parser.add_argument(
        "--frequency", "-f",
        type=float,
        default=433.92,
        help="Frequency in MHz (default: 433.92 EU, US: 315)",
    )

    # GSM scanner
    gsm_parser = subparsers.add_parser(
        "gsm",
        help="Detect phone activity on GSM uplink (890-915 MHz)",
    )
    gsm_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    gsm_parser.add_argument(
        "--band", "-b",
        type=str,
        default="GSM-900",
        choices=["GSM-900", "GSM-850"],
        help="GSM band to scan (default: GSM-900)",
    )

    # LTE uplink scanner
    lte_parser = subparsers.add_parser(
        "lte",
        help="Detect phone presence via LTE uplink power density (800-915 MHz)",
    )
    lte_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    lte_parser.add_argument(
        "--bands", "-b",
        nargs="+",
        default=["Band-20", "Band-8"],
        choices=["Band-20", "Band-8", "Band-5"],
        help="LTE bands to monitor (default: Band-20 Band-8)",
    )
    lte_parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=3.0,
        help="Activity threshold in dB above baseline (default: 3.0)",
    )

    # ADS-B scanner
    adsb_parser = subparsers.add_parser(
        "adsb",
        help="Track aircraft via ADS-B (1090 MHz)",
    )
    adsb_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    adsb_parser.add_argument(
        "--native",
        action="store_true",
        help="Use native Python decoder instead of dump1090",
    )

    # AIS scanner
    ais_parser = subparsers.add_parser(
        "ais",
        help="Track vessels via AIS (162 MHz)",
    )
    ais_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    ais_parser.add_argument(
        "--native",
        action="store_true",
        help="Use native Python decoder instead of rtl_ais",
    )
    ais_parser.add_argument(
        "--rssi-device-index",
        type=int,
        default=None,
        help="Secondary RTL-SDR index for parallel RSSI sampling "
             "(enables AIS calibration). rtl_ais holds the primary SDR, "
             "so this must be a different dongle.",
    )

    # Jammer / broadband interference detector
    jammer_parser = subparsers.add_parser(
        "jammer",
        help="Hop across bands watching for raised noise floor + "
             "broadband character (jamming / interference).",
    )
    jammer_parser.add_argument(
        "--gain", "-g",
        type=int, default=40,
        help="RF gain (default: 40)",
    )
    jammer_parser.add_argument(
        "--dwell", type=float, default=1.0, dest="dwell_s",
        help="Seconds to dwell on each band per revisit (default: 1.0)",
    )
    jammer_parser.add_argument(
        "--threshold", type=float, default=10.0,
        dest="elevation_threshold_db",
        help="Elevation above baseline, in dB, before flagging (default: 10)",
    )
    jammer_parser.add_argument(
        "--flatness", type=float, default=0.5,
        dest="flatness_threshold",
        help="Spectral-flatness threshold, 0-1 (default: 0.5). Lower = "
             "fire on peakier signals too (more false positives).",
    )
    jammer_parser.add_argument(
        "--min-consec", type=int, default=3,
        help="How many consecutive elevated samples before firing "
             "(default: 3). Matches dwell × 3 seconds of sustained "
             "elevation at the default dwell.",
    )
    jammer_parser.add_argument(
        "--recalibrate", action="store_true",
        help="Force a fresh baseline acquisition instead of loading "
             "jammer_baseline.json. Use after moving the node.",
    )
    jammer_parser.add_argument(
        "--band", action="append", default=None, dest="bands",
        metavar="LABEL:CENTER_MHZ:BW_MHZ",
        help="Override the default band list. Repeat for multiple. "
             "Example: --band GPS-L1:1575.42:2",
    )

    # POCSAG/Pager scanner
    pocsag_parser = subparsers.add_parser(
        "pocsag",
        aliases=["pager"],
        help="Decode pager messages (POCSAG)",
    )
    pocsag_parser.add_argument(
        "--frequency", "-f",
        type=float,
        help="Frequency in MHz (default: region-specific)",
    )
    pocsag_parser.add_argument(
        "--region", "-r",
        choices=["us", "uk", "eu", "au"],
        default="us",
        help="Region for default frequencies (default: us)",
    )
    pocsag_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    pocsag_parser.add_argument(
        "--native",
        action="store_true",
        help="Use native Python decoder instead of multimon-ng",
    )

    # Signal Recorder
    record_parser = subparsers.add_parser(
        "record",
        aliases=["rec"],
        help="Record IQ samples to file",
    )
    record_parser.add_argument(
        "--frequency", "-f",
        type=float,
        help="Frequency in MHz",
    )
    record_parser.add_argument(
        "--preset", "-p",
        choices=["fm", "air", "adsb", "ais", "pmr", "gsm900",
                 "ism433", "ism868", "ism915", "pocsag", "noaa"],
        help="Use frequency preset",
    )
    record_parser.add_argument(
        "--sample-rate", "-s",
        type=float,
        default=2.4,
        help="Sample rate in MHz (default: 2.4)",
    )
    record_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    record_parser.add_argument(
        "--duration", "-t",
        type=float,
        default=10.0,
        help="Recording duration in seconds (default: 10)",
    )
    record_parser.add_argument(
        "--format",
        choices=["raw", "wav", "npy"],
        default="raw",
        help="Output format (default: raw)",
    )
    record_parser.add_argument(
        "--description",
        default="",
        help="Recording description",
    )
    record_parser.add_argument(
        "--list-presets",
        action="store_true",
        help="List available frequency presets",
    )

    # Signal Replay/Analysis
    replay_parser = subparsers.add_parser(
        "replay",
        aliases=["analyze"],
        help="Analyze recorded signals",
    )
    replay_parser.add_argument(
        "file",
        nargs="?",
        help="Recording file to analyze",
    )
    replay_parser.add_argument(
        "--info", "-i",
        action="store_true",
        help="Show recording information",
    )
    replay_parser.add_argument(
        "--spectrogram",
        action="store_true",
        help="Generate spectrogram",
    )
    replay_parser.add_argument(
        "--spectrum",
        action="store_true",
        help="Generate power spectrum plot",
    )
    replay_parser.add_argument(
        "--iq",
        action="store_true",
        help="Generate I/Q constellation plot",
    )
    replay_parser.add_argument(
        "--convert", "-c",
        choices=["raw", "wav", "npy", "csv"],
        help="Convert to format",
    )
    replay_parser.add_argument(
        "--save",
        help="Save plot/conversion to file",
    )

    # Generic FM scanner
    fm_parser = subparsers.add_parser(
        "fm",
        help="Generic FM scanner with band profiles (FRS, Marine, MURS, 2m, 70cm)",
    )
    fm_parser.add_argument(
        "band",
        nargs="?",
        default="pmr446",
        help="Band profile: pmr446, frs, gmrs, marine, murs, 2m, 70cm, cb, landmobile",
    )
    fm_parser.add_argument(
        "--list",
        action="store_true",
        help="List available band profiles",
    )
    fm_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    fm_parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Disable audio recording",
    )
    fm_parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Transcribe audio to text using Whisper",
    )
    fm_parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: base)",
    )
    fm_parser.add_argument(
        "--language",
        default=None,
        help="Language code for transcription (e.g. en, es)",
    )
    fm_parser.add_argument(
        "--dwell",
        type=float,
        default=5.0,
        help="Dwell time per window in seconds when hopping (default: 5.0)",
    )
    fm_parser.add_argument(
        "--channels",
        nargs="+",
        default=None,
        help="Filter to specific channel labels (e.g., --channels CALL U272 U274)",
    )

    # Wideband energy scanner
    scan_parser = subparsers.add_parser(
        "scan",
        help="Wideband energy detection scanner",
    )
    scan_parser.add_argument(
        "--frequency", "-f",
        type=float,
        default=446.05,
        help="Center frequency in MHz (default: 446.05)",
    )
    scan_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    scan_parser.add_argument(
        "--bin-width", "-b",
        type=float,
        default=12.5,
        help="Bin width in kHz (default: 12.5)",
    )
    scan_parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=10.0,
        help="SNR threshold in dB (default: 10.0)",
    )
    scan_parser.add_argument(
        "--classify",
        action="store_true",
        help="Enable automatic modulation classification for detected signals",
    )

    # ISM band scanner (rtl_433)
    ism_parser = subparsers.add_parser(
        "ism",
        help="ISM band scanner via rtl_433 (weather stations, TPMS, keyfobs, sensors)",
    )
    ism_parser.add_argument(
        "--frequency", "-f",
        type=float,
        default=433.92,
        help="Frequency in MHz (default: 433.92)",
    )
    ism_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    ism_parser.add_argument(
        "--hop",
        action="store_true",
        help="Enable frequency hopping (433/868/915 MHz)",
    )

    # WiFi probe request scanner
    wifi_parser = subparsers.add_parser(
        "wifi",
        help="Sniff WiFi probe requests to detect nearby devices",
    )
    wifi_parser.add_argument(
        "--interface", "-i",
        default="wlan1",
        help="WiFi interface with monitor mode support (default: wlan1)",
    )
    wifi_parser.add_argument(
        "--channels",
        default=None,
        help="Channels to hop (e.g. '1,6,11' or '1-11,36,149-165', "
             "default: 2.4GHz 1,6,11 + 5GHz non-DFS)",
    )
    wifi_parser.add_argument(
        "--band",
        default=None,
        choices=["2.4", "5", "all"],
        help="Quick band select: 2.4 (ch 1,6,11), 5 (non-DFS), all (2.4+5 including DFS)",
    )
    wifi_parser.add_argument(
        "--hop-interval",
        type=float,
        default=0.3,
        help="Seconds per channel hop (default: 0.3)",
    )
    wifi_parser.add_argument(
        "--min-rssi",
        type=int,
        default=-85,
        help="Minimum RSSI in dBm to log (default: -85)",
    )

    # Bluetooth BLE scanner
    bt_parser = subparsers.add_parser(
        "bluetooth",
        aliases=["bt"],
        help="Scan BLE advertisements to detect nearby devices",
    )
    bt_parser.add_argument(
        "--adapter",
        default="hci1",
        help="Bluetooth HCI adapter (default: hci1)",
    )
    bt_parser.add_argument(
        "--min-rssi",
        type=int,
        default=-90,
        help="Minimum RSSI in dBm to log (default: -90)",
    )

    # Drone video link scanner (HackRF)
    dv_parser = subparsers.add_parser(
        "drone-video",
        aliases=["dv"],
        help="Detect drone video downlinks on 2.4/5.8 GHz (requires HackRF)",
    )
    dv_parser.add_argument(
        "--band", "-b",
        choices=["2.4", "5.8"],
        default="2.4",
        help="ISM band: 2.4 or 5.8 GHz (default: 2.4)",
    )
    dv_parser.add_argument(
        "--lna-gain",
        type=int,
        default=32,
        help="HackRF LNA gain 0-40 dB (default: 32)",
    )
    dv_parser.add_argument(
        "--vga-gain",
        type=int,
        default=40,
        help="HackRF VGA gain 0-62 dB (default: 40)",
    )
    dv_parser.add_argument(
        "--amp",
        action="store_true",
        help="Enable HackRF RF amplifier (+14 dB)",
    )

    # FPV analog video scanner
    fpv_parser = subparsers.add_parser(
        "fpv",
        help="Detect and demodulate analog FPV drone video on 5.8/1.2 GHz (requires HackRF)",
    )
    fpv_parser.add_argument(
        "--band", "-b",
        choices=["5.8", "1.2"],
        default="5.8",
        help="Frequency band (default: 5.8)",
    )
    fpv_parser.add_argument(
        "--serial", "-d",
        help="HackRF serial number",
    )
    fpv_parser.add_argument(
        "--lna-gain",
        type=int,
        default=40,
        help="HackRF LNA gain 0-40 dB (default: 40)",
    )
    fpv_parser.add_argument(
        "--vga-gain",
        type=int,
        default=40,
        help="HackRF VGA gain 0-62 dB (default: 40)",
    )
    fpv_parser.add_argument(
        "--amp",
        action="store_true",
        help="Enable HackRF RF amplifier (+14 dB)",
    )

    # LoRa/Meshtastic scanner
    lora_parser = subparsers.add_parser(
        "lora",
        help="Detect LoRa/Meshtastic transmissions (868/915 MHz)",
    )
    lora_parser.add_argument(
        "--gain", "-g",
        type=int,
        default=40,
        help="RF gain (default: 40)",
    )
    lora_parser.add_argument(
        "--region", "-r",
        choices=["eu", "us"],
        default="eu",
        help="Region: eu (868 MHz) or us (915 MHz) (default: eu)",
    )

    # Meshtastic mesh scanner (serial device)
    mesh_parser = subparsers.add_parser(
        "mesh",
        help="Decode Meshtastic mesh traffic via serial device (positions, messages, telemetry)",
    )
    mesh_parser.add_argument(
        "--port", "-p",
        type=str,
        default=None,
        help="Serial port (e.g. /dev/ttyUSB0). Auto-detect if omitted.",
    )
    mesh_parser.add_argument(
        "--region", "-r",
        choices=["eu", "us"],
        default="eu",
        help="Region: eu (868 MHz) or us (915 MHz) (default: eu)",
    )

    # Central server — all captures + parsers in parallel
    server_parser = subparsers.add_parser(
        "server",
        help="Run central server with all captures and parsers from a JSON config",
    )
    server_parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="Path to JSON config file (default: configs/server.json)",
    )
    server_parser.add_argument(
        "--web",
        action="store_true",
        help="Enable web dashboard UI (default port: 8080)",
    )
    server_parser.add_argument(
        "--web-port",
        type=int,
        default=8080,
        help="Web dashboard port (default: 8080, implies --web)",
    )

    # Multi-SDR orchestrator
    multi_parser = subparsers.add_parser(
        "multi",
        help="Run multiple scanners in parallel from a JSON config file",
    )
    multi_parser.add_argument(
        "config",
        help="Path to JSON config file",
    )

    # TAK Server enrollment
    tak_parser = subparsers.add_parser(
        "tak-enroll",
        help="Enroll for TAK Server client certificate (one-time setup)",
    )
    tak_parser.add_argument(
        "--username", "-u",
        help="TAK Server username",
    )

    # TAK Server connection test
    subparsers.add_parser(
        "tak-test",
        help="Test TAK Server connection and send a test marker",
    )

    # TAK clear all SDR markers
    subparsers.add_parser(
        "tak-clear",
        help="Delete all SDR markers from TAK Server",
    )

    # Triangulation from multi-node detection logs
    tri_parser = subparsers.add_parser(
        "triangulate",
        aliases=["tri"],
        help="Triangulate emitter positions from multi-node detection logs",
    )
    tri_parser.add_argument(
        "files",
        nargs="+",
        help="Detection log files (.db) from different sensor nodes (minimum 2)",
    )
    tri_parser.add_argument(
        "--time-window", "-t",
        type=float,
        default=5.0,
        dest="time_window",
        help="Time window in seconds for correlating detections (default: 5.0)",
    )
    tri_parser.add_argument(
        "--path-loss-exp", "-n",
        type=float,
        default=None,
        dest="path_loss_exp",
        help="Path loss exponent (default: auto by signal type, ~2.7 outdoor)",
    )
    tri_parser.add_argument(
        "--rssi-ref",
        type=float,
        default=None,
        help="RSSI at 1m reference distance in dB (default: auto by signal type)",
    )
    tri_parser.add_argument(
        "--strategy", "-s",
        choices=["auto", "channel", "frequency", "metadata_id"],
        default="auto",
        help="Correlation strategy (default: auto-detect from signal type)",
    )
    tri_parser.add_argument(
        "--use-snr",
        action="store_true",
        help="Use SNR instead of raw power (better when nodes have different gains)",
    )
    tri_parser.add_argument(
        "--no-calibration",
        action="store_true",
        help="Skip per-node RSSI calibration (use raw power_db as-is)",
    )
    tri_parser.add_argument(
        "--calibration-file",
        default=None,
        metavar="PATH",
        help="Calibration DB path (default: <output>/calibration.db)",
    )

    # Opportunistic RSSI calibration
    cal_parser = subparsers.add_parser(
        "calibrate",
        aliases=["cal"],
        help="Solve per-node RX offsets against known-position emitters",
    )
    cal_sub = cal_parser.add_subparsers(dest="calibrate_cmd", metavar="subcommand")

    cal_ingest = cal_sub.add_parser(
        "ingest", help="Match detections to reference emitters and fit offsets")
    cal_ingest.add_argument("files", nargs="+",
                            help="Detection .db file(s) captured by this node")
    cal_ingest.add_argument("--node-id", required=True,
                            help="Identifier for this physical node (e.g. N01)")
    cal_ingest.add_argument("--db", default=None,
                            help="Calibration DB path (default: <output>/calibration.db)")
    cal_ingest.add_argument(
        "--emitters", default=None,
        help="Reference emitter JSON (default: configs/calibration_emitters.json)")
    cal_ingest.add_argument("--lat", type=float, default=None,
                            help="Override node latitude (defaults to stored position)")
    cal_ingest.add_argument("--lon", type=float, default=None,
                            help="Override node longitude")
    cal_ingest.add_argument("--node-alt", type=float, default=None,
                            help="Node altitude in metres above sea level (default: 0)")
    cal_ingest.add_argument(
        "--source", action="append", default=None,
        choices=["adsb", "ais", "surveyed", "all"],
        help="Restrict to one or more sources (default: all)")
    cal_ingest.add_argument("--since-hours", type=float, default=None,
                            help="Only ingest detections newer than N hours")
    cal_ingest.add_argument("--method", default=None,
                            choices=["huber", "mean"],
                            help="Fit method (default: huber)")
    cal_ingest.add_argument("--max-age-days", type=float, default=None,
                            help="Samples older than N days are excluded from the fit")
    cal_ingest.add_argument("--dry-run", action="store_true",
                            help="Print what would be ingested without writing")

    cal_show = cal_sub.add_parser("show", help="Print current solved offsets")
    cal_show.add_argument("--db", default=None)
    cal_show.add_argument("--node-id", dest="cal_node_filter", default=None,
                          help="Only show this node's offsets")
    cal_show.add_argument("--json", dest="as_json", action="store_true",
                          help="Emit JSON")

    cal_recompute = cal_sub.add_parser(
        "recompute", help="Refit cal_offsets from existing cal_samples")
    cal_recompute.add_argument("--db", default=None)
    cal_recompute.add_argument("--node-id", dest="cal_node_filter", default=None)
    cal_recompute.add_argument("--method", default=None,
                               choices=["huber", "mean"])
    cal_recompute.add_argument("--max-age-days", type=float, default=None)

    cal_setpos = cal_sub.add_parser(
        "set-position", help="Store a surveyed lat/lon for a node")
    cal_setpos.add_argument("--node-id", required=True)
    cal_setpos.add_argument("--lat", type=float, required=True)
    cal_setpos.add_argument("--lon", type=float, required=True)
    cal_setpos.add_argument("--alt", type=float, default=None)
    cal_setpos.add_argument("--mobile", action="store_true",
                            help="Mark node as mobile (skips surveyed-emitter matching)")
    cal_setpos.add_argument("--db", default=None)

    cal_watch = cal_sub.add_parser(
        "watch", help="Continuously ingest from .db files in --output")
    cal_watch.add_argument("--node-id", required=True)
    cal_watch.add_argument("--db", default=None)
    cal_watch.add_argument("--emitters", default=None)
    cal_watch.add_argument("--lat", type=float, default=None)
    cal_watch.add_argument("--lon", type=float, default=None)
    cal_watch.add_argument("--node-alt", type=float, default=None)
    cal_watch.add_argument("--interval", type=int, default=10,
                           help="Poll interval in seconds (default: 10)")
    cal_watch.add_argument("--source", action="append", default=None,
                           choices=["adsb", "ais", "surveyed", "all"])
    cal_watch.add_argument("--since-hours", type=float, default=None)
    cal_watch.add_argument("--method", default=None,
                           choices=["huber", "mean"])
    cal_watch.add_argument("--max-age-days", type=float, default=None)
    cal_watch.add_argument("--dry-run", action="store_true")

    # Heatmap from detection logs
    heatmap_parser = subparsers.add_parser(
        "heatmap",
        help="Generate RF activity heatmap from detection logs",
    )
    heatmap_parser.add_argument(
        "files",
        nargs="+",
        help="Detection log files (.db)",
    )
    heatmap_parser.add_argument(
        "--resolution", "-r",
        type=float,
        default=0.001,
        help="Grid resolution in degrees (~111m per 0.001, default: 0.001)",
    )
    heatmap_parser.add_argument(
        "--signal-type", "-s",
        type=str,
        action="append",
        dest="signal_types",
        help="Filter to specific signal types (can repeat, default: all)",
    )

    # Device correlation from detection logs
    corr_parser = subparsers.add_parser(
        "correlate",
        aliases=["corr"],
        help="Analyze device co-occurrence across signal types",
    )
    corr_parser.add_argument(
        "files",
        nargs="+",
        help="Detection log files (.db)",
    )
    corr_parser.add_argument(
        "--window", "-w",
        type=float,
        default=30.0,
        help="Co-occurrence time window in seconds (default: 30)",
    )
    corr_parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=0.5,
        help="Minimum co-occurrence ratio 0-1 (default: 0.5)",
    )
    corr_parser.add_argument(
        "--json",
        type=str,
        default=None,
        dest="json_out",
        help="Export results to JSON file",
    )

    # Web dashboard
    web_parser = subparsers.add_parser(
        "web",
        help="Web dashboard UI (reads from output directory, standalone)",
    )
    web_parser.add_argument(
        "-p", "--port",
        type=int,
        default=8080,
        help="HTTP port (default: 8080)",
    )
    web_parser.add_argument(
        "-d", "--dir",
        type=str,
        default=None,
        help="Output directory to serve (default: --output value)",
    )

    # Meshtastic C2 agent
    agent_parser = subparsers.add_parser(
        "agent",
        help="Run as a remote Meshtastic C2 agent",
    )
    agent_parser.add_argument("--config", default="configs/agent.json",
                              help="Path to agent.json")
    agent_parser.add_argument("--state-dir", default=None)
    agent_parser.add_argument("--meshtastic-port", default=None)
    agent_parser.add_argument("--agent-id", default=None)

    # Replay a recorded detection .db over the C2 path as if from a live
    # agent. Uses the Meshtastic link from configs/agent.json.
    replay_parser = subparsers.add_parser(
        "replay-c2",
        help="Replay a detection .db over mesh as if from a specified agent",
    )
    replay_parser.add_argument("db", help="Path to a detection .db to replay")
    replay_parser.add_argument("--agent-id", required=True,
                               help="Agent identity to claim on the wire")
    replay_parser.add_argument("--config", default="configs/agent.json",
                               help="Path to agent.json (for mesh port/channel)")
    replay_parser.add_argument("--meshtastic-port", default=None,
                               help="Override mesh port from config")
    replay_parser.add_argument("--rate", type=float, default=1.0,
                               help="Target DET rate in Hz (default: 1.0)")
    replay_parser.add_argument("--max", type=int, default=None,
                               dest="max_rows",
                               help="Cap on DETs sent (default: no cap)")
    replay_parser.add_argument("--skip-handshake", action="store_true",
                               help="Don't send HELLO first — assumes server "
                               "already has this agent_id approved recently")
    replay_parser.add_argument("--require-position", action="store_true",
                               help="Skip rows without GPS (for triangulation "
                               "benchmarks)")
    replay_parser.add_argument("--require-power", action="store_true",
                               help="Skip rows with power_db=0 (for "
                               "calibration benchmarks)")
    replay_parser.add_argument("--dry-run", action="store_true",
                               help="Print what would be sent; open no link")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Wipe output directory if requested
    if getattr(args, 'wipe', False):
        output_dir = getattr(args, 'output', DEFAULT_OUTPUT)
        if os.path.isdir(output_dir):
            import glob
            files = glob.glob(os.path.join(output_dir, '**', '*'), recursive=True)
            files = [f for f in files if os.path.isfile(f)]
            if not files:
                print(f"Output directory is already empty: {output_dir}")
            else:
                print(f"Will delete {len(files)} files from {output_dir}/")
                answer = input("Are you sure? [y/N] ").strip().lower()
                if answer == 'y':
                    for f in files:
                        os.remove(f)
                    # Remove empty subdirectories
                    for dirpath, dirnames, filenames in os.walk(output_dir, topdown=False):
                        if dirpath != output_dir:
                            try:
                                os.rmdir(dirpath)
                            except OSError:
                                pass
                    print(f"Wiped {len(files)} files.")
                else:
                    print("Aborted.")
                    sys.exit(0)

    # Dispatch to appropriate scanner
    try:
        _dispatch_scanner(args)
    except ImportError as e:
        print(f"Error: Failed to import scanner module: {e}")
        print("Make sure all dependencies are installed: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"Error running scanner: {e}")
        sys.exit(1)


def _parse_channels(spec):
    """Parse channel spec like '1,6,11' or '1-11' into a list of ints."""
    channels = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            channels.extend(range(int(lo), int(hi) + 1))
        else:
            channels.append(int(part))
    return channels


def _start_gps(args):
    """Start GPS reader if --gps flag is set."""
    if not args.gps:
        return None
    from utils.gps import GPSReader
    port = args.gps_port
    gps = GPSReader(port=port)
    gps.start()
    import time
    time.sleep(1)  # Allow time for first fix
    lat, lon = gps.position
    if lat is not None:
        print(f"[GPS] Fix acquired: {lat:.6f}, {lon:.6f}")
    else:
        print(f"[GPS] Waiting for fix on {port}...")
    # Drop a sidecar JSON so the agent process can read the latest fix
    # without competing for the serial port. Only meaningful when this
    # scanner is being driven by an agent (which sets --output to its
    # state_dir/scanner), but always cheap to write.
    _start_gps_sidecar(gps, args.output)
    return gps


def _start_gps_sidecar(gps, output_dir):
    import json as _json
    import os as _os
    import threading as _threading
    import time as _time
    path = _os.path.join(output_dir, "gps.json")
    def _writer():
        while True:
            try:
                lat, lon = gps.position
                payload = {
                    "lat": lat,
                    "lon": lon,
                    "sats": getattr(gps, "satellites", 0) or 0,
                    "ts": _time.time(),
                }
                tmp = path + ".tmp"
                with open(tmp, "w") as f:
                    _json.dump(payload, f)
                _os.replace(tmp, path)
            except Exception:
                pass
            _time.sleep(5)
    t = _threading.Thread(target=_writer, daemon=True, name="gps-sidecar")
    t.start()


def _start_tak(args):
    """Start TAK client if --tak flag is set."""
    if not args.tak:
        return None
    from utils.tak import setup_tak
    return setup_tak(config_dir=args.tak_dir, callsign=args.device_id)


def _attach_tak(scanner, tak_client):
    """Attach TAK client to a scanner's logger."""
    if tak_client:
        scanner.logger.on_detection = tak_client.send_detection


def _check_sdr(device_index=0):
    """Pre-flight check that the RTL-SDR is responsive. Attempts USB reset on failure."""
    try:
        import utils.loader  # noqa: F401
        from rtlsdr import RtlSdr
        sdr = RtlSdr(device_index)
        sdr.sample_rate = 2.4e6
        sdr.center_freq = 100e6
        sdr.gain = 0
        sdr.read_samples(1024)
        sdr.close()
        return True
    except Exception as e:
        error_msg = str(e)
        if "LIBUSB_ERROR" in error_msg or "timed out" in error_msg.lower():
            print(f"[SDR] Device not responding: {error_msg}")
            print("[SDR] Attempting USB reset...")
            try:
                sdr.close()
            except Exception:
                pass
            if _reset_usb_sdr():
                # Retry after reset
                import time
                time.sleep(2)
                try:
                    sdr = RtlSdr(device_index)
                    sdr.sample_rate = 2.4e6
                    sdr.center_freq = 100e6
                    sdr.gain = 0
                    sdr.read_samples(1024)
                    sdr.close()
                    print("[SDR] USB reset successful, device recovered")
                    return True
                except Exception:
                    pass
            print("[SDR] USB reset failed. Try unplugging and replugging the SDR.")
            return False
        elif "No supported" in error_msg or "No RTL" in error_msg:
            print("[SDR] No RTL-SDR device found. Is it plugged in?")
            return False
        else:
            print(f"[SDR] Error: {error_msg}")
            return False


def _reset_usb_sdr():
    """Reset the RTL-SDR USB device."""
    import subprocess
    try:
        # Find RTL-SDR bus/device
        result = subprocess.run(
            ["lsusb"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "RTL2838" in line or "RTL2832" in line:
                parts = line.split()
                bus = parts[1]
                dev = parts[3].rstrip(":")
                path = f"/dev/bus/usb/{bus}/{dev}"
                import fcntl, os
                USBDEVFS_RESET = 21780
                fd = os.open(path, os.O_WRONLY)
                fcntl.ioctl(fd, USBDEVFS_RESET, 0)
                os.close(fd)
                return True
    except Exception:
        pass
    return False


def _dispatch_scanner(args):
    if args.command == "tak-enroll":
        _run_tak_enroll(args)
        return

    if args.command == "tak-test":
        _run_tak_test(args)
        return

    if args.command == "tak-clear":
        _run_tak_clear(args)
        return

    # Pre-flight SDR check for scanners that need it
    sdr_scanners = {"pmr", "fm", "keyfob", "tpms", "gsm", "lte", "adsb",
                    "ais", "pocsag", "scan", "ism", "record", "replay", "lora",
                    "jammer"}
    if args.command in sdr_scanners:
        if not _check_sdr(args.device_index):
            sys.exit(1)

    gps = _start_gps(args)
    tak_client = _start_tak(args)

    if args.command in ("triangulate", "tri"):
        from utils.triangulate import run_triangulation
        run_triangulation(args, tak_client=tak_client)
        return

    if args.command in ("calibrate", "cal"):
        from utils.calibration import run_calibration
        sys.exit(run_calibration(args))

    if args.command == "heatmap":
        from utils.heatmap import HeatmapGenerator
        gen = HeatmapGenerator(
            resolution=args.resolution,
            signal_types=args.signal_types,
        )
        for f in args.files:
            print(f"Loading: {f}")
            sub = HeatmapGenerator.from_db(
                f, resolution=args.resolution, signal_types=args.signal_types)
            # Merge grids
            for key, cell in sub._grid.items():
                gen._grid[key]["count"] += cell["count"]
                gen._grid[key]["total_power"] += cell["total_power"]
                gen._grid[key]["max_power"] = max(gen._grid[key]["max_power"], cell["max_power"])
            if sub._bounds:
                if gen._bounds is None:
                    gen._bounds = list(sub._bounds)
                else:
                    gen._bounds[0] = min(gen._bounds[0], sub._bounds[0])
                    gen._bounds[1] = min(gen._bounds[1], sub._bounds[1])
                    gen._bounds[2] = max(gen._bounds[2], sub._bounds[2])
                    gen._bounds[3] = max(gen._bounds[3], sub._bounds[3])
        kml_path = os.path.join(args.output, "heatmap.kml")
        gen.export_kml(kml_path)
        return

    if args.command in ("correlate", "corr"):
        from utils.correlator import DeviceCorrelator
        correlator = DeviceCorrelator(
            window_s=args.window, threshold=args.threshold)
        for f in args.files:
            print(f"Loading: {f}")
            correlator.load_db(f)
        correlator.print_report()
        if args.json_out:
            correlator.export_json(args.json_out)
        return

    if args.command == "pmr":
        from scanners.pmr import PMRScanner

        scanner = PMRScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            min_snr_db=args.min_snr,
            gain=args.gain,
            record_audio=not args.no_audio,
            transcribe_audio=args.transcribe,
            whisper_model=args.whisper_model,
            language=args.language,
            digital=args.digital,
            ppm=args.ppm,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.run()

    elif args.command == "keyfob":
        from scanners.keyfob import KeyfobScanner

        scanner = KeyfobScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            min_snr_db=args.min_snr,
            gain=args.gain,
            frequency=args.frequency * 1e6,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "tpms":
        from scanners.tpms import TPMSScanner

        scanner = TPMSScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            min_snr_db=args.min_snr,
            gain=args.gain,
            frequency=args.frequency * 1e6,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "gsm":
        from scanners.gsm import GSMScanner

        scanner = GSMScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            min_snr_db=args.min_snr,
            gain=args.gain,
            band=args.band,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "lte":
        from scanners.lte import LTEScanner

        scanner = LTEScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            gain=args.gain,
            bands=args.bands,
            activity_threshold_db=args.threshold,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "adsb":
        from scanners.adsb import ADSBScanner

        scanner = ADSBScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            gain=args.gain,
            use_dump1090=not args.native,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "ais":
        from scanners.ais import AISScanner

        scanner = AISScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            gain=args.gain,
            use_rtl_ais=not args.native,
            rssi_device_index=args.rssi_device_index,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command in ("pocsag", "pager"):
        from scanners.pocsag import POCSAGScanner

        scanner = POCSAGScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            frequency=args.frequency * 1e6 if args.frequency else None,
            region=args.region,
            gain=args.gain,
            use_multimon=not args.native,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "jammer":
        from scanners.jammer import (
            BandConfig, JammerScanner, DEFAULT_BANDS,
        )
        # Parse --band LABEL:CENTER_MHZ:BW_MHZ (repeatable). Fall back
        # to the module's default list if the user didn't override.
        bands = None
        if args.bands:
            bands = []
            for spec in args.bands:
                parts = spec.split(":")
                if len(parts) != 3:
                    print(f"Bad --band {spec!r}; need LABEL:CENTER_MHZ:BW_MHZ",
                          file=sys.stderr)
                    sys.exit(2)
                try:
                    label = parts[0]
                    center = float(parts[1]) * 1e6
                    bw = float(parts[2]) * 1e6
                except ValueError:
                    print(f"Bad --band {spec!r}; numeric fields expected",
                          file=sys.stderr)
                    sys.exit(2)
                bands.append(BandConfig(label=label, center_hz=center, bw_hz=bw))
        scanner = JammerScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            gain=args.gain,
            bands=bands,
            dwell_s=args.dwell_s,
            elevation_threshold_db=args.elevation_threshold_db,
            flatness_threshold=args.flatness_threshold,
            min_consec=args.min_consec,
            recalibrate=args.recalibrate,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command in ("record", "rec"):
        from scanners.recorder import SignalRecorder, list_presets

        if args.list_presets:
            list_presets()
            sys.exit(0)

        # Determine frequency
        if args.preset:
            frequency = SignalRecorder.PRESETS[args.preset]
        elif args.frequency:
            frequency = args.frequency
        else:
            print("Error: Specify --frequency or --preset")
            list_presets()
            sys.exit(1)

        recorder = SignalRecorder(
            output_dir=args.output,
            device_id=args.device_id,
            frequency=frequency,
            sample_rate=args.sample_rate,
            gain=args.gain,
            duration=args.duration,
            file_format=args.format,
            description=args.description,
        )
        recorder.record()

    elif args.command in ("replay", "analyze"):
        from scanners.recorder import SignalPlayer

        if not args.file:
            print("Error: Specify a recording file to analyze")
            sys.exit(1)

        player = SignalPlayer(args.file)

        if args.info or not any([args.spectrogram, args.spectrum, args.iq, args.convert]):
            player.info()

        if args.spectrogram:
            player.plot_spectrogram(args.save)

        if args.spectrum:
            out = args.save.replace(".", "_spectrum.") if args.save else None
            player.plot_power_spectrum(out)

        if args.iq:
            out = args.save.replace(".", "_iq.") if args.save else None
            player.plot_iq(out)

        if args.convert:
            if not args.save:
                print("Error: Specify --save with output path for conversion")
                sys.exit(1)
            player.export_to_format(args.save, args.convert)

    elif args.command == "fm":
        from scanners.fm import FMScanner, list_bands

        if args.list:
            list_bands()
            sys.exit(0)

        scanner = FMScanner(
            band=args.band,
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            gain=args.gain,
            record_audio=not args.no_audio,
            transcribe_audio=args.transcribe,
            whisper_model=args.whisper_model,
            language=args.language,
            dwell_time=args.dwell,
            channel_filter=args.channels,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.run()

    elif args.command == "scan":
        from scanners.wideband import WidebandScanner

        scanner = WidebandScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            center_freq=args.frequency * 1e6,
            gain=args.gain,
            bin_width=args.bin_width * 1e3,
            min_snr_db=args.threshold,
            classify=args.classify,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "ism":
        from scanners.ism import ISMScanner

        scanner = ISMScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            gain=args.gain,
            frequency=args.frequency * 1e6,
            hop=args.hop,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "wifi":
        from scanners.wifi import WiFiScanner
        from capture.wifi import (CHANNELS_24GHZ, CHANNELS_5GHZ_NON_DFS,
                                  CHANNELS_5GHZ_ALL)

        if args.channels:
            channels = _parse_channels(args.channels)
        elif args.band == "2.4":
            channels = CHANNELS_24GHZ
        elif args.band == "5":
            channels = CHANNELS_5GHZ_NON_DFS
        elif args.band == "all":
            channels = CHANNELS_24GHZ + CHANNELS_5GHZ_ALL
        else:
            channels = None  # WiFiCaptureSource default (2.4 + 5 non-DFS)
        scanner = WiFiScanner(
            interface=args.interface,
            channels=channels,
            hop_interval=args.hop_interval,
            min_rssi=args.min_rssi,
            output_dir=args.output,
            device_id=args.device_id,
            min_snr=args.min_snr,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command in ("bluetooth", "bt"):
        from scanners.bluetooth import BluetoothScanner

        scanner = BluetoothScanner(
            adapter=args.adapter,
            min_rssi=args.min_rssi,
            output_dir=args.output,
            device_id=args.device_id,
            min_snr=args.min_snr,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command in ("drone-video", "dv"):
        from scanners.drone_video import DroneVideoScanner

        scanner = DroneVideoScanner(
            output_dir=args.output,
            device_id=args.device_id,
            band=args.band,
            lna_gain=args.lna_gain,
            vga_gain=args.vga_gain,
            amp=args.amp,
            min_snr_db=args.min_snr,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "fpv":
        from scanners.fpv_analog import FPVAnalogScanner

        scanner = FPVAnalogScanner(
            output_dir=args.output,
            device_id=args.device_id,
            serial=args.serial,
            band=args.band,
            lna_gain=args.lna_gain,
            vga_gain=args.vga_gain,
            amp=args.amp,
        )
        if gps:
            scanner.logger.gps = gps
        scanner.scan()

    elif args.command == "lora":
        from scanners.lora import LoRaScanner

        scanner = LoRaScanner(
            output_dir=args.output,
            device_id=args.device_id,
            device_index=args.device_index,
            min_snr_db=args.min_snr,
            gain=args.gain,
            region=args.region,
        )
        if gps:
            scanner.logger.gps = gps
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "mesh":
        from scanners.meshtastic import MeshtasticScanner

        scanner = MeshtasticScanner(
            dev_path=args.port,
            output_dir=args.output,
            device_id=args.device_id,
            region=args.region,
            gps=gps,
        )
        _attach_tak(scanner, tak_client)
        scanner.scan()

    elif args.command == "server":
        _run_server(args, gps, tak_client)

    elif args.command == "web":
        from web import run_web_server
        output_dir = getattr(args, 'dir', None) or args.output
        run_web_server(output_dir, port=args.port)

    elif args.command == "agent":
        from agent.main import run as agent_run
        argv = []
        if args.config: argv += ["--config", args.config]
        if args.state_dir: argv += ["--state-dir", args.state_dir]
        if args.meshtastic_port: argv += ["--meshtastic-port", args.meshtastic_port]
        if args.agent_id: argv += ["--agent-id", args.agent_id]
        # Forward the top-level --gps-port only when --gps was explicitly set,
        # so the default "/dev/ttyACM0" doesn't silently override agent.json.
        if args.gps: argv += ["--gps-port", args.gps_port]
        return agent_run(argv)

    elif args.command == "replay-c2":
        _run_replay_c2(args)

    elif args.command == "multi":
        _run_multi(args)


def _run_tak_clear(args):
    """Delete all SDR markers from TAK Server."""
    import glob
    from utils.tak import setup_tak, delete_cot
    from utils import db as _db

    config_dir = args.tak_dir
    client = setup_tak(config_dir, callsign=args.device_id)
    if not client:
        print("[TAK] Connection failed")
        sys.exit(1)

    # Collect all UIDs from detection logs
    uids = set()
    for path in glob.glob(os.path.join(args.output, "*.db")):
        try:
            conn = _db.connect(path, readonly=True)
        except Exception:
            continue
        try:
            for r in _db.iter_detections(conn):
                row = _db.row_to_dict(r)
                sig_type = row.get("signal_type", "")
                channel = row.get("channel", "")
                freq = row.get("frequency_hz", 0) or 0
                if channel:
                    uids.add(f"sdr-{sig_type}-{channel}")
                else:
                    uids.add(f"sdr-{sig_type}-{float(freq)/1e6:.3f}")
        finally:
            conn.close()

    if not uids:
        print("[TAK] No SDR markers found in detection logs")
        client.close()
        return

    print(f"[TAK] Deleting {len(uids)} markers...")
    deleted = 0
    for uid in uids:
        cot = delete_cot(uid)
        if client._send(cot):
            deleted += 1

    print(f"[TAK] Deleted {deleted}/{len(uids)} markers")
    client.close()


def _run_tak_test(args):
    """Test TAK Server connection and send a test marker."""
    from utils.tak import setup_tak, detection_to_cot
    from utils.logger import SignalDetection

    config_dir = args.tak_dir
    print(f"[TAK] Testing connection (certs from {config_dir})")

    # Check cert files
    import glob
    for name in ["ca.pem", "client.pem", "client.key"]:
        path = os.path.join(config_dir, name)
        status = "found" if os.path.exists(path) else "MISSING"
        print(f"  {name}: {status}")

    p12_files = glob.glob(os.path.join(config_dir, "*.p12"))
    for p12 in p12_files:
        print(f"  {os.path.basename(p12)}: found")

    config_pref = os.path.join(config_dir, "config.pref")
    if os.path.exists(config_pref):
        print(f"  config.pref: found")
    else:
        host = os.environ.get("TAK_HOST", "(not set)")
        port = os.environ.get("TAK_PORT", "8089")
        print(f"  config.pref: not found")
        print(f"  TAK_HOST={host}, TAK_PORT={port}")

    print()

    client = setup_tak(config_dir, callsign=args.device_id)
    if not client:
        print("\n[TAK] Connection FAILED. Check config above.")
        sys.exit(1)

    print(f"[TAK] Connection OK")

    # Send a test marker at the GPS position or a default
    gps = None
    if args.gps:
        try:
            gps = _start_gps(args)
        except Exception:
            pass
    lat = gps.latitude if gps and hasattr(gps, 'latitude') and gps.latitude else 0.0
    lon = gps.longitude if gps and hasattr(gps, 'longitude') and gps.longitude else 0.0

    det = SignalDetection.create(
        signal_type="test",
        frequency_hz=0,
        power_db=0,
        noise_floor_db=0,
        channel="TEST",
        latitude=lat,
        longitude=lon,
        device_id=args.device_id,
    )

    cot = detection_to_cot(det, args.device_id)
    if cot:
        result = client._send(cot)
        if result:
            if lat != 0:
                print(f"[TAK] Test marker sent at {lat:.4f}, {lon:.4f}")
            else:
                print(f"[TAK] Test marker sent (no GPS — marker at 0,0)")
                print(f"[TAK] Use --gps flag to send at your position")
        else:
            print("[TAK] Send FAILED")
    else:
        print("[TAK] Could not build CoT (no GPS coordinates)")
        print("[TAK] Use --gps flag or set coordinates manually")

    client.close()


def _run_tak_enroll(args):
    """Enroll for a TAK Server client certificate."""
    import getpass
    from utils.tak import parse_tak_config, extract_ca_pem, enroll_client_cert

    config_dir = args.tak_dir
    config = parse_tak_config(config_dir)

    # Extract CA cert
    p12_path = os.path.join(config_dir, "caCert.p12")
    ca_pem = os.path.join(config_dir, "ca.pem")
    extract_ca_pem(p12_path, config.get("ca_password", "atakatak"), ca_pem)
    print(f"[TAK] CA cert: {ca_pem}")

    # Get credentials
    username = args.username or input("TAK username: ")
    password = getpass.getpass("TAK password: ")

    enrollment_port = config.get("enrollment_port", 8446)
    uid = f"sdr-{args.device_id}"

    cert_path, key_path = enroll_client_cert(
        host=config["host"],
        port=enrollment_port,
        ca_pem=ca_pem,
        username=username,
        password=password,
        cert_dir=config_dir,
        uid=uid,
    )
    print(f"[TAK] Enrolled. Cert: {cert_path}")
    print(f"[TAK] Use --tak flag to stream detections to TAK Server.")


def _run_server(args, gps, tak_client):
    """Run the central server with all captures and parsers."""
    import json as json_mod
    import signal as sig
    from scanners.server import ServerOrchestrator

    # Find config file
    config_path = args.config
    if config_path is None:
        # Default: configs/server.json relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(project_root, "configs", "server.json")

    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}")
        print("Create one or specify path: python3 sdr.py server <config.json>")
        sys.exit(1)

    with open(config_path) as f:
        config = json_mod.load(f)

    print(f"[SERVER] Config: {config_path}")
    print(f"[SERVER] Captures: {len(config.get('captures', []))}")

    # Web UI — CLI flag, explicit port, or JSON config
    web_port = None
    if getattr(args, 'web', False) or getattr(args, 'web_port', 8080) != 8080:
        web_port = getattr(args, 'web_port', 8080)
    if web_port is None:
        web_port = config.get("web_port")

    server = ServerOrchestrator(
        config=config,
        output_dir=args.output,
        gps=gps,
        tak_client=tak_client,
        use_gps=args.gps,
        gps_port=args.gps_port,
        use_tak=args.tak,
        tak_dir=args.tak_dir,
        web_port=web_port,
    )

    import threading as _threading
    _shutting_down = _threading.Event()

    def _signal_handler(signum, frame):
        if _shutting_down.is_set():
            os.write(2, b"\n[SERVER] Force-exit.\n")
            os._exit(130)
        _shutting_down.set()
        os.write(2, b"\n[SERVER] Shutdown requested - finishing cleanup (Ctrl+C again to force).\n")
        server._stop_event.set()
    sig.signal(sig.SIGINT, _signal_handler)
    sig.signal(sig.SIGTERM, _signal_handler)

    # Snapshot terminal state so we can restore it if a subprocess mangles it
    # (e.g. hcitool/hcidump disabling ISIG, which would swallow Ctrl+C).
    _tty_state = None
    try:
        import termios
        if sys.stdin.isatty():
            _tty_state = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    def _restore_tty():
        if _tty_state is not None:
            try:
                import termios
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _tty_state)
            except Exception:
                pass

    server.setup()
    try:
        server.start()
    finally:
        _restore_tty()
        server.stop()
        _restore_tty()


def _run_single_scanner(entry, output_dir, use_gps, gps_port, min_snr):
    """Run one scanner entry in a child process."""
    import signal as sig

    sig.signal(sig.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt))

    gps = None
    if use_gps:
        from utils.gps import GPSReader
        import time
        gps = GPSReader(port=gps_port)
        gps.start()
        time.sleep(1)

    name = entry.get("name", f"sdr-{entry['device_index']}")
    scanner_type = entry["type"]
    device_index = entry["device_index"]
    device_id = entry.get("device_id", f"rtlsdr-{device_index:03d}")
    gain = entry.get("gain", 40)

    if scanner_type == "pmr":
        from scanners.pmr import PMRScanner
        scanner = PMRScanner(
            output_dir=output_dir,
            device_id=device_id,
            device_index=device_index,
            min_snr_db=min_snr,
            gain=gain,
            transcribe_audio=entry.get("transcribe", False),
            whisper_model=entry.get("whisper_model", "base"),
            language=entry.get("language"),
        )
        if gps:
            scanner.logger.gps = gps
        print(f"[{name}] Starting PMR446 on device {device_index}")
        scanner.run()

    elif scanner_type == "fm":
        from scanners.fm import FMScanner
        scanner = FMScanner(
            band=entry["band"],
            output_dir=output_dir,
            device_id=device_id,
            device_index=device_index,
            gain=gain,
            dwell_time=entry.get("dwell", 5.0),
            channel_filter=entry.get("channels"),
            transcribe_audio=entry.get("transcribe", False),
            whisper_model=entry.get("whisper_model", "base"),
            language=entry.get("language"),
        )
        if gps:
            scanner.logger.gps = gps
        ch_count = len(scanner.channels)
        print(f"[{name}] Starting {entry['band']} ({ch_count} channels) on device {device_index}")
        scanner.run()


def _run_replay_c2(args):
    """Replay a recorded detection .db over the C2 mesh.

    Exercises the server ingest path (agent ->  mesh -> AgentManager ->
    SQLite) without live RF. Doubles as a deterministic triangulation
    or calibration benchmark: the same .db pumped through a stable
    mesh link should produce the same server-side artifacts every time.
    """
    from agent.replay import replay_db_to_link, iter_det_rows

    if not os.path.exists(args.db):
        print(f"error: {args.db}: not found", file=sys.stderr)
        sys.exit(2)

    # Dry-run: encode + print only. No mesh link, no config needed.
    if args.dry_run:
        from comms import protocol as P
        from agent.replay import _det_for_row
        seq = 1
        for row in iter_det_rows(args.db,
                                 require_position=args.require_position,
                                 require_power=args.require_power):
            print(_det_for_row(args.agent_id, seq, row))
            seq += 1
            if args.max_rows is not None and seq > args.max_rows:
                break
        return

    # Real mesh: pull the port + channel from agent config, same pattern
    # as `sdr.py agent`.
    from agent.config import AgentConfig
    from comms.meshlink import MeshLink
    cfg = AgentConfig.load(args.config)
    port = args.meshtastic_port or cfg.meshtastic_port
    if not port:
        print("ERROR: meshtastic_port not configured (pass --meshtastic-port "
              "or set it in agent.json)", file=sys.stderr)
        sys.exit(2)
    link = MeshLink.from_serial(port=port, channel_index=cfg.mesh_channel_index)

    print(f"Replaying {args.db} as agent={args.agent_id} "
          f"at {args.rate:.1f} DET/s (Ctrl+C to stop)")
    stop_flag = {"stop": False}
    import signal as _sig
    def _int(*_):
        stop_flag["stop"] = True
    _sig.signal(_sig.SIGINT, _int)
    _sig.signal(_sig.SIGTERM, _int)

    def _progress(seq, stats):
        # Minimal running indicator — one dot per sent DET.
        if stats.sent_dets % 10 == 0:
            print(f"  {stats.sent_dets} sent", flush=True)

    stats = replay_db_to_link(
        link=link, db_path=args.db, agent_id=args.agent_id,
        rate_per_sec=args.rate, max_rows=args.max_rows,
        skip_handshake=args.skip_handshake,
        require_position=args.require_position,
        require_power=args.require_power,
        stop=lambda: stop_flag["stop"],
        on_progress=_progress,
    )
    print(f"\nDone. sent={stats.sent_dets} of {stats.total_rows} rows"
          f" (no_pos={stats.skipped_no_position},"
          f" no_power={stats.skipped_no_power}),"
          f" hello={'sent' if stats.sent_hello else 'skipped'}")


def _run_multi(args):
    """Launch multiple scanners in parallel from a JSON config file."""
    import json
    import multiprocessing

    with open(args.config) as f:
        config = json.load(f)

    scanners = config.get("scanners", [])
    if not scanners:
        print("Error: No scanners defined in config file")
        sys.exit(1)

    print(f"[multi] Launching {len(scanners)} scanner(s)...")

    processes = []
    for entry in scanners:
        p = multiprocessing.Process(
            target=_run_single_scanner,
            args=(entry, args.output, args.gps, args.gps_port, args.min_snr),
            name=entry.get("name", f"sdr-{entry['device_index']}"),
        )
        processes.append(p)

    for p in processes:
        p.start()
        print(f"[multi] Started {p.name} (pid {p.pid})")

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\n[multi] Stopping all scanners...")
        for p in processes:
            p.terminate()
        for p in processes:
            p.join(timeout=5)
        print("[multi] All scanners stopped.")


if __name__ == "__main__":
    main()

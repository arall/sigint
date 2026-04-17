"""
Central Server Orchestrator

Runs all capture sources simultaneously — HackRF (wideband via channelizer),
RTL-SDR, BLE, WiFi — feeding all protocol parsers in parallel from a single
JSON config.

Usage:
    python3 sdr.py server                      # built-in default config
    python3 sdr.py server configs/server.json   # custom config
"""

import json
import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import SignalLogger  # noqa: E402

# Signal types that don't self-report position — candidates for node tasking
TASKABLE_SIGNALS = {
    "keyfob", "tpms", "BLE-Adv", "WiFi-Probe",
    "PMR446", "GSM-UPLINK-GSM-900", "GSM-UPLINK-GSM-850",
    "LTE-UPLINK-Band-20", "LTE-UPLINK-Band-8", "LTE-UPLINK-Band-5",
    "lora", "ISM", "pocsag", "DroneCtrl",
}

# Friendly display names for parser/scanner module identifiers.
# Used by _write_server_info() so the UI never shows raw Python names.
DISPLAY_NAMES = {
    # BLE
    # `apple_continuity` is misnamed in code — it actually tracks ALL BLE
    # devices (phones, watches, IoT, etc.) and just has extra decoding for
    # Apple Continuity messages on top. Surface it as "BLE Devices" in the UI.
    "apple_continuity": "BLE Devices",
    "remoteid_ble":     "Drone RemoteID",
    # WiFi
    "probe_request":    "WiFi Probes",
    "beacon":           "WiFi APs",
    "remoteid_wifi":    "Drone RemoteID",
    # Sub-GHz / ISM
    "keyfob":           "Keyfobs",
    "tpms":             "TPMS",
    "lora":             "LoRa",
    "elrs":             "ELRS",
    "meshtastic":       "Meshtastic",
    # Voice / FM
    "fm_voice":         "FM Voice",
    # Cellular
    "gsm":              "GSM uplink",
    "lte":              "LTE uplink",
    # Standalone scanner types (sdr.py subcommand names)
    "pmr":              "PMR446",
    "adsb":             "ADS-B",
    "ais":              "AIS",
    "ism":              "ISM (rtl_433)",
    "pocsag":           "POCSAG",
    "fm":               "FM scanner",
    "drone-video":      "Drone video",
    "fpv":              "FPV analog video",
    "scan":             "Wideband scan",
    "bluetooth":        "BLE adv",
    "bt":               "BLE adv",
    "wifi":             "WiFi probes",
    "record":           "IQ recorder",
}


def _display(name):
    """Map an internal module/scanner name to a human-readable label."""
    if not name:
        return ""
    return DISPLAY_NAMES.get(name, name)


def _display_list(names):
    """Map a list of internal names to friendly labels (in place)."""
    return [_display(n) for n in (names or [])]


# Coverage description for known standalone scanner types.
# Maps scanner_type -> (human-readable range, mode).
_STANDALONE_COVERAGE = {
    "pmr":        ("446.00625\u2013446.09375 MHz (PMR446 ch 1\u20138)", "continuous"),
    "fm":         ("depends on --band profile",                        "hopping"),
    "adsb":       ("1090 MHz (Mode S)",                                 "continuous"),
    "ais":        ("161.975 / 162.025 MHz (marine ch 87B/88B)",         "continuous"),
    "pocsag":     ("153\u2013170 MHz (POCSAG paging)",                  "continuous"),
    "ism":        ("433.92 / 868 / 915 MHz ISM",                        "continuous"),
    "lora":       ("868.1\u2013869.525 MHz (EU) or 902\u2013928 MHz (US)", "continuous"),
    "mesh":       ("868/915 MHz Meshtastic mesh (serial device)",          "passive"),
    "keyfob":     ("433.92 MHz (or 315 MHz)",                           "continuous"),
    "tpms":       ("433.92 MHz (or 315 MHz)",                           "continuous"),
    "gsm":        ("876\u2013915 MHz (GSM900 uplink)",                  "hopping"),
    "lte":        ("LTE uplink bands",                                  "hopping"),
    "drone-video":("2.4 / 5.8 GHz ISM (HackRF)",                        "continuous"),
    "fpv":        ("5.8 / 1.2 GHz FPV analog video (HackRF)",            "hopping"),
    "scan":       ("wideband energy scan",                              "hopping"),
}

# LoRa channel definitions (used when creating LoRa parsers)
LORA_CHANNELS_EU = {
    "868.1": 868.1e6, "868.3": 868.3e6,
    "868.5": 868.5e6, "869.525": 869.525e6,
}


# ANSI color codes
_C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "bg_black": "\033[40m",
}

# Signal type → color
_TYPE_COLOR = {
    "BLE-Adv": "cyan",
    "WiFi-Probe": "blue",
    "WiFi-AP": "blue",
    "lora": "magenta",
    "keyfob": "yellow",
    "tpms": "yellow",
    "ADS-B": "green",
    "PMR446": "red",
    "dPMR": "red",
    "70cm": "red",
    "MarineVHF": "red",
    "2m": "red",
    "FRS": "red",
    "FM_voice": "red",
    "RemoteID": "red",
    "DroneCtrl": "red",
    "GSM-UPLINK-GSM-900": "white",
    "GSM-UPLINK-GSM-850": "white",
    "ISM": "yellow",
    "pocsag": "white",
}


def _col(color, text):
    """Wrap text in ANSI color."""
    return f"{_C.get(color, '')}{text}{_C['reset']}"


def _extract_details(detection):
    """Extract a short detail string from detection metadata."""
    sig = detection.signal_type
    try:
        meta = json.loads(detection.metadata) if detection.metadata else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}

    if sig == "BLE-Adv":
        parts = []
        pid = meta.get("persona_id")
        if pid:
            parts.append(pid)
        name = meta.get("name")
        if name:
            parts.append(f'"{name[:20]}"')
        apple = meta.get("apple_device")
        mfr = meta.get("manufacturer")
        if apple:
            parts.append(f"[{apple}]")
        elif mfr:
            parts.append(f"[{mfr[:16]}]")
        if meta.get("randomized"):
            parts.append("rand")
        return " ".join(parts)
    elif sig == "WiFi-Probe":
        parts = []
        pid = meta.get("persona_id")
        if pid:
            parts.append(pid)
        ssids = meta.get("ssids") or []
        if isinstance(ssids, list) and ssids:
            s = ", ".join(ssids[:2])
            if len(ssids) > 2:
                s += f" +{len(ssids) - 2}"
            parts.append(f'"{s[:28]}"')
        else:
            ssid = meta.get("ssid")
            if ssid:
                parts.append(f'"{ssid[:20]}"')
        mfr = meta.get("manufacturer")
        if mfr:
            parts.append(f"[{mfr[:16]}]")
        if meta.get("randomized"):
            parts.append("rand")
        return " ".join(parts)
    elif sig == "WiFi-AP":
        ssid = meta.get("ssid") or "(hidden)"
        crypto = meta.get("crypto", "")
        bssid = meta.get("bssid", "")
        parts = [ssid[:20]]
        if bssid:
            parts.append(bssid)
        if crypto:
            parts.append(crypto)
        return " ".join(parts)
    elif sig == "ADS-B":
        cs = meta.get("callsign", "").strip()
        alt = meta.get("altitude", "")
        parts = [cs] if cs else []
        if alt:
            parts.append(f"FL{alt // 100}" if alt >= 10000 else f"{alt}ft")
        return " ".join(parts)
    elif sig == "keyfob":
        return meta.get("protocol", "")[:28]
    elif sig == "tpms":
        sid = meta.get("sensor_id", "")
        return f"ID:{sid}" if sid else ""
    elif sig == "lora":
        bw = meta.get("bandwidth_khz", "")
        return f"BW:{bw}kHz" if bw else ""
    elif sig in ("PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS", "FM_voice"):
        t = meta.get("transcript", "")
        if t:
            return f'"{t[:60]}"'
        ch = detection.channel or ""
        dur = meta.get("duration_s", "")
        return f"{ch} {dur}s" if dur else ch
    elif sig == "RemoteID":
        return meta.get("serial_number", "") or meta.get("ua_type", "")
    elif sig == "DroneCtrl":
        return meta.get("drone_type", "")
    return ""


def _create_parser(name, logger, channel_cfg=None, capture_cfg=None):
    """Factory: create a parser instance by name."""
    if name == "keyfob":
        from parsers.ook.keyfob import KeyfobParser
        freq = (channel_cfg or {}).get("freq_mhz", 433.92) * 1e6
        sr = (channel_cfg or {}).get("bandwidth_mhz", 2.0) * 1e6
        return KeyfobParser(logger=logger, sample_rate=sr, center_freq=freq)

    elif name == "tpms":
        from parsers.ook.tpms import TPMSParser
        freq = (channel_cfg or {}).get("freq_mhz", 433.92) * 1e6
        sr = (channel_cfg or {}).get("bandwidth_mhz", 2.0) * 1e6
        return TPMSParser(logger=logger, sample_rate=sr, center_freq=freq)

    elif name == "elrs":
        from parsers.lora.elrs import ELRSParser
        freq = (channel_cfg or {}).get("freq_mhz", 868.0) * 1e6
        sr = (channel_cfg or {}).get("bandwidth_mhz", 2.4) * 1e6
        return ELRSParser(logger=logger, sample_rate=sr, center_freq=freq)

    elif name == "lora":
        from parsers.lora.energy import LoRaEnergyParser
        freq = (channel_cfg or {}).get("freq_mhz", 868.3) * 1e6
        sr = (channel_cfg or {}).get("bandwidth_mhz", 2.4) * 1e6
        # HackRF has higher noise floor — require chirp signature to avoid
        # false positives from wideband noise
        cap_type = (capture_cfg or {}).get("type", "rtlsdr")
        min_chirp = 0.15 if cap_type == "hackrf" else 0.0
        min_snr = 12.0 if cap_type == "hackrf" else 8.0
        return LoRaEnergyParser(
            logger=logger, sample_rate=sr, center_freq=freq,
            channels=LORA_CHANNELS_EU, min_snr_db=min_snr,
            min_chirp_confidence=min_chirp)

    elif name == "meshtastic":
        from parsers.meshtastic.mesh import MeshtasticParser
        region = (channel_cfg or {}).get("region", "eu")
        return MeshtasticParser(
            logger=logger, capture_source=None, region=region)

    elif name == "gsm":
        from parsers.cellular.gsm import GSMBurstParser
        freq = (channel_cfg or {}).get("freq_mhz", 900.0) * 1e6
        sr = (channel_cfg or {}).get("bandwidth_mhz", 2.0) * 1e6
        return GSMBurstParser(
            logger=logger, sample_rate=sr, center_freq=freq)

    elif name == "lte":
        from parsers.cellular.lte import LTEPowerParser
        sr = (channel_cfg or {}).get("bandwidth_mhz", 2.0) * 1e6
        return LTEPowerParser(logger=logger, sample_rate=sr)

    elif name == "fm_voice":
        from parsers.fm.voice import FMVoiceParser
        freq = (channel_cfg or {}).get("freq_mhz", 446.1) * 1e6
        # Use actual decimated sample rate from channelizer, not config bandwidth
        sr = (channel_cfg or {}).get("_actual_sample_rate_hz",
              (channel_cfg or {}).get("bandwidth_mhz", 0.25) * 1e6)
        band = (channel_cfg or {}).get("band", "pmr446")
        output_dir = logger.output_dir if hasattr(logger, 'output_dir') else "output"
        return FMVoiceParser(
            logger=logger, sample_rate=sr, center_freq=freq, band=band,
            output_dir=str(output_dir),
            transcribe=(channel_cfg or {}).get("transcribe", False),
            whisper_model=(channel_cfg or {}).get("whisper_model", "base"),
            language=(channel_cfg or {}).get("language"),
        )

    elif name == "apple_continuity":
        from parsers.ble.apple_continuity import AppleContinuityParser
        output_dir = os.path.dirname(logger.output_dir) if hasattr(logger, 'output_dir') else "output"
        persona_path = os.path.join(str(logger.output_dir), "personas_bt.json")
        return AppleContinuityParser(
            logger=logger, persona_db_path=persona_path)

    elif name == "remoteid_ble":
        from parsers.ble.remote_id import RemoteIDParser
        return RemoteIDParser(logger=logger)

    elif name == "probe_request":
        from parsers.wifi.probe_request import ProbeRequestParser
        persona_path = os.path.join(str(logger.output_dir), "personas.json")
        return ProbeRequestParser(
            logger=logger, persona_db_path=persona_path)

    elif name == "beacon":
        from parsers.wifi.beacon import BeaconParser
        ap_db_path = os.path.join(str(logger.output_dir), "aps.json")
        return BeaconParser(logger=logger, ap_db_path=ap_db_path)

    elif name == "remoteid_wifi":
        from parsers.wifi.remote_id import WiFiRemoteIDParser
        return WiFiRemoteIDParser(logger=logger)

    else:
        print(f"  [WARN] Unknown parser: {name}")
        return None


class ServerOrchestrator:
    """
    Central server — runs all capture sources and parsers simultaneously.

    Reads a JSON config describing capture devices and parser assignments,
    creates the full pipeline, and runs everything in parallel threads.
    """

    def __init__(self, config, output_dir, gps=None, tak_client=None,
                 use_gps=False, gps_port="/dev/ttyACM0",
                 use_tak=False, tak_dir=None, web_port=None):
        self.config = config
        self.gps = gps
        self.tak_client = tak_client
        self._stop_event = threading.Event()
        self._threads = []
        self._captures = []
        self._channelizers = []
        self._parsers = {}  # name -> parser instance
        self._start_time = None
        self._web_port = web_port

        # Per-capture health: name -> {"status": str, "message": str, "updated": iso}
        # Status values: "pending", "running", "degraded", "failed"
        self._capture_status = {}
        self._status_lock = threading.Lock()

        # Optional Meshtastic C2 link
        self._agent_manager = None
        self._meshlink = None

        # Global flags to pass to standalone subprocesses
        self._output_dir = output_dir
        self._use_gps = use_gps
        self._gps_port = gps_port
        self._use_tak = use_tak
        self._tak_dir = tak_dir

        # Shared logger
        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="server",
            device_id="server",
            min_snr_db=0,
        )
        if gps:
            self.logger.gps = gps

        # Detection tracking — per-type state for dashboard
        self._pending_tasks = []
        self._type_counts = Counter()
        self._type_last_seen = {}   # signal_type → timestamp str
        self._type_last_snr = {}    # signal_type → float
        self._type_last_detail = {} # signal_type → detail str
        self._type_uniques = {}     # signal_type → set of unique IDs
        self._recent_events = []    # last N events for the feed
        self._max_recent = 12

        # Live heatmap — generates periodic KML overlays
        from utils.heatmap import LiveHeatmap
        self._heatmap = LiveHeatmap(
            output_dir=output_dir,
            interval_s=config.get("heatmap_interval_s", 60.0),
        )

        # Movement trail tracker — emits CoT polylines for mobile emitters
        from utils.tak import TrailTracker
        self._trail_tracker = TrailTracker(tak_client=tak_client)

        # (Correlations used to live in a long-running DeviceCorrelator
        # instance here with a 30s export loop. They're computed on
        # demand from SQL now — see web/fetch.py fetch_correlations.)
        self._persona_flush_interval = config.get(
            "persona_flush_interval_s", 30.0)
        self._last_persona_flush = 0.0

        self.logger.on_detection = self._on_detection

    def _on_detection(self, detection):
        """Called for every logged detection. Track state for dashboard."""
        sig = detection.signal_type
        self._type_counts[sig] += 1
        self._type_last_seen[sig] = detection.timestamp.split("T")[1].split(".")[0]
        if detection.snr_db > 0:
            self._type_last_snr[sig] = detection.snr_db

        detail = _extract_details(detection)
        if detail:
            self._type_last_detail[sig] = detail

        # Track unique identifiers per type
        uid = None
        try:
            meta = json.loads(detection.metadata) if detection.metadata else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}

        if sig == "BLE-Adv":
            uid = meta.get("persona_id") or detection.channel
        elif sig == "WiFi-Probe":
            uid = meta.get("persona_id") or detection.device_id
        elif sig == "WiFi-AP":
            uid = meta.get("bssid") or detection.device_id
        elif sig == "ADS-B":
            uid = meta.get("icao") or detection.channel
        elif sig == "keyfob":
            uid = meta.get("data_hex")
        elif sig == "tpms":
            uid = meta.get("sensor_id")
        elif sig == "lora":
            uid = f'{detection.frequency_hz:.0f}'
        elif sig in ("PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS"):
            uid = detection.channel

        if uid:
            if sig not in self._type_uniques:
                self._type_uniques[sig] = set()
            self._type_uniques[sig].add(uid)

        # Recent events feed
        ts = detection.timestamp.split("T")[1].split(".")[0]
        ch = detection.channel or ""
        freq = detection.frequency_hz / 1e6
        snr = detection.snr_db
        line = f"{ts}  {sig:12s} {ch:6s}  {freq:8.3f} MHz  {snr:5.1f} dB  {detail}"
        self._recent_events.append((sig, line))
        if len(self._recent_events) > self._max_recent:
            self._recent_events.pop(0)

        # Feed live heatmap and trail tracker. Correlations are computed
        # on demand from the detection log (see web/fetch.py
        # fetch_correlations) so there's no in-memory correlator to feed.
        try:
            self._heatmap.on_detection(detection)
        except Exception:
            pass
        try:
            self._trail_tracker.on_detection(detection)
        except Exception:
            pass

        if detection.signal_type in TASKABLE_SIGNALS:
            self._pending_tasks.append({
                "freq": detection.frequency_hz,
                "signal_type": detection.signal_type,
                "timestamp": detection.timestamp,
                "power_db": detection.power_db,
            })

    def setup(self):
        """Parse config and create all captures, channelizers, and parsers."""
        # Optional Meshtastic C2 link
        meshcfg = self.config.get("meshlink")
        if meshcfg:
            try:
                from comms.meshlink import MeshLink
                from server.agent_manager import AgentManager
                port = meshcfg.get("port")
                channel_index = int(meshcfg.get("channel_index", 0))
                self._meshlink = MeshLink.from_serial(port=port, channel_index=channel_index)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                agents_db = os.path.join(self._output_dir, f"agents_{ts}.db")
                state_dir = os.path.join(self._output_dir, "agents_state")
                self._agent_manager = AgentManager(
                    link=self._meshlink,
                    state_dir=state_dir,
                    detection_db_path=agents_db,
                )
                self._set_status("meshlink", "running", f"port={port} db={os.path.basename(agents_db)}")
            except Exception as e:
                self._set_status("meshlink", "failed", str(e)[:200])

        captures_cfg = self.config.get("captures", [])

        # Check if any capture needs root
        needs_root = any(e["type"] in ("ble", "wifi") for e in captures_cfg)
        if needs_root and os.geteuid() != 0:
            print("[WARN] BLE/WiFi captures require root. Run with: sudo python3 sdr.py server")
            print("       BLE/WiFi captures will be skipped.")

        for entry in captures_cfg:
            cap_type = entry["type"]
            cap_name = entry.get("name", cap_type)

            self._set_status(cap_name, "pending", "setting up")
            try:
                if cap_type == "hackrf":
                    self._setup_hackrf(entry, cap_name)
                elif cap_type == "rtlsdr":
                    self._setup_rtlsdr(entry, cap_name)
                elif cap_type == "rtlsdr_sweep":
                    self._setup_rtlsdr_sweep(entry, cap_name)
                elif cap_type == "ble":
                    self._setup_ble(entry, cap_name)
                elif cap_type == "wifi":
                    self._setup_wifi(entry, cap_name)
                elif cap_type == "standalone":
                    self._setup_standalone(entry, cap_name)
                else:
                    print(f"  [WARN] Unknown capture type: {cap_type}")
                    self._set_status(cap_name, "failed", f"unknown capture type: {cap_type}")
            except Exception as e:
                print(f"  [ERROR] Failed to setup '{cap_name}': {e}")
                print(f"          Skipping this capture, others will continue.")
                self._set_status(cap_name, "failed", f"setup error: {e}")

        print(f"\n[SERVER] {len(self._captures)} capture sources, "
              f"{len(self._parsers)} parsers configured")

        # Pre-build compact capture summary lines for the live dashboard
        self._capture_lines = []
        for entry in self.config.get("captures", []):
            cap_name = entry.get("name", entry["type"])
            cap_type = entry["type"]
            if cap_type == "hackrf":
                serial = entry.get("serial", "")
                short_serial = serial[-8:] if serial else "?"
                center = entry.get("center_freq_mhz", 0)
                sr = entry.get("sample_rate_mhz", 20)
                channels = entry.get("channels", [])
                # HackRF + channelizer = simultaneous wideband
                device_str = f"HackRF {short_serial}"
                band_str = f"{center} MHz / {sr} MS/s"
                mode = _col("green", "simultaneous") if channels else "wideband"
                self._capture_lines.append(
                    f"  {_col('bold', cap_name):<20s} {_col('dim', device_str):<26s} "
                    f"{band_str:<22s} {mode}")
                for ch in channels:
                    parsers = ", ".join(ch.get("parsers", []))
                    bw = ch.get("bandwidth_mhz", 2.0)
                    self._capture_lines.append(
                        f"  {'':<20s} {_col('dim', '└'):<14s} "
                        f"{ch.get('name', '')} @ {ch['freq_mhz']} MHz "
                        f"{_col('dim', f'({bw} MHz)'):<18s} "
                        f"{_col('dim', parsers)}")
            elif cap_type == "rtlsdr":
                dev_idx = entry.get("device_index", 0)
                freq = entry.get("center_freq_mhz", 0)
                parsers = ", ".join(entry.get("parsers", []))
                device_str = f"RTL-SDR #{dev_idx}"
                self._capture_lines.append(
                    f"  {_col('bold', cap_name):<20s} {_col('dim', device_str):<26s} "
                    f"{freq} MHz  {_col('dim', parsers)}")
            elif cap_type == "rtlsdr_sweep":
                dev_idx = entry.get("device_index", 0)
                start = entry.get("band_start_mhz", 0)
                end = entry.get("band_end_mhz", 0)
                parsers = ", ".join(entry.get("parsers", []))
                device_str = f"RTL-SDR #{dev_idx}"
                mode = _col("yellow", "hopping")
                self._capture_lines.append(
                    f"  {_col('bold', cap_name):<20s} {_col('dim', device_str):<26s} "
                    f"{start}-{end} MHz  {mode}  {_col('dim', parsers)}")
            elif cap_type == "ble":
                adapter = entry.get("adapter", "hci1")
                parsers = ", ".join(entry.get("parsers", []))
                self._capture_lines.append(
                    f"  {_col('bold', cap_name):<20s} {_col('dim', adapter):<26s} "
                    f"2.4 GHz  {_col('dim', parsers)}")
            elif cap_type == "wifi":
                iface = entry.get("interface", "wlan1")
                chs = entry.get("channels", [])
                parsers = ", ".join(entry.get("parsers", []))
                mode = _col("yellow", "hopping") if len(chs) > 1 else ""
                ch_str = f"ch {','.join(str(c) for c in chs)}" if chs else ""
                self._capture_lines.append(
                    f"  {_col('bold', cap_name):<20s} {_col('dim', iface):<26s} "
                    f"2.4 GHz {ch_str}  {mode}  {_col('dim', parsers)}")
            elif cap_type == "standalone":
                scanner = entry.get("scanner_type", "?")
                dev_idx = entry.get("device_index")
                args = " ".join(entry.get("args", []))
                device_str = f"RTL-SDR #{dev_idx}" if dev_idx is not None else ""
                desc = f"{scanner} {args}".strip()
                self._capture_lines.append(
                    f"  {_col('bold', cap_name):<20s} {_col('dim', device_str):<26s} "
                    f"{desc}")

        # Write structured capture info for the web UI
        self._write_server_info()

    def _set_status(self, name, status, message=""):
        """Update per-capture health status and surface it to terminal + web."""
        prev = None
        with self._status_lock:
            prev = self._capture_status.get(name, {}).get("status")
            self._capture_status[name] = {
                "status": status,
                "message": message,
                "updated": datetime.now().isoformat(),
            }
        # Only print on transitions so the terminal isn't spammed
        if prev != status:
            color = {
                "running": "green",
                "pending": "dim",
                "degraded": "yellow",
                "failed": "red",
            }.get(status, "white")
            badge = _col(color, f"[{status.upper()}]")
            line = f"  {badge} {name}"
            if message:
                line += f": {message}"
            try:
                print(line)
            except Exception:
                pass
        # Re-publish server_info.json so the web UI picks up the change
        try:
            self._write_server_info()
        except Exception:
            pass

    def _write_server_info(self):
        """Write server_info.json to output dir for the standalone web UI."""
        captures = []
        for entry in self.config.get("captures", []):
            cap = {
                "name": entry.get("name", entry["type"]),
                "type": entry["type"],
            }
            cap_type = entry["type"]
            if cap_type == "hackrf":
                serial = entry.get("serial", "")
                cap["device"] = f"HackRF {serial[-8:]}" if serial else "HackRF"
                center = entry.get("center_freq_mhz", 0)
                sr = entry.get("sample_rate_mhz", 20)
                cap["center_freq_mhz"] = center
                cap["sample_rate_mhz"] = sr
                cap["lna_gain"] = entry.get("lna_gain")
                cap["vga_gain"] = entry.get("vga_gain")
                cap["transcribe"] = entry.get("transcribe", False)
                cap["whisper_model"] = entry.get("whisper_model", "base")
                cap["language"] = entry.get("language")
                cap["coverage"] = f"{center - sr/2:.2f}\u2013{center + sr/2:.2f} MHz"
                cap["mode"] = "continuous"
                cap["channels"] = []
                for ch in entry.get("channels", []):
                    cap["channels"].append({
                        "name": ch.get("name", ""),
                        "freq_mhz": ch.get("freq_mhz"),
                        "bandwidth_mhz": ch.get("bandwidth_mhz"),
                        "band": ch.get("band"),
                        "parsers": _display_list(ch.get("parsers", [])),
                        "transcribe": ch.get("transcribe", False),
                    })
            elif cap_type == "rtlsdr":
                cap["device"] = f"RTL-SDR #{entry.get('device_index', 0)}"
                center = entry.get("center_freq_mhz", 0)
                sr = entry.get("sample_rate_mhz", 2.4)
                cap["center_freq_mhz"] = center
                cap["sample_rate_mhz"] = sr
                cap["parsers"] = _display_list(entry.get("parsers", []))
                cap["coverage"] = f"{center - sr/2:.4f}\u2013{center + sr/2:.4f} MHz"
                cap["mode"] = "continuous"
            elif cap_type == "rtlsdr_sweep":
                cap["device"] = f"RTL-SDR #{entry.get('device_index', 0)}"
                cap["band_start_mhz"] = entry.get("band_start_mhz", 0)
                cap["band_end_mhz"] = entry.get("band_end_mhz", 0)
                cap["mode"] = "hopping"
                cap["parsers"] = _display_list(entry.get("parsers", []))
                cap["coverage"] = f"{cap['band_start_mhz']}\u2013{cap['band_end_mhz']} MHz"
            elif cap_type == "ble":
                cap["device"] = entry.get("adapter", "hci1")
                cap["parsers"] = _display_list(entry.get("parsers", []))
                # BLE adv listens on all 3 primary advertising channels simultaneously
                cap["coverage"] = "2402 / 2426 / 2480 MHz (adv ch 37/38/39)"
                cap["mode"] = "passive"
            elif cap_type == "wifi":
                cap["device"] = entry.get("interface", "wlan1")
                # Resolve channel list (custom > band preset > default)
                try:
                    from capture.wifi import (
                        CHANNELS_24GHZ, CHANNELS_5GHZ_NON_DFS,
                        CHANNELS_5GHZ_ALL, CHANNELS_DEFAULT, channel_to_freq)
                except Exception:
                    CHANNELS_24GHZ = [1, 6, 11]
                    CHANNELS_5GHZ_NON_DFS = [36, 40, 44, 48, 149, 153, 157, 161, 165]
                    CHANNELS_5GHZ_ALL = CHANNELS_5GHZ_NON_DFS
                    CHANNELS_DEFAULT = CHANNELS_24GHZ + CHANNELS_5GHZ_NON_DFS
                    channel_to_freq = lambda ch: None  # noqa: E731
                band = entry.get("band")
                chs = entry.get("channels")
                if not chs:
                    if band == "2.4":
                        chs = CHANNELS_24GHZ
                    elif band == "5":
                        chs = CHANNELS_5GHZ_NON_DFS
                    elif band == "all":
                        chs = CHANNELS_24GHZ + CHANNELS_5GHZ_ALL
                    else:
                        chs = CHANNELS_DEFAULT
                cap["channels"] = chs
                cap["band"] = band
                cap["parsers"] = _display_list(entry.get("parsers", []))
                # Per-channel sub-list with MHz so the UI can render uniformly
                cap["channel_list"] = [
                    {"name": str(c), "freq_mhz": channel_to_freq(c)}
                    for c in chs
                ]
                # Build coverage string: channel count + freq sample
                freqs = [channel_to_freq(c) for c in chs]
                freqs = [f for f in freqs if f]
                if freqs:
                    cap["coverage"] = (
                        f"{len(chs)} channels "
                        f"({min(freqs)}\u2013{max(freqs)} MHz)")
                else:
                    cap["coverage"] = f"{len(chs)} channels"
                cap["mode"] = "hopping" if len(chs) > 1 else "continuous"
            elif cap_type == "standalone":
                cap["device"] = f"RTL-SDR #{entry.get('device_index', '')}" if entry.get("device_index") is not None else ""
                scanner = entry.get("scanner_type", "")
                cap["scanner_type"] = scanner
                cap["scanner_label"] = _display(scanner)
                cap["args"] = entry.get("args", [])
                info = _STANDALONE_COVERAGE.get(scanner)
                if info:
                    cap["coverage"] = info[0]
                    cap["mode"] = info[1]

            # Attach health status (status / message / updated)
            with self._status_lock:
                status_entry = self._capture_status.get(cap["name"])
            if status_entry:
                cap["status"] = status_entry.get("status", "pending")
                cap["status_message"] = status_entry.get("message", "")
                cap["status_updated"] = status_entry.get("updated", "")
            else:
                cap["status"] = "pending"
                cap["status_message"] = ""
            captures.append(cap)

        info = {
            "started": datetime.now().isoformat(),
            "captures": captures,
        }

        if self._agent_manager is not None:
            info["agents"] = {
                "approved": self._agent_manager.approved(),
                "pending": self._agent_manager.pending(),
                "info": {aid: self._agent_manager.agent_info(aid)
                         for aid in self._agent_manager.approved()},
            }

        info_path = os.path.join(self._output_dir, "server_info.json")
        try:
            with open(info_path, "w") as f:
                json.dump(info, f, indent=2)
        except Exception:
            pass

    def _setup_hackrf(self, entry, name):
        """Setup HackRF + channelizer + parsers."""
        from capture.hackrf_iq import HackRFCaptureSource
        from capture.channelizer import Channelizer

        center = entry["center_freq_mhz"] * 1e6
        sr = entry.get("sample_rate_mhz", 20) * 1e6

        capture = HackRFCaptureSource(
            center_freq=center,
            sample_rate=sr,
            lna_gain=entry.get("lna_gain", 32),
            vga_gain=entry.get("vga_gain", 40),
            amp_enable=entry.get("amp_enable", False),
            serial=entry.get("serial"),
            ppm=entry.get("ppm", 0),
        )

        # Use actual_center_freq (PPM-corrected) so channelizer frequency
        # shifts align with real signal positions, not commanded frequency
        channelizer = Channelizer(
            center_freq=capture.actual_center_freq, sample_rate=sr)

        channels = list(entry.get("channels", []))

        # Auto-discover voice bands that fit within this HackRF's bandwidth
        channels = self._auto_discover_voice_bands(entry, channels, center, sr)
        # Store effective channels so the dashboard can display them
        entry["channels"] = channels

        for ch in channels:
            ch_freq = ch["freq_mhz"] * 1e6
            ch_bw = ch.get("bandwidth_mhz", 2.0) * 1e6
            # Actual output rate after integer decimation (may differ from ch_bw)
            decimation = max(1, int(sr / ch_bw))
            ch_sr = sr / decimation

            # Store actual decimated rate so parser factories use it
            ch["_actual_sample_rate_hz"] = ch_sr

            # Create parsers for this channel
            ch_parsers = []
            for parser_name in ch.get("parsers", []):
                parser = _create_parser(parser_name, self.logger, ch, entry)
                if parser:
                    ch_parsers.append(parser)
                    self._parsers[f"{name}.{ch['name']}.{parser_name}"] = parser

            if ch_parsers:
                # All parsers on this channel get the same narrowband IQ
                def make_callback(parsers):
                    def cb(samples):
                        for p in parsers:
                            try:
                                p.handle_frame(samples)
                            except Exception:
                                pass
                    return cb

                channelizer.add_channel(
                    name=ch.get("name", str(ch_freq)),
                    freq_hz=ch_freq,
                    bandwidth_hz=ch_bw,
                    output_sample_rate=ch_sr,
                    callback=make_callback(ch_parsers),
                )

        capture.add_parser(channelizer.handle_frame)
        self._captures.append((name, capture))
        self._channelizers.append(channelizer)
        print(f"  [+] HackRF '{name}': {center/1e6:.1f} MHz, "
              f"{sr/1e6:.0f} MS/s, {len(channels)} channels")

    @staticmethod
    def _auto_discover_voice_bands(entry, channels, center, sr):
        """Add fm_voice channels for band profiles that fit within bandwidth.

        Skips bands already covered by an explicit channel config (matched by
        the 'band' field).  Returns the extended channel list.
        """
        from parsers.fm.voice import BAND_PROFILES

        half_bw = sr / 2
        # Bands already configured explicitly
        configured_bands = {ch.get("band") for ch in channels if ch.get("band")}

        # Global voice settings from capture entry
        transcribe = entry.get("transcribe", False)
        whisper_model = entry.get("whisper_model", "base")
        language = entry.get("language")

        for band_key, profile in BAND_PROFILES.items():
            if band_key in configured_bands:
                continue

            # Check if ALL channels in this band fall within capture range
            freqs = list(profile["channels"].values())
            ch_bw = profile["channel_bw"]
            if not freqs:
                continue

            min_freq = min(freqs) - ch_bw / 2
            max_freq = max(freqs) + ch_bw / 2

            if min_freq < center - half_bw or max_freq > center + half_bw:
                continue

            # All channels fit — create a channelizer channel centered on
            # the band with enough bandwidth to cover all channels + margin
            band_center = (min_freq + max_freq) / 2
            band_span = max_freq - min_freq
            # Round up bandwidth to give filter room (min 25 kHz margin each side)
            band_bw = band_span + max(ch_bw * 4, 50000)

            ch_cfg = {
                "name": band_key,
                "freq_mhz": band_center / 1e6,
                "bandwidth_mhz": band_bw / 1e6,
                "band": band_key,
                "transcribe": transcribe,
                "whisper_model": whisper_model,
                "parsers": ["fm_voice"],
            }
            if language:
                ch_cfg["language"] = language

            channels.append(ch_cfg)
            print(f"  [auto] voice band '{profile['name']}': "
                  f"{min_freq/1e6:.3f}-{max_freq/1e6:.3f} MHz "
                  f"({len(freqs)} channels)")

        return channels

    def _setup_rtlsdr(self, entry, name):
        """Setup RTL-SDR fixed-frequency capture + parsers."""
        from capture.rtlsdr_iq import RTLSDRCaptureSource

        freq = entry["center_freq_mhz"] * 1e6
        sr = entry.get("sample_rate_mhz", 2.4) * 1e6

        capture = RTLSDRCaptureSource(
            center_freq=freq,
            sample_rate=sr,
            gain=entry.get("gain", 40),
            device_index=entry.get("device_index", 0),
        )

        for parser_name in entry.get("parsers", []):
            parser = _create_parser(parser_name, self.logger, entry, entry)
            if parser:
                capture.add_parser(parser.handle_frame)
                self._parsers[f"{name}.{parser_name}"] = parser

        self._captures.append((name, capture))
        print(f"  [+] RTL-SDR '{name}': {freq/1e6:.1f} MHz, "
              f"{sr/1e6:.1f} MS/s")

    def _setup_rtlsdr_sweep(self, entry, name):
        """Setup RTL-SDR sweep capture + parsers."""
        from capture.rtlsdr_sweep import RTLSDRSweepCaptureSource

        band_start = entry["band_start_mhz"] * 1e6
        band_end = entry["band_end_mhz"] * 1e6
        sr = entry.get("sample_rate_mhz", 2.0) * 1e6

        capture = RTLSDRSweepCaptureSource(
            band_start=band_start,
            band_end=band_end,
            sample_rate=sr,
            gain=entry.get("gain", 40),
            device_index=entry.get("device_index", 0),
        )

        for parser_name in entry.get("parsers", []):
            parser = _create_parser(parser_name, self.logger, entry, entry)
            if parser:
                capture.add_parser(parser.handle_frame)
                self._parsers[f"{name}.{parser_name}"] = parser

        self._captures.append((name, capture))
        print(f"  [+] RTL-SDR sweep '{name}': "
              f"{band_start/1e6:.1f}-{band_end/1e6:.1f} MHz")

    def _setup_ble(self, entry, name):
        """Setup BLE capture + parsers."""
        from capture.ble import BLECaptureSource

        capture = BLECaptureSource(
            adapter=entry.get("adapter", "hci1"))

        for parser_name in entry.get("parsers", []):
            parser = _create_parser(parser_name, self.logger, entry, entry)
            if parser:
                capture.add_parser(parser.handle_frame)
                self._parsers[f"{name}.{parser_name}"] = parser

        self._captures.append((name, capture))
        print(f"  [+] BLE '{name}': adapter {entry.get('adapter', 'hci1')}")

    def _setup_wifi(self, entry, name):
        """Setup WiFi capture + parsers."""
        from capture.wifi import WiFiCaptureSource

        channels = entry.get("channels")  # None = WiFiCaptureSource default (2.4+5 GHz)
        capture = WiFiCaptureSource(
            interface=entry.get("interface", "wlan1"),
            channels=channels,
            hop_interval=entry.get("hop_interval", 0.3),
        )

        for parser_name in entry.get("parsers", []):
            parser = _create_parser(parser_name, self.logger, entry, entry)
            if parser:
                capture.add_parser(parser.handle_frame)
                self._parsers[f"{name}.{parser_name}"] = parser

        self._captures.append((name, capture))
        print(f"  [+] WiFi '{name}': interface {entry.get('interface', 'wlan1')}")

    def _setup_standalone(self, entry, name):
        """Setup standalone scanner as subprocess (ADS-B, AIS, PMR, etc.)."""
        # Standalone scanners run as child processes — not threaded captures.
        # We store their config and launch them separately.
        self._captures.append((name, ("standalone", entry)))
        print(f"  [+] Standalone '{name}': type={entry.get('scanner_type', '?')}")

    @staticmethod
    def _check_conflicting_processes():
        """Check for existing SDR processes that might hold device handles."""
        import subprocess as sp
        # Collect our own PID + all ancestor PIDs to exclude
        own_pids = set()
        pid = os.getpid()
        while pid > 1:
            own_pids.add(str(pid))
            try:
                with open(f'/proc/{pid}/stat') as f:
                    pid = int(f.read().split(')')[1].split()[1])
            except Exception:
                break

        conflicts = []
        for pattern, desc in [
            ("hackrf_transfer", "HackRF"),
            ("sdr.py.*server", "SDR server"),
            ("rtl_", "RTL-SDR"),
            ("hcitool.*lescan", "BLE scanner"),
            ("hcidump", "BLE dump"),
        ]:
            try:
                result = sp.run(
                    ["pgrep", "-fa", pattern],
                    capture_output=True, text=True, timeout=3)
                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    pid_str = line.split()[0]
                    if pid_str not in own_pids:
                        conflicts.append((desc, line.strip()))
            except Exception:
                pass
        return conflicts

    def start(self):
        """Launch all captures in threads and run status display."""
        self._start_time = time.time()

        # Check for conflicting processes that might hold device handles
        conflicts = self._check_conflicting_processes()
        if conflicts:
            print(f"\n{_col('red', '[ERROR]')} Conflicting processes detected:")
            for desc, proc in conflicts:
                print(f"  {_col('yellow', desc)}: {proc}")
            print(f"\nKill them first: sudo kill -9 {' '.join(p.split()[0] for _, p in conflicts)}")
            print(f"Or run: sudo pkill -f 'sdr.py.*server'")
            sys.exit(1)

        # When the server runs as root (it has to, for WiFi monitor mode /
        # BLE HCI), the output directory and every file in it end up owned
        # by root with mode 0o644 / 0o755. A non-root user trying to read
        # those files from the web UI can read the main .db bytes but
        # can't create the `-shm` sidecar SQLite needs for WAL reader
        # coordination — every readonly open fails with "attempt to write
        # a readonly database". Unblock that by making the output dir
        # world-writable and setting a permissive umask so new files land
        # 0o666. Use umask instead of per-file chmods so it covers audio
        # WAVs, JSON sidecars, and files created by standalone subprocesses.
        try:
            os.umask(0o002)
            os.makedirs(str(self.logger.output_dir), exist_ok=True)
            os.chmod(str(self.logger.output_dir), 0o777)
        except OSError as e:
            print(f"  [WARN] Could not chmod output dir: {e}")

        db_path = self.logger.start()

        print(f"\n{_col('bold', '[SERVER]')} Logging to: {_col('dim', db_path)}")
        print(f"{_col('bold', '[SERVER]')} Starting {len(self._captures)} capture sources...\n")

        # Redirect parser/capture stdout to log file to keep terminal clean
        log_path = os.path.join(str(self.logger.output_dir), "server_console.log")
        self._log_file = open(log_path, "w")
        self._real_stdout = sys.stdout
        # Give threads 2 seconds to print startup messages, then redirect
        import builtins
        self._original_print = builtins.print
        self._print_lock = threading.Lock()

        def _server_print(*args, **kwargs):
            """Thread-safe print: [SERVER] goes to terminal, rest to log file."""
            with self._print_lock:
                msg = " ".join(str(a) for a in args)
                if msg.startswith("[SERVER]") or msg.startswith("  Started:"):
                    self._original_print(*args, **kwargs)
                else:
                    kwargs["file"] = self._log_file
                    self._original_print(*args, **kwargs)
                    self._log_file.flush()

        for name, capture in self._captures:
            if isinstance(capture, tuple) and capture[0] == "standalone":
                # Launch standalone scanner as subprocess
                t = threading.Thread(
                    target=self._run_standalone,
                    args=(name, capture[1]),
                    daemon=True,
                    name=f"server-{name}",
                )
            else:
                t = threading.Thread(
                    target=self._run_capture,
                    args=(name, capture),
                    daemon=True,
                    name=f"server-{name}",
                )
            self._threads.append(t)
            t.start()
            print(f"  Started: {name} (thread {t.name})")

        # Start web UI if configured
        if self._web_port:
            from web import start_web_server_background
            start_web_server_background(
                self._output_dir,
                port=self._web_port,
                agent_manager=self._agent_manager,
            )
            print(f"  [+] Web UI: http://0.0.0.0:{self._web_port}/")

        print(f"\n{_col('bold', '[SERVER]')} All captures running. {_col('dim', 'Ctrl+C to stop.')}")
        print(f"{_col('bold', '[SERVER]')} Parser output → {_col('dim', log_path)}\n")

        # Redirect parser prints to log file (keep terminal clean)
        builtins.print = _server_print

        # Dashboard display loop
        try:
            while not self._stop_event.is_set():
                self._poll_capture_health()
                self._flush_personas_if_due()
                self._print_dashboard()
                self._stop_event.wait(2.0)
        except KeyboardInterrupt:
            pass

    def _flush_personas_if_due(self):
        """Periodically persist BLE/WiFi personas so the web UI can load them."""
        if self._persona_flush_interval <= 0:
            return
        now = time.time()
        if now - self._last_persona_flush < self._persona_flush_interval:
            return
        self._last_persona_flush = now
        for parser in self._parsers.values():
            flush = getattr(parser, "flush", None)
            if callable(flush):
                try:
                    flush()
                except Exception:
                    pass

    def _poll_capture_health(self):
        """Check capture sources for degraded state (e.g. HackRF queue drops)."""
        for name, capture in self._captures:
            if isinstance(capture, tuple):
                continue  # standalone — status tracked by _run_standalone
            # HackRF queue drops → degraded
            drops = getattr(capture, "_drop_count", 0)
            if drops:
                last_drops = getattr(capture, "_reported_drops", 0)
                if drops != last_drops:
                    self._set_status(
                        name, "degraded",
                        f"dropped {drops} blocks (sample rate too high?)")
                    capture._reported_drops = drops

    def stop(self):
        """Signal all captures to stop and wait for threads."""
        # Restore normal print
        import builtins
        if hasattr(self, '_original_print'):
            builtins.print = self._original_print
        if hasattr(self, '_log_file') and self._log_file:
            self._log_file.close()

        print("\n[SERVER] Stopping all captures...")
        self._stop_event.set()

        for name, capture in self._captures:
            if not isinstance(capture, tuple):
                capture.stop()

        for t in self._threads:
            t.join(timeout=2)

        # Flush channelizer coalesce buffers so parsers see final samples
        for ch in self._channelizers:
            try:
                ch.flush()
            except Exception:
                pass

        # Shutdown parsers (persist state)
        for name, parser in self._parsers.items():
            try:
                parser.shutdown()
            except Exception:
                pass

        # Export final heatmap (correlations are computed on demand from SQL)
        try:
            self._heatmap.flush()
        except Exception:
            pass

        total = self.logger.stop()
        uptime = timedelta(seconds=int(time.time() - self._start_time))
        print(f"\n[SERVER] Stopped. Uptime: {uptime}. Total detections: {total}.")

    def _run_capture(self, name, capture):
        """Run a capture source (blocking) with auto-restart on failure."""
        backoff = 5
        attempt = 0
        while not self._stop_event.is_set():
            attempt += 1
            # Reset transient state so a retried capture starts clean.
            capture._process = None
            capture._drop_count = 0
            capture._reported_drops = 0
            if hasattr(capture, "_drop_first"):
                del capture._drop_first

            status_msg = "" if attempt == 1 else f"restart #{attempt - 1}"
            self._set_status(name, "running", status_msg)
            try:
                capture.start()
                reason = "capture ended unexpectedly"
            except Exception as e:
                if self._stop_event.is_set():
                    return
                print(f"\n  [ERROR] {name}: {e}")
                reason = str(e)[:180]

            if self._stop_event.is_set():
                return
            self._set_status(name, "failed", f"{reason} — retrying in {backoff}s")
            if self._stop_event.wait(backoff):
                return
            backoff = min(backoff * 2, 60)

    def _run_standalone(self, name, entry):
        """Run a standalone scanner in a subprocess."""
        import subprocess as sp

        scanner_type = entry.get("scanner_type", "")
        # sdr.py lives in src/, one level up from scanners/
        src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sdr_py = os.path.join(src_dir, "sdr.py")

        # Build command: python sdr.py [global args] scanner_type [scanner args]
        cmd = [sys.executable, sdr_py]

        # Global args (before subcommand)
        if entry.get("device_index") is not None:
            cmd.extend(["--device-index", str(entry["device_index"])])
        if self._output_dir:
            cmd.extend(["--output", str(self._output_dir)])
        if self._use_gps:
            cmd.append("--gps")
            if self._gps_port != "/dev/ttyACM0":
                cmd.extend(["--gps-port", self._gps_port])
        if self._use_tak:
            cmd.append("--tak")
            if self._tak_dir:
                cmd.extend(["--tak-dir", self._tak_dir])

        # Subcommand
        cmd.append(scanner_type)

        # Scanner-specific args (after subcommand)
        if entry.get("gain") is not None:
            cmd.extend(["--gain", str(entry["gain"])])

        # Extra args from config (e.g. ["--transcribe", "--digital", "marine"])
        extra_args = entry.get("args", [])
        cmd.extend(extra_args)

        try:
            proc = sp.Popen(
                cmd, cwd=src_dir,
                stdin=sp.DEVNULL,
                stdout=sp.PIPE, stderr=sp.PIPE,
                start_new_session=True,
            )
            print(f"  [standalone] {name}: pid {proc.pid}, cmd: {' '.join(cmd)}")
            self._set_status(name, "running", f"pid {proc.pid}")

            # Drain stdout/stderr in background threads. If we don't,
            # the subprocess will block on print() once its 64KB pipe
            # buffer fills, freezing the SDR pipeline.
            stderr_tail = []   # rolling buffer of last few stderr lines
            log_dir = self._output_dir or "."
            try:
                stdout_log = open(
                    os.path.join(str(log_dir), f"standalone_{name}.log"),
                    "ab", buffering=0)
            except Exception:
                stdout_log = None

            def _drain(stream, tail=None):
                try:
                    for chunk in iter(lambda: stream.read(4096), b""):
                        if not chunk:
                            break
                        if stdout_log is not None:
                            try:
                                stdout_log.write(chunk)
                            except Exception:
                                pass
                        if tail is not None:
                            try:
                                text = chunk.decode("utf-8", errors="replace")
                                for line in text.splitlines():
                                    line = line.strip()
                                    if line:
                                        tail.append(line)
                                if len(tail) > 20:
                                    del tail[:-20]
                            except Exception:
                                pass
                except Exception:
                    pass

            threading.Thread(
                target=_drain, args=(proc.stdout,), daemon=True,
                name=f"drain-{name}-out").start()
            threading.Thread(
                target=_drain, args=(proc.stderr, stderr_tail), daemon=True,
                name=f"drain-{name}-err").start()

            while not self._stop_event.is_set():
                if proc.poll() is not None:
                    # Process exited — drain threads will catch any final output
                    err = "\n".join(stderr_tail).strip()
                    if proc.returncode != 0:
                        last = stderr_tail[-1] if stderr_tail else f"exit {proc.returncode}"
                        print(f"\n  [ERROR] standalone {name} exited ({proc.returncode}): {err[:200]}")
                        self._set_status(name, "failed", last[:200])
                    else:
                        self._set_status(name, "failed", "exited cleanly")
                    break
                self._stop_event.wait(1.0)

            if stdout_log is not None:
                try:
                    stdout_log.close()
                except Exception:
                    pass

            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except sp.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        except Exception as e:
            if not self._stop_event.is_set():
                print(f"\n  [ERROR] standalone {name}: {e}")
                self._set_status(name, "failed", str(e)[:200])

    def _write_line(self, text=""):
        """Write a line directly to the real stdout, bypassing print override.
        Uses \\r\\n because subprocesses (hcitool/hcidump) may set raw terminal mode
        where \\n alone doesn't return the cursor to column 0."""
        self._real_stdout.write(text + "\r\n")

    def _print_dashboard(self):
        """Redraw the full-screen dashboard."""
        uptime = timedelta(seconds=int(time.time() - self._start_time))
        now = datetime.now().strftime("%H:%M:%S")
        total = self.logger.detection_count

        # GPS
        gps_str = _col("dim", "no fix")
        if self.gps:
            lat, lon = self.gps.position
            if lat and lon:
                gps_str = f"{lat:.4f}, {lon:.4f}"

        # DB path
        db_name = os.path.basename(str(self.logger.db_path or ""))

        # Determine active signal types — show configured + any with detections
        # Order: voice first (red), then rf (yellow/magenta/green), then wireless (cyan/blue)
        type_order = [
            "PMR446", "dPMR", "70cm", "MarineVHF", "2m", "FRS",
            "RemoteID", "DroneCtrl",
            "keyfob", "tpms", "lora", "ISM",
            "ADS-B",
            "GSM-UPLINK-GSM-900", "GSM-UPLINK-GSM-850",
            "pocsag",
            "BLE-Adv", "WiFi-Probe",
        ]
        # Add any types that appeared but aren't in the ordered list
        seen_types = set(self._type_counts.keys())
        all_types = []
        for t in type_order:
            if t in seen_types:
                all_types.append(t)
        for t in sorted(seen_types - set(type_order)):
            all_types.append(t)

        # Build table rows
        rows = []
        for sig in all_types:
            count = self._type_counts.get(sig, 0)
            color = _TYPE_COLOR.get(sig, "white")
            last = self._type_last_seen.get(sig, "")
            snr = self._type_last_snr.get(sig)
            snr_str = f"{snr:5.1f} dB" if snr is not None else _col("dim", "   -   ")
            detail = self._type_last_detail.get(sig, "")
            uniq = len(self._type_uniques.get(sig, set()))
            uniq_str = f"({uniq})" if uniq > 1 else ""

            name_str = _col(color, f"{sig:15s}")
            count_str = f"{count:6d}"
            last_str = last if last else _col("dim", "   -   ")
            detail_str = f"{detail[:62]}" if detail else ""

            rows.append(
                f"  {name_str} {count_str} {uniq_str:>5s}  "
                f"{last_str}  {snr_str}  {detail_str}"
            )

        # Recent events
        recent_lines = []
        for sig, line in self._recent_events:
            color = _TYPE_COLOR.get(sig, "white")
            # Color just the signal type portion
            parts = line.split(sig, 1)
            if len(parts) == 2:
                colored = f"{parts[0]}{_col(color, sig)}{parts[1]}"
            else:
                colored = line
            recent_lines.append(f"  {colored}")

        sep = _col("dim", "-" * 110)
        w = self._write_line

        with self._print_lock:
            # Clear screen via ANSI escape (no subprocess, works in raw tty mode)
            self._real_stdout.write("\033[2J\033[H")

            w(sep)
            w(f"  {_col('bold', 'SDR SERVER')}  {now}  |  "
              f"up {_col('bold', str(uptime))}  |  "
              f"{_col('bold', str(total))} detections  |  "
              f"GPS: {gps_str}")
            w(f"  {_col('dim', db_name)}")
            w(sep)

            # Configured captures
            w(f"  {_col('bold', 'Listening')}")
            w(sep)
            for cl in self._capture_lines:
                w(cl)
            w(sep)

            # Table header
            w(f"  {_col('bold', 'Signal'):>24s} {_col('bold', ' Count'):>6s} "
              f"{_col('bold', 'Uniq'):>5s}  "
              f"{_col('bold', 'Last'):>8s}  {_col('bold', '    SNR'):>8s}  "
              f"{_col('bold', 'Details')}")
            w(sep)

            # Table rows
            if rows:
                for row in rows:
                    w(row)
            else:
                w(f"  {_col('dim', 'waiting for detections...')}")

            # Recent events
            w(sep)
            w(f"  {_col('bold', 'Recent')}")
            w(sep)
            if recent_lines:
                for line in recent_lines:
                    w(line)
            else:
                w(f"  {_col('dim', '...')}")

            w(sep)
            w(f"  {_col('dim', 'Ctrl+C to stop')}")
            self._real_stdout.flush()

"""
HackRF capture worker — runs one `type: "hackrf"` server capture in its
own process.

The server spawns `sdr.py hackrf-worker --name <name> --entry <json>`
per HackRF so the channelizer + parsers get their own interpreter (and
GIL) instead of sharing the server process with BLE, WiFi, the web UI
and every other HackRF. Detections are written to the unified DB here,
then relayed to the server over stdout so its dashboard, heatmap and
trail tracker still see them.

stdout protocol (one line each, prefix may land mid-line if another
thread's print() interleaves — the server searches for it):
    @@hackrf-det <SignalDetection as JSON>
    @@hackrf-drops <cumulative dropped block count>
"""

import json
import os
import signal as sig
import sys
import threading
from dataclasses import asdict

from utils.logger import SignalDetection, SignalLogger

DET_PREFIX = "@@hackrf-det "
DROPS_PREFIX = "@@hackrf-drops "

# How often the watchdog reports drops and checks the server is alive
_WATCH_INTERVAL_S = 2.0

_out_lock = threading.Lock()


def _emit(line):
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def encode_detection(detection):
    return DET_PREFIX + json.dumps(asdict(detection))


def parse_line(line):
    """Decode a worker stdout line.

    Returns ("det", SignalDetection), ("drops", int), or None for
    ordinary log output.
    """
    for prefix in (DET_PREFIX, DROPS_PREFIX):
        idx = line.find(prefix)
        if idx < 0:
            continue
        payload = line[idx + len(prefix):].strip()
        try:
            if prefix == DET_PREFIX:
                return ("det", SignalDetection(**json.loads(payload)))
            return ("drops", int(payload))
        except (ValueError, TypeError):
            return None
    return None


def run_worker(entry, name, output_dir, gps=None):
    """Build and run the HackRF pipeline. Returns a process exit code."""
    from scanners.server import build_hackrf_pipeline

    # stdout is a pipe to the server — block buffering would hold parser
    # output (and hackrf_<name>.log) back until exit.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    logger = SignalLogger(
        output_dir=output_dir,
        signal_type="hackrf",
        device_id="server",
        min_snr_db=0,
        session_label=f"hackrf:{name}",
    )
    logger.gps = gps
    logger.on_detection = lambda d: _emit(encode_detection(d))

    try:
        capture, channelizer, parsers = build_hackrf_pipeline(
            entry, name, logger)
    except Exception as e:
        sys.stderr.write(f"setup error: {type(e).__name__}: {e}\n")
        return 1

    stopping = threading.Event()

    def _stop(signum, frame):
        stopping.set()
        capture.stop()
    sig.signal(sig.SIGTERM, _stop)
    sig.signal(sig.SIGINT, _stop)

    # The server starts us in our own session, so a hard-killed server
    # would leave us holding the HackRF. Exit when we get reparented.
    parent_pid = os.getppid()

    def _watch():
        reported = 0
        while not stopping.wait(_WATCH_INTERVAL_S):
            if os.getppid() != parent_pid:
                stopping.set()
                capture.stop()
                return
            drops = getattr(capture, "_drop_count", 0)
            if drops != reported:
                _emit(f"{DROPS_PREFIX}{drops}")
                reported = drops

    threading.Thread(target=_watch, daemon=True, name="hackrf-watch").start()

    logger.start()
    error = None
    try:
        capture.start()
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    finally:
        was_stopped = stopping.is_set()
        stopping.set()
        try:
            channelizer.flush()
        except Exception:
            pass
        for parser in parsers.values():
            try:
                parser.shutdown()
            except Exception:
                pass
        logger.stop()

    if was_stopped and error is None:
        return 0
    sys.stderr.write((error or "capture ended unexpectedly") + "\n")
    return 1

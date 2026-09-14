"""
Tests for running server HackRF captures in a subprocess.

Covers:
  - stdout protocol: detection + drop lines round-trip, tolerate a
    prefix interleaved mid-line, ignore ordinary log output
  - server setup defaults `type: "hackrf"` to a worker subprocess and
    `"subprocess": false` keeps the in-process pipeline
  - server supervisor: builds the worker command, relays detections to
    the dashboard, marks the capture degraded on drops
  - run_worker: relays logged detections, stamps session ended_at, exits
    non-zero when the capture ends on its own
  - `sdr.py hackrf-worker` CLI reports setup errors on stderr

Run:
    python3 tests/sw/test_hackrf_worker.py
"""

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src')
sys.path.insert(0, SRC)


def _entry(**overrides):
    entry = {
        "name": "uhf",
        "type": "hackrf",
        "center_freq_mhz": 434,
        "sample_rate_mhz": 4,
        "channels": [
            {"name": "keyfob", "freq_mhz": 433.92, "bandwidth_mhz": 2,
             "parsers": ["keyfob"]},
        ],
    }
    entry.update(overrides)
    return entry


def _detection():
    from utils.logger import SignalDetection
    return SignalDetection.create(
        signal_type="keyfob", frequency_hz=433.92e6,
        power_db=-40.0, noise_floor_db=-60.0, channel="keyfob",
        metadata=json.dumps({"data_hex": "abcd"}))


def _server(tmp, entry):
    from scanners.server import ServerOrchestrator
    return ServerOrchestrator(config={"captures": [entry]}, output_dir=tmp)


def test_detection_line_round_trips():
    from scanners import hackrf_worker
    det = _detection()
    line = hackrf_worker.encode_detection(det) + "\n"
    assert hackrf_worker.parse_line(line) == ("det", det)
    # Another thread's print() can land in front of our line
    assert hackrf_worker.parse_line("[WARN] partial" + line) == ("det", det)


def test_drops_and_plain_lines():
    from scanners import hackrf_worker
    assert hackrf_worker.parse_line("@@hackrf-drops 42\n") == ("drops", 42)
    assert hackrf_worker.parse_line("[*] Channel 'keyfob': 433.920 MHz\n") is None
    assert hackrf_worker.parse_line("@@hackrf-det {not json\n") is None


def test_setup_defaults_to_subprocess():
    with tempfile.TemporaryDirectory() as tmp:
        entry = _entry()
        srv = _server(tmp, entry)
        srv._setup_hackrf(entry, "uhf")
        assert srv._captures == [("uhf", ("hackrf", entry))]
        assert srv._parsers == {}
        # Auto-discovered voice bands are resolved for the dashboard
        assert any(ch.get("parsers") == ["fm_voice"] for ch in entry["channels"])


def test_setup_in_process_opt_out():
    from capture.hackrf_iq import HackRFCaptureSource
    with tempfile.TemporaryDirectory() as tmp:
        entry = _entry(subprocess=False)
        srv = _server(tmp, entry)
        srv._setup_hackrf(entry, "uhf")
        name, capture = srv._captures[0]
        assert isinstance(capture, HackRFCaptureSource)
        assert "uhf.keyfob.keyfob" in srv._parsers
        assert len(srv._channelizers) == 1


def test_supervisor_relays_worker_output():
    with tempfile.TemporaryDirectory() as tmp:
        entry = _entry()
        srv = _server(tmp, entry)
        srv._use_gps = True
        seen = {}
        srv._supervise_subprocess = (
            lambda name, cmd, log_name, on_line=None:
            seen.update(cmd=cmd, log_name=log_name, on_line=on_line))
        srv._run_hackrf_worker("uhf", entry)

        cmd = seen["cmd"]
        i = cmd.index("hackrf-worker")
        assert cmd[i + 1:i + 3] == ["--name", "uhf"]
        assert json.loads(cmd[cmd.index("--entry") + 1]) == entry
        assert cmd[cmd.index("--gps-port") + 1] == "sidecar"
        assert seen["log_name"] == "hackrf_uhf.log"

        from scanners import hackrf_worker
        on_line = seen["on_line"]
        assert on_line(hackrf_worker.encode_detection(_detection()) + "\n")
        assert srv._type_counts["keyfob"] == 1
        assert srv._type_uniques["keyfob"] == {"abcd"}

        assert on_line("@@hackrf-drops 0\n")
        assert "uhf" not in srv._capture_status
        assert on_line("@@hackrf-drops 7\n")
        assert srv._capture_status["uhf"]["status"] == "degraded"
        assert not on_line("regular log line\n")


def test_run_worker_relays_and_closes_session():
    from capture.hackrf_iq import HackRFCaptureSource
    from scanners import hackrf_worker, server

    orig_build = server.build_hackrf_pipeline
    orig_start = HackRFCaptureSource.start
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    loggers = []

    def spy_build(entry, name, logger):
        loggers.append(logger)
        return orig_build(entry, name, logger)

    def fake_start(self):
        # A capture that logs one detection, then loses the device
        loggers[0].log(_detection())

    server.build_hackrf_pipeline = spy_build
    HackRFCaptureSource.start = fake_start
    out, err = io.StringIO(), io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sys.stdout, sys.stderr = out, err
            try:
                rc = hackrf_worker.run_worker(_entry(), "uhf", tmp)
            finally:
                sys.stdout, sys.stderr = orig_stdout, orig_stderr

            assert rc == 1
            assert "capture ended unexpectedly" in err.getvalue()
            dets = [hackrf_worker.parse_line(l) for l in out.getvalue().splitlines()]
            dets = [d for d in dets if d and d[0] == "det"]
            assert len(dets) == 1 and dets[0][1].signal_type == "keyfob"

            conn = sqlite3.connect(os.path.join(tmp, "detections.db"))
            kind, label, ended = conn.execute(
                "SELECT kind, label, ended_at FROM sessions").fetchone()
            n = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
            conn.close()
            assert (kind, label) == ("scanner:hackrf", "hackrf:uhf")
            assert ended is not None
            assert n == 1
    finally:
        HackRFCaptureSource.start = orig_start
        server.build_hackrf_pipeline = orig_build


def test_cli_reports_setup_error():
    bad = _entry(channels=[{"name": "far", "freq_mhz": 900, "parsers": ["keyfob"]}])
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(
            [sys.executable, os.path.join(SRC, "sdr.py"), "--output", tmp,
             "hackrf-worker", "--name", "uhf", "--entry", json.dumps(bad)],
            capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "outside capture window" in r.stderr


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
            traceback.print_exc()
        except Exception as e:
            failures += 1
            print(f"  ERR  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(0 if failures == 0 else 1)

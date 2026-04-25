"""Tests for MeshtasticGpsReader and write_gps_sidecar."""
import json
import os
import sys
import threading
import time

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from utils.gps import MeshtasticGpsReader, write_gps_sidecar  # noqa: E402


def test_reader_picks_up_provider_value():
    state = {"v": (None, None, 0)}
    r = MeshtasticGpsReader(provider=lambda: state["v"], poll_interval=0.05)
    r.start()
    try:
        time.sleep(0.1)
        assert r.position == (None, None)
        state["v"] = (42.5, 1.5, 7)
        deadline = time.time() + 1.0
        while r.position == (None, None) and time.time() < deadline:
            time.sleep(0.05)
        assert r.position == (42.5, 1.5)
        assert r.satellites == 7
    finally:
        r.stop()


def test_reader_swallows_provider_exceptions():
    def boom():
        raise RuntimeError("backend down")
    r = MeshtasticGpsReader(provider=boom, poll_interval=0.05)
    r.start()
    try:
        time.sleep(0.15)
        # No fix, no crash.
        assert r.position == (None, None)
        assert r.satellites == 0
    finally:
        r.stop()


def test_sidecar_writer_only_writes_when_fix_present(tmp_path):
    state = {"v": (None, None, 0)}
    r = MeshtasticGpsReader(provider=lambda: state["v"], poll_interval=0.05)
    r.start()
    sidecar = str(tmp_path / "scanner" / "gps.json")
    stop = threading.Event()
    try:
        write_gps_sidecar(r, sidecar, interval=0.05, stop_event=stop)
        time.sleep(0.2)
        assert not os.path.exists(sidecar), "no fix yet — sidecar should not exist"
        state["v"] = (42.5095, 1.5359, 9)
        deadline = time.time() + 1.5
        while not os.path.exists(sidecar) and time.time() < deadline:
            time.sleep(0.05)
        assert os.path.exists(sidecar)
        with open(sidecar) as f:
            payload = json.load(f)
        assert payload["lat"] == 42.5095
        assert payload["lon"] == 1.5359
        assert payload["sats"] == 9
        assert "ts" in payload
    finally:
        stop.set()
        r.stop()


def test_meshlink_get_local_position_handles_missing_backend_method():
    """MeshLink with a bare backend (e.g. tests' FakeBackend) should return
    (None, None, 0) rather than raising — keeps test backends light."""
    from comms.meshlink import MeshLink

    class BareBackend:
        def set_callback(self, cb):
            pass
        def send_text(self, t):
            pass

    link = MeshLink(backend=BareBackend())
    assert link.get_local_position() == (None, None, 0)

"""
Tests for agent/replay.py — the recorded-db replay path used by
`sdr.py replay-c2`.

Covers:
  - iter_det_rows shape + filters (require_position / require_power)
  - _det_for_row encodes a wire-compatible DET line with all fields
  - replay_db_to_link happy path: sends HELLO then a DET per row
  - --skip-handshake suppresses HELLO
  - require_position / require_power skip rows but still count them in stats
  - max_rows caps DETs
  - stop callback ends the loop
  - Link-send failure doesn't burn through seq (row gets skipped, next
    row retries with the same seq)
  - Round-trip: DET produced by the replayer decodes back through
    comms.protocol to the same agent_id + type + freq on the server

Run:
    python3 tests/sw/test_replay_c2.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


class FakeLink:
    def __init__(self, fail_first=False):
        self.sent = []
        self._fail_first = fail_first
        self._fail_count = 0

    def send(self, text):
        if self._fail_first and self._fail_count == 0:
            self._fail_count += 1
            raise RuntimeError("simulated mesh failure")
        self.sent.append(text)


def _populate_db(path, rows):
    """rows: list of (signal_type, channel, freq_hz, power_db, lat, lon)."""
    from utils import db as _db
    from utils.logger import SignalDetection
    conn = _db.connect(path)
    for sig, ch, freq, power, lat, lon in rows:
        det = SignalDetection.create(
            signal_type=sig, frequency_hz=freq,
            power_db=power, noise_floor_db=-95,
            channel=ch, latitude=lat, longitude=lon,
            device_id="test",
        )
        _db.insert_detection(conn, det)
    conn.close()


def test_iter_det_rows_yields_all_rows_in_id_order():
    from agent.replay import iter_det_rows
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cap.db")
    _populate_db(path, [
        ("keyfob", "CH1", 433.92e6, -60, 42.51, 1.53),
        ("keyfob", "CH1", 433.92e6, -62, 42.51, 1.53),
        ("keyfob", "CH2", 433.92e6, -58, 42.51, 1.53),
    ])
    rows = list(iter_det_rows(path))
    assert len(rows) == 3
    assert [r["channel"] for r in rows] == ["CH1", "CH1", "CH2"]


def test_iter_det_rows_require_position_filters_rows_without_gps():
    from agent.replay import iter_det_rows
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cap.db")
    _populate_db(path, [
        ("keyfob", "CH1", 433.92e6, -60, 42.51, 1.53),
        ("keyfob", "CH2", 433.92e6, -60, None, None),
    ])
    rows = list(iter_det_rows(path, require_position=True))
    assert len(rows) == 1 and rows[0]["channel"] == "CH1"


def test_iter_det_rows_require_power_filters_zero_power():
    from agent.replay import iter_det_rows
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cap.db")
    _populate_db(path, [
        ("ADS-B", "ABC", 1090e6, 0, 42.6, 1.55),   # zero power — dropped
        ("ADS-B", "DEF", 1090e6, -22, 42.6, 1.55),
    ])
    rows = list(iter_det_rows(path, require_power=True))
    assert [r["channel"] for r in rows] == ["DEF"]


def test_replay_sends_hello_then_dets_and_counts():
    from agent.replay import replay_db_to_link
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cap.db")
    _populate_db(path, [
        ("keyfob", "CH1", 433.92e6, -60, 42.51, 1.53),
        ("keyfob", "CH1", 433.92e6, -58, 42.51, 1.53),
    ])
    link = FakeLink()
    stats = replay_db_to_link(
        link=link, db_path=path, agent_id="N99",
        rate_per_sec=10.0, sleep=lambda _: None,
    )
    assert stats.sent_hello
    assert stats.sent_dets == 2
    assert stats.total_rows == 2
    # First frame is HELLO, then two DETs, each with matching agent id
    # and monotonic seq.
    assert link.sent[0].startswith("HELLO|N99|")
    dets = [t for t in link.sent if t.startswith("DET|N99|")]
    assert len(dets) == 2
    seqs = [int(d.split("|")[2]) for d in dets]
    assert seqs == [1, 2]


def test_skip_handshake_does_not_send_hello():
    from agent.replay import replay_db_to_link
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cap.db")
    _populate_db(path, [("keyfob", "CH1", 433.92e6, -60, 42.51, 1.53)])
    link = FakeLink()
    stats = replay_db_to_link(
        link=link, db_path=path, agent_id="N99",
        rate_per_sec=10.0, sleep=lambda _: None,
        skip_handshake=True,
    )
    assert not stats.sent_hello
    assert all(not t.startswith("HELLO|") for t in link.sent)
    assert stats.sent_dets == 1


def test_max_rows_caps_dets_sent():
    from agent.replay import replay_db_to_link
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cap.db")
    _populate_db(path, [
        ("keyfob", "CH1", 433.92e6, -60, 42.51, 1.53),
        ("keyfob", "CH1", 433.92e6, -58, 42.51, 1.53),
        ("keyfob", "CH1", 433.92e6, -55, 42.51, 1.53),
    ])
    link = FakeLink()
    stats = replay_db_to_link(
        link=link, db_path=path, agent_id="N99",
        rate_per_sec=10.0, sleep=lambda _: None,
        max_rows=2, skip_handshake=True,
    )
    assert stats.sent_dets == 2


def test_stop_callback_aborts_early():
    from agent.replay import replay_db_to_link
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cap.db")
    _populate_db(path, [("keyfob", "CH" + str(i), 433.92e6, -60, 42.51, 1.53)
                        for i in range(10)])
    link = FakeLink()
    count = [0]
    def stop():
        count[0] += 1
        return count[0] > 3  # first 3 rows pass, then abort
    stats = replay_db_to_link(
        link=link, db_path=path, agent_id="N99",
        rate_per_sec=10.0, sleep=lambda _: None,
        stop=stop, skip_handshake=True,
    )
    assert stats.sent_dets == 3


def test_link_send_failure_does_not_burn_seq():
    """If `link.send` raises mid-replay, the failed row is dropped but
    the next row retries with the same seq so the server sees a
    contiguous stream."""
    from agent.replay import replay_db_to_link
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "cap.db")
    _populate_db(path, [
        ("keyfob", "CH1", 433.92e6, -60, 42.51, 1.53),
        ("keyfob", "CH2", 433.92e6, -58, 42.51, 1.53),
        ("keyfob", "CH3", 433.92e6, -55, 42.51, 1.53),
    ])
    link = FakeLink(fail_first=True)
    stats = replay_db_to_link(
        link=link, db_path=path, agent_id="N99",
        rate_per_sec=10.0, sleep=lambda _: None,
        skip_handshake=True,
    )
    # HELLO was skipped, DET#1 failed silently, DET#2 and DET#3 succeeded.
    dets = [t for t in link.sent if t.startswith("DET|N99|")]
    assert len(dets) == 2
    seqs = [int(d.split("|")[2]) for d in dets]
    assert seqs == [1, 2]   # no gap — failed send didn't burn seq 1


def test_det_roundtrips_through_comms_protocol():
    """A DET encoded by the replayer should decode cleanly server-side."""
    from agent.replay import _det_for_row
    from comms import protocol as P
    row = {
        "ts_epoch": 1700000000.0,
        "signal_type": "keyfob",
        "frequency_hz": 433.92e6,
        "power_db": -65.0,
        "snr_db": 30.0,
        "channel": "CH1",
        "latitude": 42.51,
        "longitude": 1.53,
        "metadata": "",
    }
    wire = _det_for_row("N99", 7, row)
    msg = P.decode(wire)
    assert msg.tag == "DET"
    assert msg.agent_id == "N99"
    assert msg.seq == 7
    assert msg.fields["type"] == "keyfob"
    assert abs(float(msg.fields["freq_mhz"]) - 433.92) < 0.001
    assert int(msg.fields["rssi"]) == -65


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
        except Exception as e:
            failures += 1
            print(f"  ERR  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(0 if failures == 0 else 1)

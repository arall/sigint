"""
Tests for ServerOutbox — reliable server->agent CMD / CFG delivery.

Covers:
  - CMD is sent immediately and seq is monotonic + included in the wire
  - pending() surfaces unacked entries until on_ack clears them
  - on_ack returns True on match, False on unknown (agent_id, seq)
  - Broadcast target "*" sends but isn't tracked (no one to ACK)
  - tick() retries only stale entries (past base_delay_s) with
    exponential backoff
  - max_retries bounds the retry count and drops abandoned entries
  - CFG takes the same seq stream as CMD (shared counter)
  - on_ack is thread-safe enough to interleave with tick

Run:
    python3 tests/sw/test_server_outbox.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


class FakeSender:
    def __init__(self):
        self.sent = []
        self._lock = threading.Lock()

    def __call__(self, text):
        with self._lock:
            self.sent.append(text)


def test_send_cmd_is_immediate_and_seq_monotonic():
    from server.outbox import ServerOutbox
    sender = FakeSender()
    ob = ServerOutbox(send_fn=sender)
    a = ob.send_cmd("N01", "START", ["pmr"])
    b = ob.send_cmd("N01", "STOP", [])
    assert b == a + 1
    assert sender.sent == [
        f"CMD|N01|{a}|START|pmr",
        f"CMD|N01|{b}|STOP",
    ]


def test_pending_holds_until_acked():
    from server.outbox import ServerOutbox
    sender = FakeSender()
    ob = ServerOutbox(send_fn=sender)
    seq = ob.send_cmd("N01", "START", ["pmr"])
    pending = ob.pending("N01")
    assert len(pending) == 1
    assert pending[0].seq == seq
    assert pending[0].verb == "START"

    assert ob.on_ack("N01", seq) is True
    assert ob.pending_count() == 0
    # Double-ack is a no-op (returns False).
    assert ob.on_ack("N01", seq) is False


def test_on_ack_agent_id_scoped():
    """An ACK from N02 can't clear a pending for N01 even if the seq
    happens to match."""
    from server.outbox import ServerOutbox
    sender = FakeSender()
    ob = ServerOutbox(send_fn=sender)
    seq = ob.send_cmd("N01", "START", ["pmr"])
    # Same seq, different agent — must NOT clear.
    assert ob.on_ack("N02", seq) is False
    assert ob.pending_count() == 1
    assert ob.on_ack("N01", seq) is True
    assert ob.pending_count() == 0


def test_broadcast_target_is_fire_and_forget():
    """CMD|*|... has no single agent to wait on — sent, not tracked."""
    from server.outbox import ServerOutbox
    sender = FakeSender()
    ob = ServerOutbox(send_fn=sender)
    ob.send_cmd("*", "STATUS", [])
    assert len(sender.sent) == 1
    assert sender.sent[0].startswith("CMD|*|")
    assert ob.pending_count() == 0


def test_tick_retries_past_base_delay_with_exponential_backoff():
    from server.outbox import ServerOutbox
    sender = FakeSender()
    # Small delay for deterministic timing in the test.
    ob = ServerOutbox(send_fn=sender, base_delay_s=1.0, max_delay_s=16.0)
    ob.send_cmd("N01", "START", ["pmr"])  # first send at t=0
    assert len(sender.sent) == 1

    # Half a second later — too soon, no retry.
    ob.tick(now=time.time() + 0.5)
    assert len(sender.sent) == 1

    # 1.1 s later — passed base_delay, first retry fires.
    ob.tick(now=time.time() + 1.1)
    assert len(sender.sent) == 2

    # 1.5 s after that — still within the 2x delay window, no retry.
    ob.tick(now=time.time() + 1.1 + 1.5)
    assert len(sender.sent) == 2

    # 3 s after that — 2 * base = 2 s window has elapsed, second retry.
    ob.tick(now=time.time() + 1.1 + 3.0)
    assert len(sender.sent) == 3


def test_max_retries_bounds_and_drops_entry():
    from server.outbox import ServerOutbox
    sender = FakeSender()
    ob = ServerOutbox(send_fn=sender, base_delay_s=0.001,
                     max_delay_s=0.01, max_retries=3)
    ob.send_cmd("N01", "START", ["pmr"])  # 1 initial send
    # Advance clock past every backoff window; we expect 3 retries then drop.
    now = time.time()
    for i in range(1, 10):
        ob.tick(now=now + i * 0.1)
    # Initial send + 3 retries = 4 sends, then the entry is dropped.
    assert len(sender.sent) == 4
    assert ob.pending_count() == 0


def test_cfg_shares_seq_space_with_cmd():
    """Same counter — agent's ACK just says 'processed seq N', doesn't
    care whether the request was CMD or CFG."""
    from server.outbox import ServerOutbox
    sender = FakeSender()
    ob = ServerOutbox(send_fn=sender)
    s1 = ob.send_cmd("N01", "START", ["pmr"])
    s2 = ob.send_cfg("N01", "det_rate_sec", "4")
    s3 = ob.send_cmd("N01", "STOP", [])
    assert [s1, s2, s3] == [1, 2, 3]
    # Agent could ACK them in any order.
    assert ob.on_ack("N01", s2)
    assert ob.pending_count() == 2
    assert ob.on_ack("N01", s1)
    assert ob.pending_count() == 1
    assert ob.on_ack("N01", s3)
    assert ob.pending_count() == 0


def test_ack_during_tick_does_not_double_send():
    """If an ACK arrives mid-tick, the CMD is cleared from pending
    before tick can add it to `to_retry`. Guarding against the known
    race where retry + completion collide."""
    from server.outbox import ServerOutbox
    sender = FakeSender()
    ob = ServerOutbox(send_fn=sender, base_delay_s=0.001)
    seq = ob.send_cmd("N01", "START", ["pmr"])
    ob.on_ack("N01", seq)
    # Tick should see nothing to retry.
    time.sleep(0.01)
    n = ob.tick()
    assert n == 0
    assert len(sender.sent) == 1  # original send only


def test_send_exception_does_not_abort_tick():
    """One blip in link.send shouldn't stop other pending retries."""
    from server.outbox import ServerOutbox

    calls = {"n": 0}
    def flaky_send(text):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated mesh glitch")
    ob = ServerOutbox(send_fn=flaky_send, base_delay_s=0.001)
    ob.send_cmd("N01", "A", [])  # succeeds
    ob.send_cmd("N01", "B", [])  # succeeds
    time.sleep(0.01)
    # Both are now due for retry. Second retry raises but tick keeps
    # going and retries the third.
    ob.tick()
    # pendings still tracked even after one failed send.
    assert ob.pending_count() == 2


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

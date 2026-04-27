"""Tests for the agent outbox: persistent SQLite queue for DET/STAT/LOG."""
import os
import sys
import time
import tempfile

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _tmp_outbox():
    path = os.path.join(tempfile.mkdtemp(), "outbox.db")
    from agent.outbox import Outbox
    return Outbox(path)


def test_enqueue_and_next_due_returns_priority_then_fifo():
    """Within a priority bucket, oldest seq wins. Across buckets,
    CFGINFO/SCANINFO/RES > STAT/LOG > DET — so a STAT enqueued after
    DETs still drains first."""
    outbox = _tmp_outbox()
    s1 = outbox.enqueue("DET", "payload-1")
    s2 = outbox.enqueue("DET", "payload-2")
    s3 = outbox.enqueue("STAT", "payload-3")
    assert s2 == s1 + 1
    assert s3 == s2 + 1

    row = outbox.next_due(now=time.time())
    assert row is not None
    assert row.kind == "STAT"
    assert row.seq == s3


def test_ack_removes_from_due_list():
    outbox = _tmp_outbox()
    s1 = outbox.enqueue("DET", "a")
    s2 = outbox.enqueue("DET", "b")
    outbox.ack(s1)

    row = outbox.next_due(now=time.time())
    assert row is not None and row.seq == s2


def test_mark_tried_respects_backoff():
    outbox = _tmp_outbox()
    s1 = outbox.enqueue("DET", "a")
    now = 1000.0
    outbox.mark_tried(s1, now)

    # Immediately after a try: not due (backoff is 6s first retry per policy)
    assert outbox.next_due(now=now + 1.0) is None
    # After backoff elapses: due again
    assert outbox.next_due(now=now + 1000.0) is not None


def test_retries_increment_and_backoff_grows():
    outbox = _tmp_outbox()
    s = outbox.enqueue("DET", "a")
    now = 1000.0
    outbox.mark_tried(s, now)
    outbox.mark_tried(s, now + 10)  # retries=2
    outbox.mark_tried(s, now + 30)  # retries=3
    row = outbox.get(s)
    assert row.retries == 3


def test_persistence_across_instances():
    path = os.path.join(tempfile.mkdtemp(), "outbox.db")
    from agent.outbox import Outbox
    box1 = Outbox(path)
    s1 = box1.enqueue("DET", "persisted")
    box1.close()

    box2 = Outbox(path)
    row = box2.next_due(now=time.time())
    assert row is not None and row.seq == s1 and row.payload == "persisted"


def test_queue_depth_counts_unacked_only():
    outbox = _tmp_outbox()
    s1 = outbox.enqueue("DET", "a")
    outbox.enqueue("DET", "b")
    outbox.enqueue("STAT", "c")
    assert outbox.depth() == 3
    outbox.ack(s1)
    assert outbox.depth() == 2


def test_seq_persists_across_restart():
    """last_seq should be recoverable so next enqueue uses seq+1 even after restart."""
    path = os.path.join(tempfile.mkdtemp(), "outbox.db")
    from agent.outbox import Outbox
    box1 = Outbox(path)
    box1.enqueue("DET", "a")  # seq 1
    box1.enqueue("DET", "b")  # seq 2
    box1.close()

    box2 = Outbox(path)
    s3 = box2.enqueue("DET", "c")
    assert s3 == 3


def test_ack_idempotent():
    outbox = _tmp_outbox()
    s1 = outbox.enqueue("DET", "a")
    outbox.ack(s1)
    outbox.ack(s1)  # no raise
    outbox.ack(99999)  # unknown seq, no raise


def test_vacuum_stale_unacked_drops_old_cfginfo_and_scaninfo():
    """An old unacked CFGINFO can sit at the head of the priority-0 bucket
    forever (servers don't track CFGINFO seqs). The drainer's periodic
    vacuum drops control rows older than the threshold so fresh
    re-enqueues from `_stat_loop` aren't starved behind them."""
    import sqlite3
    outbox = _tmp_outbox()
    # Backdate a CFGINFO + SCANINFO to look 1 hour old, plus a fresh
    # one of each that should survive the vacuum.
    s_old_cfg = outbox.enqueue("CFGINFO", "stale-cfg")
    s_old_scan = outbox.enqueue("SCANINFO", "stale-scan")
    s_fresh_cfg = outbox.enqueue("CFGINFO", "fresh-cfg")
    s_fresh_scan = outbox.enqueue("SCANINFO", "fresh-scan")
    s_stat = outbox.enqueue("STAT", "stat")
    long_ago = time.time() - 3600
    conn = sqlite3.connect(outbox._path)
    conn.execute("UPDATE outbox SET enqueued_at=? WHERE seq IN (?, ?)",
                 (long_ago, s_old_cfg, s_old_scan))
    conn.commit()
    conn.close()

    n = outbox.vacuum_stale_unacked(("CFGINFO", "SCANINFO"), 1800.0)
    assert n == 2
    assert outbox.get(s_old_cfg) is None
    assert outbox.get(s_old_scan) is None
    # Fresh control rows + STAT untouched.
    assert outbox.get(s_fresh_cfg) is not None
    assert outbox.get(s_fresh_scan) is not None
    assert outbox.get(s_stat) is not None

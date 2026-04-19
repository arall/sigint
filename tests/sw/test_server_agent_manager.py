"""Tests for AgentManager: server-side ingestion of DET/STAT/HELLO + approval."""
import json
import os
import sys
import tempfile
import time

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class FakeLink:
    def __init__(self):
        self.sent = []
        self._cb = None
    def on_message(self, cb): self._cb = cb
    def send(self, text): self.sent.append(text)


def test_hello_adds_pending_agent(tmp_path):
    from server.agent_manager import AgentManager

    link = FakeLink()
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=str(tmp_path / "agents.db"))
    link._cb("HELLO|N01|0.1|rpi0w")
    assert "N01" in mgr.pending()
    assert "N01" not in mgr.approved()


def test_approve_moves_pending_to_approved_and_sends_APPROVE(tmp_path):
    from server.agent_manager import AgentManager

    link = FakeLink()
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=str(tmp_path / "agents.db"))
    link._cb("HELLO|N01|0.1|rpi0w")
    mgr.approve("N01")
    assert "N01" in mgr.approved()
    assert "N01" not in mgr.pending()
    assert any(t.startswith("APPROVE|N01") for t in link.sent)

    # Persists to agents.json
    with open(os.path.join(tmp_path, "agents.json")) as f:
        data = json.load(f)
    assert "N01" in data.get("approved", {})


def test_det_from_approved_agent_inserts_into_db_and_acks(tmp_path):
    from server.agent_manager import AgentManager
    import sqlite3

    link = FakeLink()
    db_path = str(tmp_path / "agents.db")
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=db_path)
    link._cb("HELLO|N01|0.1|rpi0w")
    mgr.approve("N01")

    link.sent.clear()
    link._cb("DET|N01|42|pmr|446.00625|-62|48.1234|2.4567|1744812345|ch3")

    # Ack sent
    assert any(t == "ACK|N01|42|ok" for t in link.sent)

    # Row present in db
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT device_id, signal_type, frequency_hz FROM detections"
    ).fetchone()
    conn.close()
    assert row[0] == "N01"
    assert row[1] == "pmr"
    assert abs(row[2] - 446.00625e6) < 1


def test_det_from_unapproved_agent_is_ignored(tmp_path):
    from server.agent_manager import AgentManager
    link = FakeLink()
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=str(tmp_path / "agents.db"))
    link._cb("DET|N99|1|pmr|446|-60|0|0|0|")
    # No ack, no insertion
    assert link.sent == []


def test_duplicate_det_is_deduplicated(tmp_path):
    from server.agent_manager import AgentManager
    import sqlite3
    link = FakeLink()
    db_path = str(tmp_path / "agents.db")
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=db_path)
    link._cb("HELLO|N01|0.1|rpi0w")
    mgr.approve("N01")

    link._cb("DET|N01|1|pmr|446|-60|0|0|0|")
    link._cb("DET|N01|1|pmr|446|-60|0|0|0|")

    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
    conn.close()
    assert n == 1


def test_stat_updates_last_seen(tmp_path):
    from server.agent_manager import AgentManager
    link = FakeLink()
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=str(tmp_path / "agents.db"))
    link._cb("HELLO|N01|0.1|rpi0w")
    mgr.approve("N01")
    link._cb("STAT|N01|5|pmr|running|48.1|2.4|9|42|1000")
    info = mgr.agent_info("N01")
    assert info["scanner"] == "pmr"
    assert info["state"] == "running"
    assert info["last_seen_at"] > 0


def test_hello_from_approved_agent_resends_approve(tmp_path):
    """Agent only HELLOs while unadopted (agent.py:294). A HELLO from an
    already-approved agent therefore means the agent lost its state (fresh
    service install, state.json wipe) — server must re-send APPROVE so the
    agent re-adopts without `adopted: true` being hand-edited back in."""
    from server.agent_manager import AgentManager
    link = FakeLink()
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=str(tmp_path / "agents.db"))
    link._cb("HELLO|N01|0.1|rpi0w")
    mgr.approve("N01")
    # Clear the initial APPROVE from the send log so we can assert
    # re-approve is the only new outgoing frame.
    link.sent.clear()

    # Agent comes back with wiped state — HELLOs again.
    link._cb("HELLO|N01|0.1|rpi0w")

    approves = [t for t in link.sent if t.startswith("APPROVE|N01")]
    assert len(approves) == 1, (
        f"expected one re-APPROVE, got {link.sent!r}")
    # Still approved, last_seen updated.
    assert "N01" in mgr.approved()
    assert mgr.approved()["N01"]["last_seen_at"] > 0


def test_hello_from_approved_agent_survives_restart(tmp_path):
    """agents.json persists approval across server restarts. After a
    restart, a new HELLO from a previously-approved agent must still
    trigger a re-APPROVE (nothing in memory yet — but agents.json has
    the entry)."""
    from server.agent_manager import AgentManager

    # First session: approve N01, shut down.
    link1 = FakeLink()
    mgr1 = AgentManager(link=link1, state_dir=str(tmp_path),
                        detection_db_path=str(tmp_path / "agents.db"))
    link1._cb("HELLO|N01|0.1|rpi0w")
    mgr1.approve("N01")

    # Second session: fresh manager reads agents.json, no in-memory state.
    link2 = FakeLink()
    mgr2 = AgentManager(link=link2, state_dir=str(tmp_path),
                        detection_db_path=str(tmp_path / "agents.db"))
    assert "N01" in mgr2.approved()
    # HELLO should trigger a re-APPROVE, not move to pending.
    link2._cb("HELLO|N01|0.1|rpi0w")
    approves = [t for t in link2.sent if t.startswith("APPROVE|N01")]
    assert len(approves) == 1
    assert "N01" not in mgr2.pending()


def test_send_cmd_goes_through_outbox_and_ack_clears_it(tmp_path):
    """Operator clicks Start → AgentManager hands to ServerOutbox →
    CMD wire is sent with seq → agent ACK clears the pending. Guards
    the whole reliable-CMD round-trip."""
    from server.agent_manager import AgentManager
    link = FakeLink()
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=str(tmp_path / "agents.db"))
    link._cb("HELLO|N01|0.1|rpi0w")
    mgr.approve("N01")
    link.sent.clear()

    seq = mgr.send_cmd("N01", "START", ["pmr"])
    # Wire format carries seq at position 2.
    cmd = [t for t in link.sent if t.startswith("CMD|N01|")][0]
    parts = cmd.split("|")
    assert parts[2] == str(seq)
    assert parts[3] == "START"
    assert mgr.pending_outbox("N01") != []

    # Agent ACKs with matching seq — pending clears.
    link._cb(f"ACK|N01|{seq}|ok")
    assert mgr.pending_outbox("N01") == []


def test_cmd_from_unknown_agent_ack_is_ignored(tmp_path):
    """ACK from a non-approved agent shouldn't feed the outbox."""
    from server.agent_manager import AgentManager
    link = FakeLink()
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=str(tmp_path / "agents.db"))
    # No approval — ACK should be filtered by the pre-dispatch gate.
    link._cb("ACK|N99|42|ok")
    assert mgr.pending_outbox() == []


def test_hello_from_unknown_agent_still_goes_pending(tmp_path):
    """Regression guard: only approved agents get the re-APPROVE path;
    new agents still land in pending."""
    from server.agent_manager import AgentManager
    link = FakeLink()
    mgr = AgentManager(link=link, state_dir=str(tmp_path),
                       detection_db_path=str(tmp_path / "agents.db"))
    link._cb("HELLO|N99|0.1|rpi0w")
    assert "N99" in mgr.pending()
    # No APPROVE emitted for pending agents.
    assert not any(t.startswith("APPROVE|") for t in link.sent)

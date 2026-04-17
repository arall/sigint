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

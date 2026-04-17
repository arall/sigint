"""End-to-end: Agent + AgentManager wired via fake bus. Verifies the full
adoption -> CMD START -> DET flow -> ACK loop works without real hardware."""
import os
import sys
import sqlite3
import tempfile
import threading
import time

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class Bus:
    def __init__(self):
        self._lst = []; self._lock = threading.Lock()
    def register(self, l):
        with self._lock: self._lst.append(l)
    def deliver(self, sender, text):
        with self._lock: lst = list(self._lst)
        for l in lst:
            if l is not sender: l._on_bus_text(text)


class FakeBackend:
    def __init__(self, bus):
        self._bus = bus; self._cb = None
        bus.register(self)
    def set_callback(self, cb): self._cb = cb
    def send_text(self, t): self._bus.deliver(self, t)
    def _on_bus_text(self, t):
        if self._cb: self._cb(t)


def test_e2e_adoption_and_det_delivery():
    from comms.meshlink import MeshLink
    from server.agent_manager import AgentManager
    from agent.agent import Agent

    with tempfile.TemporaryDirectory() as tmp_path:
        bus = Bus()
        srv_link = MeshLink(backend=FakeBackend(bus))
        ag_link = MeshLink(backend=FakeBackend(bus))

        agents_db = os.path.join(tmp_path, "agents.db")
        mgr = AgentManager(link=srv_link, state_dir=tmp_path,
                           detection_db_path=agents_db)

        agent = Agent(
            state_dir=os.path.join(tmp_path, "agent"),
            agent_id="N01",
            meshlink=ag_link,
            scanner_mgr=None,
        )
        agent.start(hello_interval=0.1, stat_interval=0.2, drain_interval=0.1)

        # Wait for HELLO, approve
        deadline = time.time() + 2.0
        while "N01" not in mgr.pending() and time.time() < deadline:
            time.sleep(0.05)
        assert "N01" in mgr.pending()
        mgr.approve("N01")
        deadline = time.time() + 2.0
        while not agent._state.adopted and time.time() < deadline:
            time.sleep(0.05)
        assert agent._state.adopted

        # Agent enqueues a DET
        agent.enqueue_det("pmr", 446.00625, -62, 48.1234, 2.4567, 1744812345, "ch3")

        # Wait for DET to arrive and be ACKed
        deadline = time.time() + 3.0
        while time.time() < deadline:
            conn = sqlite3.connect(agents_db)
            try:
                n = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
            finally:
                conn.close()
            if n >= 1 and agent._outbox.depth() == 0:
                break
            time.sleep(0.1)

        assert n == 1
        assert agent._outbox.depth() == 0   # acked

        agent.stop()

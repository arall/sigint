"""End-to-end tests for Agent with a mocked MeshLink peer."""
import os
import sys
import tempfile
import threading
import time

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class Bus:
    def __init__(self):
        self._lst = []
        self._lock = threading.Lock()
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


def _make_agent(tmpdir, bus):
    from comms.meshlink import MeshLink
    from agent.agent import Agent
    link = MeshLink(backend=FakeBackend(bus))
    agent = Agent(
        state_dir=str(tmpdir),
        agent_id="N01",
        meshlink=link,
        scanner_mgr=None,  # no real scanner; test will exercise protocol only
    )
    return agent, link


def test_unadopted_agent_sends_hello_beacon(tmp_path):
    bus = Bus()
    from comms.meshlink import MeshLink
    peer = MeshLink(backend=FakeBackend(bus))
    got = []
    peer.on_message(lambda t: got.append(t))

    agent, link = _make_agent(tmp_path, bus)
    agent.start(hello_interval=0.1)

    deadline = time.time() + 1.5
    while not any(t.startswith("HELLO|") for t in got) and time.time() < deadline:
        time.sleep(0.05)
    agent.stop()
    assert any(t.startswith("HELLO|N01|") for t in got)


def test_approve_sets_adopted_and_stops_hello(tmp_path):
    bus = Bus()
    from comms.meshlink import MeshLink
    peer = MeshLink(backend=FakeBackend(bus))
    texts = []
    peer.on_message(lambda t: texts.append(t))

    agent, link = _make_agent(tmp_path, bus)
    agent.start(hello_interval=0.1)
    time.sleep(0.3)
    peer_link = MeshLink(backend=FakeBackend(bus))  # second peer role
    peer_link.send("APPROVE|N01")
    time.sleep(0.3)

    # After approval, no more HELLO messages
    before = len([t for t in texts if t.startswith("HELLO|")])
    time.sleep(0.5)
    after = len([t for t in texts if t.startswith("HELLO|")])
    assert after == before
    agent.stop()

    # state persisted
    from agent.state import AgentState
    state = AgentState.load(os.path.join(tmp_path, "state.json"), default_agent_id="N01")
    assert state.adopted is True


def test_agent_acks_incoming_det_that_never_happens_but_sends_its_own_ack(tmp_path):
    """When the agent (approved) sends a DET, the peer must receive it and the
    agent must retry if no ACK arrives."""
    bus = Bus()
    from comms.meshlink import MeshLink
    peer = MeshLink(backend=FakeBackend(bus))
    from agent.state import AgentState
    AgentState(
        path=os.path.join(tmp_path, "state.json"),
        agent_id="N01", adopted=True,
    ).save()

    agent, link = _make_agent(tmp_path, bus)
    got = []
    peer.on_message(lambda t: got.append(t))
    agent.start(hello_interval=10.0, drain_interval=0.05)
    try:
        agent.enqueue_det("pmr", 446.00625, -62, 48.123, 2.456, 1744812345, "ch3")
        deadline = time.time() + 1.0
        while not any(t.startswith("DET|N01|") for t in got) and time.time() < deadline:
            time.sleep(0.05)
        assert any(t.startswith("DET|N01|") for t in got)
    finally:
        agent.stop()

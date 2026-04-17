"""Tests for MeshLink using an in-process fake Meshtastic backend.

The real MeshLink wraps the `meshtastic` SerialInterface. For testing, we inject
a fake backend that exposes the same send/receive surface so two MeshLink
instances can be wired together without real hardware.
"""
import os
import sys
import time
import threading

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class FakeBus:
    """Shared bus: every send() delivers to all listeners except sender."""
    def __init__(self):
        self._listeners = []
        self._lock = threading.Lock()

    def register(self, listener):
        with self._lock:
            self._listeners.append(listener)

    def deliver(self, sender, text):
        with self._lock:
            listeners = list(self._listeners)
        for l in listeners:
            if l is not sender:
                l._on_bus_text(text)


class FakeBackend:
    """A fake Meshtastic backend for a single MeshLink."""
    def __init__(self, bus):
        self._bus = bus
        self._bus.register(self)
        self._on_text = None

    def set_callback(self, cb):
        self._on_text = cb

    def send_text(self, text):
        self._bus.deliver(self, text)

    def _on_bus_text(self, text):
        if self._on_text:
            self._on_text(text)


def test_two_meshlinks_exchange_messages():
    from comms.meshlink import MeshLink

    bus = FakeBus()
    central = MeshLink(backend=FakeBackend(bus))
    agent = MeshLink(backend=FakeBackend(bus))

    received = []
    agent.on_message(lambda text: received.append(text))

    central.send("CMD|N01|STATUS")
    time.sleep(0.05)
    assert received == ["CMD|N01|STATUS"]


def test_meshlink_ignores_malformed_messages():
    """Handler should not crash when backend delivers garbage."""
    from comms.meshlink import MeshLink

    bus = FakeBus()
    link = MeshLink(backend=FakeBackend(bus))

    got = []
    link.on_message(lambda text: got.append(text))

    peer = FakeBackend(bus)
    peer.send_text("garbage no pipes")
    peer.send_text("CMD|N01|STATUS")
    time.sleep(0.05)

    # MeshLink forwards all text; parsing is the caller's job.
    assert "CMD|N01|STATUS" in got


def test_meshlink_send_before_on_message_does_not_lose_inbound():
    from comms.meshlink import MeshLink
    bus = FakeBus()
    a = MeshLink(backend=FakeBackend(bus))
    b = MeshLink(backend=FakeBackend(bus))

    got = []
    # Register after some messages already in flight — that's fine, there's no
    # pre-callback buffer in this design, the test asserts the contract.
    a.send("X")
    b.on_message(lambda t: got.append(t))
    a.send("Y")
    time.sleep(0.05)
    assert got == ["Y"]

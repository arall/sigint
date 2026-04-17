"""MeshLink: thin wrapper around the Meshtastic SerialInterface for C2.

In production, construct MeshLink.from_serial(port=...) which opens the device.
In tests, pass a custom backend that implements `send_text(text)` and
`set_callback(callable)`. The backend is the only I/O surface we touch.
"""
from __future__ import annotations

from typing import Callable, Optional


# Module-level registry of active backends keyed by id(). pypubsub listeners
# must be module-level functions (not nested closures or bound methods of
# nested classes) to avoid pypubsub 4.x silently dropping subscriptions.
_BACKENDS: dict[int, "_BackendState"] = {}


class _BackendState:
    """Opaque per-backend state referenced from module-level pubsub callbacks."""

    def __init__(self, channel_index: int):
        self.channel_index = channel_index
        self.iface = None
        self.cb: Optional[Callable[[str], None]] = None


def _on_receive_text(packet, interface):
    """Module-level pubsub listener — survives pypubsub weakref quirks."""
    text = packet.get("decoded", {}).get("text")
    if not text:
        return
    for state in list(_BACKENDS.values()):
        if state.cb:
            try:
                state.cb(text)
            except Exception:
                pass


class MeshLink:
    def __init__(self, backend):
        self._backend = backend
        self._on_message: Optional[Callable[[str], None]] = None
        backend.set_callback(self._dispatch)

    @classmethod
    def from_serial(cls, port: str, channel_index: int = 0) -> "MeshLink":
        # Lazy import so tests don't require the meshtastic package to be present
        import meshtastic
        import meshtastic.serial_interface
        from pubsub import pub

        state = _BackendState(channel_index=channel_index)
        _BACKENDS[id(state)] = state

        # Subscribe the module-level handler exactly once per process.
        # pypubsub dedups multiple subscribes of the same function to the same
        # topic, so it's safe to call on every from_serial() invocation.
        pub.subscribe(_on_receive_text, "meshtastic.receive.text")

        state.iface = meshtastic.serial_interface.SerialInterface(devPath=port)

        class _SerialBackend:
            def __init__(self, state):
                self._state = state

            def set_callback(self, cb):
                self._state.cb = cb

            def send_text(self, text):
                self._state.iface.sendText(text, channelIndex=self._state.channel_index)

        return cls(backend=_SerialBackend(state))

    def on_message(self, handler: Callable[[str], None]) -> None:
        self._on_message = handler

    def send(self, text: str) -> None:
        self._backend.send_text(text)

    def _dispatch(self, text: str) -> None:
        cb = self._on_message
        if cb is not None:
            try:
                cb(text)
            except Exception:
                pass

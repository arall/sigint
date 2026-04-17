"""MeshLink: thin wrapper around the Meshtastic SerialInterface for C2.

In production, construct MeshLink.from_serial(port=...) which opens the device.
In tests, pass a custom backend that implements `send_text(text)` and
`set_callback(callable)`. The backend is the only I/O surface we touch.
"""
from __future__ import annotations

from typing import Callable, Optional


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

        class _SerialBackend:
            def __init__(self, port, channel_index):
                self._iface = meshtastic.serial_interface.SerialInterface(devPath=port)
                self._channel_index = channel_index
                self._cb = None
                pub.subscribe(self._on_receive, "meshtastic.receive.text")

            def set_callback(self, cb):
                self._cb = cb

            def send_text(self, text):
                self._iface.sendText(text, channelIndex=self._channel_index)

            def _on_receive(self, packet, interface):
                try:
                    decoded = packet.get("decoded", {})
                    text = decoded.get("text")
                    if text and self._cb:
                        self._cb(text)
                except Exception:
                    pass

        return cls(backend=_SerialBackend(port, channel_index))

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

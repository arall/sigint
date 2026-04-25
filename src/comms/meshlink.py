"""MeshLink: thin wrapper around the Meshtastic SerialInterface for C2.

In production, construct MeshLink.from_serial(port=...) which opens the device.
In tests, pass a custom backend that implements `send_text(text)` and
`set_callback(callable)`. The backend is the only I/O surface we touch.
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple


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

            def get_local_position(self) -> Tuple[Optional[float], Optional[float], int]:
                # Returns (lat, lon, sats) for the local node, or (None,None,0)
                # if no fix. Drives MeshtasticGpsReader on nodes whose only GPS
                # is inside the meshtastic radio (T-Echo's L76K, Heltec
                # Wireless Tracker's UC6580 — both wired internally to the
                # device's MCU, not exposed on USB serial).
                iface = self._state.iface
                if iface is None:
                    return None, None, 0
                try:
                    info = iface.getMyNodeInfo()
                except Exception:
                    return None, None, 0
                if not info:
                    return None, None, 0
                pos = info.get("position") or {}
                lat = pos.get("latitude")
                lon = pos.get("longitude")
                sats = pos.get("satsInView") or pos.get("sats") or 0
                return lat, lon, int(sats or 0)

            def is_alive(self) -> bool:
                iface = self._state.iface
                if iface is None:
                    return False
                # The meshtastic StreamInterface reader thread is the only
                # robust signal across version skew: on a USB disconnect, the
                # `__reader` thread catches SerialException/OSError, calls
                # `_disconnected()`, and exits — but it does NOT set
                # `_wantExit` (only `close()` does). So checking _wantExit
                # alone misses real-world disconnects (verified against
                # meshtastic 2.7.8 stream_interface.py:212-232). The reader
                # thread being dead is the unambiguous "iface is dead" signal.
                rx = getattr(iface, "_rxThread", None)
                if rx is not None and not rx.is_alive():
                    return False
                return not getattr(iface, "_wantExit", False)

        return cls(backend=_SerialBackend(state))

    def on_message(self, handler: Callable[[str], None]) -> None:
        self._on_message = handler

    def send(self, text: str) -> None:
        self._backend.send_text(text)

    def get_local_position(self) -> Tuple[Optional[float], Optional[float], int]:
        getter = getattr(self._backend, "get_local_position", None)
        if getter is None:
            return None, None, 0
        try:
            return getter()
        except Exception:
            return None, None, 0

    def is_alive(self) -> bool:
        # True if the underlying meshtastic iface (or test backend) is healthy.
        # When the meshtastic SerialInterface hits a USB disconnect it sets
        # _wantExit but doesn't tear the agent process down — agents go
        # "zombie" (active service, dead radio). The agent's watchdog uses
        # this to decide when to exit so systemd restarts.
        checker = getattr(self._backend, "is_alive", None)
        if checker is None:
            return True  # test backends without the method are always alive
        try:
            return bool(checker())
        except Exception:
            return False

    def _dispatch(self, text: str) -> None:
        cb = self._on_message
        if cb is not None:
            try:
                cb(text)
            except Exception:
                pass

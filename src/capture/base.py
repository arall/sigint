"""
Base capture source — owns one hardware device and emits raw frames
to registered parser callbacks.
"""

import threading
from abc import ABC, abstractmethod


class BaseCaptureSource(ABC):
    """Owns one hardware device. Produces raw data frames to registered callbacks."""

    def __init__(self):
        self._callbacks = []
        self._stop_event = threading.Event()

    def add_parser(self, callback):
        """Register a parser callback. Called with raw data frames."""
        self._callbacks.append(callback)

    def _emit(self, frame):
        """Send a raw data frame to all registered parsers."""
        for cb in self._callbacks:
            try:
                cb(frame)
            except Exception:
                pass  # Never let one parser crash another

    @property
    def stopped(self):
        return self._stop_event.is_set()

    @abstractmethod
    def start(self):
        """Start capturing. Blocks until stop() is called."""
        ...

    @abstractmethod
    def stop(self):
        """Stop capturing and release hardware."""
        ...

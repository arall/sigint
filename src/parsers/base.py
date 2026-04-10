"""
Base parser — consumes raw frames from a capture source and produces
SignalDetection objects via a shared SignalLogger.
"""

from abc import ABC, abstractmethod


class BaseParser(ABC):
    """Consumes raw frames from a capture source, produces SignalDetections."""

    def __init__(self, logger):
        self.logger = logger

    @abstractmethod
    def handle_frame(self, frame):
        """Process one raw data frame. Log detections via self.logger."""
        ...

    def shutdown(self):
        """Called on clean exit. Override to persist state."""
        pass

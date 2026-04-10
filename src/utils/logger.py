#!/usr/bin/env python3
"""
Signal Logger Module
Captures and stores signal detections for later processing.
Supports CSV output (and later API upload).
"""

import csv
import os
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SignalDetection:
    """Represents a detected signal."""

    timestamp: str
    signal_type: str  # e.g., "PMR446", "WiFi", "Bluetooth", "DMR"
    frequency_hz: float
    power_db: float
    noise_floor_db: float
    snr_db: float  # Signal-to-noise ratio
    channel: Optional[str] = None  # e.g., "CH1", "CH2" for PMR
    latitude: Optional[float] = None  # GPS coordinates (for triangulation)
    longitude: Optional[float] = None
    device_id: Optional[str] = None  # Identifier for the SDR device
    audio_file: Optional[str] = None  # Path to recorded audio file
    metadata: str = ""  # JSON string for additional signal-specific data

    @classmethod
    def create(
        cls,
        signal_type: str,
        frequency_hz: float,
        power_db: float,
        noise_floor_db: float,
        channel: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        device_id: Optional[str] = None,
        audio_file: Optional[str] = None,
        metadata: str = "",
    ) -> "SignalDetection":
        """Create a new signal detection with current timestamp."""
        return cls(
            timestamp=datetime.now().isoformat(),
            signal_type=signal_type,
            frequency_hz=frequency_hz,
            power_db=power_db,
            noise_floor_db=noise_floor_db,
            snr_db=round(power_db - noise_floor_db, 2),
            channel=channel,
            latitude=latitude,
            longitude=longitude,
            device_id=device_id,
            audio_file=audio_file,
            metadata=metadata,
        )


class SignalLogger:
    """
    Logs signal detections to CSV (and later to API).
    Thread-safe for concurrent signal capture.
    """

    CSV_HEADERS = [
        "timestamp",
        "signal_type",
        "frequency_hz",
        "power_db",
        "noise_floor_db",
        "snr_db",
        "channel",
        "latitude",
        "longitude",
        "device_id",
        "audio_file",
        "metadata",
    ]

    def __init__(
        self,
        output_dir: str = "output",
        signal_type: str = "signals",
        device_id: Optional[str] = None,
        min_snr_db: float = 5.0,  # Minimum SNR to log (filter noise)
        gps=None,  # Optional GPSReader instance for auto lat/lon
    ):
        """
        Initialize the signal logger.

        Args:
            output_dir: Directory to store CSV files
            signal_type: Type of signals being captured (used in filename)
            device_id: Identifier for this SDR device
            min_snr_db: Minimum SNR threshold to log a detection
        """
        self.output_dir = Path(output_dir)
        self.signal_type = signal_type
        self.device_id = device_id
        self.min_snr_db = min_snr_db
        self.gps = gps

        self._lock = threading.Lock()
        self._running = False
        self._csv_path = None
        self._csv_file = None
        self._csv_writer = None
        self._detection_count = 0
        self.on_detection = None  # Optional callback: fn(SignalDetection) -> None

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_csv_path(self) -> Path:
        """Generate CSV filename with timestamp."""
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.output_dir / f"{self.signal_type}_{date_str}.csv"

    def start(self) -> str:
        """Start the logger and return the output file path."""
        if self._running:
            return str(self._csv_path)

        self._csv_path = self._get_csv_path()
        self._csv_file = open(self._csv_path, "w", newline="")
        self._csv_writer = csv.DictWriter(
            self._csv_file, fieldnames=self.CSV_HEADERS)
        self._csv_writer.writeheader()
        self._csv_file.flush()

        self._running = True
        return str(self._csv_path)

    def stop(self) -> int:
        """Stop the logger and return total detections logged."""
        self._running = False

        if self._csv_file:
            self._csv_file.close()
            self._csv_file = None

        return self._detection_count

    def log(self, detection: SignalDetection) -> bool:
        """
        Log a signal detection immediately to CSV.

        Args:
            detection: The signal detection to log

        Returns:
            True if detection was logged (met SNR threshold), False otherwise
        """
        with self._lock:
            if detection.snr_db < self.min_snr_db:
                return False

            # Add device_id if not set
            if detection.device_id is None and self.device_id:
                detection.device_id = self.device_id

            # Auto-fill GPS coordinates if not set
            if detection.latitude is None and detection.longitude is None and self.gps:
                detection.latitude, detection.longitude = self.gps.position

            # Write immediately (synchronous) for real-time logging
            self._write_detection_locked(detection)

            if self.on_detection:
                try:
                    self.on_detection(detection)
                except Exception:
                    pass  # Never let callback errors break logging

            return True

    def log_signal(
        self,
        signal_type: str,
        frequency_hz: float,
        power_db: float,
        noise_floor_db: float,
        channel: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        audio_file: Optional[str] = None,
        metadata: str = "",
    ) -> bool:
        """
        Convenience method to log a signal without creating SignalDetection manually.

        Returns:
            True if detection was logged, False if below SNR threshold
        """
        detection = SignalDetection.create(
            signal_type=signal_type,
            frequency_hz=frequency_hz,
            power_db=power_db,
            noise_floor_db=noise_floor_db,
            channel=channel,
            latitude=latitude,
            longitude=longitude,
            device_id=self.device_id,
            audio_file=audio_file,
            metadata=metadata,
        )
        return self.log(detection)

    def _write_detection_locked(self, detection: SignalDetection):
        """Write a single detection to CSV. Caller must hold self._lock."""
        if self._csv_writer is None:
            return

        self._csv_writer.writerow(asdict(detection))
        self._csv_file.flush()
        os.fsync(self._csv_file.fileno())
        self._detection_count += 1

    @property
    def detection_count(self) -> int:
        """Return the number of detections logged so far."""
        return self._detection_count

    # Future API integration placeholder
    def _upload_to_api(self, detection: SignalDetection) -> bool:
        """
        Upload detection to central API.
        TODO: Implement when API is available.
        """
        # api_url = os.environ.get("SIGNAL_API_URL")
        # if not api_url:
        #     return False
        # response = requests.post(f"{api_url}/detections", json=asdict(detection))
        # return response.ok
        return False


# Convenience function for quick logging
_default_logger: Optional[SignalLogger] = None


def get_logger(
    output_dir: str = "output",
    signal_type: str = "signals",
    device_id: Optional[str] = None,
    min_snr_db: float = 5.0,
) -> SignalLogger:
    """Get or create a default signal logger."""
    global _default_logger
    if _default_logger is None:
        _default_logger = SignalLogger(
            output_dir=output_dir,
            signal_type=signal_type,
            device_id=device_id,
            min_snr_db=min_snr_db,
        )
    return _default_logger

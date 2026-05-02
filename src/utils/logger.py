#!/usr/bin/env python3
"""
Signal Logger Module
Captures and stores signal detections in a per-session SQLite database
(WAL mode) so multiple writers (parsers, scanners) and readers (web
dashboard, triangulation) can share the same file safely.
"""

import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils import db as _db


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
    Logs signal detections to the unified `output/detections.db`.
    Thread-safe for concurrent signal capture.

    Each logger instance opens a `sessions` row on `start()` and tags
    every detection it writes with that session id, then stamps the
    session's `ended_at` on `stop()`. Multiple loggers can share the
    same DB file — SQLite's WAL mode + a per-connection busy_timeout
    serialise concurrent writers.
    """

    def __init__(
        self,
        output_dir: str = "output",
        signal_type: str = "signals",
        device_id: Optional[str] = None,
        min_snr_db: float = 5.0,  # Minimum SNR to log (filter noise)
        gps=None,  # Optional GPSReader instance for auto lat/lon
        db_path: Optional[str] = None,
        session_kind: Optional[str] = None,
        session_label: Optional[str] = None,
    ):
        """
        Initialize the signal logger.

        Args:
            output_dir: Directory to store the DB file
            signal_type: Free-form name for this run (becomes the
                default session label when `session_label` is omitted).
                No longer affects file naming — there's only ever one
                file per output dir.
            device_id: Identifier for this SDR device
            min_snr_db: Minimum SNR threshold to log a detection
            db_path: Optional explicit path. Defaults to
                `<output_dir>/detections.db`.
            session_kind: Override the `sessions.kind` value. Defaults
                to `"scanner:<signal_type>"`.
            session_label: Override the `sessions.label` value. Defaults
                to `signal_type`.
        """
        self.output_dir = Path(output_dir)
        self.signal_type = signal_type
        self.device_id = device_id
        self.min_snr_db = min_snr_db
        self.gps = gps
        self._session_kind = session_kind or f"scanner:{signal_type}"
        self._session_label = session_label or signal_type

        self._lock = threading.Lock()
        self._running = False
        self._db_path = Path(db_path) if db_path else None
        self._conn = None
        self._session_id: Optional[int] = None
        self._detection_count = 0
        self.on_detection = None  # Optional callback: fn(SignalDetection) -> None

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Optional[Path]:
        return self._db_path

    @property
    def session_id(self) -> Optional[int]:
        """The sessions.id row this logger writes to. None until start()."""
        return self._session_id

    def start(self) -> str:
        """Start the logger and return the output file path."""
        if self._running:
            return str(self._db_path)

        if self._db_path is None:
            self._db_path = Path(_db.default_db_path(str(self.output_dir)))

        self._conn = _db.connect(str(self._db_path))
        import os as _os
        self._session_id = _db.open_session(
            self._conn,
            kind=self._session_kind,
            label=self._session_label,
            pid=_os.getpid(),
        )
        self._running = True
        return str(self._db_path)

    def stop(self) -> int:
        """Stop the logger and return total detections logged."""
        self._running = False
        if self._conn is not None:
            try:
                if self._session_id is not None:
                    _db.close_session(self._conn, self._session_id)
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        return self._detection_count

    def log(self, detection: SignalDetection) -> bool:
        """
        Log a signal detection immediately to the DB.

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
        """Write a single detection to SQLite. Caller must hold self._lock."""
        if self._conn is None:
            return
        _db.insert_detection(
            self._conn, detection,
            session_id=self._session_id,
        )
        self._detection_count += 1

    def log_transcript(self, audio_file: str, text: str,
                       language: Optional[str] = None) -> None:
        """Upsert a Whisper transcript into the session DB.

        The async transcriber worker calls this when a transcription
        completes. Uses the same writer connection + lock as the
        detection writer, so there's no connection-per-write churn
        and transcripts arrive in the same .db as the detections
        that reference them.
        """
        if not audio_file or not text:
            return
        with self._lock:
            if self._conn is None:
                return
            try:
                _db.insert_transcript(self._conn, audio_file, text, language)
            except Exception as e:
                print(f"[logger] log_transcript failed: {e}")

    @property
    def detection_count(self) -> int:
        """Return the number of detections logged so far."""
        return self._detection_count


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

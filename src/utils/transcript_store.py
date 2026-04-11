"""
Transcript sidecar store.

Persistent JSON map of audio filename -> transcript, saved atomically.
Used by the async transcriber to publish results, and by the web tailer
to back-fill detections after the fact.
"""

import json
import os
import tempfile
import threading


class TranscriptStore:
    """Thread-safe sidecar JSON: {audio_filename: transcript}."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._data = loaded
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_locked(self):
        """Atomic write. Caller must hold self._lock."""
        directory = os.path.dirname(self.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".transcripts.", suffix=".tmp", dir=directory)
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, indent=2)
            # mkstemp creates the file mode 600 — make it world-readable so
            # a non-root web UI can pick it up alongside the CSV log.
            try:
                os.chmod(tmp_path, 0o644)
            except OSError:
                pass
            os.replace(tmp_path, self.path)
        except Exception:
            # Non-fatal — we'll retry on the next update
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def set(self, audio_file, transcript):
        """Store a transcript and persist."""
        if not audio_file:
            return
        key = os.path.basename(audio_file)
        with self._lock:
            self._data[key] = transcript
            self._save_locked()

    def get(self, audio_file):
        if not audio_file:
            return None
        key = os.path.basename(audio_file)
        with self._lock:
            return self._data.get(key)

    def snapshot(self):
        """Return a shallow copy of the full mapping."""
        with self._lock:
            return dict(self._data)

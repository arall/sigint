"""
Background transcription worker.

Consumes (audio_file, model, language) jobs from a queue and runs Whisper
in a dedicated daemon thread, so the scanner pipeline never blocks on
transcription. Results are published to a TranscriptStore sidecar so the
web UI can back-fill already-logged detections.
"""

import os
import queue
import threading

from utils.transcript_store import TranscriptStore


class AsyncTranscriber:
    """Single-worker background transcription queue."""

    def __init__(self, output_dir, transcript_path=None):
        self.output_dir = output_dir
        self.transcript_path = transcript_path or os.path.join(
            output_dir, "transcripts.json")
        self.store = TranscriptStore(self.transcript_path)
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker = None
        self._started = False

    def start(self):
        if self._started:
            return
        self._started = True
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="async-transcriber")
        self._worker.start()

    def submit(self, audio_file, model="base", language=None):
        """Enqueue an audio file for transcription. Non-blocking."""
        if not audio_file:
            return
        self.start()
        self._queue.put((audio_file, model, language))

    def stop(self, timeout=2.0):
        """Signal the worker to stop. Does not wait for the queue to drain."""
        self._stop_event.set()
        # Wake the worker up
        self._queue.put(None)
        if self._worker:
            self._worker.join(timeout=timeout)

    def _run(self):
        # Import lazily — whisper pulls in torch (~1GB), and users who
        # never transcribe should never pay that cost.
        try:
            from utils.transcriber import transcribe
        except Exception as e:
            print(f"[async-transcribe] import failed: {e}")
            return

        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job is None:
                break
            audio_file, model, language = job
            try:
                if not os.path.isfile(audio_file):
                    continue
                text = transcribe(audio_file, model_name=model, language=language)
                if text:
                    self.store.set(audio_file, text)
                    base = os.path.basename(audio_file)
                    print(f'  \U0001F4DD transcribed {base}: "{text[:80]}"')
            except Exception as e:
                print(f"[async-transcribe] failed on {audio_file}: {e}")

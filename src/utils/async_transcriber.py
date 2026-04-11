"""
Background transcription worker.

Consumes (audio_file, model, language) jobs from a queue and runs
Whisper in a dedicated daemon thread, so the scanner pipeline never
blocks on transcription. Results land in the session .db's
`transcripts` table via the SignalLogger's `log_transcript()` writer,
which the web UI reads with a JOIN on `audio_file` to back-fill the
Voice tab rows that were logged with empty transcripts during the
race window.
"""

import os
import queue
import threading


class AsyncTranscriber:
    """Single-worker background transcription queue."""

    def __init__(self, logger):
        """
        Args:
            logger: a SignalLogger instance. The worker calls
                logger.log_transcript(audio_file, text, language)
                for every completed job. The logger must have been
                started before submit() is called, but that's the
                normal scanner ordering (logger.start() then the
                first detection arrives).
        """
        self.logger = logger
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
        self._queue.put(None)   # wake the worker up
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
                    self.logger.log_transcript(audio_file, text, language=language)
                    base = os.path.basename(audio_file)
                    print(f'  \U0001F4DD transcribed {base}: "{text[:80]}"')
            except Exception as e:
                print(f"[async-transcribe] failed on {audio_file}: {e}")

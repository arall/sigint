"""
DMR Scanner — direct-mode (simplex) DMR voice capture via dsd-fme.

Drives an RTL-SDR through dsd-fme's built-in `rtl:dev:freq:gain:ppm:bw`
input, with `-P -7 <dir>` so each completed call is written to its own
.wav file. A directory watcher picks up newly-finalised WAVs (dsd-fme
writes a TEMP_*.wav and renames it to the final name with TGT/SRC
metadata when the call ends), logs a SignalDetection per call, and
hands the WAV to the async transcriber.

Why dsd-fme and not dsdccx: dsdccx (the project's existing decoder for
dPMR via utils/dpmr_decode.py) was tuned for repeater traffic and
produces heavy FEC errors on direct-mode DMR even when sync is good.
dsd-fme's `-fs` (DMR BS/MS Simplex) decode handles direct mode
cleanly. See memory/project_dmr_capture.md for the diagnosis trail.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import SignalLogger  # noqa: E402

# Per-call WAV file naming from dsd-fme. The exact set of fields between
# the random tag and TGT/SRC varies by version: older docs describe
# `..._{sys}_{gi}_TGT_<tgt>_SRC_<src>.wav`; current lwvmobile builds
# emit `..._DMR_CC_<n>_GROUP_TGT_<tgt>_SRC_<src>.wav`. We only require
# the date/time/random header (to confirm it's a real per-call file)
# and the TGT/SRC tokens at the tail — everything in between is the
# system / colour-code / call-type description, captured as `info`.
_FINAL_RE = re.compile(
    r"^(?P<date>\d{8})_(?P<time>\d{6})_(?P<rand>\d{5})_"
    r"(?P<info>.+?)_TGT_(?P<tgt>[^_]+)_SRC_(?P<src>[^.]+)\.wav$"
)


class DMRScanner:
    """Direct-mode DMR scanner backed by dsd-fme.

    Single-frequency continuous capture. The dsd-fme subprocess owns
    the RTL-SDR for the lifetime of the scanner — same hardware
    contention rules as the existing PMR/ADS-B/AIS standalone
    scanners (one process per dongle).
    """

    # The min_snr_db check on the SignalLogger is a noise gate. dsd-fme
    # only writes a WAV if it actually decoded voice frames, so by the
    # time we log, we know there was a real call. Stamp a comfortable
    # SNR so the logger doesn't drop the row.
    _PLACEHOLDER_POWER_DB = -30.0
    _PLACEHOLDER_NOISE_DB = -90.0

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        device_serial: str = None,
        frequency: float = 145.525e6,
        gain: int = 25,
        ppm: int = 0,
        bandwidth_khz: int = 12,
        squelch: int = 100,
        transcribe_audio: bool = False,
        whisper_model: str = "base",
        language: str = None,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.output_dir = output_dir
        self.device_id = device_id
        self.device_index = device_index
        self.device_serial = device_serial or None
        self.frequency = float(frequency)
        self.gain = int(gain)
        self.ppm = int(ppm)
        self.bandwidth_khz = int(bandwidth_khz)
        self.squelch = int(squelch)
        self.transcribe_audio = transcribe_audio
        self.whisper_model = whisper_model
        self.language = language

        # Per-call WAVs go directly under output/audio/ so the web
        # server's flat /audio/<file>.wav handler (and the basename-keyed
        # transcripts table) work without remapping. dsd-fme's filename
        # already includes a date+time+random prefix, so collisions with
        # other scanners' WAVs aren't a concern.
        self.wav_dir = os.path.join(output_dir, "audio")
        os.makedirs(self.wav_dir, exist_ok=True)

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="dmr",
            device_id=device_id,
            min_snr_db=0,  # We gate on dsd-fme producing a WAV, not SNR.
        )

        self._async_transcriber = None
        if self.transcribe_audio:
            from utils.async_transcriber import AsyncTranscriber
            self._async_transcriber = AsyncTranscriber(logger=self.logger)

        self._proc = None
        self._stop_event = threading.Event()
        self._seen_files = set()

    def _build_cmd(self):
        # rtl:dev:freq:gain:ppm:bw[:sq[:vol]]
        # freq is "145.525M" form; bw is integer kHz.
        # dsd-fme resolves `dev` as a serial first (exact match), then as an
        # index. With multiple dongles sharing serial 00000001, an index can
        # collide; pass a uniquely-flashed serial via device_serial to pin the
        # exact dongle. Falls back to the index when no serial is configured.
        dev = self.device_serial if self.device_serial else self.device_index
        rtl_arg = (
            f"rtl:{dev}:{self.frequency / 1e6}M:"
            f"{self.gain}:{self.ppm}:{self.bandwidth_khz}"
        )
        if self.squelch:
            rtl_arg += f":{self.squelch}"
        return [
            "dsd-fme",
            "-fs",          # DMR BS/MS Simplex (direct-mode)
            "-P",           # Per-call WAV files
            "-7", self.wav_dir,
            "-i", rtl_arg,
            "-o", "null",   # No PulseAudio output (would fail under sudo)
        ]

    def _drain_stderr(self):
        """Forward dsd-fme stderr to stdout so the operator sees sync events.

        dsd-fme is verbose (per-frame sync line); we keep it minimal
        by only printing lines that contain useful info: sync state,
        call metadata, errors.
        """
        if self._proc is None or self._proc.stderr is None:
            return
        try:
            for line in self._proc.stderr:
                if self._stop_event.is_set():
                    break
                try:
                    text = line.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    continue
                if not text:
                    continue
                # Strip ANSI colour codes for log readability
                text = re.sub(r"\x1b\[[0-9;]*m", "", text)
                # Print only call-relevant lines (Sync changes, errors, end-of-call)
                if any(tok in text for tok in
                        ("Sync: +DMR", "TLC", "ERR", "Error",
                         "Total ", "Group Call", "Private Call",
                         "rtlsdr", "Failed")):
                    print(f"  [dsd-fme] {text}")
        except Exception:
            pass

    def _watch_calls(self):
        """Poll the WAV dir for newly-finalised per-call files.

        dsd-fme writes a TEMP_*.wav while a call is in progress and
        renames it to the final TGT/SRC name when the call ends. We
        treat the appearance of a non-TEMP .wav as the signal to log
        a detection.
        """
        # Seed with anything already present so we don't reprocess
        # files from a previous run.
        try:
            for entry in os.scandir(self.wav_dir):
                if entry.name.endswith(".wav") and not entry.name.startswith("TEMP_"):
                    self._seen_files.add(entry.name)
        except FileNotFoundError:
            pass

        while not self._stop_event.is_set():
            try:
                new = []
                for entry in os.scandir(self.wav_dir):
                    name = entry.name
                    if not name.endswith(".wav"):
                        continue
                    if name.startswith("TEMP_"):
                        continue
                    if name in self._seen_files:
                        continue
                    new.append(entry)
                for entry in new:
                    self._seen_files.add(entry.name)
                    self._handle_call(entry.name, entry.path)
            except Exception as e:
                print(f"  [DMR] watcher error: {e}")
            self._stop_event.wait(1.0)

    def _handle_call(self, basename: str, full_path: str):
        """Log a SignalDetection for a finalised per-call WAV.

        Only WAVs whose names match the dsd-fme per-call pattern are
        logged. Other scanners' WAVs (PMR, FM) live in the same
        directory and must be ignored.
        """
        m = _FINAL_RE.match(basename)
        if not m:
            return

        meta = {
            "tgt": m.group("tgt"),
            "src": m.group("src"),
            "info": m.group("info"),
        }

        try:
            size = os.path.getsize(full_path)
        except OSError:
            size = 0
        meta["bytes"] = size
        meta["frequency_mhz"] = round(self.frequency / 1e6, 6)

        # The web /audio handler is flat (output/audio/<basename>) and
        # the transcripts table keys on basename, so store basename only.
        self.logger.log_signal(
            signal_type="DMR",
            frequency_hz=self.frequency,
            power_db=self._PLACEHOLDER_POWER_DB,
            noise_floor_db=self._PLACEHOLDER_NOISE_DB,
            channel="DMR",
            audio_file=basename,
            metadata=json.dumps(meta),
        )

        print(
            f"  📞 DMR call logged: TGT={meta['tgt']} SRC={meta['src']} "
            f"freq={self.frequency / 1e6:.4f} MHz file={basename}"
        )

        if self._async_transcriber:
            self._async_transcriber.submit(
                full_path,
                model=self.whisper_model,
                language=self.language,
            )

    def run(self):
        print("Initializing DMR scanner (dsd-fme + RTL-SDR)...")
        print(f"  Frequency: {self.frequency / 1e6:.4f} MHz")
        print(f"  Gain: {self.gain} dB  (PPM: {self.ppm}, BW: {self.bandwidth_khz} kHz)")
        print(f"  Per-call WAVs: {self.wav_dir}")

        cmd = self._build_cmd()
        print(f"  Command: {' '.join(cmd)}")

        env = os.environ.copy()
        if not env.get("LD_LIBRARY_PATH"):
            # Match the convention used elsewhere — V4 fork of librtlsdr
            # lives in /usr/local/lib.
            env["LD_LIBRARY_PATH"] = "/usr/local/lib"

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            print("ERROR: dsd-fme not found. Build from "
                  "https://github.com/lwvmobile/dsd-fme and `sudo make install`.")
            return
        except Exception as e:
            print(f"ERROR: failed to spawn dsd-fme: {e}")
            return

        output_file = self.logger.start()
        print(f"Logging to: {output_file}")
        if self._async_transcriber:
            self._async_transcriber.start()

        stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True, name="dmr-stderr")
        watcher_thread = threading.Thread(
            target=self._watch_calls, daemon=True, name="dmr-watcher")
        stderr_thread.start()
        watcher_thread.start()

        try:
            while True:
                if self._proc.poll() is not None:
                    print(f"\n[ERROR] dsd-fme exited (returncode={self._proc.returncode})")
                    break
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n\nStopping DMR scanner...")
        finally:
            self._stop_event.set()
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            stderr_thread.join(timeout=2.0)
            watcher_thread.join(timeout=2.0)

            # Catch any TEMP_* the watcher might have missed if a call
            # was in flight at shutdown — these will be partial WAVs
            # but still useful for transcription on the next run.
            try:
                for entry in os.scandir(self.wav_dir):
                    if entry.name.endswith(".wav") and entry.name not in self._seen_files \
                            and not entry.name.startswith("TEMP_"):
                        self._handle_call(entry.name, entry.path)
            except Exception:
                pass

            if self._async_transcriber:
                try:
                    self._async_transcriber.stop(timeout=1.0)
                except Exception:
                    pass

            total = self.logger.stop()
            print(f"Total DMR calls logged: {total}")


if __name__ == "__main__":
    scanner = DMRScanner()
    scanner.run()

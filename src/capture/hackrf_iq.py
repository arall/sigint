"""
HackRF IQ Capture Source — wideband IQ capture via hackrf_transfer subprocess.

HackRF One provides 20 MHz instantaneous bandwidth (vs RTL-SDR's 2.4 MHz),
covering multiple protocols in a single capture window.

Emits numpy complex64 arrays (IQ sample blocks) to registered parsers.
hackrf_transfer outputs int8 IQ pairs to a pipe — a dedicated reader thread
drains the pipe into a queue to prevent backpressure, and the main capture
thread processes blocks from the queue.

Requirements:
- hackrf_transfer (apt install hackrf, or brew install hackrf)
- HackRF One hardware
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

from capture.base import BaseCaptureSource


class HackRFCaptureSource(BaseCaptureSource):
    """Captures wideband IQ from HackRF via hackrf_transfer pipe."""

    def __init__(
        self,
        center_freq,
        sample_rate=20e6,
        lna_gain=32,
        vga_gain=40,
        amp_enable=False,
        block_size=256 * 1024,
        serial=None,
        ppm=0,
    ):
        super().__init__()
        self.center_freq = center_freq
        self.sample_rate = sample_rate
        # Actual tuned frequency accounting for crystal error.
        # The channelizer should use this (not center_freq) so that
        # frequency shifts align with real signal positions.
        self.actual_center_freq = center_freq * (1 + ppm * 1e-6) if ppm else center_freq
        self.lna_gain = lna_gain
        self.vga_gain = vga_gain
        self.amp_enable = amp_enable
        self.block_size = block_size
        self.serial = serial
        self.ppm = ppm
        self._process = None

    def start(self):
        """Start hackrf_transfer and stream IQ to parsers. Blocks until stop()."""
        if not shutil.which('hackrf_transfer'):
            raise RuntimeError("hackrf_transfer not found. Install with: apt install hackrf")

        cmd = [
            'hackrf_transfer',
            '-r', '-',              # RX to stdout (pipe)
            '-f', str(int(self.center_freq)),
            '-s', str(int(self.sample_rate)),
            '-l', str(self.lna_gain),
            '-g', str(self.vga_gain),
        ]
        if self.amp_enable:
            cmd.extend(['-a', '1'])
        if self.serial:
            cmd.extend(['-d', self.serial])

        ppm_info = f", ppm {self.ppm}" if self.ppm else ""
        print(f"[*] HackRF: {self.center_freq/1e6:.3f} MHz, "
              f"{self.sample_rate/1e6:.1f} MS/s, "
              f"LNA {self.lna_gain} dB, VGA {self.vga_gain} dB"
              f"{' +AMP' if self.amp_enable else ''}{ppm_info}")

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,  # unbuffered — read raw fd via os.read in _pipe_reader
        )

        # Read stderr in background
        stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True)
        stderr_thread.start()

        # Dedicated pipe reader thread — drains hackrf_transfer stdout into
        # a queue as fast as possible to prevent pipe backpressure.
        # Small queue + drop-oldest semantics keeps consumers on fresh data;
        # we'd rather drop stale samples than lag the parser pipeline.
        sample_queue = queue.Queue(maxsize=4)
        reader_thread = threading.Thread(
            target=self._pipe_reader,
            args=(sample_queue,),
            daemon=True,
        )
        reader_thread.start()

        # Process blocks from queue — this is where channelizer/parsers run
        try:
            while not self._stop_event.is_set():
                try:
                    samples = sample_queue.get(timeout=2.0)
                except queue.Empty:
                    # Check if hackrf_transfer died
                    if self._process and self._process.poll() is not None:
                        break
                    continue
                self._emit(samples)
        finally:
            self._cleanup()

    def stop(self):
        """Signal the capture to stop."""
        self._stop_event.set()

    # Ignore drops in the first few seconds after start — parsers are still
    # initialising (loading models, opening DBs, first numpy allocations),
    # which produces a harmless transient drop before steady state.
    WARMUP_SECONDS = 10

    def _pipe_reader(self, sample_queue):
        """Dedicated thread: read raw bytes from pipe and convert to complex64.

        Uses os.read on the raw fd (bufsize=0 in Popen) instead of
        BufferedReader.read(N). The buffered version blocks until exactly N
        bytes are accumulated, which deadlocks against hackrf_transfer at
        high rates: hackrf_transfer's write() blocks once the kernel pipe
        is full, while the reader is still inside one big read() that won't
        return until the buffer fills — but it can't fill if the writer is
        blocked. os.read returns whatever is currently in the pipe (drains
        it on every syscall), so the writer can keep flowing.
        """
        bytes_per_block = self.block_size * 2  # 2 bytes per IQ sample (int8 I + int8 Q)
        warmup_deadline = time.time() + self.WARMUP_SECONDS
        fd = self._process.stdout.fileno()
        leftover = bytearray()

        while not self._stop_event.is_set():
            try:
                # os.read returns whatever's available, up to bytes_per_block.
                # Accumulate until we have a full block, then dispatch.
                chunk = os.read(fd, bytes_per_block - len(leftover))
                if not chunk:
                    break
                leftover.extend(chunk)
                if len(leftover) < bytes_per_block:
                    continue
                raw = bytes(leftover)
                leftover = bytearray()

                # Convert int8 IQ pairs to complex64
                iq_int8 = np.frombuffer(raw, dtype=np.int8)
                iq_int8 = iq_int8[:len(iq_int8) - len(iq_int8) % 2]
                iq_pairs = iq_int8.reshape(-1, 2)
                samples = (iq_pairs[:, 0].astype(np.float32) +
                           1j * iq_pairs[:, 1].astype(np.float32)) / 128.0

                try:
                    sample_queue.put_nowait(samples)
                except queue.Full:
                    # Drop the OLDEST queued block, then enqueue the new one.
                    # This guarantees the consumer always processes the most
                    # recent samples — better real-time latency than letting
                    # the parser fall behind by many seconds.
                    try:
                        sample_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        sample_queue.put_nowait(samples)
                    except queue.Full:
                        pass
                    now = time.time()
                    if now < warmup_deadline:
                        # Startup transient — don't surface as "degraded".
                        continue
                    # Initialise drop tracking lazily. server.py:_run_capture
                    # pre-creates _drop_count=0 between retries but deletes
                    # _drop_first, so anchor the "is this a fresh window?"
                    # check on _drop_first, not _drop_count.
                    if not hasattr(self, '_drop_first'):
                        self._drop_first = now
                        self._drop_count = 0
                    self._drop_count += 1
                    # Log every 50 drops to avoid spam
                    if self._drop_count % 50 == 1:
                        print(f"  [WARN] HackRF can't keep up — dropped {self._drop_count} blocks "
                              f"({(now - self._drop_first):.1f}s); reduce sample rate or move parsers off this capture")
            except Exception as e:
                if not self._stop_event.is_set():
                    import traceback
                    print(f"  [ERROR] HackRF reader thread died ({self.center_freq/1e6:.1f} MHz): {type(e).__name__}: {e}", flush=True)
                    traceback.print_exc()
                    break

    def _drain_stderr(self):
        """Read stderr and print errors."""
        while self._process and self._process.poll() is None:
            try:
                line = self._process.stderr.readline()
                if line:
                    msg = line.decode('utf-8', errors='replace').strip()
                    if msg and 'hackrf' in msg.lower():
                        print(f"  [HackRF] {msg}")
            except Exception:
                break

    def _cleanup(self):
        """Terminate hackrf_transfer."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            except Exception:
                pass
            self._process = None

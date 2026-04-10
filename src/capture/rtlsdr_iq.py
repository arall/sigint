"""
RTL-SDR IQ Capture Source — owns one RTL-SDR dongle and streams IQ
samples to registered parser callbacks.

Emits numpy complex64 arrays (IQ sample blocks) via async streaming.
Reusable at any frequency — keyfob, TPMS, LoRa, etc.

Requirements:
- pyrtlsdr
- RTL-SDR dongle (e.g., RTL-SDR Blog V4)
"""

import queue
import threading
import time

from capture.base import BaseCaptureSource


class RTLSDRCaptureSource(BaseCaptureSource):
    """Captures IQ samples from an RTL-SDR dongle via async streaming."""

    def __init__(
        self,
        center_freq,
        sample_rate=2.0e6,
        gain=40,
        device_index=0,
        block_size=256 * 1024,
    ):
        super().__init__()
        self.center_freq = center_freq
        self.sample_rate = sample_rate
        self.gain = gain
        self.device_index = device_index
        self.block_size = block_size
        self._sdr = None

    def start(self):
        """Open SDR, start async reader, emit IQ blocks. Blocks until stop()."""
        import utils.loader  # noqa: F401 — must import before rtlsdr on macOS
        from rtlsdr import RtlSdr

        self._sdr = RtlSdr(self.device_index)
        try:
            self._sdr.sample_rate = self.sample_rate
            self._sdr.center_freq = self.center_freq
            self._sdr.gain = self.gain

            print(f"[*] RTL-SDR: {self._sdr.center_freq/1e6:.3f} MHz, "
                  f"{self._sdr.sample_rate/1e6:.1f} MS/s, gain {self._sdr.gain} dB")

            time.sleep(1)  # Let AGC settle

            sample_queue = queue.Queue(maxsize=64)
            reader = threading.Thread(
                target=self._async_reader,
                args=(sample_queue,),
                daemon=True,
            )
            reader.start()

            while not self._stop_event.is_set():
                try:
                    samples = sample_queue.get(timeout=2.0)
                except queue.Empty:
                    continue
                self._emit(samples)

        finally:
            self._cleanup()

    def stop(self):
        """Signal the capture to stop."""
        self._stop_event.set()

    def _async_reader(self, sample_queue):
        """Background thread that reads IQ samples via async streaming."""
        def callback(samples, _context):
            if self._stop_event.is_set():
                self._sdr.cancel_read_async()
                return
            try:
                sample_queue.put_nowait(samples)
            except queue.Full:
                pass  # Drop if consumer can't keep up

        try:
            self._sdr.read_samples_async(callback, self.block_size)
        except Exception:
            if not self._stop_event.is_set():
                raise

    def _cleanup(self):
        """Close the SDR device."""
        if self._sdr:
            try:
                self._sdr.close()
            except Exception:
                pass
            self._sdr = None

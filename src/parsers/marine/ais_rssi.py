"""
AIS channel RSSI monitor.

rtl_ais is an exclusive SDR consumer and its NMEA output carries no
signal-level information — see docs/roadmap.md "AIS RSSI capture".
This module runs a **parallel** RSSI sampler on a second RTL-SDR,
continuously measuring power on AIS1 (161.975 MHz) and AIS2
(162.025 MHz). The `AISParser` queries it at log time so decoded
vessel detections get real `power_db` instead of the uncalibratable
zero that rtl_ais gives us.

When only one SDR is available, callers should simply not start this
thread; the parser tolerates a missing monitor and falls back to
`power_db=0` (unchanged pre-commit behaviour). The calibration
extractor drops those rows defensively, so no corrupted samples
leak into the fit.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional


AIS_CENTER_FREQ = 162.0e6
AIS1_FREQ = 161.975e6
AIS2_FREQ = 162.025e6
DEFAULT_SAMPLE_RATE = 1.6e6
DEFAULT_SAMPLES = 256 * 1024
RING_SIZE = 100
AIS_CHANNEL_BW_HZ = 12500


class AISChannelRSSI:
    """Background thread: samples AIS1 + AIS2 power from a secondary RTL-SDR.

    Public API is deliberately small — the parser only needs
    `recent_power(freq_hz=...)` and the scanner needs `start`/`stop`.
    """

    def __init__(
        self,
        device_index: int,
        gain: int = 40,
        sample_rate: float = DEFAULT_SAMPLE_RATE,
        samples_per_read: int = DEFAULT_SAMPLES,
        ring_size: int = RING_SIZE,
        max_age_s: float = 3.0,
    ):
        self._device_index = device_index
        self._gain = gain
        self._sample_rate = sample_rate
        self._samples_per_read = samples_per_read
        self._max_age_s = max_age_s
        self._ring: deque = deque(maxlen=ring_size)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sdr = None

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._sdr is not None:
            try:
                self._sdr.close()
            except Exception:
                pass
            self._sdr = None

    # -- sampling loop ---------------------------------------------------

    def _loop(self) -> None:
        # Import heavy deps lazily so the parser module stays import-safe
        # even if pyrtlsdr / scipy aren't installed.
        try:
            import utils.loader  # noqa: F401
            from rtlsdr import RtlSdr
            from scipy import signal as _sig
            import numpy as np
        except Exception as e:
            print(f"[AIS-RSSI] startup failed: {e}")
            return

        try:
            self._sdr = RtlSdr(self._device_index)
            self._sdr.sample_rate = self._sample_rate
            self._sdr.center_freq = AIS_CENTER_FREQ
            self._sdr.gain = self._gain
        except Exception as e:
            print(f"[AIS-RSSI] SDR open failed: {e}")
            return

        try:
            while not self._stop.is_set():
                try:
                    samples = self._sdr.read_samples(self._samples_per_read)
                    a1, a2 = self._compute_channel_power(samples, _sig, np)
                except Exception as e:
                    print(f"[AIS-RSSI] sample error: {e}")
                    time.sleep(0.5)
                    continue
                with self._lock:
                    self._ring.append((time.time(), a1, a2))
        finally:
            try:
                self._sdr.close()
            except Exception:
                pass
            self._sdr = None

    def _compute_channel_power(self, samples, _sig, np) -> tuple:
        """Welch PSD over the AIS band, return (ais1_db, ais2_db) in dBFS."""
        freqs, psd = _sig.welch(samples, fs=self._sample_rate, nperseg=4096)
        freqs = freqs + AIS_CENTER_FREQ - self._sample_rate / 2
        ais1_mask = np.abs(freqs - AIS1_FREQ) < AIS_CHANNEL_BW_HZ
        ais2_mask = np.abs(freqs - AIS2_FREQ) < AIS_CHANNEL_BW_HZ
        a1 = float(10 * np.log10(np.mean(psd[ais1_mask]) + 1e-10))
        a2 = float(10 * np.log10(np.mean(psd[ais2_mask]) + 1e-10))
        return a1, a2

    # -- queries ---------------------------------------------------------

    def recent_power(
        self,
        freq_hz: Optional[float] = None,
        max_age_s: Optional[float] = None,
    ) -> Optional[float]:
        """Return the most recent in-window RSSI for the channel nearest
        `freq_hz`. When `freq_hz` is None, returns max(ais1, ais2) —
        rtl_ais doesn't tell us which channel decoded the NMEA, so the
        strong channel is our best-effort attribution.
        """
        max_age = self._max_age_s if max_age_s is None else max_age_s
        now = time.time()
        with self._lock:
            if not self._ring:
                return None
            ts, a1, a2 = self._ring[-1]
        if (now - ts) > max_age:
            return None
        if freq_hz is None:
            return max(a1, a2)
        # Closest channel wins.
        if abs(freq_hz - AIS1_FREQ) <= abs(freq_hz - AIS2_FREQ):
            return a1
        return a2

    # -- test hooks ------------------------------------------------------

    def inject_sample_for_tests(self, ais1_db: float, ais2_db: float,
                                 ts: Optional[float] = None) -> None:
        """Append a synthetic sample. Only for tests — no SDR needed."""
        with self._lock:
            self._ring.append((ts if ts is not None else time.time(),
                               float(ais1_db), float(ais2_db)))

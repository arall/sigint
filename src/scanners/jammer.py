"""
Jammer / broadband-interference scanner.

Hops across a configurable list of bands, samples ~1 s of IQ at each,
feeds the result through `dsp.jammer` and emits a SignalDetection when
sustained broadband energy raises the noise floor above a per-band
baseline. See docs/scanners.md for the detection model and what's
(not) caught.

Design notes:
- One RTL-SDR per instance. Multiple bands = sequential hops; revisit
  time is ~(dwell × num_bands), so a 5-band default = 5 s between
  revisits per band. Fine for sustained jamming, misses sub-dwell
  bursts by design.
- Baseline is established on first run (~CALIBRATION_SAMPLES samples
  per band) and persisted to `output/jammer_baseline.json`. Subsequent
  runs load the saved baseline so a jammer active at startup doesn't
  calibrate itself out.
- Detections are logged with `signal_type="jamming"` + a per-band
  `channel` label; metadata carries `baseline_db`, `observed_db`,
  `elevation_db`, `flatness`, `bandwidth_hz`. Calibration offsets
  apply transparently — the dashboard reads absolute dBm.
"""

from __future__ import annotations

import json
import os
import signal as sig
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Project root (parent of src)
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.loader  # noqa: F401,E402 - required before rtlsdr on macOS
import numpy as np  # noqa: E402
from rtlsdr import RtlSdr  # noqa: E402

from dsp.jammer import (  # noqa: E402
    BandSample, DetectionState, band_sample_from_iq, decide, run_baseline,
)
from utils.logger import SignalLogger  # noqa: E402


# Default RTL-SDR-compatible bands. Each: (label, center_hz, bw_hz).
# The bw_hz drives the IQ sample rate — a 2 MHz window gives enough
# resolution to see "broadband raised floor vs narrowband peak" without
# blowing past the RTL-SDR's comfortable rate. 2.4 / 5.8 GHz need a
# HackRF; not in the default list.
DEFAULT_BANDS: List[tuple] = [
    ("GPS-L1",      1575.42e6, 2.0e6),
    ("Meshtastic-EU", 869.525e6, 0.5e6),
    ("ISM-915",      915.0e6,   1.0e6),
    ("GSM-900-DL",   942.5e6,   10.0e6),  # band-wide, capped to RTL rate below
    ("Marine-VHF",   162.0e6,   0.5e6),
]

DEFAULT_GAIN = 40
MIN_SAMPLE_RATE_HZ = 1.0e6      # lower bound for the RTL-SDR; below this
                                 # the dongle doesn't lock properly
MAX_SAMPLE_RATE_HZ = 2.4e6      # practical RTL-SDR ceiling
SAMPLES_PER_DWELL = 256 * 1024  # ~0.1-0.25 s depending on rate
DEFAULT_DWELL_S = 1.0
DEFAULT_HOP_SLEEP_S = 0.05      # settling time after a retune
CALIBRATION_SAMPLES = 10        # per band, at scanner start


def _clamp_sample_rate(bw_hz: float) -> float:
    """RTL-SDR sample rate has to cover the band, with a bit of margin,
    but can't exceed what the dongle can stream cleanly."""
    # 1.25× margin so the band isn't right at the edge of the Nyquist.
    wanted = max(MIN_SAMPLE_RATE_HZ, bw_hz * 1.25)
    return float(min(wanted, MAX_SAMPLE_RATE_HZ))


@dataclass
class BandConfig:
    label: str
    center_hz: float
    bw_hz: float
    sample_rate: float = 0.0

    def __post_init__(self):
        if self.sample_rate <= 0:
            self.sample_rate = _clamp_sample_rate(self.bw_hz)


class JammerScanner:
    """RTL-SDR-driven broadband-interference scanner."""

    def __init__(
        self,
        output_dir: Optional[str] = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        gain: int = DEFAULT_GAIN,
        bands: Optional[List[BandConfig]] = None,
        dwell_s: float = DEFAULT_DWELL_S,
        elevation_threshold_db: float = 10.0,
        flatness_threshold: float = 0.5,
        min_consec: int = 3,
        recalibrate: bool = False,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")
        self.output_dir = output_dir
        self.device_index = device_index
        self.gain = gain
        self.dwell_s = dwell_s
        self.elevation_threshold_db = elevation_threshold_db
        self.flatness_threshold = flatness_threshold
        self.min_consec = min_consec
        self.recalibrate = recalibrate
        if bands is None:
            bands = [BandConfig(label=l, center_hz=c, bw_hz=bw)
                     for l, c, bw in DEFAULT_BANDS]
        self.bands = bands

        os.makedirs(output_dir, exist_ok=True)
        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="jamming",
            device_id=device_id,
            min_snr_db=0,
        )

        # Per-band rolling detection state. Keyed by band label so a
        # re-ordered band list picks up where the old run left off.
        self._states: Dict[str, DetectionState] = {
            b.label: DetectionState() for b in self.bands
        }
        self._sdr: Optional[RtlSdr] = None
        self._stop = False

    # -- persistence -----------------------------------------------------

    @property
    def baseline_path(self) -> str:
        return os.path.join(self.output_dir, "jammer_baseline.json")

    def _load_baselines(self) -> None:
        if self.recalibrate or not os.path.exists(self.baseline_path):
            return
        try:
            with open(self.baseline_path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for band in self.bands:
            b = data.get(band.label)
            if isinstance(b, dict) and "baseline_db" in b:
                try:
                    self._states[band.label].baseline_db = float(b["baseline_db"])
                except (TypeError, ValueError):
                    pass

    def _save_baselines(self) -> None:
        data = {
            band.label: {
                "baseline_db": self._states[band.label].baseline_db,
                "center_hz": band.center_hz,
                "bw_hz": band.bw_hz,
                "saved_at": time.time(),
            }
            for band in self.bands
            if self._states[band.label].baseline_db is not None
        }
        tmp = self.baseline_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.baseline_path)

    # -- sampling --------------------------------------------------------

    def _sample_band(self, band: BandConfig) -> Optional[BandSample]:
        """Tune, settle, read IQ, reduce to a BandSample."""
        try:
            self._sdr.sample_rate = band.sample_rate
            self._sdr.center_freq = band.center_hz
            self._sdr.gain = self.gain
        except Exception as e:
            print(f"[jammer] retune failed for {band.label}: {e}", file=sys.stderr)
            return None
        time.sleep(DEFAULT_HOP_SLEEP_S)
        try:
            samples = self._sdr.read_samples(SAMPLES_PER_DWELL)
        except Exception as e:
            print(f"[jammer] read failed for {band.label}: {e}", file=sys.stderr)
            return None
        return band_sample_from_iq(samples, band.sample_rate)

    def _calibrate_band(self, band: BandConfig) -> None:
        """Gather CALIBRATION_SAMPLES, set baseline from their median."""
        state = self._states[band.label]
        if state.baseline_db is not None and not self.recalibrate:
            return
        print(f"[jammer] calibrating {band.label} "
              f"({CALIBRATION_SAMPLES} samples)...")
        readings: List[BandSample] = []
        for _ in range(CALIBRATION_SAMPLES):
            s = self._sample_band(band)
            if s is not None:
                readings.append(s)
            if self._stop:
                return
        if readings:
            state.baseline_db = run_baseline(readings)
            print(f"[jammer] {band.label} baseline: "
                  f"{state.baseline_db:+.1f} dBFS "
                  f"(flatness {np.mean([r.flatness for r in readings]):.2f})")

    # -- main loop -------------------------------------------------------

    def scan(self) -> None:
        def _stop_handler(signum, frame):
            self._stop = True
        sig.signal(sig.SIGINT, _stop_handler)
        sig.signal(sig.SIGTERM, _stop_handler)

        print("=" * 70)
        print("           Jammer / broadband-interference scanner")
        print("=" * 70)
        print(f"Bands ({len(self.bands)}):")
        for b in self.bands:
            print(f"  {b.label:<16}  {b.center_hz/1e6:>9.3f} MHz  "
                  f"bw {b.bw_hz/1e6:>5.2f} MHz  sr {b.sample_rate/1e6:.2f} MS/s")
        print(f"Threshold: +{self.elevation_threshold_db:.1f} dB over baseline, "
              f"flatness > {self.flatness_threshold:.2f}, "
              f"consec: {self.min_consec}")
        print("-" * 70)

        output_file = self.logger.start()
        print(f"Logging to: {output_file}")

        try:
            self._sdr = RtlSdr(self.device_index)
        except Exception as e:
            print(f"[jammer] SDR open failed: {e}", file=sys.stderr)
            self.logger.stop()
            return

        try:
            self._load_baselines()
            for band in self.bands:
                if self._stop:
                    break
                self._calibrate_band(band)
            self._save_baselines()
            if self._stop:
                return

            print("\n[jammer] watching bands (Ctrl-C to stop)\n")
            while not self._stop:
                for band in self.bands:
                    if self._stop:
                        break
                    self._step(band)
                    # Dwell-per-band pacing: sleep out the remaining time
                    # budget so we don't peg CPU spinning on fast dongles.
                    time.sleep(max(0.0, self.dwell_s
                                        - DEFAULT_HOP_SLEEP_S
                                        - 0.05))
        finally:
            self._save_baselines()
            try:
                self._sdr.close()
            except Exception:
                pass
            total = self.logger.stop()
            print(f"\n[jammer] total detections logged: {total}")

    def _step(self, band: BandConfig) -> None:
        sample = self._sample_band(band)
        if sample is None:
            return
        state = self._states[band.label]
        fired, transition_off = decide(
            sample, state,
            elevation_threshold_db=self.elevation_threshold_db,
            flatness_threshold=self.flatness_threshold,
            min_consec=self.min_consec,
        )
        if fired:
            self._emit(band, sample, state)
        elif transition_off:
            print(f"[jammer] {band.label}: cleared "
                  f"(floor back to {sample.noise_floor_db:+.1f} dBFS)")

    def _emit(self, band: BandConfig, sample: BandSample,
              state: DetectionState) -> None:
        baseline = state.baseline_db or sample.noise_floor_db
        elevation = sample.noise_floor_db - baseline
        meta = {
            "baseline_db": round(baseline, 2),
            "observed_db": round(sample.noise_floor_db, 2),
            "elevation_db": round(elevation, 2),
            "flatness": round(sample.flatness, 3),
            "bandwidth_hz": band.bw_hz,
            "bins": sample.bins,
        }
        print(f"[jammer] {band.label}: JAMMING elev +{elevation:.1f} dB, "
              f"flat {sample.flatness:.2f}")
        self.logger.log_signal(
            signal_type="jamming",
            frequency_hz=band.center_hz,
            power_db=sample.noise_floor_db,
            noise_floor_db=baseline,
            channel=band.label,
            metadata=json.dumps(meta),
        )

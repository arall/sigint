"""
Wideband Energy Detection Scanner

Monitors a 2.4 MHz window and detects ANY transmission by measuring
energy per frequency bin. Designed for signal detection + RSSI measurement,
not protocol decoding. Foundation for multi-node triangulation.

Identifies known channels (PMR446, FRS/GMRS, Baofeng, etc.) when detected.

Usage:
    python sdr.py scan                  # Scan around 446 MHz (PMR/UHF)
    python sdr.py scan -f 162           # Scan AIS band
    python sdr.py scan -f 446 -b 25    # 25 kHz bins
"""

import sys
import os
import time
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.loader  # noqa: F401,E402

import numpy as np  # noqa: E402
from rtlsdr import RtlSdr  # noqa: E402

from utils.logger import SignalLogger  # noqa: E402

# Defaults
DEFAULT_CENTER_FREQ = 446.05e6
DEFAULT_SAMPLE_RATE = 2.4e6
DEFAULT_GAIN = 40
DEFAULT_NUM_SAMPLES = 256 * 1024
DEFAULT_BIN_WIDTH = 12500  # 12.5 kHz

# Known channel database
# Each entry: (frequency_hz, name, service)
KNOWN_CHANNELS = []

# PMR446 (EU, 16 channels: 8 analog + 8 digital)
for i, f in enumerate([446.00625, 446.01875, 446.03125, 446.04375,
                        446.05625, 446.06875, 446.08125, 446.09375], 1):
    KNOWN_CHANNELS.append((f * 1e6, f"PMR CH{i}", "PMR446"))
for i, f in enumerate([446.10625, 446.11875, 446.13125, 446.14375,
                        446.15625, 446.16875, 446.18125, 446.19375], 9):
    KNOWN_CHANNELS.append((f * 1e6, f"PMR CH{i}", "PMR446-D"))

# FRS / GMRS (US)
_frs = [462.5625, 462.5875, 462.6125, 462.6375, 462.6625, 462.6875, 462.7125,
        467.5625, 467.5875, 467.6125, 467.6375, 467.6625, 467.6875, 467.7125,
        462.5500, 462.5750, 462.6000, 462.6250, 462.6500, 462.6750, 462.7000, 462.7250]
for i, f in enumerate(_frs, 1):
    KNOWN_CHANNELS.append((f * 1e6, f"FRS/GMRS CH{i}", "FRS"))

# Common Baofeng / ham UHF repeater outputs (EU/US)
for f in [433.500, 434.000, 434.500, 435.000, 438.500, 439.000, 439.500,
          440.000, 440.500, 441.000, 442.000, 443.000, 444.000, 445.000,
          446.500, 447.000, 448.000, 449.000]:
    KNOWN_CHANNELS.append((f * 1e6, f"UHF {f:.1f}", "Ham-UHF"))

# Common Baofeng / ham VHF
for f in [144.800, 145.000, 145.200, 145.500, 145.600, 146.000, 146.520,
          146.940, 147.000, 147.060, 147.300, 147.500]:
    KNOWN_CHANNELS.append((f * 1e6, f"VHF {f:.1f}", "Ham-VHF"))

# AIS
KNOWN_CHANNELS.append((161.975e6, "AIS-1 (87B)", "AIS"))
KNOWN_CHANNELS.append((162.025e6, "AIS-2 (88B)", "AIS"))

# NOAA weather
for i, f in enumerate([162.400, 162.425, 162.450, 162.475, 162.500, 162.525, 162.550], 1):
    KNOWN_CHANNELS.append((f * 1e6, f"NOAA WX{i}", "NOAA"))

# CB Radio (27 MHz)
_cb_base = 26.965
_cb_freqs = [_cb_base + i * 0.010 for i in range(40)]
# CB has gaps, use the standard 40-channel plan
_cb_plan = [
    26.965, 26.975, 26.985, 27.005, 27.015, 27.025, 27.035, 27.055,
    27.065, 27.075, 27.085, 27.105, 27.115, 27.125, 27.135, 27.155,
    27.165, 27.175, 27.185, 27.205, 27.215, 27.225, 27.255, 27.235,
    27.245, 27.265, 27.275, 27.285, 27.295, 27.305, 27.315, 27.325,
    27.335, 27.345, 27.355, 27.365, 27.375, 27.385, 27.395, 27.405
]
for i, f in enumerate(_cb_plan, 1):
    KNOWN_CHANNELS.append((f * 1e6, f"CB CH{i}", "CB"))

# Sort by frequency for efficient lookup
KNOWN_CHANNELS.sort(key=lambda x: x[0])


def identify_channel(freq_hz: float, tolerance_hz: float = 15000) -> Optional[Tuple[str, str]]:
    """Match a frequency to the closest known channel within tolerance.

    Returns (name, service) or None if no match within tolerance.
    """
    best = None
    best_dist = tolerance_hz + 1
    for ch_freq, name, service in KNOWN_CHANNELS:
        dist = abs(freq_hz - ch_freq)
        if dist <= tolerance_hz and dist < best_dist:
            best = (name, service)
            best_dist = dist
    return best


def calculate_power_spectrum(samples, sample_rate):
    """Calculate power spectrum using FFT."""
    fft_result = np.fft.fftshift(np.fft.fft(samples))
    power_spectrum = 20 * np.log10(np.abs(fft_result) + 1e-10)
    freqs = np.fft.fftshift(np.fft.fftfreq(len(samples), 1 / sample_rate))
    return freqs, power_spectrum


def get_bin_power(freqs, power_spectrum, center_freq, bin_center_freq, bin_width):
    """Calculate mean power for a frequency bin."""
    actual_freq = freqs + center_freq
    mask = (actual_freq >= bin_center_freq - bin_width / 2) & (
        actual_freq <= bin_center_freq + bin_width / 2)
    if np.any(mask):
        return np.mean(power_spectrum[mask])
    return -100


class Detection:
    """An active or completed signal detection, possibly spanning multiple bins."""

    def __init__(self, center_freq: float, power: float, snr: float):
        self.center_freq = center_freq
        self.peak_power = power
        self.peak_snr = snr
        self.start_time = datetime.now()
        self.last_seen = time.time()
        self.active = True
        self.bin_indices = set()
        # Channel identification
        match = identify_channel(center_freq)
        self.channel_name = match[0] if match else None
        self.channel_service = match[1] if match else None
        # AMC classification
        self.modulation = None
        self.mod_confidence = 0.0

    def update(self, power: float, snr: float):
        self.last_seen = time.time()
        if power > self.peak_power:
            self.peak_power = power
        if snr > self.peak_snr:
            self.peak_snr = snr

    @property
    def duration(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def label(self) -> str:
        if self.channel_name:
            return f"{self.channel_name}"
        return f"{self.center_freq/1e6:.4f} MHz"


class WidebandScanner:
    """Wideband energy detection scanner.

    Divides the RTL-SDR's capture bandwidth into frequency bins and
    detects transmissions by measuring energy above noise floor.
    Merges adjacent active bins into single detections.
    Identifies known channels (PMR, FRS, ham, etc.).
    """

    HOLDOVER_TIME = 1.5  # Seconds before ending a detection

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        center_freq: float = DEFAULT_CENTER_FREQ,
        gain: int = DEFAULT_GAIN,
        bin_width: float = DEFAULT_BIN_WIDTH,
        min_snr_db: float = 10.0,
        sample_rate: float = DEFAULT_SAMPLE_RATE,
        classify: bool = False,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.device_id = device_id
        self.device_index = device_index
        self.center_freq = center_freq
        self.gain = gain
        self.bin_width = bin_width
        self.min_snr_db = min_snr_db
        self.sample_rate = sample_rate
        self.num_samples = DEFAULT_NUM_SAMPLES

        # Compute bin layout
        half_bw = sample_rate / 2
        self.bin_centers = np.arange(
            center_freq - half_bw + bin_width / 2,
            center_freq + half_bw,
            bin_width
        )
        self.num_bins = len(self.bin_centers)

        self.classify = classify
        self._classifier = None
        if classify:
            from dsp.amc import classify_modulation
            self._classifier = classify_modulation

        # Active detections (merged from adjacent bins)
        self._detections: Dict[int, Detection] = {}  # detection_id -> Detection
        self._bin_to_detection: Dict[int, int] = {}   # bin_idx -> detection_id
        self._next_detection_id = 0

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="wideband",
            device_id=device_id,
            min_snr_db=min_snr_db,
        )
        self.sdr = None

    def _find_or_create_detection(self, bin_idx: int, freq: float,
                                  power: float, snr: float) -> int:
        """Find an existing detection for this bin or adjacent bins, or create new."""
        # Check if this bin is already part of a detection
        if bin_idx in self._bin_to_detection:
            det_id = self._bin_to_detection[bin_idx]
            det = self._detections[det_id]
            # Update center freq to strongest bin in this frame
            if power > det.peak_power:
                det.center_freq = freq
                self._re_identify(det)
            det.update(power, snr)
            return det_id

        # Check adjacent bins for an existing detection to merge with
        for neighbor in [bin_idx - 1, bin_idx + 1]:
            if neighbor in self._bin_to_detection:
                det_id = self._bin_to_detection[neighbor]
                det = self._detections[det_id]
                det.bin_indices.add(bin_idx)
                self._bin_to_detection[bin_idx] = det_id
                if power > det.peak_power:
                    det.center_freq = freq
                    self._re_identify(det)
                det.update(power, snr)
                return det_id

        # New detection
        det_id = self._next_detection_id
        self._next_detection_id += 1
        det = Detection(freq, power, snr)
        det.bin_indices.add(bin_idx)
        self._detections[det_id] = det
        self._bin_to_detection[bin_idx] = det_id
        return det_id

    @staticmethod
    def _re_identify(det: Detection):
        """Re-run channel identification after center frequency changed."""
        match = identify_channel(det.center_freq)
        if match:
            det.channel_name = match[0]
            det.channel_service = match[1]

    def _filter_spurious(self, active_bins: Dict[int, Tuple[float, float, float]]
                         ) -> Dict[int, Tuple[float, float, float]]:
        """Remove likely image and intermod artifacts.

        Suppresses:
        1. Mirror images symmetric around center freq or any strong signal
        2. Intermod pairs symmetric around a strong signal
        3. Weak signals within the capture bandwidth of a much stronger one
        """
        if not active_bins:
            return active_bins

        filtered = dict(active_bins)
        to_remove = set()
        bin_tolerance = 3  # bins of slop when matching mirror frequencies

        # 1. Mirror image rejection around center frequency
        for idx, (freq, power, snr) in list(filtered.items()):
            mirror_freq = 2 * self.center_freq - freq
            mirror_idx = int(np.argmin(np.abs(self.bin_centers - mirror_freq)))
            if mirror_idx in filtered and mirror_idx != idx:
                mirror_power = filtered[mirror_idx][1]
                if mirror_power - power >= 8:
                    to_remove.add(idx)

        # 2. Intermod rejection: find pairs of weak signals symmetric around
        #    a strong signal — classic 2nd-order intermod products.
        sorted_bins = sorted(filtered.items(), key=lambda x: x[1][1], reverse=True)
        strong = [(idx, f, p) for idx, (f, p, s) in sorted_bins if s >= 20]

        for strong_idx, strong_freq, strong_power in strong:
            for idx, (freq, power, snr) in list(filtered.items()):
                if idx == strong_idx or idx in to_remove:
                    continue
                # Check if this bin has a mirror around the strong signal
                mirror_freq = 2 * strong_freq - freq
                mirror_idx = int(np.argmin(np.abs(self.bin_centers - mirror_freq)))
                if abs(self.bin_centers[mirror_idx] - mirror_freq) > bin_tolerance * self.bin_width:
                    continue
                if mirror_idx in filtered and mirror_idx != idx:
                    # Both sides of the intermod pair exist — suppress both
                    # if significantly weaker than the strong signal
                    if strong_power - power >= 10:
                        to_remove.add(idx)
                    mirror_power = filtered[mirror_idx][1]
                    if strong_power - mirror_power >= 10:
                        to_remove.add(mirror_idx)

        # 3. Spectral leakage: suppress weak signals anywhere in the capture
        #    bandwidth if a much stronger signal exists (>15 dB difference).
        for i, (idx_a, (_, power_a, _)) in enumerate(sorted_bins):
            if idx_a in to_remove:
                continue
            for idx_b, (_, power_b, _) in sorted_bins[i + 1:]:
                if idx_b in to_remove:
                    continue
                if (power_a - power_b) >= 15:
                    to_remove.add(idx_b)

        for idx in to_remove:
            del filtered[idx]

        return filtered

    def _process_bins(self, bin_powers: np.ndarray, noise_floor: float,
                      samples=None):
        """Process all bins: detect signals, merge adjacent, track state."""
        now = time.time()
        active_bin_set = set()

        # Collect bins above threshold
        candidate_bins: Dict[int, Tuple[float, float, float]] = {}
        for i, bin_freq in enumerate(self.bin_centers):
            snr = bin_powers[i] - noise_floor
            if snr >= self.min_snr_db:
                candidate_bins[i] = (bin_freq, bin_powers[i], snr)

        # Filter out image artifacts and spectral leakage
        clean_bins = self._filter_spurious(candidate_bins)

        # Create/update detections from clean bins
        for i, (bin_freq, power, snr) in clean_bins.items():
            active_bin_set.add(i)
            self._find_or_create_detection(i, bin_freq, power, snr)

        # Check for expired detections
        expired = []
        for det_id, det in self._detections.items():
            if not det.active:
                continue

            # Check if any of this detection's bins are still active
            still_active = any(b in active_bin_set for b in det.bin_indices)

            if still_active:
                det.last_seen = now
                # Run AMC on first detection if enabled and not yet classified
                if (self._classifier and samples is not None
                        and det.modulation is None and det.peak_snr > self.min_snr_db):
                    try:
                        # Extract IQ around detection frequency
                        freq_offset = det.center_freq - self.center_freq
                        t = np.arange(len(samples)) / self.sample_rate
                        shifted = samples * np.exp(-1j * 2 * np.pi * freq_offset * t)
                        # Low-pass to detection bandwidth
                        seg_len = min(4096, len(shifted))
                        amc_result = self._classifier(shifted[:seg_len], self.sample_rate)
                        if amc_result["modulation"] != "Noise":
                            det.modulation = amc_result["modulation"]
                            det.mod_confidence = amc_result["confidence"]
                    except Exception:
                        pass
            elif now - det.last_seen >= self.HOLDOVER_TIME:
                # Transmission ended
                det.active = False
                expired.append(det_id)

                meta = {
                    "duration_s": round(det.duration, 2),
                    "peak_snr_db": round(det.peak_snr, 1),
                    "bin_width_hz": self.bin_width,
                    "num_bins": len(det.bin_indices),
                }
                if det.modulation:
                    meta["modulation"] = det.modulation
                    meta["mod_confidence"] = round(det.mod_confidence, 2)

                self.logger.log_signal(
                    signal_type=det.channel_service or "unknown",
                    frequency_hz=det.center_freq,
                    power_db=det.peak_power,
                    noise_floor_db=noise_floor,
                    channel=det.channel_name,
                    metadata=json.dumps(meta),
                )

        # Clean up expired detections
        for det_id in expired:
            det = self._detections[det_id]
            for b in det.bin_indices:
                self._bin_to_detection.pop(b, None)
            del self._detections[det_id]

    def _display(self, bin_powers: np.ndarray, noise_floor: float):
        """Display spectrum and active detections."""
        print("\033[H\033[J", end="")

        freq_lo = self.bin_centers[0] / 1e6
        freq_hi = self.bin_centers[-1] / 1e6

        print("=" * 70)
        print("          Wideband Energy Scanner - RTL-SDR")
        print("=" * 70)
        print(f"  Center: {self.center_freq/1e6:.3f} MHz  |"
              f"  Range: {freq_lo:.3f} - {freq_hi:.3f} MHz")
        print(f"  Bins: {self.num_bins} x {self.bin_width/1e3:.1f} kHz  |"
              f"  Noise: {noise_floor:.1f} dB  |"
              f"  Threshold: +{self.min_snr_db:.0f} dB")
        print(f"  Detections logged: {self.logger.detection_count}")
        print("-" * 70)

        # Spectrum bar
        bar_width = 64
        bins_per_char = max(1, self.num_bins // bar_width)
        bar = ""
        for i in range(0, min(self.num_bins, bar_width * bins_per_char), bins_per_char):
            chunk = bin_powers[i:i + bins_per_char]
            max_snr = np.max(chunk) - noise_floor
            if max_snr >= self.min_snr_db:
                bar += "\033[91m█\033[0m"
            elif max_snr >= self.min_snr_db * 0.5:
                bar += "\033[93m▓\033[0m"
            else:
                bar += "\033[90m░\033[0m"
        print(f"  [{bar}]")
        print(f"   {freq_lo:<.3f}{' ' * (bar_width - 18)}{freq_hi:>.3f} MHz")
        print("-" * 70)

        # Active detections (merged, identified)
        active = [d for d in self._detections.values() if d.active]
        active.sort(key=lambda d: d.peak_power, reverse=True)

        if active:
            hdr_mod = " {'Modulation':>12s}" if self.classify else ""
            print(f"  {'Signal':<22s} {'Freq':>11s} {'Power':>7s}"
                  f" {'SNR':>6s} {'Dur':>6s}"
                  + (f"  {'Modulation':>12s}" if self.classify else "")
                  + f"  {'Strength'}")
            print(f"  {'─' * 22} {'─' * 11} {'─' * 7} {'─' * 6} {'─' * 6}"
                  + (f"  {'─' * 12}" if self.classify else "")
                  + f"  {'─' * 20}")
            for det in active[:12]:
                snr_bar_len = int(min(det.peak_snr / 30 * 20, 20))
                snr_bar = "█" * snr_bar_len + "░" * (20 - snr_bar_len)

                label = det.label
                if len(label) > 22:
                    label = label[:19] + "..."

                svc_color = ""
                if det.channel_service == "PMR446":
                    svc_color = "\033[92m"  # Green
                elif det.channel_service == "FRS":
                    svc_color = "\033[94m"  # Blue
                elif det.channel_service in ("Ham-UHF", "Ham-VHF"):
                    svc_color = "\033[95m"  # Magenta
                elif det.channel_service:
                    svc_color = "\033[96m"  # Cyan
                reset = "\033[0m" if svc_color else ""

                mod_str = ""
                if self.classify:
                    if det.modulation:
                        mod_str = f"  {det.modulation:>12s}"
                    else:
                        mod_str = f"  {'...':>12s}"

                freq_str = f"{det.center_freq/1e6:.4f} MHz"
                print(f"  {svc_color}{label:<22s}{reset} {freq_str:>11s}"
                      f" {det.peak_power:>5.1f}dB {det.peak_snr:>4.1f}dB"
                      f" {det.duration:>5.1f}s{mod_str}  {snr_bar}")

            if len(active) > 12:
                print(f"  ... and {len(active) - 12} more")
        else:
            print("  No active transmissions")

        print("-" * 70)
        print("  Ctrl+C to stop")

    def scan(self):
        """Run the wideband scanner."""
        try:
            self.sdr = RtlSdr(self.device_index)
            self.sdr.sample_rate = self.sample_rate
            self.sdr.center_freq = self.center_freq
            self.sdr.gain = self.gain

            # Count known channels in our range
            freq_lo = self.bin_centers[0]
            freq_hi = self.bin_centers[-1]
            known_in_range = [
                (f, n, s) for f, n, s in KNOWN_CHANNELS
                if freq_lo <= f <= freq_hi
            ]

            print(f"Wideband scanner initialized")
            print(f"  Sample rate: {self.sdr.sample_rate/1e6:.1f} MHz")
            print(f"  Center freq: {self.sdr.center_freq/1e6:.3f} MHz")
            print(f"  Gain: {self.sdr.gain} dB")
            print(f"  Bins: {self.num_bins} x {self.bin_width/1e3:.1f} kHz")
            print(f"  Known channels in range: {len(known_in_range)}")
            if known_in_range:
                services = set(s for _, _, s in known_in_range)
                print(f"  Services: {', '.join(sorted(services))}")
            print()

            output_file = self.logger.start()
            print(f"Logging to: {output_file}\n")

            time.sleep(0.5)

            while True:
                samples = self.sdr.read_samples(self.num_samples)
                freqs, power_spectrum = calculate_power_spectrum(
                    samples, self.sample_rate)

                noise_floor = np.median(power_spectrum)

                # Compute power per bin
                bin_powers = np.empty(self.num_bins)
                for i, bin_freq in enumerate(self.bin_centers):
                    bin_powers[i] = get_bin_power(
                        freqs, power_spectrum, self.center_freq,
                        bin_freq, self.bin_width)

                self._process_bins(bin_powers, noise_floor, samples)
                self._display(bin_powers, noise_floor)
                time.sleep(0.2)

        except KeyboardInterrupt:
            print("\n\nStopping scan...")

            # Log remaining active detections
            for det in self._detections.values():
                if det.active:
                    self.logger.log_signal(
                        signal_type=det.channel_service or "unknown",
                        frequency_hz=det.center_freq,
                        power_db=det.peak_power,
                        noise_floor_db=0,
                        channel=det.channel_name,
                        metadata=json.dumps({
                            "duration_s": round(det.duration, 2),
                            "peak_snr_db": round(det.peak_snr, 1),
                            "bin_width_hz": self.bin_width,
                            "num_bins": len(det.bin_indices),
                        }),
                    )

        except Exception as e:
            print(f"\nError: {e}")
            print("Make sure RTL-SDR is connected and pyrtlsdr is installed.")
            import traceback
            traceback.print_exc()

        finally:
            if self.sdr:
                self.sdr.close()
            count = self.logger.stop()
            print(f"Total detections logged: {count}")

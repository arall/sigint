"""
Generic FM Scanner
Configurable narrowband FM scanner with band profiles.
Reuses the PMR446 demodulation pipeline for any FM radio band.

Supports bands wider than 2.4 MHz by hopping between sub-band windows.

Usage:
    python sdr.py fm pmr446              # PMR446 (same as 'sdr.py pmr')
    python sdr.py fm frs                 # FRS/GMRS
    python sdr.py fm marine              # Marine VHF
    python sdr.py fm murs                # MURS
    python sdr.py fm 2m                  # 2m amateur
    python sdr.py fm 70cm                # 70cm amateur
    python sdr.py fm --list              # List available bands
"""

import sys
import os
import json
import time
import threading
import queue
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.loader  # noqa: F401,E402 - Must be imported before rtlsdr

import numpy as np  # noqa: E402
from rtlsdr import RtlSdr  # noqa: E402

from scanners.pmr import (  # noqa: E402
    calculate_power_spectrum,
    get_channel_power,
    extract_and_demodulate_buffers,
    save_audio,
)
from utils.logger import SignalLogger  # noqa: E402
from utils.transcriber import transcribe  # noqa: E402


# ---------------------------------------------------------------------------
# Band profiles
# ---------------------------------------------------------------------------
# Each profile defines channels, bandwidth, FM deviation, and optional windows.
# Channels are {label: frequency_hz}.
# If all channels fit within 2.4 MHz, a single window is used automatically.
# Otherwise, channels are grouped into windows that the scanner hops between.

BAND_PROFILES = {
    "pmr446": {
        "name": "PMR446",
        "description": "EU license-free UHF (446 MHz, 16 channels, 12.5 kHz)",
        "channels": {
            "CH1": 446.00625e6, "CH2": 446.01875e6,
            "CH3": 446.03125e6, "CH4": 446.04375e6,
            "CH5": 446.05625e6, "CH6": 446.06875e6,
            "CH7": 446.08125e6, "CH8": 446.09375e6,
            "CH9": 446.10625e6, "CH10": 446.11875e6,
            "CH11": 446.13125e6, "CH12": 446.14375e6,
            "CH13": 446.15625e6, "CH14": 446.16875e6,
            "CH15": 446.18125e6, "CH16": 446.19375e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
    },
    "frs": {
        "name": "FRS/GMRS",
        "description": "US license-free UHF (462/467 MHz, 22 channels)",
        "channels": {
            # FRS/GMRS 1-7 (12.5 kHz, shared FRS/GMRS)
            "CH1": 462.5625e6, "CH2": 462.5875e6,
            "CH3": 462.6125e6, "CH4": 462.6375e6,
            "CH5": 462.6625e6, "CH6": 462.6875e6,
            "CH7": 462.7125e6,
            # FRS 8-14 (12.5 kHz, FRS only)
            "CH8": 467.5625e6, "CH9": 467.5875e6,
            "CH10": 467.6125e6, "CH11": 467.6375e6,
            "CH12": 467.6625e6, "CH13": 467.6875e6,
            "CH14": 467.7125e6,
            # FRS/GMRS 15-22 (25 kHz, higher power on GMRS)
            "CH15": 462.5500e6, "CH16": 462.5750e6,
            "CH17": 462.6000e6, "CH18": 462.6250e6,
            "CH19": 462.6500e6, "CH20": 462.6750e6,
            "CH21": 462.7000e6, "CH22": 462.7250e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
    },
    "gmrs": {
        "name": "GMRS Repeater",
        "description": "GMRS repeater outputs (467 MHz, 8 channels, 25 kHz)",
        "channels": {
            "RPT1": 462.5500e6, "RPT2": 462.5750e6,
            "RPT3": 462.6000e6, "RPT4": 462.6250e6,
            "RPT5": 462.6500e6, "RPT6": 462.6750e6,
            "RPT7": 462.7000e6, "RPT8": 462.7250e6,
        },
        "channel_bw": 25000,
        "fm_deviation": 5000,
    },
    "marine": {
        "name": "Marine VHF",
        "description": "Maritime channels (156-162 MHz, 25 kHz)",
        "channels": {
            # International marine VHF channels (simplex, most used)
            "CH01": 156.050e6,   # Port operations
            "CH02": 156.100e6,   # Port operations
            "CH03": 156.150e6,   # Port operations
            "CH04": 156.200e6,   # Coast guard liaison
            "CH05": 156.250e6,   # Port operations
            "CH06": 156.300e6,   # Intership safety
            "CH07": 156.350e6,   # Commercial
            "CH08": 156.400e6,   # Commercial
            "CH09": 156.450e6,   # Calling (commercial)
            "CH10": 156.500e6,   # Commercial
            "CH11": 156.550e6,   # VTS (vessel traffic)
            "CH12": 156.600e6,   # Port operations / VTS
            "CH13": 156.650e6,   # Bridge-to-bridge safety
            "CH14": 156.700e6,   # Port operations / VTS
            "CH15": 156.750e6,   # Environmental
            "CH16": 156.800e6,   # Distress / calling
            "CH17": 156.850e6,   # State control
            "CH68": 156.425e6,   # Non-commercial
            "CH69": 156.475e6,   # Non-commercial
            "CH70": 156.525e6,   # DSC (digital selective calling)
            "CH71": 156.575e6,   # Non-commercial
            "CH72": 156.625e6,   # Non-commercial
            "CH73": 156.675e6,   # Port operations
            "CH74": 156.725e6,   # Port operations
            "CH77": 156.875e6,   # Port operations
            # AIS channels
            "AIS1": 161.975e6,
            "AIS2": 162.025e6,
        },
        "channel_bw": 25000,
        "fm_deviation": 5000,
    },
    "murs": {
        "name": "MURS",
        "description": "US Multi-Use Radio Service (151/154 MHz, 5 channels)",
        "channels": {
            "CH1": 151.820e6,  # 11.25 kHz
            "CH2": 151.880e6,  # 11.25 kHz
            "CH3": 151.940e6,  # 11.25 kHz
            "CH4": 154.570e6,  # 20 kHz
            "CH5": 154.600e6,  # 20 kHz
        },
        "channel_bw": 20000,
        "fm_deviation": 5000,
    },
    "2m": {
        "name": "2m Amateur",
        "description": "VHF amateur FM simplex (144-148 MHz)",
        "channels": {
            # Common FM simplex frequencies
            "CALL": 145.500e6,    # EU calling frequency
            "S20": 145.300e6,     # FM simplex
            "S21": 145.3125e6,
            "S22": 145.325e6,
            "S23": 145.3375e6,
            "USCALL": 146.520e6,  # US calling frequency
            "146.55": 146.550e6,  # US simplex
            "146.58": 146.580e6,
            "147.42": 147.420e6,
            "147.45": 147.450e6,
            "147.48": 147.480e6,
            "147.51": 147.510e6,
            "147.54": 147.540e6,
            "147.57": 147.570e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
    },
    "70cm": {
        "name": "70cm Amateur",
        "description": "UHF amateur FM simplex (430-440 MHz)",
        "channels": {
            # EU simplex
            "CALL": 433.500e6,    # EU calling frequency
            "U272": 433.200e6,
            "U274": 433.250e6,
            "U276": 433.300e6,
            "U278": 433.350e6,
            "U280": 433.400e6,
            "U282": 433.450e6,
            "U284": 433.500e6,
            # US simplex
            "USCALL": 446.000e6,  # US calling frequency
            "446.025": 446.025e6,
            "446.050": 446.050e6,
            "446.075": 446.075e6,
            "446.100": 446.100e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
    },
    "cb": {
        "name": "CB Radio (EU FM)",
        "description": "EU CB radio FM mode (27 MHz, 40 channels, 10 kHz)",
        "channels": {
            "CH1": 26.965e6, "CH2": 26.975e6, "CH3": 26.985e6,
            "CH4": 27.005e6, "CH5": 27.015e6, "CH6": 27.025e6,
            "CH7": 27.035e6, "CH8": 27.055e6, "CH9": 27.065e6,
            "CH10": 27.075e6, "CH11": 27.085e6, "CH12": 27.105e6,
            "CH13": 27.115e6, "CH14": 27.125e6, "CH15": 27.135e6,
            "CH16": 27.155e6, "CH17": 27.165e6, "CH18": 27.175e6,
            "CH19": 27.185e6, "CH20": 27.205e6, "CH21": 27.215e6,
            "CH22": 27.225e6, "CH23": 27.255e6, "CH24": 27.235e6,
            "CH25": 27.245e6, "CH26": 27.265e6, "CH27": 27.275e6,
            "CH28": 27.285e6, "CH29": 27.295e6, "CH30": 27.305e6,
            "CH31": 27.315e6, "CH32": 27.325e6, "CH33": 27.335e6,
            "CH34": 27.345e6, "CH35": 27.355e6, "CH36": 27.365e6,
            "CH37": 27.375e6, "CH38": 27.385e6, "CH39": 27.395e6,
            "CH40": 27.405e6,
        },
        "channel_bw": 10000,
        "fm_deviation": 2000,
    },
    "landmobile": {
        "name": "Land Mobile",
        "description": "VHF land mobile (157-163 MHz, utilities/rail/security/industry)",
        "channels": {
            # Land mobile band between marine VHF segments (157.5-160.6 MHz)
            # Common Spanish allocations: rail, port ops, utilities, private security
            "157.50": 157.500e6,
            "157.75": 157.750e6,
            "158.00": 158.000e6,
            "158.25": 158.250e6,
            "158.50": 158.500e6,
            "158.75": 158.750e6,
            "159.00": 159.000e6,
            "159.25": 159.250e6,
            "159.50": 159.500e6,
            "159.75": 159.750e6,
            "160.00": 160.000e6,
            "160.25": 160.250e6,
            "160.50": 160.500e6,
            # Upper marine/land overlap and weather
            "160.60": 160.600e6,
            "160.80": 160.800e6,
            "161.00": 161.000e6,
            "161.25": 161.250e6,
            "161.50": 161.500e6,
            "161.75": 161.750e6,
            "162.00": 162.000e6,
            # NOAA weather (US) / EU utility
            "162.40": 162.400e6,
            "162.55": 162.550e6,
        },
        "channel_bw": 25000,
        "fm_deviation": 5000,
    },
    "tetra": {
        "name": "TETRA Emergency",
        "description": "EU police/fire/EMS TETRA (380-400 MHz, encrypted, energy detection only)",
        "channels": {
            # TETRA emergency services band, 25 kHz carriers
            # Sample points spaced ~1.8 MHz apart to maximize coverage per window
            # Each point monitors energy in a 25 kHz bin; wideband activity
            # will show as elevated power across nearby bins
            "380.0": 380.000e6, "381.8": 381.800e6,
            "383.6": 383.600e6, "385.4": 385.400e6,
            "387.2": 387.200e6, "389.0": 389.000e6,
            "390.8": 390.800e6, "392.6": 392.600e6,
            "394.4": 394.400e6, "396.2": 396.200e6,
            "398.0": 398.000e6, "399.9": 399.900e6,
        },
        "channel_bw": 25000,
        "fm_deviation": 5000,  # Not FM, but used for energy detection bandwidth
        "record_audio": False,
    },
    "tetra-priv": {
        "name": "TETRA Private",
        "description": "TETRA utilities/private security (410-430 MHz, encrypted, energy detection only)",
        "channels": {
            "410.0": 410.000e6, "411.8": 411.800e6,
            "413.6": 413.600e6, "415.4": 415.400e6,
            "417.2": 417.200e6, "419.0": 419.000e6,
            "420.8": 420.800e6, "422.6": 422.600e6,
            "424.4": 424.400e6, "426.2": 426.200e6,
            "428.0": 428.000e6, "430.0": 430.000e6,
        },
        "channel_bw": 25000,
        "fm_deviation": 5000,
        "record_audio": False,
    },
    "p25": {
        "name": "P25",
        "description": "US public safety P25 (VHF/UHF, often encrypted, energy detection only)",
        "channels": {
            # Common P25 public safety VHF frequencies
            "VHF1": 155.475e6,   # Federal law enforcement
            "VHF2": 155.7525e6,  # Interop calling
            "VHF3": 156.0375e6,
            "VHF4": 156.1125e6,
            "VHF5": 159.4725e6,  # Federal interop
            # Common P25 UHF frequencies
            "UHF1": 453.2125e6,
            "UHF2": 453.4625e6,
            "UHF3": 460.0125e6,
            "UHF4": 460.2125e6,
            "UHF5": 460.5125e6,
            # National interoperability channels
            "VCALL": 155.7525e6,  # V-CALL (VHF calling)
            "VTAC11": 151.1375e6,
            "VTAC12": 154.4525e6,
            "UTAC41": 453.4625e6,
            "UTAC42": 453.7125e6,
            "UTAC43": 453.8625e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
        "record_audio": False,
    },
}


# ---------------------------------------------------------------------------
# Window computation
# ---------------------------------------------------------------------------

SDR_BANDWIDTH = 2.4e6  # RTL-SDR usable bandwidth
SDR_USABLE_BW = 2.0e6  # Leave margin at band edges (roll-off)


def compute_windows(channels, usable_bw=SDR_USABLE_BW):
    """Group channels into windows that fit within RTL-SDR bandwidth.

    Returns list of (center_freq, {label: freq_hz, ...}) tuples.
    """
    sorted_chs = sorted(channels.items(), key=lambda x: x[1])

    windows = []
    current_group = [sorted_chs[0]]

    for label, freq in sorted_chs[1:]:
        group_min = current_group[0][1]
        # Check if this channel fits in the current window
        if freq - group_min <= usable_bw:
            current_group.append((label, freq))
        else:
            # Finalize current window and start new one
            windows.append(current_group)
            current_group = [(label, freq)]

    windows.append(current_group)

    result = []
    for group in windows:
        freqs = [f for _, f in group]
        center = (min(freqs) + max(freqs)) / 2
        ch_dict = {label: freq for label, freq in group}
        result.append((center, ch_dict))

    return result


def list_bands():
    """Print available band profiles."""
    print("Available band profiles:\n")
    for key, profile in BAND_PROFILES.items():
        windows = compute_windows(profile["channels"])
        n_ch = len(profile["channels"])
        n_win = len(windows)
        hop = f", {n_win} windows (hops)" if n_win > 1 else ""
        print(f"  {key:10s}  {profile['name']:20s}  {n_ch:2d} channels"
              f"  {profile['channel_bw']/1e3:.1f} kHz BW{hop}")
        print(f"             {profile['description']}")
    print()


# ---------------------------------------------------------------------------
# Generic FM Scanner
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 2.4e6
DEFAULT_GAIN = 40
DEFAULT_NUM_SAMPLES = 256 * 1024


class FMScanner:
    """Generic narrowband FM scanner with configurable band profiles."""

    DETECTION_SNR_DB = 15.0  # Must exceed adjacent-channel leakage from strong signals
    AUDIO_SAMPLE_RATE = 16000
    TX_HOLDOVER_TIME = 2.0
    MIN_TX_DURATION = 0.5  # seconds — discard noise spikes (sample-based, not wall-clock)

    def __init__(
        self,
        band="pmr446",
        output_dir=None,
        device_id="rtlsdr-001",
        device_index=0,
        gain=DEFAULT_GAIN,
        sample_rate=DEFAULT_SAMPLE_RATE,
        record_audio=True,
        transcribe_audio=False,
        whisper_model="base",
        language=None,
        dwell_time=5.0,
        channel_filter=None,
    ):
        if band not in BAND_PROFILES:
            raise ValueError(f"Unknown band '{band}'. Use --list to see available bands.")

        self.profile = BAND_PROFILES[band]
        self.band_key = band
        self.device_index = device_index
        self.channels = self.profile["channels"]
        if channel_filter:
            self.channels = {k: v for k, v in self.channels.items()
                            if k in channel_filter}
            if not self.channels:
                raise ValueError(f"No channels matched filter: {channel_filter}")
        self.channel_bw = self.profile["channel_bw"]
        self.fm_deviation = self.profile["fm_deviation"]
        self.gain = gain
        self.sample_rate = sample_rate
        self.num_samples = DEFAULT_NUM_SAMPLES
        # Profile can disable audio (e.g. encrypted digital modes)
        if not self.profile.get("record_audio", True):
            record_audio = False
        self.record_audio = record_audio
        self.transcribe_audio = transcribe_audio
        self.whisper_model = whisper_model
        self.language = language
        self.dwell_time = dwell_time

        # Compute windows
        self.windows = compute_windows(self.channels)
        self.current_window_idx = 0
        self.needs_hopping = len(self.windows) > 1

        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")
        self.output_dir = output_dir
        self.audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type=self.profile["name"].lower().replace("/", "_").replace(" ", "_"),
            device_id=device_id,
            min_snr_db=0,
        )
        self.sdr = None

        # Per-channel transmission state
        self._tx_active = {ch: False for ch in self.channels}
        self._wideband_buffers = {ch: [] for ch in self.channels}
        self._tx_start = {ch: None for ch in self.channels}
        self._tx_last_active = {ch: None for ch in self.channels}
        self._tx_peak_snr = {ch: 0.0 for ch in self.channels}
        self._tx_peak_power = {ch: -100.0 for ch in self.channels}
        self._tx_signal_samples = {ch: 0 for ch in self.channels}
        self._sample_offset = 0

    def _get_audio_filename(self, channel):
        timestamp = self._tx_start[channel].strftime("%Y%m%d_%H%M%S")
        band = self.band_key
        return os.path.join(self.audio_dir, f"{band}_{channel}_{timestamp}.wav")

    def _finalize_transmission(self, channel, ch_freq, noise_floor):
        """End a transmission: demod, save audio, transcribe, log."""
        self._tx_active[channel] = False
        audio_file = None
        transcript = None

        # Compute signal duration from signal-present samples only
        # (excludes holdover noise that inflates the count)
        duration = self._tx_signal_samples[channel] / self.sample_rate

        # Discard noise spikes — real voice transmissions are longer
        if duration < self.MIN_TX_DURATION:
            self._wideband_buffers[channel] = []
            self._tx_peak_snr[channel] = 0.0
            self._tx_peak_power[channel] = -100.0
            self._tx_last_active[channel] = None
            self._tx_signal_samples[channel] = 0
            return None

        if self.record_audio and self._wideband_buffers[channel]:
            try:
                center_freq = self._current_center_freq
                full_audio, audio_rate = extract_and_demodulate_buffers(
                    self._wideband_buffers[channel], self.sample_rate,
                    center_freq, ch_freq, self.AUDIO_SAMPLE_RATE,
                    fm_deviation=self.fm_deviation)
                if len(full_audio) > 0:
                    # Update duration from actual audio output
                    duration = len(full_audio) / audio_rate
                    audio_file = self._get_audio_filename(channel)
                    save_audio(full_audio, audio_rate, audio_file)
            except Exception as e:
                print(f"Audio processing error: {e}", file=sys.stderr)
            self._wideband_buffers[channel] = []

        if self.transcribe_audio and audio_file:
            try:
                transcript = transcribe(
                    audio_file, model_name=self.whisper_model,
                    language=self.language)
                if transcript:
                    print(f"\n  >> {channel}: \"{transcript}\"\n")
            except Exception as e:
                print(f"Transcription error: {e}", file=sys.stderr)

        meta = {}
        if transcript:
            meta["transcript"] = transcript
        metadata = json.dumps(meta) if meta else ""

        self.logger.log_signal(
            signal_type=self.profile["name"],
            frequency_hz=ch_freq,
            power_db=self._tx_peak_power[channel],
            noise_floor_db=noise_floor,
            channel=channel,
            audio_file=os.path.basename(audio_file) if audio_file else None,
            metadata=metadata,
        )

        self._tx_peak_snr[channel] = 0.0
        self._tx_peak_power[channel] = -100.0
        self._tx_last_active[channel] = None
        self._tx_signal_samples[channel] = 0

        return audio_file

    def _process_channel(self, samples, channel, ch_freq, snr, power,
                         noise_floor, sample_offset=0):
        """Track transmission state for a channel. Same logic as PMR scanner."""
        is_signal = snr >= self.DETECTION_SNR_DB
        now = time.time()

        if is_signal:
            self._tx_last_active[channel] = now
            if snr > self._tx_peak_snr[channel]:
                self._tx_peak_snr[channel] = snr
            if power > self._tx_peak_power[channel]:
                self._tx_peak_power[channel] = power

            if not self._tx_active[channel]:
                self._tx_active[channel] = True
                self._tx_start[channel] = datetime.now()
                self._tx_peak_snr[channel] = snr
                self._tx_peak_power[channel] = power

            # Count only signal-present samples for duration filtering
            self._tx_signal_samples[channel] += len(samples)

        if self._tx_active[channel] and self.record_audio:
            self._wideband_buffers[channel].append(
                (sample_offset, samples.copy()))

        if not is_signal and self._tx_active[channel]:
            elapsed = now - (self._tx_last_active[channel] or now)
            if elapsed >= self.TX_HOLDOVER_TIME:
                self._finalize_transmission(channel, ch_freq, noise_floor)

    def _has_active_tx_in_window(self, window_channels):
        """Check if any channel in a window has an active transmission."""
        return any(self._tx_active[ch] for ch in window_channels)

    def _finalize_window_transmissions(self, window_channels, noise_floor):
        """Finalize all active transmissions in a window before hopping away."""
        for ch in window_channels:
            if self._tx_active[ch]:
                self._finalize_transmission(
                    ch, self.channels[ch], noise_floor)

    def _async_reader_thread(self, sample_queue, stop_event):
        """Background thread that continuously reads IQ via async streaming."""
        def callback(samples, _context):
            if stop_event.is_set():
                self.sdr.cancel_read_async()
                return
            try:
                sample_queue.put_nowait(samples)
            except queue.Full:
                pass

        try:
            self.sdr.read_samples_async(callback, self.num_samples)
        except Exception:
            if not stop_event.is_set():
                raise

    def display_channels(self, window_channels, channel_powers, noise_floor,
                         window_idx, n_windows):
        """Display channel activity for the current window."""
        print("\033[H\033[J", end="")
        print("=" * 64)
        title = f"{self.profile['name']} Scanner"
        if n_windows > 1:
            title += f"  [Window {window_idx + 1}/{n_windows}]"
        print(f"        {title}")
        print("=" * 64)
        print(f"\nNoise Floor: {noise_floor:.1f} dB  |  "
              f"BW: {self.channel_bw/1e3:.1f} kHz  |  "
              f"Dev: {self.fm_deviation/1e3:.1f} kHz")
        print(f"Detections logged: {self.logger.detection_count}")
        if n_windows > 1:
            print(f"Dwell time: {self.dwell_time:.0f}s per window")
        print("-" * 64)

        # Sort channels by frequency for display
        sorted_chs = sorted(window_channels.items(), key=lambda x: x[1])

        for label, freq in sorted_chs:
            power = channel_powers.get(label, -100)
            freq_mhz = freq / 1e6
            snr = power - noise_floor

            bar_length = max(0, min(30, int(snr)))
            bar = "█" * bar_length + "░" * (30 - bar_length)

            is_active = self._tx_active.get(label, False)
            if snr > 15:
                status = "ACTIVE" + (" REC" if is_active else "")
                color = "\033[91m"
            elif snr > 8:
                status = "WEAK  " + (" REC" if is_active else "")
                color = "\033[93m"
            else:
                status = "IDLE  "
                color = "\033[90m"

            print(f"{label:>8s} ({freq_mhz:11.5f} MHz): "
                  f"{color}{bar}\033[0m {power:6.1f} dB  {status}")

        print("-" * 64)
        if not self.profile.get("record_audio", True):
            print("Mode: ENERGY DETECTION ONLY (encrypted/digital)")
        elif self.record_audio:
            print(f"Audio recording: ON (>{self.DETECTION_SNR_DB:.0f} dB SNR)")
        print("\nPress Ctrl+C to exit")

    def _scan_window(self, window_idx, sample_queue, stop_event, noise_floor):
        """Scan a single window: tune, stream, detect until dwell expires."""
        center_freq, window_channels = self.windows[window_idx]
        self._current_center_freq = center_freq

        # Retune SDR
        self.sdr.center_freq = center_freq

        # Drain stale samples from previous window
        while not sample_queue.empty():
            try:
                sample_queue.get_nowait()
            except queue.Empty:
                break

        # Brief settle time after retune
        time.sleep(0.05)

        dwell_start = time.time()
        last_display_time = 0

        while not stop_event.is_set():
            # Check dwell timeout (only if hopping and no active TX)
            if self.needs_hopping:
                elapsed = time.time() - dwell_start
                if elapsed >= self.dwell_time:
                    if not self._has_active_tx_in_window(window_channels):
                        break
                    # Extend dwell if TX active, but cap at 3x dwell
                    if elapsed >= self.dwell_time * 3:
                        self._finalize_window_transmissions(
                            window_channels, noise_floor)
                        break

            try:
                samples = sample_queue.get(timeout=2.0)
            except queue.Empty:
                continue

            current_offset = self._sample_offset
            self._sample_offset += len(samples)

            freqs, power_spectrum = calculate_power_spectrum(
                samples, self.sample_rate)
            noise_floor = np.median(power_spectrum)

            channel_powers = {}
            for label, ch_freq in window_channels.items():
                power = get_channel_power(
                    freqs, power_spectrum, center_freq, ch_freq,
                    bandwidth=self.channel_bw)
                channel_powers[label] = power
                snr = power - noise_floor
                self._process_channel(
                    samples, label, ch_freq, snr, power, noise_floor,
                    sample_offset=current_offset)

            # Drain queued chunks
            while not sample_queue.empty():
                try:
                    samples = sample_queue.get_nowait()
                except queue.Empty:
                    break

                current_offset = self._sample_offset
                self._sample_offset += len(samples)

                freqs, power_spectrum = calculate_power_spectrum(
                    samples, self.sample_rate)
                noise_floor = np.median(power_spectrum)

                channel_powers = {}
                for label, ch_freq in window_channels.items():
                    power = get_channel_power(
                        freqs, power_spectrum, center_freq, ch_freq,
                        bandwidth=self.channel_bw)
                    channel_powers[label] = power
                    snr = power - noise_floor
                    self._process_channel(
                        samples, label, ch_freq, snr, power, noise_floor,
                        sample_offset=current_offset)

            # Throttle display
            now = time.time()
            if now - last_display_time >= 0.2:
                self.display_channels(
                    window_channels, channel_powers, noise_floor,
                    window_idx, len(self.windows))
                last_display_time = now

        return noise_floor

    def run(self):
        """Run the FM scanner with continuous async IQ streaming."""
        n_ch = len(self.channels)
        n_win = len(self.windows)
        print(f"Initializing {self.profile['name']} scanner...")
        print(f"  {n_ch} channels, {self.channel_bw/1e3:.1f} kHz spacing, "
              f"±{self.fm_deviation/1e3:.1f} kHz deviation")
        if n_win > 1:
            print(f"  {n_win} windows (hopping, {self.dwell_time:.0f}s dwell)")
        else:
            print(f"  Single window (no hopping needed)")

        noise_floor = -60
        sample_queue = queue.Queue(maxsize=64)
        stop_event = threading.Event()

        try:
            self.sdr = RtlSdr(self.device_index)
            self.sdr.sample_rate = self.sample_rate
            self.sdr.gain = self.gain

            # Set initial center frequency
            center_freq, _ = self.windows[0]
            self.sdr.center_freq = center_freq
            self._current_center_freq = center_freq

            print(f"  Sample rate: {self.sdr.sample_rate / 1e6:.1f} MHz")
            print(f"  Gain: {self.sdr.gain} dB")

            output_file = self.logger.start()
            print(f"  Logging to: {output_file}")
            print(f"\nScanning...\n")

            time.sleep(1)

            # Start async reader
            reader_thread = threading.Thread(
                target=self._async_reader_thread,
                args=(sample_queue, stop_event),
                daemon=True,
            )
            reader_thread.start()

            while not stop_event.is_set():
                noise_floor = self._scan_window(
                    self.current_window_idx, sample_queue,
                    stop_event, noise_floor)

                if self.needs_hopping and not stop_event.is_set():
                    self.current_window_idx = (
                        (self.current_window_idx + 1) % len(self.windows))

        except KeyboardInterrupt:
            print("\n\nStopping scan...")
            stop_event.set()

            # Finalize any active transmissions across all windows
            for ch, ch_freq in self.channels.items():
                if self._tx_active[ch]:
                    audio_file = None
                    if self.record_audio and self._wideband_buffers[ch]:
                        try:
                            full_audio, _ = extract_and_demodulate_buffers(
                                self._wideband_buffers[ch], self.sample_rate,
                                self._current_center_freq, ch_freq,
                                self.AUDIO_SAMPLE_RATE,
                                fm_deviation=self.fm_deviation)
                            audio_file = self._get_audio_filename(ch)
                            save_audio(full_audio, self.AUDIO_SAMPLE_RATE,
                                       audio_file)
                            print(f"Saved audio: {os.path.basename(audio_file)}")
                        except Exception as e:
                            print(f"Audio save error: {e}", file=sys.stderr)

                    self.logger.log_signal(
                        signal_type=self.profile["name"],
                        frequency_hz=ch_freq,
                        power_db=self._tx_peak_power[ch],
                        noise_floor_db=noise_floor,
                        channel=ch,
                        audio_file=(os.path.basename(audio_file)
                                    if audio_file else None),
                    )

        except Exception as e:
            stop_event.set()
            print(f"Error: {e}")
            print("\nMake sure:")
            print("  1. RTL-SDR is connected")
            print("  2. pyrtlsdr is installed: pip install pyrtlsdr")
            print("  3. No other program is using the SDR")
        finally:
            stop_event.set()
            if self.sdr:
                self.sdr.close()
                print("SDR closed.")
            total = self.logger.stop()
            print(f"Total detections logged: {total}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generic FM Scanner")
    parser.add_argument("band", nargs="?", default="pmr446",
                        help="Band profile name")
    parser.add_argument("--list", action="store_true",
                        help="List available bands")
    args = parser.parse_args()

    if args.list:
        list_bands()
    else:
        scanner = FMScanner(band=args.band)
        scanner.run()

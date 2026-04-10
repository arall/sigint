"""
PMR446 Scanner Module
Scans PMR446 channels (446 MHz) using RTL-SDR.
Supports both analog FM (channels 1-8) and digital dPMR/DMR (channels 1-16).
"""

import sys
import os
import wave
import threading
import queue
from datetime import datetime
from math import gcd

# Get project root (parent of src)
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.loader  # noqa: F401,E402 - Must be imported before rtlsdr

import time  # noqa: E402

import numpy as np  # noqa: E402
from rtlsdr import RtlSdr  # noqa: E402
from scipy import signal as scipy_signal  # noqa: E402

from utils.logger import SignalLogger  # noqa: E402
from utils.transcriber import transcribe  # noqa: E402

# PMR446 analog channel frequencies (in Hz) - 12.5 kHz spacing
PMR_CHANNELS = {
    1: 446.00625e6,
    2: 446.01875e6,
    3: 446.03125e6,
    4: 446.04375e6,
    5: 446.05625e6,
    6: 446.06875e6,
    7: 446.08125e6,
    8: 446.09375e6,
}

# Digital PMR446 channels (dPMR/DMR) - 6.25 kHz spacing, 446.1-446.2 MHz
DPMR_CHANNELS = {
    1: 446.103125e6,
    2: 446.109375e6,
    3: 446.115625e6,
    4: 446.121875e6,
    5: 446.128125e6,
    6: 446.134375e6,
    7: 446.140625e6,
    8: 446.146875e6,
    9: 446.153125e6,
    10: 446.159375e6,
    11: 446.165625e6,
    12: 446.171875e6,
    13: 446.178125e6,
    14: 446.184375e6,
    15: 446.190625e6,
    16: 446.196875e6,
}

# Default configuration
DEFAULT_SAMPLE_RATE = 2.4e6  # 2.4 MHz sample rate
DEFAULT_CENTER_FREQ = 446.05e6  # Center of PMR band
DEFAULT_GAIN = 40  # RF gain
DEFAULT_NUM_SAMPLES = 256 * 1024  # Number of samples per read
NOISE_THRESHOLD_DB = -50  # Threshold above noise floor to detect signal


def calculate_power_spectrum(samples, sample_rate):
    """Calculate power spectrum using FFT with Blackman-Harris window.

    The window provides ~92 dB sidelobe rejection, preventing a strong signal
    on one PMR channel from leaking into adjacent channel power measurements
    (12.5 kHz spacing).
    """
    window = np.blackman(len(samples))
    # Normalize by coherent gain (sum/N) so signal power is preserved
    coherent_gain = np.sum(window) / len(window)
    fft_result = np.fft.fftshift(np.fft.fft(samples * window / coherent_gain))
    power_spectrum = 20 * np.log10(np.abs(fft_result) + 1e-10)
    freqs = np.fft.fftshift(np.fft.fftfreq(len(samples), 1 / sample_rate))
    return freqs, power_spectrum


def get_channel_power(freqs, power_spectrum, center_freq, channel_freq, bandwidth=12500):
    """Calculate average power for a specific channel.

    Averages in linear domain (not dB) so a strong signal in a few bins
    is not diluted by noise-floor bins in the same channel band.
    """
    actual_freq = freqs + center_freq
    channel_mask = (actual_freq >= channel_freq - bandwidth / 2) & (
        actual_freq <= channel_freq + bandwidth / 2
    )
    if np.any(channel_mask):
        linear = 10 ** (power_spectrum[channel_mask] / 20)
        return 20 * np.log10(np.mean(linear) + 1e-10)
    return -100  # Return very low power if channel not in range


def extract_and_demodulate_buffers(buffers, sample_rate, center_freq, channel_freq,
                                    audio_rate=16000, fm_deviation=2500):
    """Extract channel and FM demodulate from offset-tagged IQ buffers.

    Processes each chunk independently (avoiding phase discontinuities from
    sample gaps between reads) and inserts silence for the gaps so audio
    plays back at correct speed.

    Args:
        buffers: List of (sample_offset, samples) tuples.
    """
    freq_offset = channel_freq - center_freq

    # Rational resampling: sample_rate → audio_rate via resample_poly
    # Uses GCD to find exact up/down factors, giving exact audio_rate output
    # (e.g., 250 kHz → 16 kHz: up=8, down=125; 2 MHz → 16 kHz: up=1, down=125)
    g = gcd(int(audio_rate), int(sample_rate))
    resample_up = int(audio_rate) // g
    resample_down = int(sample_rate) // g
    actual_audio_rate = int(audio_rate)

    audio_chunks = []
    last_end_offset = None
    prev_channel_last = None  # Last decimated IQ sample for phase continuity

    for offset, chunk in buffers:
        if len(chunk) < 200:
            continue

        # Insert silence for the gap between this chunk and the previous one
        if last_end_offset is not None:
            gap_samples = offset - last_end_offset
            if gap_samples > 0:
                gap_audio_samples = int(gap_samples / sample_rate * actual_audio_rate)
                if gap_audio_samples > 0:
                    audio_chunks.append(np.zeros(gap_audio_samples, dtype=np.float32))
                    prev_channel_last = None  # Phase continuity broken by gap

        last_end_offset = offset + len(chunk)

        # Frequency shift with correct absolute time
        t = (np.arange(len(chunk)) + offset) / sample_rate
        shifted = chunk * np.exp(-2j * np.pi * freq_offset * t)

        # Resample to audio rate with proper anti-aliasing (resample_poly uses FIR)
        # Pad with zeros to absorb the FIR filter startup/shutdown transient,
        # then trim the corresponding output samples
        pad_in = resample_down * 12  # ~12 output samples of padding
        pad_out = int(np.ceil(pad_in * resample_up / resample_down))
        padded = np.concatenate([np.zeros(pad_in, dtype=shifted.dtype),
                                 shifted,
                                 np.zeros(pad_in, dtype=shifted.dtype)])
        channel_full = scipy_signal.resample_poly(padded, resample_up, resample_down)
        channel_iq = channel_full[pad_out:-pad_out] if pad_out > 0 else channel_full

        # FM demodulate (polar discriminator)
        # Prepend last sample from previous chunk for phase continuity at boundary
        if prev_channel_last is not None:
            demod_iq = np.concatenate([[prev_channel_last], channel_iq])
        else:
            demod_iq = channel_iq
        prev_channel_last = channel_iq[-1]

        phase = np.angle(demod_iq[1:] * np.conj(demod_iq[:-1]))
        audio = phase * (actual_audio_rate / (2 * np.pi * fm_deviation))

        audio_chunks.append(audio.astype(np.float32))

    if not audio_chunks:
        return np.array([], dtype=np.float32), actual_audio_rate

    full_audio = np.concatenate(audio_chunks)

    # Low-pass at 3.4 kHz on final audio (now at audio_rate, numerically stable)
    nyq = actual_audio_rate / 2
    cutoff = min(3400 / nyq, 0.99)
    b, a = scipy_signal.butter(4, cutoff, btype='low')
    full_audio = scipy_signal.lfilter(b, a, full_audio)

    # De-click: two-pass approach to remove crackling from chunk boundary artifacts.
    # Pass 1: Median filter removes single-sample impulsive noise.
    # Pass 2: Interpolate over remaining large spikes (multi-sample transients
    # from resample_poly edge effects at USB buffer boundaries).
    full_audio = scipy_signal.medfilt(full_audio, kernel_size=5)
    diff = np.abs(np.diff(full_audio))
    spike_threshold = max(np.percentile(diff, 99.95) * 1.5, 0.4)
    spike_mask = np.zeros(len(full_audio), dtype=bool)
    for idx in np.where(diff > spike_threshold)[0]:
        spike_mask[max(0, idx - 1):min(len(full_audio), idx + 3)] = True
    good = ~spike_mask
    if np.any(good) and np.any(spike_mask):
        full_audio[spike_mask] = np.interp(
            np.where(spike_mask)[0], np.where(good)[0], full_audio[good])

    return full_audio.astype(np.float32), actual_audio_rate


def save_audio(audio_samples, sample_rate, filepath):
    """Save audio samples to WAV file."""
    # Normalize to int16 range
    if audio_samples.dtype != np.int16:
        # Normalize float audio to int16
        max_val = np.max(np.abs(audio_samples))
        if max_val > 0:
            audio_samples = audio_samples / max_val
        # Leave some headroom
        audio_samples = (audio_samples * 32000).astype(np.int16)

    with wave.open(filepath, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_samples.tobytes())


class PMRScanner:
    """PMR446 channel scanner using RTL-SDR."""

    # Minimum SNR to detect/record a transmission
    DETECTION_SNR_DB = 15.0  # Must exceed adjacent-channel leakage from strong signals
    AUDIO_SAMPLE_RATE = 16000  # 16 kHz audio output

    # Holdover time in seconds - keeps transmission "alive" during brief signal drops
    # This prevents one transmission from being split into multiple detections
    TX_HOLDOVER_TIME = 2.0  # 2s holdover to bridge voice pauses
    MIN_TX_DURATION = 0.5   # seconds — discard noise spikes (sample-based)

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        min_snr_db: float = 5.0,
        gain: int = DEFAULT_GAIN,
        sample_rate: float = DEFAULT_SAMPLE_RATE,
        center_freq: float = DEFAULT_CENTER_FREQ,
        record_audio: bool = True,
        transcribe_audio: bool = False,
        whisper_model: str = "base",
        language: str = None,
        digital: bool = False,
    ):
        # Default output to project_root/output
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.output_dir = output_dir
        self.device_id = device_id
        self.device_index = device_index
        self.min_snr_db = min_snr_db
        self.gain = gain
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.num_samples = DEFAULT_NUM_SAMPLES
        self.record_audio = record_audio
        self.transcribe_audio = transcribe_audio
        self.whisper_model = whisper_model
        self.language = language
        self.digital = digital

        # Create audio subdirectory
        self.audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="pmr446",
            device_id=device_id,
            min_snr_db=0,  # We handle thresholding ourselves
        )
        self.sdr = None

        # Track active transmissions per channel (analog)
        self._tx_active = {ch: False for ch in PMR_CHANNELS}
        self._wideband_buffers = {ch: []
                                  for ch in PMR_CHANNELS}  # Store (offset, samples) tuples
        self._tx_start = {ch: None for ch in PMR_CHANNELS}
        # Last time signal was above threshold
        self._tx_last_active = {ch: None for ch in PMR_CHANNELS}
        self._tx_peak_snr = {ch: 0.0 for ch in PMR_CHANNELS}
        self._tx_peak_power = {ch: -100.0 for ch in PMR_CHANNELS}
        self._sample_offset = 0  # Cumulative sample count for phase continuity

        # Digital channel state
        self._dpmr_active = {}       # ch -> bool
        self._dpmr_start = {}        # ch -> datetime
        self._dpmr_last_active = {}  # ch -> time.time()
        self._dpmr_peak_snr = {}     # ch -> float
        self._dpmr_peak_power = {}   # ch -> float
        self._dpmr_buffers = {}      # ch -> list of (offset, samples) tuples
        for ch in DPMR_CHANNELS:
            self._dpmr_active[ch] = False
            self._dpmr_start[ch] = None
            self._dpmr_last_active[ch] = None
            self._dpmr_peak_snr[ch] = 0.0
            self._dpmr_peak_power[ch] = -100.0
            self._dpmr_buffers[ch] = []

    def _get_audio_filename(self, channel: int) -> str:
        """Generate audio filename with timestamp and channel."""
        timestamp = self._tx_start[channel].strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.audio_dir, f"pmr_ch{channel}_{timestamp}.wav")

    def _process_channel(self, samples, channel: int, channel_freq: float, snr: float, power: float, noise_floor: float, sample_offset: int = 0):
        """
        Process a channel - track transmission state and record audio.
        Only logs ONE detection per transmission (when TX ends after holdover period).
        Uses holdover timer to prevent signal fluctuations from creating multiple detections.
        """
        is_signal_present = snr >= self.DETECTION_SNR_DB
        now = time.time()

        if is_signal_present:
            # Signal is present - update last active time
            self._tx_last_active[channel] = now

            # Track peak values during transmission
            if snr > self._tx_peak_snr[channel]:
                self._tx_peak_snr[channel] = snr
            if power > self._tx_peak_power[channel]:
                self._tx_peak_power[channel] = power

            if not self._tx_active[channel]:
                # Transmission just started
                self._tx_active[channel] = True
                self._tx_start[channel] = datetime.now()
                self._tx_peak_snr[channel] = snr
                self._tx_peak_power[channel] = power

        # Buffer IQ samples whenever TX is active (including holdover)
        # This prevents audio gaps during brief signal dips in voice pauses
        # Store sample offset for phase-continuous frequency shifting
        if self._tx_active[channel] and self.record_audio:
            self._wideband_buffers[channel].append(
                (sample_offset, samples.copy()))

        if not is_signal_present and self._tx_active[channel]:
            # Signal dropped - check if holdover period has passed
            time_since_last_signal = now - \
                (self._tx_last_active[channel] or now)

            if time_since_last_signal >= self.TX_HOLDOVER_TIME:
                # Holdover expired - transmission has truly ended
                self._tx_active[channel] = False

                audio_file = None
                transcript = None

                # Check signal duration from actual samples (not wall-clock
                # which includes holdover time)
                total_samples = sum(len(s) for _, s in self._wideband_buffers[channel])
                signal_duration = total_samples / self.sample_rate

                if signal_duration < self.MIN_TX_DURATION:
                    # Too short — noise spike, discard
                    self._wideband_buffers[channel] = []
                elif self.record_audio and self._wideband_buffers[channel]:
                    try:
                        full_audio, audio_rate = extract_and_demodulate_buffers(
                            self._wideband_buffers[channel], self.sample_rate,
                            self.center_freq, channel_freq, self.AUDIO_SAMPLE_RATE)
                        if len(full_audio) > 0:
                            audio_file = self._get_audio_filename(channel)
                            save_audio(full_audio, audio_rate, audio_file)
                    except Exception as e:
                        print(f"Audio processing error: {e}", file=sys.stderr)
                    self._wideband_buffers[channel] = []

                # Transcribe audio to text
                if self.transcribe_audio and audio_file:
                    try:
                        transcript = transcribe(
                            audio_file, model_name=self.whisper_model,
                            language=self.language)
                        if transcript:
                            print(f"\n  📝 CH{channel}: \"{transcript}\"\n")
                    except Exception as e:
                        print(f"Transcription error: {e}", file=sys.stderr)

                # Build metadata JSON
                import json
                meta = {}
                if transcript:
                    meta["transcript"] = transcript
                metadata = json.dumps(meta) if meta else ""

                # Log ONE detection for this transmission
                self.logger.log_signal(
                    signal_type="PMR446",
                    frequency_hz=channel_freq,
                    power_db=self._tx_peak_power[channel],
                    noise_floor_db=noise_floor,
                    channel=f"CH{channel}",
                    audio_file=os.path.basename(
                        audio_file) if audio_file else None,
                    metadata=metadata,
                )

                # Reset peak tracking
                self._tx_peak_snr[channel] = 0.0
                self._tx_peak_power[channel] = -100.0
                self._tx_last_active[channel] = None

                return audio_file

        return None

    # DSD expects 48 kHz discriminator audio
    DSD_SAMPLE_RATE = 48000

    def _save_discriminator_audio(self, buffers, channel_freq):
        """Extract discriminator (raw FM demod) audio from IQ buffers at 48 kHz.

        This produces the 4FSK baseband that DSD/dsd-fme can decode.
        Unlike analog FM, we use wider deviation and no low-pass voice filter.
        """
        freq_offset = channel_freq - self.center_freq
        total_decimation = int(self.sample_rate / self.DSD_SAMPLE_RATE)
        actual_rate = int(self.sample_rate / total_decimation)

        audio_chunks = []
        prev_last = None

        for offset, chunk in buffers:
            if len(chunk) < 200:
                continue

            t = (np.arange(len(chunk)) + offset) / self.sample_rate
            shifted = chunk * np.exp(-2j * np.pi * freq_offset * t)

            # Decimate to 48 kHz — wider bandwidth than analog to preserve 4FSK
            pad_in = total_decimation * 12
            pad_out = pad_in // total_decimation
            padded = np.concatenate([np.zeros(pad_in, dtype=shifted.dtype),
                                     shifted,
                                     np.zeros(pad_in, dtype=shifted.dtype)])
            channel_full = scipy_signal.resample_poly(padded, 1, total_decimation)
            channel_iq = channel_full[pad_out:-pad_out] if pad_out > 0 else channel_full

            # FM discriminator (polar)
            if prev_last is not None:
                demod_iq = np.concatenate([[prev_last], channel_iq])
            else:
                demod_iq = channel_iq
            prev_last = channel_iq[-1]

            # Wider deviation for digital (no voice-band filtering)
            phase = np.angle(demod_iq[1:] * np.conj(demod_iq[:-1]))
            audio_chunks.append(phase.astype(np.float32))

        if not audio_chunks:
            return None

        full_audio = np.concatenate(audio_chunks)

        # Save as WAV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ch_mhz = channel_freq / 1e6
        filepath = os.path.join(
            self.audio_dir, f"dpmr_{ch_mhz:.6f}_{timestamp}.wav")
        save_audio(full_audio, actual_rate, filepath)
        return filepath

    def _process_digital_channel(self, samples, channel, channel_freq, snr, power, noise_floor, sample_offset=0):
        """Process a digital PMR channel — energy detection + discriminator recording."""
        is_signal_present = snr >= self.DETECTION_SNR_DB
        now = time.time()

        if is_signal_present:
            self._dpmr_last_active[channel] = now
            if snr > self._dpmr_peak_snr[channel]:
                self._dpmr_peak_snr[channel] = snr
            if power > self._dpmr_peak_power[channel]:
                self._dpmr_peak_power[channel] = power

            if not self._dpmr_active[channel]:
                self._dpmr_active[channel] = True
                self._dpmr_start[channel] = datetime.now()
                self._dpmr_peak_snr[channel] = snr
                self._dpmr_peak_power[channel] = power

        # Buffer IQ during active transmission (including holdover)
        if self._dpmr_active[channel] and self.record_audio:
            self._dpmr_buffers[channel].append(
                (sample_offset, samples.copy()))

        if not is_signal_present and self._dpmr_active[channel]:
            time_since = now - (self._dpmr_last_active[channel] or now)
            if time_since >= self.TX_HOLDOVER_TIME:
                self._dpmr_active[channel] = False

                # Check signal duration from actual samples
                total_samples = sum(len(s) for _, s in self._dpmr_buffers[channel])
                duration = total_samples / self.sample_rate

                # Save discriminator audio for DSD decoding
                audio_file = None
                if duration < self.MIN_TX_DURATION:
                    self._dpmr_buffers[channel] = []
                elif self.record_audio and self._dpmr_buffers[channel]:
                    try:
                        audio_file = self._save_discriminator_audio(
                            self._dpmr_buffers[channel], channel_freq)
                        if audio_file:
                            print(
                                f"\n  >> D{channel} discriminator saved: "
                                f"{os.path.basename(audio_file)} ({duration:.1f}s)\n")
                    except Exception as e:
                        print(f"Digital audio error: {e}", file=sys.stderr)
                    self._dpmr_buffers[channel] = []

                import json
                meta = json.dumps({
                    "mode": "digital",
                    "duration_s": round(duration, 1),
                })

                self.logger.log_signal(
                    signal_type="dPMR446",
                    frequency_hz=channel_freq,
                    power_db=self._dpmr_peak_power[channel],
                    noise_floor_db=noise_floor,
                    channel=f"D{channel}",
                    audio_file=os.path.basename(audio_file) if audio_file else None,
                    metadata=meta,
                )

                self._dpmr_peak_snr[channel] = 0.0
                self._dpmr_peak_power[channel] = -100.0
                self._dpmr_last_active[channel] = None

    def display_channels(self, channel_powers, noise_floor, recording_channels=None, dpmr_powers=None):
        """Display channel activity with a visual indicator."""
        print("\033[H\033[J", end="")  # Clear screen
        print("=" * 60)
        print("        PMR446 Channel Monitor - RTL-SDR")
        print("=" * 60)
        print(f"\nNoise Floor: {noise_floor:.1f} dB")
        print(
            f"Detection Threshold: {noise_floor + abs(NOISE_THRESHOLD_DB):.1f} dB")
        print(f"Detections logged: {self.logger.detection_count}")
        print("-" * 60)

        for ch_num, freq in PMR_CHANNELS.items():
            power = channel_powers.get(ch_num, -100)
            freq_mhz = freq / 1e6

            # Calculate signal strength relative to noise
            signal_strength = power - noise_floor

            # Create visual bar
            bar_length = max(0, min(30, int(signal_strength)))
            bar = "█" * bar_length + "░" * (30 - bar_length)

            # Determine activity status
            is_recording = recording_channels and ch_num in recording_channels
            if signal_strength > 15:
                status = "🔴 ACTIVE" + (" 🎙" if is_recording else "")
                color = "\033[91m"  # Red
            elif signal_strength > 8:
                status = "🟡 WEAK  " + (" 🎙" if is_recording else "")
                color = "\033[93m"  # Yellow
            else:
                status = "⚪ IDLE  "
                color = "\033[90m"  # Gray

            print(
                f"CH {ch_num} ({freq_mhz:.5f} MHz): {color}{bar}\033[0m {power:6.1f} dB {status}"
            )

        # Show digital channels if enabled
        if self.digital and dpmr_powers:
            print()
            print("  Digital PMR (dPMR/DMR) - energy detection")
            print("-" * 60)
            for ch_num, freq in DPMR_CHANNELS.items():
                power = dpmr_powers.get(ch_num, -100)
                freq_mhz = freq / 1e6
                signal_strength = power - noise_floor

                bar_length = max(0, min(30, int(signal_strength)))
                bar = "█" * bar_length + "░" * (30 - bar_length)

                if signal_strength > 15:
                    status = "🔴 ACTIVE"
                    color = "\033[91m"
                elif signal_strength > 8:
                    status = "🟡 WEAK  "
                    color = "\033[93m"
                else:
                    status = "⚪ IDLE  "
                    color = "\033[90m"

                print(
                    f" D{ch_num:2d} ({freq_mhz:.6f} MHz): {color}{bar}\033[0m {power:6.1f} dB {status}"
                )

        print("-" * 60)
        if self.record_audio:
            print("Audio recording: ON (signals > 10 dB SNR)")
        if self.digital:
            print("Digital detection: ON (dPMR/DMR energy)")
        print("\nPress Ctrl+C to exit")

    def _async_reader_thread(self, sample_queue, stop_event):
        """Background thread that continuously reads IQ samples via async streaming."""
        def callback(samples, _context):
            if stop_event.is_set():
                self.sdr.cancel_read_async()
                return
            try:
                sample_queue.put_nowait(samples)
            except queue.Full:
                pass  # Drop oldest if consumer can't keep up (unlikely)

        try:
            self.sdr.read_samples_async(callback, self.num_samples)
        except Exception:
            if not stop_event.is_set():
                raise

    def _process_all_channels(self, samples, freqs, power_spectrum, noise_floor, current_offset):
        """Process both analog and digital channels for one chunk."""
        channel_powers = {}
        active_channels = set()

        for ch_num, ch_freq in PMR_CHANNELS.items():
            power = get_channel_power(
                freqs, power_spectrum, self.center_freq, ch_freq
            )
            channel_powers[ch_num] = power
            snr = power - noise_floor

            self._process_channel(
                samples, ch_num, ch_freq, snr, power, noise_floor,
                sample_offset=current_offset)

            if self._tx_active.get(ch_num):
                active_channels.add(ch_num)

        # Digital channels (energy detection, 6.25 kHz bandwidth)
        dpmr_powers = {}
        if self.digital:
            for ch_num, ch_freq in DPMR_CHANNELS.items():
                power = get_channel_power(
                    freqs, power_spectrum, self.center_freq, ch_freq,
                    bandwidth=6250)
                dpmr_powers[ch_num] = power
                snr = power - noise_floor
                self._process_digital_channel(
                    samples, ch_num, ch_freq, snr, power, noise_floor,
                    sample_offset=current_offset)

        return channel_powers, active_channels, dpmr_powers

    def run(self):
        """Run the PMR scanner with continuous async IQ streaming."""
        print("Initializing RTL-SDR...")

        noise_floor = -60  # Initial estimate, updated each iteration
        sample_queue = queue.Queue(maxsize=64)
        stop_event = threading.Event()

        try:
            self.sdr = RtlSdr(self.device_index)

            # Configure SDR
            self.sdr.sample_rate = self.sample_rate
            self.sdr.center_freq = self.center_freq
            self.sdr.gain = self.gain

            print(f"Sample Rate: {self.sdr.sample_rate / 1e6:.1f} MHz")
            print(f"Center Frequency: {self.sdr.center_freq / 1e6:.3f} MHz")
            print(f"Gain: {self.sdr.gain} dB")

            # Start logging
            output_file = self.logger.start()
            print(f"Logging to: {output_file}")
            print("\nStarting PMR channel scan (async streaming)...\n")

            time.sleep(1)

            # Start async reader in background thread
            reader_thread = threading.Thread(
                target=self._async_reader_thread,
                args=(sample_queue, stop_event),
                daemon=True,
            )
            reader_thread.start()

            last_display_time = 0
            display_interval = 0.2  # Update display at ~5 fps

            while True:
                # Block until at least one chunk is available
                try:
                    samples = sample_queue.get(timeout=2.0)
                except queue.Empty:
                    continue

                # Process this chunk
                current_offset = self._sample_offset
                self._sample_offset += len(samples)

                freqs, power_spectrum = calculate_power_spectrum(
                    samples, self.sample_rate
                )
                noise_floor = np.median(power_spectrum)

                channel_powers, active_channels, dpmr_powers = self._process_all_channels(
                    samples, freqs, power_spectrum, noise_floor, current_offset)

                # Drain any additional queued chunks (process all, display once)
                while not sample_queue.empty():
                    try:
                        samples = sample_queue.get_nowait()
                    except queue.Empty:
                        break

                    current_offset = self._sample_offset
                    self._sample_offset += len(samples)

                    freqs, power_spectrum = calculate_power_spectrum(
                        samples, self.sample_rate
                    )
                    noise_floor = np.median(power_spectrum)

                    channel_powers, active_channels, dpmr_powers = self._process_all_channels(
                        samples, freqs, power_spectrum, noise_floor, current_offset)

                # Throttle display updates to ~5 fps
                now = time.time()
                if now - last_display_time >= display_interval:
                    self.display_channels(
                        channel_powers, noise_floor, active_channels, dpmr_powers)
                    last_display_time = now

        except KeyboardInterrupt:
            print("\n\nStopping scan...")
            stop_event.set()

            # Save any remaining IQ buffers and log active transmissions
            for ch_num, ch_freq in PMR_CHANNELS.items():
                if self._tx_active[ch_num]:
                    audio_file = None
                    if self.record_audio and self._wideband_buffers[ch_num]:
                        full_audio, _ = extract_and_demodulate_buffers(
                            self._wideband_buffers[ch_num], self.sample_rate,
                            self.center_freq, ch_freq, self.AUDIO_SAMPLE_RATE)
                        audio_file = self._get_audio_filename(ch_num)
                        save_audio(
                            full_audio, self.AUDIO_SAMPLE_RATE, audio_file)
                        print(
                            f"Saved audio for CH{ch_num}: {os.path.basename(audio_file)}")

                    # Log the interrupted transmission
                    self.logger.log_signal(
                        signal_type="PMR446",
                        frequency_hz=ch_freq,
                        power_db=self._tx_peak_power[ch_num],
                        noise_floor_db=noise_floor,
                        channel=f"CH{ch_num}",
                        audio_file=os.path.basename(
                            audio_file) if audio_file else None,
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

            # Stop logger and report
            total_detections = self.logger.stop()
            print(f"Total detections logged: {total_detections}")


# Allow running directly for testing
if __name__ == "__main__":
    scanner = PMRScanner()
    scanner.run()

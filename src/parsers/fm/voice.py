"""
FM Voice Parser — channelizer-compatible FM demodulator and recorder.

Receives narrowband IQ from the channelizer (already frequency-shifted and
decimated to the channel bandwidth), detects voice activity on predefined
sub-channels, FM-demodulates active transmissions, records audio to WAV,
and optionally transcribes with Whisper.

Reuses the proven PMR demod pipeline: resample_poly decimation, polar
discriminator, low-pass filter, de-click.
"""

import json
import os
import time

import numpy as np

from parsers.base import BaseParser
from utils.logger import SignalDetection

# Import PMR's battle-tested DSP functions
from scanners.pmr import (
    calculate_power_spectrum,
    extract_and_demodulate_buffers,
    save_audio,
)


def _channel_power_linear(samples, sample_rate, center_freq, channel_freq,
                           bandwidth=12500):
    """Compute channel power by averaging in linear domain (not dB).

    Unlike get_channel_power which averages dB values, this correctly
    measures total power for narrowband FM signals spread across many
    FFT bins — especially important when the channelizer delivers small
    blocks with fine FFT bin resolution.

    Returns (channel_power_db, noise_floor_db).
    """
    window = np.blackman(len(samples))
    coherent_gain = np.sum(window) / len(window)
    fft_result = np.fft.fftshift(np.fft.fft(samples * window / coherent_gain))
    power_linear = np.abs(fft_result) ** 2
    freqs = np.fft.fftshift(np.fft.fftfreq(len(samples), 1 / sample_rate))

    actual_freq = freqs + center_freq
    channel_mask = ((actual_freq >= channel_freq - bandwidth / 2) &
                    (actual_freq <= channel_freq + bandwidth / 2))

    if not np.any(channel_mask):
        return -100.0, -100.0

    # Channel power: average linear power, then to dB
    ch_power_db = 10 * np.log10(np.mean(power_linear[channel_mask]) + 1e-20)

    # Noise floor: median of bins outside all channels (approximate with
    # full-spectrum median in linear domain)
    noise_db = 10 * np.log10(np.median(power_linear) + 1e-20)

    return ch_power_db, noise_db

# Band profiles — channel maps reusable across server configs.
# Frequencies are absolute Hz. channel_bw and fm_deviation in Hz.
BAND_PROFILES = {
    "pmr446": {
        "name": "PMR446",
        "signal_type": "PMR446",
        "channels": {
            "CH1": 446.00625e6, "CH2": 446.01875e6,
            "CH3": 446.03125e6, "CH4": 446.04375e6,
            "CH5": 446.05625e6, "CH6": 446.06875e6,
            "CH7": 446.08125e6, "CH8": 446.09375e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
    },
    "pmr446_digital": {
        "name": "PMR446 Digital",
        "signal_type": "dPMR",
        "channels": {
            "D1": 446.103125e6, "D2": 446.109375e6,
            "D3": 446.115625e6, "D4": 446.121875e6,
            "D5": 446.128125e6, "D6": 446.134375e6,
            "D7": 446.140625e6, "D8": 446.146875e6,
            "D9": 446.153125e6, "D10": 446.159375e6,
            "D11": 446.165625e6, "D12": 446.171875e6,
            "D13": 446.178125e6, "D14": 446.184375e6,
            "D15": 446.190625e6, "D16": 446.196875e6,
        },
        "channel_bw": 6250,
        "fm_deviation": 2500,
    },
    "70cm_eu": {
        "name": "70cm EU Simplex",
        "signal_type": "70cm",
        "channels": {
            "CALL": 433.500e6,
            "U272": 433.200e6, "U274": 433.250e6,
            "U276": 433.300e6, "U278": 433.350e6,
            "U280": 433.400e6, "U282": 433.450e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
    },
    "marine": {
        "name": "Marine VHF",
        "signal_type": "MarineVHF",
        "channels": {
            "CH16": 156.800e6, "CH06": 156.300e6,
            "CH09": 156.450e6, "CH10": 156.500e6,
            "CH12": 156.600e6, "CH13": 156.650e6,
            "CH14": 156.700e6, "CH15": 156.750e6,
            "CH67": 156.375e6, "CH68": 156.425e6,
            "CH69": 156.475e6, "CH71": 156.575e6,
            "CH72": 156.625e6, "CH73": 156.675e6,
            "CH74": 156.725e6, "CH77": 156.875e6,
        },
        "channel_bw": 25000,
        "fm_deviation": 5000,
    },
    "2m": {
        "name": "2m Simplex",
        "signal_type": "2m",
        "channels": {
            "CALL": 145.500e6,
            "S20": 145.300e6, "S21": 145.3125e6,
            "S22": 145.325e6, "S23": 145.3375e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
    },
    "frs": {
        "name": "FRS/GMRS",
        "signal_type": "FRS",
        "channels": {
            "FRS1": 462.5625e6, "FRS2": 462.5875e6,
            "FRS3": 462.6125e6, "FRS4": 462.6375e6,
            "FRS5": 462.6625e6, "FRS6": 462.6875e6,
            "FRS7": 462.7125e6,
        },
        "channel_bw": 12500,
        "fm_deviation": 2500,
    },
}


class FMVoiceParser(BaseParser):
    """
    Channelizer-compatible FM voice demodulator.

    Receives narrowband IQ (centered at the channelizer channel's frequency),
    monitors predefined sub-channels for voice activity, demodulates and
    records active transmissions.
    """

    DETECTION_SNR_DB = 10.0  # HackRF proven unusable for voice; 10 dB safe for RTL-SDR path
    TX_HOLDOVER_TIME = 2.0  # seconds — bridges voice pauses
    MIN_TX_DURATION = 0.5   # seconds — filters sub-second noise spikes (sample-based, not wall-clock)
    MAX_TX_DURATION = 30.0  # seconds — force-finalize runaway recordings
    AUDIO_SAMPLE_RATE = 16000

    def __init__(self, logger, sample_rate, center_freq, band="pmr446",
                 output_dir="output", min_snr_db=6.0,
                 transcribe=False, whisper_model="base", language=None):
        """
        Args:
            logger: SignalLogger instance.
            sample_rate: Channelizer output sample rate (Hz).
            center_freq: Channelizer channel center frequency (Hz).
            band: Band profile name (key in BAND_PROFILES).
            output_dir: Directory for audio files.
            min_snr_db: Minimum SNR to log a detection.
            transcribe: Enable Whisper transcription.
            whisper_model: Whisper model size.
            language: Force transcription language (None = auto-detect).
        """
        super().__init__(logger)
        self.sample_rate = sample_rate
        self.center_freq = center_freq
        self.min_snr_db = min_snr_db
        self.transcribe = transcribe
        self.whisper_model = whisper_model
        self.language = language

        # Load band profile
        profile = BAND_PROFILES.get(band)
        if not profile:
            raise ValueError(
                f"Unknown band '{band}'. Available: "
                f"{', '.join(BAND_PROFILES.keys())}")

        self.band_name = profile["name"]
        self.signal_type = profile["signal_type"]
        self.channels = profile["channels"]
        self.channel_bw = profile["channel_bw"]
        self.fm_deviation = profile["fm_deviation"]

        # Filter channels to those within our bandwidth
        half_bw = sample_rate / 2
        self.active_channels = {}
        for label, freq in self.channels.items():
            offset = abs(freq - center_freq)
            if offset + self.channel_bw / 2 <= half_bw:
                self.active_channels[label] = freq

        if not self.active_channels:
            print(f"  [WARN] fm_voice '{band}': no channels within "
                  f"{center_freq/1e6:.3f} MHz ± {half_bw/1e6:.1f} MHz")

        # Per-channel transmission state
        self._tx_active = {}
        self._tx_start = {}
        self._tx_peak_snr = {}
        self._tx_peak_power = {}
        self._tx_last_active = {}
        self._tx_buffers = {}  # (sample_offset, samples) tuples
        for ch in self.active_channels:
            self._tx_active[ch] = False
            self._tx_start[ch] = None
            self._tx_peak_snr[ch] = 0.0
            self._tx_peak_power[ch] = -100.0
            self._tx_last_active[ch] = None
            self._tx_buffers[ch] = []

        self._sample_offset = 0
        self._detection_count = 0

        # Audio output directory
        self._audio_dir = os.path.join(output_dir, "audio")
        os.makedirs(self._audio_dir, exist_ok=True)

    @property
    def detection_count(self):
        return self._detection_count

    def handle_frame(self, samples):
        """Process narrowband IQ block from channelizer."""
        now = time.time()
        current_offset = self._sample_offset
        self._sample_offset += len(samples)

        if len(samples) < 200:
            return

        # Compute dB power spectrum for logging (same scale as PMR scanner)
        freqs, power_spectrum = calculate_power_spectrum(
            samples, self.sample_rate)
        noise_floor = np.median(power_spectrum)

        for ch_label, ch_freq in self.active_channels.items():
            # Linear-domain averaging for detection — correctly measures
            # narrowband FM power even with fine FFT bin resolution
            power_linear, noise_linear = _channel_power_linear(
                samples, self.sample_rate,
                center_freq=self.center_freq,
                channel_freq=ch_freq,
                bandwidth=self.channel_bw,
            )
            snr = power_linear - noise_linear

            # dB-domain average for logged power — consistent scale with
            # the standalone PMR and FM scanners
            actual_freq = freqs + self.center_freq
            mask = ((actual_freq >= ch_freq - self.channel_bw / 2) &
                    (actual_freq <= ch_freq + self.channel_bw / 2))
            power = np.mean(power_spectrum[mask]) if np.any(mask) else -100.0

            if snr >= self.DETECTION_SNR_DB:
                # Signal active — accumulate
                self._tx_last_active[ch_label] = now
                self._tx_peak_snr[ch_label] = max(
                    self._tx_peak_snr[ch_label], snr)
                self._tx_peak_power[ch_label] = max(
                    self._tx_peak_power[ch_label], power)
                self._tx_buffers[ch_label].append(
                    (current_offset, samples.copy()))

                if not self._tx_active[ch_label]:
                    self._tx_active[ch_label] = True
                    self._tx_start[ch_label] = now

            elif self._tx_active[ch_label]:
                # Signal dropped below threshold — keep recording during
                # holdover to capture full audio (voice has natural pauses
                # and SNR dips between syllables)
                self._tx_buffers[ch_label].append(
                    (current_offset, samples.copy()))
                elapsed = now - (self._tx_last_active[ch_label] or now)
                if elapsed >= self.TX_HOLDOVER_TIME:
                    self._finalize_tx(ch_label, noise_floor)

            # Force-finalize if recording exceeds max duration
            if (self._tx_active[ch_label] and self._tx_start[ch_label]
                    and now - self._tx_start[ch_label] > self.MAX_TX_DURATION):
                self._finalize_tx(ch_label, noise_floor)

    def _finalize_tx(self, ch_label, noise_floor):
        """Demodulate, save audio, optionally transcribe, and log."""
        ch_freq = self.active_channels[ch_label]
        duration = time.time() - self._tx_start[ch_label]
        peak_snr = self._tx_peak_snr[ch_label]
        peak_power = self._tx_peak_power[ch_label]
        buffers = self._tx_buffers[ch_label]

        # Reset state
        self._tx_active[ch_label] = False
        self._tx_start[ch_label] = None
        self._tx_peak_snr[ch_label] = 0.0
        self._tx_peak_power[ch_label] = -100.0
        self._tx_last_active[ch_label] = None
        self._tx_buffers[ch_label] = []

        if peak_snr < self.min_snr_db or not buffers:
            return

        # Compute actual signal duration from buffered samples (not wall-clock,
        # which includes holdover time and would let noise spikes through)
        total_samples = sum(len(s) for _, s in buffers)
        signal_duration = total_samples / self.sample_rate

        # Discard noise spikes — real voice transmissions are longer
        if signal_duration < self.MIN_TX_DURATION:
            return

        # Coalesce adjacent small channelizer blocks into larger contiguous
        # chunks so extract_and_demodulate_buffers can process them
        # efficiently (the channelizer delivers ~325 samples per block at
        # 250 kHz, but the demod pipeline needs >200 samples per chunk)
        coalesced = []
        cur_off, cur_samp = buffers[0]
        for off, samp in buffers[1:]:
            if off == cur_off + len(cur_samp):
                cur_samp = np.concatenate([cur_samp, samp])
            else:
                coalesced.append((cur_off, cur_samp))
                cur_off, cur_samp = off, samp
        coalesced.append((cur_off, cur_samp))

        # FM demodulate
        audio_file = None
        transcript = None
        try:
            audio, audio_rate = extract_and_demodulate_buffers(
                coalesced,
                sample_rate=self.sample_rate,
                center_freq=self.center_freq,
                channel_freq=ch_freq,
                audio_rate=self.AUDIO_SAMPLE_RATE,
                fm_deviation=self.fm_deviation,
            )

            if len(audio) > 0:
                # Save audio
                ts_str = time.strftime("%Y%m%d_%H%M%S")
                freq_mhz = ch_freq / 1e6
                filename = (f"fm_{self.signal_type}_{ch_label}_"
                            f"{freq_mhz:.5f}_{ts_str}.wav")
                audio_path = os.path.join(self._audio_dir, filename)
                save_audio(audio, audio_rate, audio_path)
                audio_file = filename

                # Transcribe
                if self.transcribe:
                    try:
                        from utils.transcriber import transcribe as whisper_transcribe
                        result = whisper_transcribe(
                            audio_path,
                            model_name=self.whisper_model,
                            language=self.language,
                        )
                        if result:
                            transcript = result.strip() if isinstance(result, str) else result.get("text", "").strip()
                    except Exception as e:
                        print(f"  [WARN] Transcription failed: {e}")

        except Exception as e:
            print(f"  [WARN] FM demod failed for {ch_label}: {e}")
            return

        # Build metadata
        metadata = {
            "duration_s": round(signal_duration, 2),
            "band": self.band_name,
            "modulation": "FM",
            "deviation_hz": self.fm_deviation,
        }
        if transcript:
            metadata["transcript"] = transcript

        detection = SignalDetection.create(
            signal_type=self.signal_type,
            frequency_hz=ch_freq,
            power_db=peak_power,
            noise_floor_db=noise_floor,
            channel=ch_label,
            audio_file=audio_file,
            metadata=json.dumps(metadata),
        )
        self.logger.log(detection)
        self._detection_count += 1

    def shutdown(self):
        """Finalize any in-progress transmissions."""
        for ch_label in list(self._tx_active):
            if self._tx_active[ch_label] and self._tx_buffers[ch_label]:
                self._finalize_tx(ch_label, noise_floor=-80.0)

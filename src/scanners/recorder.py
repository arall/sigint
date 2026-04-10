#!/usr/bin/env python3
"""
Signal Recorder/Replay Module
Record raw IQ samples and replay/analyze recorded signals.

Features:
- Record IQ samples at any frequency
- Multiple file formats (raw, WAV, numpy)
- Metadata preservation (frequency, sample rate, gain, timestamp)
- Timed recordings
- Signal replay and analysis
- Spectrogram generation from recordings
"""

import json
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

# Conditional imports
try:
    from rtlsdr import RtlSdr

    HAS_RTLSDR = True
except ImportError:
    HAS_RTLSDR = False

try:
    from scipy import signal as scipy_signal
    from scipy.io import wavfile

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


@dataclass
class RecordingMetadata:
    """Metadata for a recorded signal file."""

    frequency: float  # Center frequency in Hz
    sample_rate: float  # Sample rate in Hz
    gain: float  # RF gain
    timestamp: str  # ISO format timestamp
    duration: float  # Recording duration in seconds
    num_samples: int  # Total number of IQ samples
    format: str  # File format (raw, wav, npy)
    description: str = ""  # Optional description
    bandwidth: float = 0.0  # Signal bandwidth if known
    modulation: str = ""  # Modulation type if known

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "frequency": self.frequency,
            "sample_rate": self.sample_rate,
            "gain": self.gain,
            "timestamp": self.timestamp,
            "duration": self.duration,
            "num_samples": self.num_samples,
            "format": self.format,
            "description": self.description,
            "bandwidth": self.bandwidth,
            "modulation": self.modulation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RecordingMetadata":
        """Create from dictionary."""
        return cls(
            frequency=data["frequency"],
            sample_rate=data["sample_rate"],
            gain=data["gain"],
            timestamp=data["timestamp"],
            duration=data["duration"],
            num_samples=data["num_samples"],
            format=data["format"],
            description=data.get("description", ""),
            bandwidth=data.get("bandwidth", 0.0),
            modulation=data.get("modulation", ""),
        )


@dataclass
class RecordingStats:
    """Statistics for a recording session."""

    samples_recorded: int = 0
    bytes_written: int = 0
    duration: float = 0.0
    peak_power: float = -100.0
    avg_power: float = -100.0
    dropped_samples: int = 0


class SignalRecorder:
    """
    Record and replay RF signals using RTL-SDR.

    Supports multiple file formats and preserves metadata
    for accurate signal reproduction and analysis.
    """

    # Common frequency presets (MHz)
    PRESETS = {
        "fm": 100.0,  # FM broadcast band
        "air": 121.5,  # Aircraft emergency
        "adsb": 1090.0,  # ADS-B
        "ais": 162.0,  # AIS
        "pmr": 446.0,  # PMR446
        "gsm900": 935.0,  # GSM 900 downlink
        "ism433": 433.92,  # ISM band
        "ism868": 868.0,  # ISM band EU
        "ism915": 915.0,  # ISM band US
        "pocsag": 152.0,  # Pager
        "noaa": 137.5,  # NOAA weather satellites
    }

    def __init__(
        self,
        output_dir: str = "output",
        device_id: int = 0,
        frequency: float = 100.0,  # MHz
        sample_rate: float = 2.4,  # MHz
        gain: int = 40,
        duration: float = 10.0,  # seconds
        file_format: str = "raw",
        description: str = "",
    ):
        self.output_dir = output_dir
        # device_id can be an int (RTL-SDR index) or string label
        # RtlSdr() needs an int index; default to 0
        if isinstance(device_id, int):
            self.device_index = device_id
        else:
            self.device_index = 0
        self.device_id = device_id
        self.frequency = frequency * 1e6  # Convert to Hz
        self.sample_rate = sample_rate * 1e6  # Convert to Hz
        self.gain = gain
        self.duration = duration
        self.file_format = file_format.lower()
        self.description = description

        self.stats = RecordingStats()
        self.running = False

        os.makedirs(output_dir, exist_ok=True)

    def _generate_filename(self, extension: str) -> str:
        """Generate a unique filename for the recording."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        freq_mhz = self.frequency / 1e6
        return os.path.join(
            self.output_dir, f"recording_{freq_mhz:.3f}MHz_{timestamp}.{extension}"
        )

    def _calculate_power(self, samples: np.ndarray) -> tuple[float, float]:
        """Calculate peak and average power in dB."""
        magnitude = np.abs(samples)
        if len(magnitude) == 0:
            return -100.0, -100.0

        # Avoid log of zero
        magnitude = np.maximum(magnitude, 1e-10)

        peak_power = 20 * np.log10(np.max(magnitude))
        avg_power = 20 * np.log10(np.mean(magnitude))

        return peak_power, avg_power

    def record(self) -> Optional[str]:
        """
        Record IQ samples to file.

        Returns the path to the recorded file, or None if recording failed.
        """
        if not HAS_RTLSDR:
            print("Error: pyrtlsdr not installed. Install with: pip install pyrtlsdr")
            return None

        print(f"\n{'=' * 60}")
        print(f"  SIGNAL RECORDER")
        print(f"{'=' * 60}")
        print(f"  Frequency:   {self.frequency / 1e6:.4f} MHz")
        print(f"  Sample Rate: {self.sample_rate / 1e6:.2f} MHz")
        print(f"  Gain:        {self.gain} dB")
        print(f"  Duration:    {self.duration:.1f} seconds")
        print(f"  Format:      {self.file_format}")
        print(f"{'=' * 60}\n")

        try:
            sdr = RtlSdr(self.device_index)
            sdr.sample_rate = self.sample_rate
            sdr.center_freq = self.frequency
            sdr.gain = self.gain

            # Calculate number of samples needed
            total_samples = int(self.sample_rate * self.duration)
            chunk_size = 256 * 1024  # 256K samples per chunk
            num_chunks = (total_samples + chunk_size - 1) // chunk_size

            # Prepare output file
            if self.file_format == "raw":
                filepath = self._generate_filename("raw")
                file_handle = open(filepath, "wb")
            elif self.file_format == "wav":
                if not HAS_SCIPY:
                    print("Error: scipy required for WAV format")
                    sdr.close()
                    return None
                filepath = self._generate_filename("wav")
                all_samples = []
            elif self.file_format == "npy":
                filepath = self._generate_filename("npy")
                all_samples = []
            else:
                print(f"Error: Unknown format '{self.file_format}'")
                sdr.close()
                return None

            print(f"Recording to: {filepath}")
            print(f"Press Ctrl+C to stop early\n")

            self.running = True
            self.stats = RecordingStats()
            start_time = time.time()
            samples_collected = 0

            try:
                for i in range(num_chunks):
                    if not self.running:
                        break

                    # Calculate samples for this chunk
                    remaining = total_samples - samples_collected
                    chunk_samples = min(chunk_size, remaining)

                    if chunk_samples <= 0:
                        break

                    # Read samples
                    samples = sdr.read_samples(chunk_samples)
                    samples_collected += len(samples)

                    # Calculate power
                    peak, avg = self._calculate_power(samples)
                    self.stats.peak_power = max(self.stats.peak_power, peak)
                    self.stats.avg_power = avg

                    # Write to file
                    if self.file_format == "raw":
                        # Interleaved I/Q as float32
                        iq_data = np.zeros(len(samples) * 2, dtype=np.float32)
                        iq_data[0::2] = samples.real.astype(np.float32)
                        iq_data[1::2] = samples.imag.astype(np.float32)
                        file_handle.write(iq_data.tobytes())
                        self.stats.bytes_written += len(iq_data) * 4
                    else:
                        all_samples.append(samples)

                    # Progress update
                    elapsed = time.time() - start_time
                    progress = (samples_collected / total_samples) * 100
                    print(
                        f"\r  Progress: {progress:5.1f}% | "
                        f"Samples: {samples_collected:,} | "
                        f"Peak: {peak:+6.1f} dB | "
                        f"Time: {elapsed:.1f}s",
                        end="",
                        flush=True,
                    )

            except KeyboardInterrupt:
                print("\n\nRecording stopped by user")
                self.running = False

            # Finalize file
            if self.file_format == "raw":
                file_handle.close()
            elif self.file_format == "wav":
                combined = np.concatenate(all_samples)
                # Convert complex to stereo (I=left, Q=right)
                stereo = np.zeros((len(combined), 2), dtype=np.float32)
                stereo[:, 0] = combined.real.astype(np.float32)
                stereo[:, 1] = combined.imag.astype(np.float32)
                wavfile.write(filepath, int(self.sample_rate), stereo)
                self.stats.bytes_written = os.path.getsize(filepath)
            elif self.file_format == "npy":
                combined = np.concatenate(all_samples)
                np.save(filepath, combined)
                self.stats.bytes_written = os.path.getsize(filepath)

            # Update stats
            self.stats.samples_recorded = samples_collected
            self.stats.duration = time.time() - start_time

            # Save metadata
            metadata = RecordingMetadata(
                frequency=self.frequency,
                sample_rate=self.sample_rate,
                gain=self.gain,
                timestamp=datetime.now().isoformat(),
                duration=self.stats.duration,
                num_samples=samples_collected,
                format=self.file_format,
                description=self.description,
            )

            meta_path = filepath + ".json"
            with open(meta_path, "w") as f:
                json.dump(metadata.to_dict(), f, indent=2)

            sdr.close()

            # Print summary
            print(f"\n\n{'=' * 60}")
            print(f"  RECORDING COMPLETE")
            print(f"{'=' * 60}")
            print(f"  File:        {filepath}")
            print(f"  Metadata:    {meta_path}")
            print(f"  Samples:     {self.stats.samples_recorded:,}")
            print(f"  Size:        {self.stats.bytes_written / 1e6:.2f} MB")
            print(f"  Duration:    {self.stats.duration:.2f} seconds")
            print(f"  Peak Power:  {self.stats.peak_power:+.1f} dB")
            print(f"{'=' * 60}\n")

            return filepath

        except Exception as e:
            print(f"\nError during recording: {e}")
            return None

    def stop(self):
        """Stop the current recording."""
        self.running = False


class SignalPlayer:
    """
    Analyze and visualize recorded signals.

    Note: Actual RF transmission requires appropriate hardware
    and licensing. This class focuses on analysis and visualization.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.metadata: Optional[RecordingMetadata] = None
        self.samples: Optional[np.ndarray] = None

        self._load_recording()

    def _load_recording(self):
        """Load the recorded signal and metadata."""
        # Load metadata
        meta_path = self.filepath + ".json"
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                self.metadata = RecordingMetadata.from_dict(json.load(f))
        else:
            print(f"Warning: No metadata file found at {meta_path}")
            # Try to infer from filename
            self.metadata = None

        # Determine format from extension
        ext = os.path.splitext(self.filepath)[1].lower()

        if ext == ".raw":
            self._load_raw()
        elif ext == ".wav":
            self._load_wav()
        elif ext == ".npy":
            self._load_npy()
        else:
            raise ValueError(f"Unknown file format: {ext}")

    def _load_raw(self):
        """Load raw IQ file (interleaved float32)."""
        with open(self.filepath, "rb") as f:
            data = np.frombuffer(f.read(), dtype=np.float32)

        # Deinterleave I and Q
        self.samples = data[0::2] + 1j * data[1::2]

    def _load_wav(self):
        """Load WAV file (stereo: I=left, Q=right)."""
        if not HAS_SCIPY:
            raise ImportError("scipy required for WAV files")

        sample_rate, data = wavfile.read(self.filepath)

        if len(data.shape) == 2:
            # Stereo: I=channel 0, Q=channel 1
            self.samples = data[:, 0].astype(np.float32) + 1j * data[:, 1].astype(
                np.float32
            )
        else:
            # Mono: assume real-only
            self.samples = data.astype(np.float32)

        # Update metadata if not loaded
        if self.metadata is None:
            self.metadata = RecordingMetadata(
                frequency=0,
                sample_rate=sample_rate,
                gain=0,
                timestamp="unknown",
                duration=len(self.samples) / sample_rate,
                num_samples=len(self.samples),
                format="wav",
            )

    def _load_npy(self):
        """Load numpy file."""
        self.samples = np.load(self.filepath)

    def info(self):
        """Print information about the recording."""
        print(f"\n{'=' * 60}")
        print(f"  RECORDING INFO")
        print(f"{'=' * 60}")
        print(f"  File: {self.filepath}")

        if self.metadata:
            print(f"  Frequency:   {self.metadata.frequency / 1e6:.4f} MHz")
            print(f"  Sample Rate: {self.metadata.sample_rate / 1e6:.2f} MHz")
            print(f"  Gain:        {self.metadata.gain} dB")
            print(f"  Duration:    {self.metadata.duration:.2f} seconds")
            print(f"  Samples:     {self.metadata.num_samples:,}")
            print(f"  Timestamp:   {self.metadata.timestamp}")
            if self.metadata.description:
                print(f"  Description: {self.metadata.description}")

        if self.samples is not None:
            peak_power = 20 * np.log10(np.max(np.abs(self.samples)) + 1e-10)
            avg_power = 20 * np.log10(np.mean(np.abs(self.samples)) + 1e-10)
            print(f"\n  Loaded Samples: {len(self.samples):,}")
            print(f"  Peak Power:     {peak_power:+.1f} dB")
            print(f"  Avg Power:      {avg_power:+.1f} dB")

        print(f"{'=' * 60}\n")

    def plot_spectrogram(self, output_path: Optional[str] = None):
        """Generate a spectrogram of the recording."""
        if not HAS_MATPLOTLIB:
            print("Error: matplotlib required for plotting")
            print("Install with: pip install matplotlib")
            return

        if not HAS_SCIPY:
            print("Error: scipy required for spectrogram")
            return

        if self.samples is None:
            print("Error: No samples loaded")
            return

        sample_rate = (
            self.metadata.sample_rate if self.metadata else 2.4e6
        )
        freq_mhz = (
            self.metadata.frequency / 1e6 if self.metadata else 0
        )

        # Compute spectrogram
        nperseg = min(1024, len(self.samples) // 8)
        f, t, Sxx = scipy_signal.spectrogram(
            self.samples, fs=sample_rate, nperseg=nperseg, noverlap=nperseg // 2
        )

        # Shift frequencies to center
        f = np.fft.fftshift(f)
        Sxx = np.fft.fftshift(Sxx, axes=0)

        # Convert to dB
        Sxx_db = 10 * np.log10(np.abs(Sxx) + 1e-10)

        # Plot
        plt.figure(figsize=(12, 6))
        plt.pcolormesh(
            t,
            (f / 1e6) + freq_mhz,
            Sxx_db,
            shading="gouraud",
            cmap="viridis",
        )
        plt.colorbar(label="Power (dB)")
        plt.ylabel("Frequency (MHz)")
        plt.xlabel("Time (s)")
        plt.title(f"Spectrogram - {freq_mhz:.4f} MHz")

        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
            print(f"Spectrogram saved to: {output_path}")
        else:
            plt.show()

        plt.close()

    def plot_power_spectrum(self, output_path: Optional[str] = None):
        """Plot the power spectrum (FFT) of the recording."""
        if not HAS_MATPLOTLIB:
            print("Error: matplotlib required for plotting")
            return

        if self.samples is None:
            print("Error: No samples loaded")
            return

        sample_rate = (
            self.metadata.sample_rate if self.metadata else 2.4e6
        )
        freq_mhz = (
            self.metadata.frequency / 1e6 if self.metadata else 0
        )

        # Use a subset for large files
        max_samples = min(len(self.samples), 1024 * 1024)
        samples = self.samples[:max_samples]

        # Compute FFT
        fft = np.fft.fftshift(np.fft.fft(samples))
        freqs = np.fft.fftshift(np.fft.fftfreq(len(samples), 1 / sample_rate))
        power_db = 20 * np.log10(np.abs(fft) + 1e-10)

        # Plot
        plt.figure(figsize=(12, 6))
        plt.plot((freqs / 1e6) + freq_mhz, power_db, linewidth=0.5)
        plt.xlabel("Frequency (MHz)")
        plt.ylabel("Power (dB)")
        plt.title(f"Power Spectrum - {freq_mhz:.4f} MHz")
        plt.grid(True, alpha=0.3)

        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
            print(f"Power spectrum saved to: {output_path}")
        else:
            plt.show()

        plt.close()

    def plot_iq(self, output_path: Optional[str] = None, num_samples: int = 10000):
        """Plot I/Q constellation and time series."""
        if not HAS_MATPLOTLIB:
            print("Error: matplotlib required for plotting")
            return

        if self.samples is None:
            print("Error: No samples loaded")
            return

        # Use subset
        samples = self.samples[: min(num_samples, len(self.samples))]
        sample_rate = (
            self.metadata.sample_rate if self.metadata else 2.4e6
        )
        t = np.arange(len(samples)) / sample_rate * 1000  # ms

        fig, axes = plt.subplots(2, 2, figsize=(12, 10))

        # I/Q constellation
        axes[0, 0].scatter(
            samples.real, samples.imag, s=1, alpha=0.3, c="blue"
        )
        axes[0, 0].set_xlabel("I (In-phase)")
        axes[0, 0].set_ylabel("Q (Quadrature)")
        axes[0, 0].set_title("I/Q Constellation")
        axes[0, 0].set_aspect("equal")
        axes[0, 0].grid(True, alpha=0.3)

        # I time series
        axes[0, 1].plot(t, samples.real, linewidth=0.5)
        axes[0, 1].set_xlabel("Time (ms)")
        axes[0, 1].set_ylabel("Amplitude")
        axes[0, 1].set_title("In-phase (I)")
        axes[0, 1].grid(True, alpha=0.3)

        # Q time series
        axes[1, 0].plot(t, samples.imag, linewidth=0.5, color="orange")
        axes[1, 0].set_xlabel("Time (ms)")
        axes[1, 0].set_ylabel("Amplitude")
        axes[1, 0].set_title("Quadrature (Q)")
        axes[1, 0].grid(True, alpha=0.3)

        # Magnitude
        axes[1, 1].plot(t, np.abs(samples), linewidth=0.5, color="green")
        axes[1, 1].set_xlabel("Time (ms)")
        axes[1, 1].set_ylabel("Magnitude")
        axes[1, 1].set_title("Signal Magnitude")
        axes[1, 1].grid(True, alpha=0.3)

        plt.tight_layout()

        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
            print(f"I/Q plot saved to: {output_path}")
        else:
            plt.show()

        plt.close()

    def export_to_format(self, output_path: str, target_format: str):
        """Convert recording to a different format."""
        if self.samples is None:
            print("Error: No samples loaded")
            return

        target_format = target_format.lower()

        if target_format == "raw":
            iq_data = np.zeros(len(self.samples) * 2, dtype=np.float32)
            iq_data[0::2] = self.samples.real.astype(np.float32)
            iq_data[1::2] = self.samples.imag.astype(np.float32)
            with open(output_path, "wb") as f:
                f.write(iq_data.tobytes())

        elif target_format == "wav":
            if not HAS_SCIPY:
                print("Error: scipy required for WAV format")
                return
            stereo = np.zeros((len(self.samples), 2), dtype=np.float32)
            stereo[:, 0] = self.samples.real.astype(np.float32)
            stereo[:, 1] = self.samples.imag.astype(np.float32)
            sample_rate = int(
                self.metadata.sample_rate if self.metadata else 2.4e6
            )
            wavfile.write(output_path, sample_rate, stereo)

        elif target_format == "npy":
            np.save(output_path, self.samples)

        elif target_format == "csv":
            # Export as CSV (I, Q columns) - useful for analysis in other tools
            with open(output_path, "w") as f:
                f.write("i,q\n")
                for s in self.samples[:100000]:  # Limit for CSV
                    f.write(f"{s.real},{s.imag}\n")

        else:
            print(f"Error: Unknown format '{target_format}'")
            return

        print(f"Exported to: {output_path}")

        # Copy metadata with updated format
        if self.metadata:
            new_meta = RecordingMetadata(
                frequency=self.metadata.frequency,
                sample_rate=self.metadata.sample_rate,
                gain=self.metadata.gain,
                timestamp=self.metadata.timestamp,
                duration=self.metadata.duration,
                num_samples=self.metadata.num_samples,
                format=target_format,
                description=self.metadata.description,
            )
            meta_path = output_path + ".json"
            with open(meta_path, "w") as f:
                json.dump(new_meta.to_dict(), f, indent=2)


def list_presets():
    """Print available frequency presets."""
    print("\nAvailable frequency presets:")
    print("-" * 40)
    for name, freq in sorted(SignalRecorder.PRESETS.items()):
        print(f"  {name:12s} {freq:8.3f} MHz")
    print()


def main():
    """Command-line interface for signal recorder."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Record and analyze RF signals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Record FM broadcast:
    python recorder.py record -f 100.3 -d 30

  Record with preset:
    python recorder.py record -p adsb -d 60

  Analyze recording:
    python recorder.py info recording.raw

  Generate spectrogram:
    python recorder.py plot recording.raw --spectrogram

  Convert format:
    python recorder.py convert recording.raw -o recording.wav
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Record command
    record_parser = subparsers.add_parser("record", help="Record signals")
    record_parser.add_argument(
        "-f", "--frequency", type=float, help="Frequency in MHz"
    )
    record_parser.add_argument(
        "-p", "--preset", choices=list(SignalRecorder.PRESETS.keys()), help="Use preset"
    )
    record_parser.add_argument(
        "-s", "--sample-rate", type=float, default=2.4, help="Sample rate (MHz)"
    )
    record_parser.add_argument(
        "-g", "--gain", type=int, default=40, help="RF gain"
    )
    record_parser.add_argument(
        "-d", "--duration", type=float, default=10.0, help="Duration (seconds)"
    )
    record_parser.add_argument(
        "--format",
        choices=["raw", "wav", "npy"],
        default="raw",
        help="Output format",
    )
    record_parser.add_argument(
        "-o", "--output", default="output", help="Output directory"
    )
    record_parser.add_argument(
        "--description", default="", help="Recording description"
    )
    record_parser.add_argument(
        "--list-presets", action="store_true", help="List frequency presets"
    )

    # Info command
    info_parser = subparsers.add_parser("info", help="Show recording info")
    info_parser.add_argument("file", help="Recording file to analyze")

    # Plot command
    plot_parser = subparsers.add_parser("plot", help="Plot recording")
    plot_parser.add_argument("file", help="Recording file to plot")
    plot_parser.add_argument(
        "--spectrogram", action="store_true", help="Generate spectrogram"
    )
    plot_parser.add_argument(
        "--spectrum", action="store_true", help="Generate power spectrum"
    )
    plot_parser.add_argument(
        "--iq", action="store_true", help="Generate I/Q plot")
    plot_parser.add_argument("-o", "--output", help="Save plot to file")

    # Convert command
    convert_parser = subparsers.add_parser("convert", help="Convert format")
    convert_parser.add_argument("file", help="Input recording file")
    convert_parser.add_argument(
        "-o", "--output", required=True, help="Output file path"
    )
    convert_parser.add_argument(
        "-f",
        "--format",
        choices=["raw", "wav", "npy", "csv"],
        help="Target format (inferred from extension if not specified)",
    )

    # Presets command
    presets_parser = subparsers.add_parser(
        "presets", help="List frequency presets")

    args = parser.parse_args()

    if args.command == "record":
        if args.list_presets:
            list_presets()
            return

        # Determine frequency
        if args.preset:
            frequency = SignalRecorder.PRESETS[args.preset]
        elif args.frequency:
            frequency = args.frequency
        else:
            print("Error: Specify --frequency or --preset")
            list_presets()
            return

        recorder = SignalRecorder(
            output_dir=args.output,
            frequency=frequency,
            sample_rate=args.sample_rate,
            gain=args.gain,
            duration=args.duration,
            file_format=args.format,
            description=args.description,
        )
        recorder.record()

    elif args.command == "info":
        player = SignalPlayer(args.file)
        player.info()

    elif args.command == "plot":
        player = SignalPlayer(args.file)

        if not any([args.spectrogram, args.spectrum, args.iq]):
            # Default: show all
            args.spectrogram = True

        if args.spectrogram:
            player.plot_spectrogram(args.output)
        if args.spectrum:
            out = args.output.replace(
                ".", "_spectrum.") if args.output else None
            player.plot_power_spectrum(out)
        if args.iq:
            out = args.output.replace(".", "_iq.") if args.output else None
            player.plot_iq(out)

    elif args.command == "convert":
        player = SignalPlayer(args.file)
        target_format = args.format or os.path.splitext(args.output)[1][1:]
        player.export_to_format(args.output, target_format)

    elif args.command == "presets":
        list_presets()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

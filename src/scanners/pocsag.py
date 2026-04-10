"""
POCSAG/Pager Decoder Module
Receives and decodes POCSAG (Post Office Code Standardization Advisory Group) pager signals.

POCSAG is used by:
- Hospitals (nurse/doctor paging)
- Emergency services (fire, ambulance)
- Restaurants (customer pagers)
- Industrial facilities

Technical details:
- Modulation: FSK (Frequency Shift Keying), ±4.5 kHz deviation
- Data rates: 512, 1200, or 2400 baud
- Encoding: BCH error correction
- Message types: Numeric, Alphanumeric, Tone-only

Common frequencies (vary by country/region):
- US: 152.0075, 152.48, 157.45, 157.77, 158.70, 462.75 MHz
- UK: 153.350, 153.3625, 153.375 MHz
- EU: 466.075, 466.230 MHz
- Australia: 148.125, 148.1625, 148.1875 MHz

This scanner can:
1. Use multimon-ng for decoding (recommended)
2. Perform native Python decoding (educational)
"""

import sys
import os
import subprocess
import shutil
import threading
import time
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from collections import defaultdict
from queue import Queue

# Get project root (parent of src)
PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.loader  # noqa: F401,E402 - Must be imported before rtlsdr

import numpy as np  # noqa: E402
from rtlsdr import RtlSdr  # noqa: E402
from scipy import signal as scipy_signal  # noqa: E402
from scipy.io import wavfile  # noqa: E402

from utils.logger import SignalLogger  # noqa: E402


# POCSAG Constants
DEFAULT_SAMPLE_RATE = 1.2e6  # 1.2 MHz for adequate filtering
AUDIO_SAMPLE_RATE = 22050    # Audio rate for multimon-ng
DEFAULT_GAIN = 40

# Common POCSAG frequencies by region
POCSAG_FREQUENCIES = {
    "US": [
        (152.0075e6, "US Common 1"),
        (152.480e6, "US Common 2"),
        (157.450e6, "US Common 3"),
        (157.770e6, "US Common 4"),
        (158.700e6, "US Common 5"),
        (462.750e6, "US UHF"),
        (929.6625e6, "US 900 MHz"),
    ],
    "UK": [
        (153.350e6, "UK Vodafone"),
        (153.3625e6, "UK Common 1"),
        (153.375e6, "UK Common 2"),
        (454.0125e6, "UK UHF"),
    ],
    "EU": [
        (466.075e6, "EU Common 1"),
        (466.230e6, "EU Common 2"),
        (169.650e6, "EU 169 MHz"),
    ],
    "AU": [
        (148.125e6, "AU Common 1"),
        (148.1625e6, "AU Common 2"),
        (148.1875e6, "AU Common 3"),
        (148.8125e6, "AU Common 4"),
    ],
}

# POCSAG sync word
POCSAG_SYNC = 0x7CD215D8
POCSAG_IDLE = 0x7A89C197

# Function code meanings
POCSAG_FUNCTION = {
    0: "Numeric",
    1: "Tone Only (Beep 1)",
    2: "Tone Only (Beep 2)",
    3: "Alphanumeric",
}

# BCH encoding lookup for POCSAG
POCSAG_BCH_POLY = 0x769


@dataclass
class PagerMessage:
    """Decoded pager message."""
    timestamp: datetime
    frequency: float
    capcode: int  # RIC (Radio Identity Code) / Address
    function: int  # 0-3
    message_type: str  # "numeric", "alpha", "tone"
    content: str
    baud_rate: int = 1200

    @property
    def function_name(self) -> str:
        return POCSAG_FUNCTION.get(self.function, "Unknown")

    def __str__(self) -> str:
        time_str = self.timestamp.strftime("%H:%M:%S")
        freq_str = f"{self.frequency/1e6:.4f}"
        if self.message_type == "tone":
            return f"[{time_str}] {freq_str} MHz | Cap: {self.capcode:07d} | {self.function_name}"
        else:
            return f"[{time_str}] {freq_str} MHz | Cap: {self.capcode:07d} | {self.message_type}: {self.content}"


@dataclass
class PagerStats:
    """Statistics for a pager capcode."""
    capcode: int
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    numeric_count: int = 0
    alpha_count: int = 0
    tone_count: int = 0
    last_message: str = ""


def check_tools_installed() -> Dict[str, bool]:
    """Check which pager decoding tools are available."""
    tools = {
        'multimon-ng': shutil.which('multimon-ng'),
        'rtl_fm': shutil.which('rtl_fm'),
        'sox': shutil.which('sox'),
    }
    return {k: v is not None for k, v in tools.items()}


def bch_check(codeword: int) -> bool:
    """Verify BCH error correction on POCSAG codeword."""
    # Simplified BCH check - returns True if valid
    syndrome = 0
    for i in range(31, -1, -1):
        if syndrome & 0x400:
            syndrome = ((syndrome << 1) | (
                (codeword >> i) & 1)) ^ POCSAG_BCH_POLY
        else:
            syndrome = (syndrome << 1) | ((codeword >> i) & 1)
    return syndrome == 0


def decode_numeric_message(codewords: List[int]) -> str:
    """Decode numeric POCSAG message from codewords."""
    # Numeric encoding: 4 bits per digit
    # 0-9 = digits, 10=space, 11=U, 12=-, 13=], 14=[, 15=reserved
    numeric_chars = "0123456789 U-][?"
    message = ""

    for cw in codewords:
        if cw == POCSAG_IDLE:
            continue
        if cw & 0x80000000:  # Message codeword (bit 31 = 1)
            # Extract 20 data bits (bits 30-11)
            data = (cw >> 11) & 0xFFFFF
            # 5 BCD digits per codeword
            for i in range(4, -1, -1):
                digit = (data >> (i * 4)) & 0xF
                message += numeric_chars[digit]

    return message.strip()


def decode_alpha_message(codewords: List[int]) -> str:
    """Decode alphanumeric POCSAG message from codewords."""
    # POCSAG alphanumeric: 7-bit ASCII transmitted LSB first
    # Data bits from each codeword are extracted LSB first (transmission order)
    # Then 7-bit characters are decoded by reversing to MSB-first for ASCII
    all_bits = []

    for cw in codewords:
        if cw == POCSAG_IDLE:
            continue
        if cw & 0x80000000:  # Message codeword (bit 31 = 1)
            # Extract 20 data bits (bits 30-11), LSB first
            data = (cw >> 11) & 0xFFFFF
            for i in range(20):
                all_bits.append((data >> i) & 1)

    # Decode 7-bit ASCII characters
    message = ""
    for i in range(0, len(all_bits) - 6, 7):
        # Bits are in LSB-first order; reverse to MSB-first for ASCII value
        char_val = 0
        for j in range(7):
            char_val |= all_bits[i + j] << j
        if char_val == 0:
            break  # End of message / null terminator
        if 32 <= char_val < 127:
            message += chr(char_val)

    return message.strip()


class MultimonNGDecoder:
    """Decoder using multimon-ng."""

    def __init__(self, frequency: float, sample_rate: int = AUDIO_SAMPLE_RATE):
        self.frequency = frequency
        self.sample_rate = sample_rate
        self.process = None
        self.running = False
        self.messages: List[PagerMessage] = []
        self.stats: Dict[int, PagerStats] = {}
        self._lock = threading.Lock()
        self._output_thread = None

    def start(self, audio_pipe_path: str) -> bool:
        """Start multimon-ng process."""
        if not shutil.which('multimon-ng'):
            return False

        try:
            # multimon-ng reads from stdin or file
            self.process = subprocess.Popen(
                [
                    'multimon-ng',
                    '-t', 'raw',
                    '-a', 'POCSAG512',
                    '-a', 'POCSAG1200',
                    '-a', 'POCSAG2400',
                    '-f', 'alpha',
                    audio_pipe_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )

            self.running = True
            self._output_thread = threading.Thread(
                target=self._read_output, daemon=True)
            self._output_thread.start()

            return True

        except Exception as e:
            print(f"Error starting multimon-ng: {e}")
            return False

    def stop(self):
        """Stop multimon-ng process."""
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _read_output(self):
        """Read and parse multimon-ng output."""
        # Output format: POCSAG1200: Address: 1234567  Function: 0  Alpha:   Hello World
        pattern = re.compile(
            r'POCSAG(\d+):\s+Address:\s+(\d+)\s+Function:\s+(\d+)\s+'
            r'(Alpha|Numeric|Tone Only):\s*(.*)?'
        )

        while self.running and self.process:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break

                line = line.strip()
                match = pattern.match(line)

                if match:
                    baud = int(match.group(1))
                    capcode = int(match.group(2))
                    function = int(match.group(3))
                    msg_type = match.group(4).lower().replace(" ", "_")
                    content = match.group(5) or ""

                    msg = PagerMessage(
                        timestamp=datetime.now(),
                        frequency=self.frequency,
                        capcode=capcode,
                        function=function,
                        message_type=msg_type if "tone" not in msg_type else "tone",
                        content=content.strip(),
                        baud_rate=baud,
                    )

                    with self._lock:
                        self.messages.append(msg)

                        # Update stats
                        if capcode not in self.stats:
                            self.stats[capcode] = PagerStats(capcode=capcode)

                        stats = self.stats[capcode]
                        stats.last_seen = datetime.now()
                        stats.message_count += 1
                        stats.last_message = content

                        if msg_type == "numeric":
                            stats.numeric_count += 1
                        elif msg_type == "alpha":
                            stats.alpha_count += 1
                        else:
                            stats.tone_count += 1

            except Exception:
                pass

    def get_messages(self) -> List[PagerMessage]:
        """Get all decoded messages."""
        with self._lock:
            return list(self.messages)

    def get_recent_messages(self, count: int = 20) -> List[PagerMessage]:
        """Get most recent messages."""
        with self._lock:
            return list(self.messages[-count:])


class POCSAGScanner:
    """
    POCSAG pager scanner using RTL-SDR.

    Can operate in two modes:
    1. multimon-ng mode: Uses multimon-ng for decoding (recommended)
    2. Native mode: Python-based decoding (educational)
    """

    def __init__(
        self,
        output_dir: str = None,
        device_id: str = "rtlsdr-001",
        device_index: int = 0,
        gain: int = DEFAULT_GAIN,
        frequency: float = None,
        region: str = "US",
        use_multimon: bool = True,
    ):
        if output_dir is None:
            output_dir = os.path.join(PROJECT_ROOT, "output")

        self.output_dir = output_dir
        self.device_id = device_id
        self.device_index = device_index
        self.gain = gain
        self.region = region.upper()
        self.use_multimon = use_multimon
        self.sample_rate = DEFAULT_SAMPLE_RATE

        # Set frequency - use provided or first from region
        if frequency:
            self.frequency = frequency
        elif self.region in POCSAG_FREQUENCIES:
            self.frequency = POCSAG_FREQUENCIES[self.region][0][0]
        else:
            self.frequency = 152.0075e6  # Default US frequency

        os.makedirs(output_dir, exist_ok=True)

        self.logger = SignalLogger(
            output_dir=output_dir,
            signal_type="pocsag",
            device_id=device_id,
            min_snr_db=0,
        )

        self.sdr = None
        self.messages: List[PagerMessage] = []
        self.stats: Dict[int, PagerStats] = {}
        self.decoder = None

        # For audio output to multimon-ng
        self.audio_pipe = None
        self.audio_file = None

        # Check available tools
        self.tools = check_tools_installed()

    def _fm_demodulate(self, samples: np.ndarray, sample_rate: float) -> np.ndarray:
        """FM demodulate IQ samples."""
        # Compute instantaneous phase
        phase = np.angle(samples)
        # Differentiate phase (FM demodulation)
        freq = np.diff(np.unwrap(phase))
        # Normalize
        freq = freq / np.max(np.abs(freq) + 1e-10)
        return freq.astype(np.float32)

    def _resample_audio(self, audio: np.ndarray, orig_rate: float, target_rate: float) -> np.ndarray:
        """Resample audio to target sample rate."""
        if orig_rate == target_rate:
            return audio

        # Use scipy resample
        num_samples = int(len(audio) * target_rate / orig_rate)
        return scipy_signal.resample(audio, num_samples).astype(np.float32)

    def scan_multimon(self):
        """Scan using multimon-ng for decoding."""
        import tempfile

        print("Starting POCSAG decoder with multimon-ng...")

        # Create a named pipe for audio
        pipe_dir = tempfile.mkdtemp()
        pipe_path = os.path.join(pipe_dir, "audio_pipe")

        try:
            # Create FIFO
            os.mkfifo(pipe_path)

            # Start multimon-ng
            self.decoder = MultimonNGDecoder(self.frequency)
            if not self.decoder.start(pipe_path):
                print("Failed to start multimon-ng. Falling back to native mode.")
                os.unlink(pipe_path)
                os.rmdir(pipe_dir)
                self.scan_native()
                return

            # Initialize SDR
            self.sdr = RtlSdr(self.device_index)
            self.sdr.sample_rate = self.sample_rate
            self.sdr.center_freq = self.frequency
            self.sdr.gain = self.gain

            print(f"Tuned to {self.frequency/1e6:.4f} MHz")
            print(f"Sample rate: {self.sample_rate/1e6:.1f} MHz")
            print(f"Gain: {self.gain} dB")
            print(f"\nListening for pager signals...\n")

            # Open pipe for writing
            pipe_fd = None
            pipe_fd = os.open(pipe_path, os.O_WRONLY)

            num_samples = 128 * 1024

            while True:
                # Read IQ samples
                samples = self.sdr.read_samples(num_samples)

                # FM demodulate
                audio = self._fm_demodulate(samples, self.sample_rate)

                # Resample to audio rate
                audio = self._resample_audio(
                    audio, self.sample_rate, AUDIO_SAMPLE_RATE)

                # Convert to 16-bit signed int for multimon-ng
                audio_int16 = (audio * 32767).astype(np.int16)

                # Write to pipe
                try:
                    os.write(pipe_fd, audio_int16.tobytes())
                except BrokenPipeError:
                    break

                # Update display
                self._display_messages()

        except KeyboardInterrupt:
            print("\n\nStopping scan...")
        finally:
            if self.decoder:
                self.decoder.stop()
            if self.sdr:
                self.sdr.close()
            try:
                if pipe_fd is not None:
                    os.close(pipe_fd)
            except Exception:
                pass
            try:
                os.unlink(pipe_path)
                os.rmdir(pipe_dir)
            except:
                pass

    def scan_native(self):
        """Scan using native Python decoding (limited functionality)."""
        print("Using native Python POCSAG decoding...")
        print("Note: multimon-ng provides much better decoding accuracy.\n")

        try:
            self.sdr = RtlSdr(self.device_index)
            self.sdr.sample_rate = self.sample_rate
            self.sdr.center_freq = self.frequency
            self.sdr.gain = self.gain

            print(f"Tuned to {self.frequency/1e6:.4f} MHz")
            print(f"Sample rate: {self.sample_rate/1e6:.1f} MHz")
            print(f"Gain: {self.gain} dB")
            print(f"\nNative decoding has limited accuracy.")
            print("Install multimon-ng for production use.\n")

            num_samples = 256 * 1024

            while True:
                samples = self.sdr.read_samples(num_samples)

                # FM demodulate
                audio = self._fm_demodulate(samples, self.sample_rate)

                # Calculate signal level
                signal_power = 10 * \
                    np.log10(np.mean(np.abs(samples)**2) + 1e-10)

                # Simple activity detection
                self._display_activity(signal_power, audio)

                time.sleep(0.1)

        except KeyboardInterrupt:
            print("\n\nStopping scan...")
        finally:
            if self.sdr:
                self.sdr.close()

    def _display_activity(self, power: float, audio: np.ndarray):
        """Display signal activity (native mode)."""
        print("\033[H\033[J", end="")  # Clear screen

        print("=" * 70)
        print("        POCSAG Scanner (Native Mode - Limited)")
        print("=" * 70)
        print(f"\nFrequency: {self.frequency/1e6:.4f} MHz")
        print(f"Signal Power: {power:.1f} dB")

        # Simple power bar
        normalized = max(0, min(1, (power + 50) / 40))
        bar_len = int(normalized * 50)
        bar = "█" * bar_len + "░" * (50 - bar_len)
        print(f"Level: [{bar}]")

        print("\n" + "-" * 70)
        print("Native decoding not fully implemented.")
        print("Install multimon-ng for message decoding:")
        print("  macOS: brew install multimon-ng")
        print("  Linux: apt install multimon-ng")
        print("-" * 70)
        print(f"\nUpdated: {datetime.now().strftime('%H:%M:%S')}")
        print("\nPress Ctrl+C to exit")

    def _display_messages(self):
        """Display decoded messages."""
        print("\033[H\033[J", end="")  # Clear screen

        print("=" * 100)
        print("                              POCSAG Pager Decoder")
        print("=" * 100)
        print(
            f"\nFrequency: {self.frequency/1e6:.4f} MHz | Region: {self.region}")

        if self.decoder:
            messages = self.decoder.get_recent_messages(15)
            stats = self.decoder.stats

            print(f"Messages received: {len(self.decoder.messages)}")
            print(f"Unique capcodes: {len(stats)}")
            print("-" * 100)

            if messages:
                print(
                    f"\n{'Time':<10} | {'Freq (MHz)':<12} | {'Capcode':<10} | {'Type':<10} | {'Message':<50}")
                print("-" * 100)

                for msg in reversed(messages):
                    time_str = msg.timestamp.strftime("%H:%M:%S")
                    freq_str = f"{msg.frequency/1e6:.4f}"
                    capcode = f"{msg.capcode:07d}"
                    msg_type = msg.message_type[:10]
                    content = msg.content[:
                                          50] if msg.content else "(tone only)"

                    print(
                        f"{time_str:<10} | {freq_str:<12} | {capcode:<10} | {msg_type:<10} | {content:<50}")
            else:
                print("\nWaiting for pager signals...")
                print("\nPager traffic depends on local activity.")
                print("Hospital/emergency frequencies are often most active.")

            # Show active capcodes
            if stats:
                print("\n" + "-" * 100)
                print("Active Pagers (by message count):")
                sorted_stats = sorted(
                    stats.values(), key=lambda x: x.message_count, reverse=True)[:10]
                for s in sorted_stats:
                    age = (datetime.now() - s.last_seen).total_seconds()
                    if age < 60:
                        indicator = "🟢"
                    elif age < 300:
                        indicator = "🟡"
                    else:
                        indicator = "🔴"
                    print(f"  {indicator} Capcode {s.capcode:07d}: {s.message_count} msgs "
                          f"(N:{s.numeric_count} A:{s.alpha_count} T:{s.tone_count})")

        print("-" * 100)
        print(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
        print("\nPress Ctrl+C to exit")

    def scan(self):
        """Run the POCSAG scanner."""
        print("=" * 70)
        print("            POCSAG Pager Decoder")
        print("=" * 70)
        print(f"\nFrequency: {self.frequency/1e6:.4f} MHz")
        print(f"Region: {self.region}")
        print(f"Device: {self.device_id}")
        print(f"Gain: {self.gain} dB")

        # Show available frequencies for region
        if self.region in POCSAG_FREQUENCIES:
            print(f"\nKnown frequencies for {self.region}:")
            for freq, name in POCSAG_FREQUENCIES[self.region]:
                marker = " *" if freq == self.frequency else ""
                print(f"  {freq/1e6:.4f} MHz - {name}{marker}")

        print("\nChecking decoder tools:")
        for tool, available in self.tools.items():
            status = "✓ installed" if available else "✗ not found"
            print(f"  {tool}: {status}")

        print("-" * 70)

        # Start logging
        output_file = self.logger.start()
        print(f"Logging to: {output_file}")

        try:
            if self.use_multimon and self.tools.get('multimon-ng'):
                self.scan_multimon()
            else:
                if self.use_multimon:
                    print("\nmultimon-ng not found. Install with:")
                    print("  macOS: brew install multimon-ng")
                    print("  Linux: apt install multimon-ng")
                    print("\nUsing native mode instead.\n")
                self.scan_native()

        finally:
            # Log decoded messages
            if self.decoder:
                for msg in self.decoder.messages:
                    self.logger.log_signal(
                        signal_type="POCSAG",
                        frequency_hz=msg.frequency,
                        power_db=0,
                        noise_floor_db=0,
                        channel=f"CAP-{msg.capcode}",
                        audio_file=f"{msg.message_type}:{msg.content[:100]}",
                    )

            total = self.logger.stop()
            print(f"\nTotal messages logged: {total}")


# Allow running directly for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="POCSAG Pager Decoder")
    parser.add_argument("--frequency", "-f", type=float, default=None,
                        help="Frequency in MHz")
    parser.add_argument("--region", "-r", type=str, default="US",
                        choices=["US", "UK", "EU", "AU"],
                        help="Region for default frequencies")
    parser.add_argument("--gain", "-g", type=int, default=DEFAULT_GAIN,
                        help="RF gain")
    parser.add_argument("--native", action="store_true",
                        help="Use native Python decoder instead of multimon-ng")

    args = parser.parse_args()

    freq = args.frequency * 1e6 if args.frequency else None

    scanner = POCSAGScanner(
        frequency=freq,
        region=args.region,
        gain=args.gain,
        use_multimon=not args.native,
    )
    scanner.scan()

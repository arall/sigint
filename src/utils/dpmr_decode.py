"""
dPMR Voice Decoder — decodes AMBE+2 voice from discriminator audio.

Uses dsdccx (DSDcc) with mbelib to decode dPMR digital voice.
Input: discriminator WAV (48 kHz S16 mono) from FM demodulator.
Output: decoded PCM WAV (8 kHz S16 mono) with intelligible voice.

Requires: dsdccx binary (built from github.com/f4exb/dsdcc with mbelib).
"""

import os
import shutil
import subprocess
import tempfile


def is_available():
    """Check if dsdccx is installed."""
    return shutil.which("dsdccx") is not None


def decode_dpmr(discriminator_path, output_path=None):
    """Decode dPMR AMBE+2 voice from a discriminator WAV file.

    Args:
        discriminator_path: path to 48 kHz S16 mono discriminator WAV.
        output_path: path for decoded WAV. If None, replaces the
                     discriminator file with a .decoded.wav suffix.

    Returns:
        path to decoded WAV on success, None on failure.
    """
    if not os.path.exists(discriminator_path):
        return None

    if not is_available():
        return None

    if output_path is None:
        base, ext = os.path.splitext(discriminator_path)
        output_path = base + ".decoded" + ext

    try:
        # sox converts WAV to raw S16 pipe, dsdccx decodes, sox converts back
        # dsdccx -d0: 2400 baud, -fm: dPMR frame type, -q: quiet
        sox_in = ["sox", discriminator_path, "-t", "s16", "-r", "48k",
                  "-c", "1", "-"]
        dsd = ["dsdccx", "-d0", "-fm", "-q", "-i", "-", "-o", "-"]
        sox_out = ["sox", "-t", "s16", "-r", "8k", "-c", "1", "-",
                   output_path]

        p_in = subprocess.Popen(sox_in, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        p_dsd = subprocess.Popen(dsd, stdin=p_in.stdout,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL)
        p_in.stdout.close()
        p_out = subprocess.Popen(sox_out, stdin=p_dsd.stdout,
                                 stderr=subprocess.DEVNULL)
        p_dsd.stdout.close()

        p_out.wait(timeout=30)
        p_dsd.wait(timeout=5)
        p_in.wait(timeout=5)

        # WAV header is 44 bytes; need actual audio data beyond that
        if p_out.returncode == 0 and os.path.getsize(output_path) > 100:
            return output_path

    except (subprocess.TimeoutExpired, OSError):
        pass

    # Clean up empty/failed output
    try:
        if os.path.exists(output_path) and os.path.getsize(output_path) <= 100:
            os.remove(output_path)
    except OSError:
        pass

    return None

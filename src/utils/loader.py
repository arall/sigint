"""
RTL-SDR Loader Module
Handles platform-specific library loading for pyrtlsdr.

Usage:
    import rtlsdr_loader  # Must be imported BEFORE rtlsdr
    from rtlsdr import RtlSdr
"""

import sys

if sys.platform == "darwin":
    import ctypes
    import ctypes.util

    _original_find_library = ctypes.util.find_library

    def _patched_find_library(name):
        """Patch find_library to locate librtlsdr from Homebrew on macOS."""
        if name in ("rtlsdr", "librtlsdr"):
            # Check Homebrew paths for Apple Silicon and Intel Macs
            for path in [
                "/opt/homebrew/opt/librtlsdr/lib/librtlsdr.dylib",  # Apple Silicon
                "/usr/local/opt/librtlsdr/lib/librtlsdr.dylib",  # Intel Mac
                "/opt/homebrew/lib/librtlsdr.dylib",
                "/usr/local/lib/librtlsdr.dylib",
            ]:
                try:
                    ctypes.CDLL(path)
                    return path
                except OSError:
                    continue
        return _original_find_library(name)

    ctypes.util.find_library = _patched_find_library

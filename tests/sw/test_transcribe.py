"""
PMR446 transcription tests.

Verifies that the Whisper transcription pipeline produces accurate text
from voice audio in English, Spanish, and Catalan — both with explicit
language hints and with auto-detection.

Test audio is generated via gTTS (Google Text-to-Speech) on first run.

Run:
    python3 tests/tx_pmr_transcribe.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# Expected phrases and their test audio files
TEST_CASES = {
    'en': {
        'text': 'Contact established on channel five, over',
        'file': os.path.join(DATA_DIR, 'voice_en.mp3'),
        # Key words that must appear in the transcription (case-insensitive)
        'keywords': ['contact', 'channel', 'over'],
    },
    'es': {
        'text': 'Contacto establecido en el canal cinco, cambio',
        'file': os.path.join(DATA_DIR, 'voice_es.mp3'),
        'keywords': ['contacto', 'canal', 'cambio'],
    },
    'ca': {
        'text': 'Contacte establert al canal cinc, canvi',
        'file': os.path.join(DATA_DIR, 'voice_ca.mp3'),
        'keywords': ['contacte', 'canal', 'canvi'],
    },
}


def generate_test_audio():
    """Generate test audio files using gTTS if they don't exist."""
    missing = {lang: tc for lang, tc in TEST_CASES.items()
               if not os.path.exists(tc['file'])}
    if not missing:
        return True

    try:
        from gtts import gTTS
    except ImportError:
        print("gTTS not installed. Install with: pip install gtts")
        print("Or provide test audio files manually.")
        return False

    os.makedirs(DATA_DIR, exist_ok=True)
    for lang, tc in missing.items():
        tts = gTTS(text=tc['text'], lang=lang)
        tts.save(tc['file'])
        print(f"  Generated {tc['file']}")
    return True


def test_transcribe_with_language_hint():
    """Transcription with explicit language must contain expected keywords."""
    from utils.transcriber import transcribe

    for lang, tc in TEST_CASES.items():
        result = transcribe(tc['file'], model_name='base', language=lang)
        assert result is not None, f"[{lang}] Transcription returned None"

        result_lower = result.lower()
        missing = [kw for kw in tc['keywords'] if kw not in result_lower]
        print(f"  [{lang}] \"{result}\"")
        assert not missing, (
            f"[{lang}] Missing keywords {missing} in: \"{result}\"")


def test_transcribe_auto_detect():
    """Transcription without language hint must still contain expected keywords."""
    from utils.transcriber import transcribe

    for lang, tc in TEST_CASES.items():
        result = transcribe(tc['file'], model_name='base')
        assert result is not None, f"[{lang}] Auto-detect returned None"

        result_lower = result.lower()
        missing = [kw for kw in tc['keywords'] if kw not in result_lower]
        print(f"  [{lang} auto] \"{result}\"")
        assert not missing, (
            f"[{lang}] Auto-detect missing keywords {missing} in: \"{result}\"")


def test_transcribe_through_demod_pipeline():
    """Transcription of FM-demodulated audio must contain expected keywords."""
    import struct
    import wave
    import numpy as np
    from scipy import signal as scipy_signal
    from utils.transcriber import transcribe
    from scanners.pmr import (
        extract_and_demodulate_buffers, save_audio,
        DEFAULT_SAMPLE_RATE, DEFAULT_CENTER_FREQ, PMR_CHANNELS,
        DEFAULT_NUM_SAMPLES,
    )

    # Use English reference audio
    wav_path = os.path.join(DATA_DIR, 'original_voice.wav')
    if not os.path.exists(wav_path):
        print("  Skipping: original_voice.wav not found")
        return

    with wave.open(wav_path, 'rb') as w:
        audio = np.array(
            struct.unpack(f'<{w.getnframes()}h', w.readframes(w.getnframes())),
            dtype=np.float64) / 32768.0
        audio_rate = w.getframerate()

    # FM modulate → demodulate (synthetic, no RF)
    channel_freq = PMR_CHANNELS[1]
    sample_rate = DEFAULT_SAMPLE_RATE
    center_freq = DEFAULT_CENTER_FREQ
    fm_dev = 2500

    n_iq = int(len(audio) * sample_rate / audio_rate)
    audio_up = scipy_signal.resample(audio, n_iq)
    freq_offset = channel_freq - center_freq
    phase = 2 * np.pi * fm_dev * np.cumsum(audio_up) / sample_rate
    carrier = 2 * np.pi * freq_offset * np.arange(n_iq) / sample_rate
    iq = np.exp(1j * (carrier + phase)).astype(np.complex64)
    noise = (np.random.randn(n_iq) + 1j * np.random.randn(n_iq)).astype(np.complex64) * 0.02
    iq += noise

    buffers = []
    offset = 0
    while offset < len(iq):
        end = min(offset + DEFAULT_NUM_SAMPLES, len(iq))
        buffers.append((offset, iq[offset:end]))
        offset = end

    demod, rate = extract_and_demodulate_buffers(
        buffers, sample_rate, center_freq, channel_freq, audio_rate, fm_dev)

    # Save to temp file for Whisper
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    save_audio(demod, rate, tmp.name)
    tmp.close()

    result = transcribe(tmp.name, model_name='base', language='en')
    os.unlink(tmp.name)

    print(f"  Demod pipeline: \"{result}\"")
    assert result is not None, "Demod transcription returned None"
    result_lower = result.lower()
    keywords = ['charlie', 'radio', 'over']
    missing = [kw for kw in keywords if kw not in result_lower]
    assert not missing, f"Missing keywords {missing} in demod transcription: \"{result}\""


def test_whisper_not_installed():
    """Transcriber returns None gracefully when whisper is missing."""
    import importlib
    import utils.transcriber as mod

    # Temporarily break the import
    original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
    def mock_import(name, *args, **kwargs):
        if name == 'whisper':
            raise ImportError("mocked")
        return original_import(name, *args, **kwargs)

    # Reset cached model
    mod._model = None
    mod._model_name = None

    import builtins
    old = builtins.__import__
    builtins.__import__ = mock_import
    try:
        result = mod.transcribe('tests/data/original_voice.wav')
        print(f"  No whisper: {result}")
        assert result is None, "Should return None when whisper unavailable"
    finally:
        builtins.__import__ = old


def test_hallucination_filter():
    """Hallucination filter catches known spam patterns."""
    from utils.transcriber import _is_hallucination

    # These should be flagged as hallucinations
    hallucinations = [
        "Subtítulos realizados por la comunidad",
        "Thank you for watching!",
        "Please subscribe to our channel",
        "www.example.com",
        "Sous-titres réalisés par...",
        "",       # empty
        "Hi",     # too short (<3 chars)
        ".",      # too short
    ]
    for text in hallucinations:
        assert _is_hallucination(text), (
            f"Should be flagged as hallucination: \"{text}\"")
        print(f"    Correctly rejected: \"{text[:40]}\"")

    # These should NOT be flagged
    real = [
        "Alpha Bravo Charlie, radio check, over",
        "Contacto establecido en el canal cinco",
        "Unit two responding to sector five",
    ]
    for text in real:
        assert not _is_hallucination(text), (
            f"Real text flagged as hallucination: \"{text}\"")
        print(f"    Correctly accepted: \"{text[:40]}\"")


def test_noise_audio_returns_none():
    """Transcribing noise-only audio returns None (not hallucinated text)."""
    import tempfile
    import numpy as np
    from scanners.pmr import save_audio
    from utils.transcriber import transcribe

    # Generate 3s of noise audio
    noise = np.random.randn(48000).astype(np.float32) * 0.1
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    save_audio(noise, 16000, tmp.name)
    tmp.close()

    result = transcribe(tmp.name, model_name='base')
    os.unlink(tmp.name)

    print(f"    Noise transcription: \"{result}\"")
    assert result is None, (
        f"Noise audio should return None, got: \"{result}\"")


if __name__ == '__main__':
    print("=" * 60)
    print("PMR446 Transcription Tests")
    print("=" * 60)

    # Generate test audio if needed
    print("\nChecking test audio...")
    if not generate_test_audio():
        sys.exit(1)

    tests = [
        ("Transcribe with language hint", test_transcribe_with_language_hint),
        ("Transcribe with auto-detect", test_transcribe_auto_detect),
        ("Transcribe through demod pipeline", test_transcribe_through_demod_pipeline),
        ("Hallucination filter", test_hallucination_filter),
        ("Noise audio returns None", test_noise_audio_returns_none),
        ("Graceful fallback without whisper", test_whisper_not_installed),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n{name}")
        try:
            fn()
            print("  PASS")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"{passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)

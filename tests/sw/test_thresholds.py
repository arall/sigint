"""
Threshold consistency regression tests.

Code-level checks that all audio paths have safe thresholds, sample-based
duration filtering, and consistent holdover. If someone changes a threshold,
this test breaks immediately.

Run:
    python3 tests/sw/test_thresholds.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def test_snr_thresholds():
    """All audio paths have DETECTION_SNR_DB >= 10 dB."""
    from scanners.pmr import PMRScanner
    from scanners.fm import FMScanner
    from parsers.fm.voice import FMVoiceParser

    min_safe = 10.0

    for cls in [PMRScanner, FMScanner, FMVoiceParser]:
        snr = cls.DETECTION_SNR_DB
        assert snr >= min_safe, (
            f"{cls.__name__}.DETECTION_SNR_DB = {snr} < {min_safe} "
            f"(too low, causes false detections)")
        print(f"    {cls.__name__}.DETECTION_SNR_DB = {snr} dB")


def test_holdover_consistent():
    """All audio paths use the same holdover time."""
    from scanners.pmr import PMRScanner
    from scanners.fm import FMScanner
    from parsers.fm.voice import FMVoiceParser

    expected = 2.0
    for cls in [PMRScanner, FMScanner, FMVoiceParser]:
        val = cls.TX_HOLDOVER_TIME
        assert val == expected, (
            f"{cls.__name__}.TX_HOLDOVER_TIME = {val} != {expected}")
        print(f"    {cls.__name__}.TX_HOLDOVER_TIME = {val}s")


def test_min_tx_duration_exists():
    """All audio paths have MIN_TX_DURATION defined."""
    from scanners.pmr import PMRScanner
    from scanners.fm import FMScanner
    from parsers.fm.voice import FMVoiceParser

    for cls in [PMRScanner, FMScanner, FMVoiceParser]:
        assert hasattr(cls, 'MIN_TX_DURATION'), (
            f"{cls.__name__} missing MIN_TX_DURATION")
        val = cls.MIN_TX_DURATION
        assert val > 0, f"{cls.__name__}.MIN_TX_DURATION = {val} <= 0"
        print(f"    {cls.__name__}.MIN_TX_DURATION = {val}s")


def test_audio_sample_rate_consistent():
    """All audio paths output at 16 kHz."""
    from scanners.pmr import PMRScanner
    from scanners.fm import FMScanner
    from parsers.fm.voice import FMVoiceParser

    expected = 16000
    for cls in [PMRScanner, FMScanner, FMVoiceParser]:
        val = cls.AUDIO_SAMPLE_RATE
        assert val == expected, (
            f"{cls.__name__}.AUDIO_SAMPLE_RATE = {val} != {expected}")


def test_voice_parser_has_max_duration():
    """FMVoiceParser has MAX_TX_DURATION to prevent runaway recordings."""
    from parsers.fm.voice import FMVoiceParser
    assert hasattr(FMVoiceParser, 'MAX_TX_DURATION'), (
        "FMVoiceParser missing MAX_TX_DURATION")
    assert FMVoiceParser.MAX_TX_DURATION > 0
    assert FMVoiceParser.MAX_TX_DURATION <= 60, (
        f"MAX_TX_DURATION = {FMVoiceParser.MAX_TX_DURATION}s seems too high")
    print(f"    FMVoiceParser.MAX_TX_DURATION = {FMVoiceParser.MAX_TX_DURATION}s")


def test_band_profiles_have_required_fields():
    """All band profiles have channel_bw and fm_deviation."""
    from parsers.fm.voice import BAND_PROFILES

    required = ['name', 'signal_type', 'channels', 'channel_bw', 'fm_deviation']
    for band_key, profile in BAND_PROFILES.items():
        for field in required:
            assert field in profile, (
                f"Band '{band_key}' missing field '{field}'")
        assert len(profile['channels']) > 0, (
            f"Band '{band_key}' has no channels")
        assert profile['fm_deviation'] > 0, (
            f"Band '{band_key}' has fm_deviation <= 0")
        print(f"    {band_key}: {len(profile['channels'])} channels, "
              f"dev ±{profile['fm_deviation']} Hz")


def run_tests():
    tests = [
        ("SNR thresholds >= 10 dB", test_snr_thresholds),
        ("Holdover time consistent (2.0s)", test_holdover_consistent),
        ("MIN_TX_DURATION defined", test_min_tx_duration_exists),
        ("Audio sample rate consistent (16 kHz)", test_audio_sample_rate_consistent),
        ("MAX_TX_DURATION defined", test_voice_parser_has_max_duration),
        ("Band profiles complete", test_band_profiles_have_required_fields),
    ]

    print("=" * 60)
    print("Threshold Consistency Tests")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, fn in tests:
        print(f"\n  {name}")
        try:
            fn()
            print(f"  [PASS]")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{passed + failed} passed")
    print("=" * 60)
    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)

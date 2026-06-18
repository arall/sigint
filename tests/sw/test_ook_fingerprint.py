"""
Tests for dsp/ook.py fingerprint_protocol.

Regression for issue #11: a keyfob whose pulses cluster cleanly
(short/long ratio in [2.2, 4.0]) but whose gaps do NOT cluster used to
crash with `TypeError: cannot unpack non-iterable NoneType object`.
The crash happened inside the parser's transmission-end handler, where
capture/base.py swallows parser exceptions — so the burst showed on the
display but no detection was ever logged.

Run:
    python3 tests/sw/test_ook_fingerprint.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _bursts(pulses_gaps):
    return [{'pulse_us': p, 'gap_us': g} for p, g in pulses_gaps]


def test_clean_pulses_irregular_gaps_does_not_crash():
    """pulse_clusters truthy + gap_clusters None + len(pulses) >= 20.

    Previously this combination tried to unpack a None gap_clusters and
    raised TypeError, which the capture layer swallowed -> no log row.
    """
    from dsp.ook import fingerprint_protocol

    # 24 bursts: alternating short(100us)/long(300us) pulses -> ratio 3.0,
    # gaps that span three widths so they never form a clean 2-cluster split.
    gaps = [120, 480, 900]
    pulses_gaps = [(100 if i % 2 == 0 else 300, gaps[i % 3]) for i in range(24)]

    fp = fingerprint_protocol(_bursts(pulses_gaps))

    assert fp['protocol'] != 'Unknown'
    assert fp['bit_count'] > 0


def test_fingerprint_always_returns_required_keys():
    """The parser does hard-key access (fp['bit_count'] etc.) on the result."""
    from dsp.ook import fingerprint_protocol

    for bursts in ([], _bursts([(100, 200)] * 3), _bursts([(100 if i % 2 else 300, 250) for i in range(30)])):
        fp = fingerprint_protocol(bursts)
        for key in ('protocol', 'code_type', 'bit_count', 'data_hex', 'confidence', 'details'):
            assert key in fp, f"missing {key} for {len(bursts)} bursts"


if __name__ == '__main__':
    test_clean_pulses_irregular_gaps_does_not_crash()
    test_fingerprint_always_returns_required_keys()
    print("ok")

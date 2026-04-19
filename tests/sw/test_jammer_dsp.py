"""
Tests for dsp/jammer.py — pure math, no hardware.

Covers the three decisions the detector makes:

  1. Spectral flatness separates "noise-like" from "signal-like"
     inputs — a prerequisite for telling broadband jammers from loud
     narrowband emitters.
  2. `band_sample_from_psd` extracts a stable median-based noise
     floor even in the presence of big peaks.
  3. `decide` fires on sustained (flatness + elevation) samples,
     ignores narrowband peaks, and honours the min_consec +
     hysteresis rules.

Run:
    python3 tests/sw/test_jammer_dsp.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


# --- flatness -------------------------------------------------------------

def test_flatness_of_uniform_is_one():
    """Perfectly flat PSD = 1.0 exactly."""
    from dsp.jammer import spectral_flatness
    psd = np.ones(1024)
    assert abs(spectral_flatness(psd) - 1.0) < 1e-9


def test_flatness_of_pure_tone_is_near_zero():
    """One huge bin, rest small — geo mean collapses, arith mean
    dominated by the peak. Ratio approaches 0."""
    from dsp.jammer import spectral_flatness
    psd = np.ones(1024) * 1e-6
    psd[512] = 1.0   # single bin 6 orders of magnitude louder
    f = spectral_flatness(psd)
    assert f < 0.02, f"expected ~0, got {f}"


def test_flatness_of_white_noise_is_high():
    """Gaussian-magnitude noise is effectively flat over a large PSD."""
    from dsp.jammer import spectral_flatness
    rng = np.random.default_rng(1)
    psd = rng.exponential(scale=1.0, size=4096)  # chi-square-ish PSD
    assert spectral_flatness(psd) > 0.55


def test_flatness_empty_or_zero_input_returns_zero():
    from dsp.jammer import spectral_flatness
    assert spectral_flatness(np.array([])) == 0.0
    assert spectral_flatness(np.zeros(128)) == 0.0


# --- band sample reduction ------------------------------------------------

def test_band_sample_median_ignores_strong_peak():
    """A single strong bin shouldn't pull the noise_floor_db estimate.
    Peak_db surfaces it separately for diagnostics."""
    from dsp.jammer import band_sample_from_psd
    psd = np.full(1024, 1e-8)
    psd[100] = 1.0
    s = band_sample_from_psd(psd)
    assert s.peak_db > -10.0
    # -80 dB = 1e-8 baseline; median shouldn't drift much.
    assert -90.0 < s.noise_floor_db < -70.0
    # One peak in an otherwise-flat field: the arith mean gets pulled
    # by the peak, so flatness drops toward 0. Verify it's well under
    # the 0.5 trigger threshold — this is exactly the "loud narrowband
    # signal" case the detector must reject.
    assert s.flatness < 0.5


# --- decide: sustained noise fires ---------------------------------------

def _sample(noise_db, flatness):
    from dsp.jammer import BandSample
    return BandSample(noise_floor_db=noise_db, peak_db=noise_db + 3,
                      flatness=flatness, bins=1024)


def test_decide_initial_sample_sets_baseline_and_does_not_fire():
    from dsp.jammer import DetectionState, decide
    st = DetectionState()
    fired, _ = decide(_sample(-80.0, 0.9), st,
                      elevation_threshold_db=10.0,
                      flatness_threshold=0.5, min_consec=3)
    assert not fired
    assert st.baseline_db == -80.0


def test_decide_fires_after_min_consec_elevated_flat_samples():
    from dsp.jammer import DetectionState, decide
    st = DetectionState(baseline_db=-80.0)
    # Two elevated samples — not enough yet.
    for _ in range(2):
        fired, _ = decide(_sample(-60.0, 0.9), st,
                          elevation_threshold_db=10.0,
                          flatness_threshold=0.5, min_consec=3)
        assert not fired
    # Third crosses the consec threshold.
    fired, _ = decide(_sample(-60.0, 0.9), st,
                      elevation_threshold_db=10.0,
                      flatness_threshold=0.5, min_consec=3)
    assert fired
    assert st.firing


def test_decide_rejects_peaky_elevation():
    """Loud-but-peaky sample is NOT a jammer — strong legit signal."""
    from dsp.jammer import DetectionState, decide
    st = DetectionState(baseline_db=-80.0)
    for _ in range(10):
        fired, _ = decide(_sample(-40.0, 0.1), st,
                          elevation_threshold_db=10.0,
                          flatness_threshold=0.5, min_consec=3)
        assert not fired


def test_decide_resets_counter_on_any_dropout():
    """Want CONSECUTIVE hits, not enough-in-a-window. Anything non-
    triggering resets the counter."""
    from dsp.jammer import DetectionState, decide
    st = DetectionState(baseline_db=-80.0)
    # hit, hit, MISS, hit, hit — should NOT fire (counter resets).
    decide(_sample(-60.0, 0.9), st, min_consec=3)
    decide(_sample(-60.0, 0.9), st, min_consec=3)
    decide(_sample(-80.0, 0.9), st, min_consec=3)  # reset
    fired1, _ = decide(_sample(-60.0, 0.9), st, min_consec=3)
    fired2, _ = decide(_sample(-60.0, 0.9), st, min_consec=3)
    assert not fired1
    assert not fired2


def test_decide_leaves_firing_state_only_after_clear():
    """Once in the firing state, must see a genuinely-cleared sample
    (below baseline + hysteresis) before returning to armed."""
    from dsp.jammer import DetectionState, decide
    st = DetectionState(baseline_db=-80.0)
    for _ in range(3):
        decide(_sample(-60.0, 0.9), st,
               elevation_threshold_db=10.0, min_consec=3)
    assert st.firing
    # Slightly reduced but still elevated — should stay firing.
    still, off = decide(_sample(-75.0, 0.9), st,
                        elevation_threshold_db=10.0,
                        hysteresis_db=3.0, min_consec=3)
    assert still
    assert not off
    # Back to baseline — transition off.
    still, off = decide(_sample(-80.0, 0.9), st,
                        elevation_threshold_db=10.0, hysteresis_db=3.0)
    assert not still
    assert off


# --- run_baseline --------------------------------------------------------

def test_run_baseline_returns_median():
    from dsp.jammer import run_baseline
    samples = [_sample(-80.0, 0.8), _sample(-79.0, 0.8),
               _sample(-81.0, 0.8), _sample(-50.0, 0.8)]  # one outlier
    # Median (50th percentile) should ignore the spike.
    b = run_baseline(samples)
    assert -82.0 <= b <= -78.0


def test_run_baseline_falls_back_when_empty():
    from dsp.jammer import run_baseline
    b = run_baseline([])
    # Any non-crashing return is acceptable for the empty case — the
    # scanner prints the baseline and moves on; we just don't want to
    # blow up on "dongle died during calibration".
    assert b < 0


# --- band_sample_from_iq sanity ------------------------------------------

def test_band_sample_from_iq_accepts_complex_input():
    """End-to-end: IQ samples → BandSample. Doesn't assert exact dB
    (scipy.welch's exact scaling isn't worth pinning in a unit test);
    just verifies the path runs and returns sane-shaped numbers."""
    from dsp.jammer import band_sample_from_iq
    rng = np.random.default_rng(42)
    samples = (rng.standard_normal(8192) + 1j * rng.standard_normal(8192)).astype(np.complex64)
    s = band_sample_from_iq(samples, sample_rate=2e6, fft_size=1024)
    assert s.bins > 0
    assert -200.0 < s.noise_floor_db < 50.0
    # Near-white noise → high flatness
    assert s.flatness > 0.5


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"  ERR  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(0 if failures == 0 else 1)

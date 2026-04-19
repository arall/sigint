#!/usr/bin/env python3
"""
Parallel SW test runner.

The DSP-heavy tests (false detections, channelizer, multiband demod)
each synthesize multi-second RF signals and run the full detection
pipeline, which takes 15-60s per test. Sequentially that's ~3.5 min
total. Running them in parallel across the Pi 5's four cores cuts
wall clock to ~max(slowest test) ≈ 1 min.

Tests are fully independent: each one sets up its own temp dir,
doesn't touch shared files, doesn't talk to hardware. Safe to run
concurrently.

Usage:
    python3 tests/run_tests.py
    python3 tests/run_tests.py --workers 2    # throttle on underpowered boxes
    python3 tests/run_tests.py --no-whisper   # skip the transcription test
"""

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ANSI colors — only used when stdout is a tty
_IS_TTY = sys.stdout.isatty()
def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _IS_TTY else s
RED    = lambda s: _c("0;31", s)
GREEN  = lambda s: _c("0;32", s)
YELLOW = lambda s: _c("0;33", s)
BOLD   = lambda s: _c("1", s)
DIM    = lambda s: _c("2", s)


# (display name, script path) pairs. Order matches the previous runner
# so a human skimming the output isn't surprised.
SW_TESTS = [
    ("Threshold consistency",          "tests/sw/test_thresholds.py"),
    ("False detection prevention",     "tests/sw/test_false_detections.py"),
    ("Multi-band demod quality",       "tests/sw/test_multiband_demod.py"),
    ("Voice detection accuracy",       "tests/sw/test_voice_detection.py"),
    ("FM voice parser",                "tests/sw/test_fm_voice_parser.py"),
    ("PMR audio quality",              "tests/sw/test_pmr_quality.py"),
    ("PMR demod pipeline",             "tests/sw/test_pmr_demod.py"),
    ("DB + logger (threading)",        "tests/sw/test_db_logger.py"),
    ("PersonaDB merge semantics",      "tests/sw/test_persona_db.py"),
    ("ApDB merge semantics",           "tests/sw/test_ap_db.py"),
    ("Web loaders",                    "tests/sw/test_web_loaders.py"),
    ("Web SQL fetch (categories)",     "tests/sw/test_web_fetch.py"),
    ("Web SQL state/log/activity",     "tests/sw/test_web_fetch_state.py"),
    ("Web sessions",                   "tests/sw/test_web_sessions.py"),
    ("Apple Continuity + AirTag",      "tests/sw/test_apple_continuity.py"),
    ("Opportunistic RSSI calibration", "tests/sw/test_calibration.py"),
    ("Live multi-node triangulation",  "tests/sw/test_triangulate_live.py"),
    ("Position overrides (drag)",      "tests/sw/test_position_overrides.py"),
    ("AgentManager (C2 ingest)",       "tests/sw/test_server_agent_manager.py"),
    ("Cross-node witnesses",           "tests/sw/test_cross_node_witnesses.py"),
]

WHISPER_TEST = ("Transcription pipeline", "tests/sw/test_transcribe.py")


def _run_one(args):
    """Worker: run a single test. Returns (name, returncode, elapsed, output)."""
    name, path = args
    t0 = time.time()
    try:
        r = subprocess.run(
            ["python3", path],
            capture_output=True, text=True,
            cwd=REPO_ROOT,
            timeout=300,
        )
        return (name, r.returncode, time.time() - t0, r.stdout + r.stderr)
    except subprocess.TimeoutExpired as e:
        return (name, -1, time.time() - t0, f"[TIMEOUT after 300s]\n{e}")
    except Exception as e:
        return (name, -1, time.time() - t0, f"[ERROR] {type(e).__name__}: {e}")


def _whisper_available():
    try:
        subprocess.run(
            ["python3", "-c", "import whisper"],
            capture_output=True, check=True, timeout=10, cwd=REPO_ROOT,
        )
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description="Parallel SW test runner")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel worker count (default: 4)")
    ap.add_argument("--no-whisper", action="store_true",
                    help="skip transcription pipeline test")
    args = ap.parse_args()

    tests = list(SW_TESTS)
    skipped = []
    if not args.no_whisper:
        if _whisper_available():
            tests.append(WHISPER_TEST)
        else:
            skipped.append((WHISPER_TEST[0], "whisper not installed"))

    print("=" * 68)
    print(f"  SDR Test Suite — {len(tests)} tests, {args.workers} workers")
    print("=" * 68)

    t0 = time.time()
    results = {}
    longest_name = max(len(n) for n, _ in tests) if tests else 0

    # Run the pool; stream results as they complete so the user sees
    # progress instead of staring at a blank screen.
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_run_one, t): t for t in tests}
        completed = 0
        for fut in as_completed(futs):
            name, rc, dt, out = fut.result()
            results[name] = (rc, dt, out)
            completed += 1
            status = GREEN("PASS") if rc == 0 else RED("FAIL")
            print(f"  [{completed:2d}/{len(tests)}] {BOLD(name):<{longest_name + 12}} "
                  f"{DIM(f'{dt:5.1f}s')}  {status}")

    wall = time.time() - t0
    print("\n" + "=" * 68)

    # Ordered summary (matches tests[] order) for fail details
    passed = failed = 0
    for name, _ in tests:
        rc, dt, out = results[name]
        if rc == 0:
            passed += 1
        else:
            failed += 1
            print(f"\n{RED(BOLD(f'FAIL: {name}'))}")
            # Print the last ~500 chars of output so the user gets context
            print("\n".join("  " + line for line in out.splitlines()[-20:]))

    for name, reason in skipped:
        print(f"  {YELLOW('SKIP')} {name} ({reason})")

    total = passed + failed
    color = GREEN if failed == 0 else RED
    print(f"\n  {color(BOLD(f'{passed}/{total} passed'))}  "
          f"{DIM(f'(wall: {wall:.1f}s)')}")
    if skipped:
        print(f"  {YELLOW(f'{len(skipped)} skipped')}")
    print("=" * 68)
    sys.exit(failed)


if __name__ == "__main__":
    main()

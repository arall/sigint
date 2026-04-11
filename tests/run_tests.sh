#!/bin/bash
#
# Run SDR test suite.
#
# Usage:
#   ./tests/run_tests.sh          # SW tests only (no hardware needed)
#   ./tests/run_tests.sh --hw     # Include HW tests (HackRF + RTL-SDR)
#   ./tests/run_tests.sh --all    # All tests including transcription
#

cd "$(dirname "$0")/.."
source venv/bin/activate

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

PASSED=0
FAILED=0
SKIPPED=0

run_test() {
    local name="$1"
    local cmd="$2"
    printf "${BOLD}%-45s${RESET}" "$name"
    if output=$(eval "$cmd" 2>&1); then
        printf "${GREEN}PASS${RESET}\n"
        PASSED=$((PASSED + 1))
    else
        printf "${RED}FAIL${RESET}\n"
        echo "$output" | tail -5 | sed 's/^/  /'
        FAILED=$((FAILED + 1))
    fi
}

skip_test() {
    local name="$1"
    local reason="$2"
    printf "${BOLD}%-45s${RESET}SKIP (%s)\n" "$name" "$reason"
    SKIPPED=$((SKIPPED + 1))
}

echo "============================================================"
echo "  SDR Test Suite"
echo "============================================================"
echo ""

# ---- Software tests (no hardware) ----
echo "${BOLD}Software tests (no hardware needed)${RESET}"
echo "------------------------------------------------------------"

run_test "Threshold consistency"          "python3 tests/sw/test_thresholds.py"
run_test "False detection prevention"     "python3 tests/sw/test_false_detections.py"
run_test "Multi-band demod quality"       "python3 tests/sw/test_multiband_demod.py"
run_test "Voice detection accuracy"       "python3 tests/sw/test_voice_detection.py"
run_test "FM voice parser"                "python3 tests/sw/test_fm_voice_parser.py"
run_test "PMR audio quality"              "python3 tests/sw/test_pmr_quality.py"
run_test "PMR demod pipeline"             "python3 tests/sw/test_pmr_demod.py"

# ---- Data layer tests ----
run_test "DB + logger (threading)"        "python3 tests/sw/test_db_logger.py"
run_test "PersonaDB merge semantics"      "python3 tests/sw/test_persona_db.py"
run_test "ApDB merge semantics"           "python3 tests/sw/test_ap_db.py"
run_test "Web loaders (categories/devices)" "python3 tests/sw/test_web_loaders.py"
run_test "Web SQL fetch (categories)"     "python3 tests/sw/test_web_fetch.py"
run_test "Web sessions"                   "python3 tests/sw/test_web_sessions.py"

# ---- Transcription tests (needs Whisper) ----
if python3 -c "import whisper" 2>/dev/null; then
    echo ""
    echo "${BOLD}Transcription tests (Whisper)${RESET}"
    echo "------------------------------------------------------------"
    run_test "Transcription pipeline"     "python3 tests/sw/test_transcribe.py"
else
    echo ""
    skip_test "Transcription pipeline" "whisper not installed"
fi

# ---- Hardware tests ----
if [[ "$1" == "--hw" || "$1" == "--all" ]]; then
    echo ""
    echo "${BOLD}Hardware tests (HackRF + RTL-SDR)${RESET}"
    echo "------------------------------------------------------------"

    if command -v hackrf_transfer &>/dev/null; then
        run_test "E2E voice (PMR CH1)"        "python3 tests/hw/test_e2e_voice.py --band pmr446 --channels 1"
        run_test "E2E voice (70cm CALL)"       "python3 tests/hw/test_e2e_voice.py --band 70cm --channels CALL"
        run_test "E2E voice (Marine CH16)"     "python3 tests/hw/test_e2e_voice.py --band marine --channels CH16"
        run_test "Scanner E2E (PMR CH1)"       "python3 tests/hw/test_scanner_e2e.py --channel 1"
    else
        skip_test "E2E voice tests" "hackrf_transfer not found"
        skip_test "Scanner E2E" "hackrf_transfer not found"
    fi
fi

# ---- Summary ----
echo ""
echo "============================================================"
TOTAL=$((PASSED + FAILED))
if [ $FAILED -eq 0 ]; then
    printf "  ${GREEN}${BOLD}All $TOTAL tests passed${RESET}"
else
    printf "  ${RED}${BOLD}$FAILED/$TOTAL tests failed${RESET}"
fi
[ $SKIPPED -gt 0 ] && printf " ($SKIPPED skipped)"
echo ""
echo "============================================================"

exit $FAILED

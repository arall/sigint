#!/bin/bash
#
# SDR test suite runner.
#
# The SW tests are dispatched to tests/run_tests.py which runs them in
# a process pool (4 workers by default, ~50s wall on a Pi 5). Hardware
# tests stay sequential — HackRF TX can only be used by one test at a
# time.
#
# Usage:
#   ./tests/run_tests.sh            # SW tests only (parallel)
#   ./tests/run_tests.sh --hw       # also include HW tests (HackRF + RTL-SDR)
#   ./tests/run_tests.sh --all      # same as --hw
#   ./tests/run_tests.sh --workers 2  # forwarded to run_tests.py
#

cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

# --- SW tests (parallel) ---
SW_ARGS=()
WANT_HW=0
for arg in "$@"; do
    case "$arg" in
        --hw|--all) WANT_HW=1 ;;
        *)          SW_ARGS+=("$arg") ;;
    esac
done

python3 tests/run_tests.py "${SW_ARGS[@]}"
SW_RC=$?

# --- HW tests (sequential — HackRF TX is exclusive) ---
if [ "$WANT_HW" -eq 1 ]; then
    echo ""
    echo "${BOLD}Hardware tests (HackRF + RTL-SDR)${RESET}"
    echo "------------------------------------------------------------"

    HW_FAILED=0
    run_hw_test() {
        local name="$1"
        local cmd="$2"
        printf "${BOLD}%-45s${RESET}" "$name"
        if output=$(eval "$cmd" 2>&1); then
            printf "${GREEN}PASS${RESET}\n"
        else
            printf "${RED}FAIL${RESET}\n"
            echo "$output" | tail -5 | sed 's/^/  /'
            HW_FAILED=$((HW_FAILED + 1))
        fi
    }

    if command -v hackrf_transfer &>/dev/null; then
        run_hw_test "E2E voice (PMR CH1)"     "python3 tests/hw/test_e2e_voice.py --band pmr446 --channels 1"
        run_hw_test "E2E voice (70cm CALL)"   "python3 tests/hw/test_e2e_voice.py --band 70cm --channels CALL"
        run_hw_test "E2E voice (Marine CH16)" "python3 tests/hw/test_e2e_voice.py --band marine --channels CH16"
        run_hw_test "Scanner E2E (PMR CH1)"   "python3 tests/hw/test_scanner_e2e.py --channel 1"
    else
        printf "${BOLD}%-45s${RESET}SKIP (hackrf_transfer not found)\n" "HW tests"
    fi

    [ $HW_FAILED -gt 0 ] && SW_RC=$((SW_RC + HW_FAILED))
fi

exit $SW_RC

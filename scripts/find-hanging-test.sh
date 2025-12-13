#!/bin/bash
# Script to find which test file causes pytest to hang
# Runs each test file individually with a timeout
# Usage: ./scripts/find-hanging-test.sh [timeout_seconds]

TIMEOUT=${1:-15}  # Default 15 second timeout per file
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "================================================"
echo "Finding hanging test file"
echo "Timeout per file: ${TIMEOUT}s"
echo "================================================"
echo ""

# Find all test files
TEST_FILES=$(find tests -name "test_*.py" -type f | sort)
TOTAL=$(echo "$TEST_FILES" | wc -l | tr -d ' ')
CURRENT=0

for test_file in $TEST_FILES; do
    CURRENT=$((CURRENT + 1))
    echo -n "[$CURRENT/$TOTAL] $test_file ... "

    # Run with timeout, capture exit code
    START_TIME=$(date +%s)
    timeout "$TIMEOUT" uv run pytest "$test_file" -q --no-header --no-cov 2>/dev/null
    EXIT_CODE=$?
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))

    if [ $EXIT_CODE -eq 124 ]; then
        echo "TIMEOUT (>${TIMEOUT}s) *** HANGING ***"
        echo ""
        echo "================================================"
        echo "FOUND HANGING TEST: $test_file"
        echo "================================================"
        echo ""
        echo "To debug further, run:"
        echo "  uv run pytest $test_file -v"
        echo ""
        echo "Or test individual classes/functions:"
        echo "  uv run pytest $test_file -v --collect-only"
        exit 1
    elif [ $EXIT_CODE -eq 0 ]; then
        echo "PASS (${DURATION}s)"
    else
        echo "FAIL (${DURATION}s, exit=$EXIT_CODE)"
    fi
done

echo ""
echo "================================================"
echo "All test files completed without hanging!"
echo "================================================"

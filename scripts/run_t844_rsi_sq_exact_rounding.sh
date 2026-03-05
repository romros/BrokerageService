#!/bin/bash
# T8.44 — RSI SQ exact + getRounded half-up sweep fins 17/17
#
# Candles oracle ja passen (candle_parity=true). Sweep decimals 0..4 amb half-up.
# Output: rounding_sweep.csv, best_rounding.json, mismatch_debug.csv
#
# Prerequisits: CSV oracle a user/t842_oracle_export (run_t843)
# NO sintètic, NO BI5, NO xarxa.
#
# Ús: ./scripts/run_t844_rsi_sq_exact_rounding.sh [--docker]

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
OUT=lab/runner/out_compare
ARTIFACTS="$OUT/artifacts/T8.44/EURUSD/1m/2026-02-01_2026-02-02"

cd "$PROJECT_ROOT"
mkdir -p "$ARTIFACTS"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

USE_DOCKER=0
for arg in "$@"; do
  case "$arg" in --docker) USE_DOCKER=1 ;; esac
done

echo "[T8.44] Executant RSI SQ-exact + getRounded half-up sweep (decimals 0..4)..."
if [ "$USE_DOCKER" = "1" ]; then
  docker run --rm -v "$PROJECT_ROOT:/app" -v "/mnt/volume-SQ/user:/mnt/volume-SQ/user:ro" -w /app python:3.11-slim \
    bash -c "pip install -q pandas 2>/dev/null; export PYTHONPATH=/app:\$PYTHONPATH; python3 $OUT/mt4_m1_rsi35_exit60_parity.py --t844 --lab-source oracle --no-api" \
    2>&1 | tee "$ARTIFACTS/run.log"
else
  python3 "$OUT/mt4_m1_rsi35_exit60_parity.py" --t844 --lab-source oracle --no-api \
    2>&1 | tee "$ARTIFACTS/run.log"
fi

EXIT=${PIPESTATUS[0]}
echo ""
echo "[T8.44] Artifacts:"
echo "  rounding_sweep.csv"
echo "  best_rounding.json"
echo "  mismatch_debug.csv"
echo "  t844_report.json"
[ $EXIT -eq 0 ] && echo "PASS (17/17)" || echo "FAIL (exit $EXIT)"
exit $EXIT

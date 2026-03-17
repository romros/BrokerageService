#!/bin/bash
# T8.45 — Execution Contract Grid (oracle real) fins 17/17
#
# Grid 2×2: entry open[i] vs open[i+1] × exit open vs close.
# Oracle mode, RSI exact, round_decimals=1.
#
# Ús: ./scripts/run_t845_execution_grid.sh [--docker]

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
OUT=lab/runner/out_compare
ARTIFACTS="$OUT/artifacts/T8.45/EURUSD/1m/2026-02-01_2026-02-02"

cd "$PROJECT_ROOT"
mkdir -p "$ARTIFACTS"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

USE_DOCKER=0
for arg in "$@"; do
  case "$arg" in --docker) USE_DOCKER=1 ;; esac
done

echo "[T8.45] Executant Execution Contract Grid (oracle, RSI exact, round_d=1)..."
if [ "$USE_DOCKER" = "1" ]; then
  docker run --rm -v "$PROJECT_ROOT:/app" -v "/mnt/volume-SQ/user:/mnt/volume-SQ/user:ro" -w /app python:3.11-slim \
    bash -c "pip install -q pandas 2>/dev/null; export PYTHONPATH=/app:\$PYTHONPATH; python3 $OUT/execution_grid.py" \
    2>&1 | tee "$ARTIFACTS/run.log"
else
  python3 "$OUT/execution_grid.py" 2>&1 | tee "$ARTIFACTS/run.log"
fi

EXIT=${PIPESTATUS[0]}
echo ""
echo "[T8.45] Artifacts: execution_grid.csv, best_execution_variant.json"
[ $EXIT -eq 0 ] && echo "PASS (17/17)" || echo "FAIL (exit $EXIT)"
exit $EXIT

#!/bin/bash
# T8.46 — Signal Event Diff (oracle real) fins identificar el bar del 17è trade
#
# Ús: ./scripts/run_t846_signal_event_diff.sh [--docker]

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
OUT=lab/runner/out_compare
ARTIFACTS="$OUT/artifacts/T8.46/EURUSD/1m/2026-02-01_2026-02-02"

cd "$PROJECT_ROOT"
mkdir -p "$ARTIFACTS"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

USE_DOCKER=0
for arg in "$@"; do
  case "$arg" in --docker) USE_DOCKER=1 ;; esac
done

echo "[T8.46] Signal Event Diff (oracle, RSI exact, round_d=None MT4 parity)..."
if [ "$USE_DOCKER" = "1" ]; then
  OUT_LOG=$(docker run --rm -v "$PROJECT_ROOT:/app" -v "/mnt/volume-SQ/user:/mnt/volume-SQ/user:ro" -w /app python:3.11-slim \
    bash -c "pip install -q pandas 2>/dev/null; export PYTHONPATH=/app; python3 $OUT/signal_event_diff.py" 2>&1)
else
  OUT_LOG=$(python3 "$OUT/signal_event_diff.py" 2>&1)
fi
EXIT=$?
echo "$OUT_LOG"
echo "$OUT_LOG" > "$ARTIFACTS/run.log" 2>/dev/null || true
echo ""
echo "[T8.46] Artifacts: signal_events_lab.csv, signal_events_sq.csv, signal_event_diff.csv, first_divergence.json, gap_report.json"
exit $EXIT

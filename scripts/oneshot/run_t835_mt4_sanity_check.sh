#!/bin/bash
# T8.35 — MT4 Boundary & Concurrency Sanity Check
#
# Executa mt4_sanity_check.py i captura stdout a run.log.
#
# Ús: ./scripts/run_t835_mt4_sanity_check.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
MT4="$OUT/simpleexample_out_MT4.csv"
REPORT_DIR="$OUT/artifacts/T8.35/eurusd_ema200_rsi35_atr_d1/EURUSD/1d"

if [ ! -f "$MT4" ]; then
  echo "ERROR: MT4 CSV no trobat: $MT4"
  exit 1
fi

mkdir -p "$REPORT_DIR"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "[T8.35] Executant mt4_sanity_check..."
python3 lab/runner/out_compare/mt4_sanity_check.py \
  --mt4 "$MT4" \
  --expected-day-offset-h 5 \
  --tolerance-seconds 60 \
  --outdir "$REPORT_DIR" \
  --top-overlaps 10 2>&1 | tee "$REPORT_DIR/run.log"

echo ""
echo "Artifacts: $REPORT_DIR/"

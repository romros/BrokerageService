#!/bin/bash
# T8.32 — Quick Parity Triage: micro-checks <20s per triar tipus de divergència
#
# Executa quick_triage.py i captura stdout a run.log.
# Prerequisit: T8.31 (indicators_LAB_full.csv, trade_diff_report.json)
#
# Ús: ./scripts/run_t832_triage.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
INDICATORS="$OUT/indicators_LAB_full.csv"
MT4="$OUT/simpleexample_out_MT4.csv"
REPORT_DIR="$OUT/artifacts/T8.32/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01"
REPORT="$REPORT_DIR/triage_report.json"

if [ ! -f "$INDICATORS" ]; then
  echo "ERROR: No indicators found; run T8.31 export or pass --indicators path."
  exit 1
fi
if [ ! -f "$MT4" ]; then
  echo "ERROR: MT4 CSV no trobat: $MT4"
  exit 1
fi

mkdir -p "$REPORT_DIR"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "[T8.32] Executant quick_triage..."
python3 lab/runner/out_compare/quick_triage.py \
  --mt4 "$MT4" \
  --indicators "$INDICATORS" \
  --report "$REPORT" \
  --n 5 2>&1 | tee "$REPORT_DIR/run.log"

echo ""
echo "Artifacts: $REPORT_DIR/"

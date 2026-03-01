#!/bin/bash
# T8.34 — D1 Series Shape Audit: policies Sunday bar (baseline, drop_sunday, merge)
#
# Executa d1_policy_audit.py i captura stdout a run.log.
# Prerequisit: T8.31 (indicators_LAB_full.csv, trade_diff_report.json)
#
# Ús: ./scripts/run_t834_d1_policy_audit.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
INDICATORS="$OUT/indicators_LAB_full.csv"
MT4="$OUT/simpleexample_out_MT4.csv"
TRADE_DIFF="$OUT/trade_diff_report.json"
REPORT_DIR="$OUT/artifacts/T8.34/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01"

if [ ! -f "$INDICATORS" ]; then
  echo "ERROR: Indicators CSV no trobat; run T8.31 export."
  exit 1
fi
if [ ! -f "$MT4" ]; then
  echo "ERROR: MT4 CSV no trobat: $MT4"
  exit 1
fi

mkdir -p "$REPORT_DIR"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "[T8.34] Executant d1_policy_audit..."
python3 lab/runner/out_compare/d1_policy_audit.py \
  --indicators "$INDICATORS" \
  --mt4 "$MT4" \
  --trade-diff "$TRADE_DIFF" \
  --outdir "$REPORT_DIR" 2>&1 | tee "$REPORT_DIR/run.log"

echo ""
echo "Artifacts: $REPORT_DIR/"

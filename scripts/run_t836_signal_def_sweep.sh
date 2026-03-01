#!/bin/bash
# T8.36 — Signal Definition Sweep
#
# Executa signal_def_sweep.py i captura stdout a run.log.
# Prerequisit: indicators_LAB_full.csv, trade_diff_report.json (opcional)
#
# Ús: ./scripts/run_t836_signal_def_sweep.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
MT4="$OUT/simpleexample_out_MT4.csv"
CANDLES="$OUT/indicators_LAB_full.csv"
REPORT_DIR="$OUT/artifacts/T8.36/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01"

if [ ! -f "$MT4" ]; then
  echo "ERROR: MT4 CSV no trobat: $MT4"
  exit 1
fi
if [ ! -f "$CANDLES" ]; then
  echo "ERROR: Indicators/candles CSV no trobat: $CANDLES"
  echo "  Executa primer: ./scripts/run_t831_trade_diff.sh"
  exit 1
fi

mkdir -p "$REPORT_DIR"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "[T8.36] Executant signal_def_sweep..."
python3 lab/runner/out_compare/signal_def_sweep.py \
  --mt4 "$MT4" \
  --candles "$CANDLES" \
  --day-offset-h 5 \
  --outdir "$REPORT_DIR" \
  --pm-window 3 2>&1 | tee "$REPORT_DIR/run.log"

echo ""
echo "Artifacts: $REPORT_DIR/"

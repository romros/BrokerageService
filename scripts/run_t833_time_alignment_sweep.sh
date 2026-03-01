#!/bin/bash
# T8.33 — Time Alignment Sweep: sweep d'offsets per maximitzar matching MT4↔LAB
#
# Executa time_alignment_sweep.py i captura stdout a run.log.
# Prerequisit: T8.31 (indicators_LAB_full.csv, LAB trades)
#
# Ús: ./scripts/run_t833_time_alignment_sweep.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
INDICATORS="$OUT/indicators_LAB_full.csv"
MT4="$OUT/simpleexample_out_MT4.csv"
LAB_TRADES="$OUT/contract_open_i_mt4_baropen/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01/trades.csv"
REPORT_DIR="$OUT/artifacts/T8.33/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01"

if [ ! -f "$INDICATORS" ]; then
  echo "ERROR: No indicators found; run T8.31 export."
  exit 1
fi
if [ ! -f "$MT4" ]; then
  echo "ERROR: MT4 CSV no trobat: $MT4"
  exit 1
fi
if [ ! -f "$LAB_TRADES" ]; then
  echo "ERROR: LAB trades no trobat: $LAB_TRADES"
  echo "  Executa primer: ./scripts/run_t830_contract_grid.sh"
  exit 1
fi

mkdir -p "$REPORT_DIR"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "[T8.33] Executant time_alignment_sweep..."
python3 lab/runner/out_compare/time_alignment_sweep.py \
  --mt4-csv "$MT4" \
  --lab-trades "$LAB_TRADES" \
  --indicators "$INDICATORS" \
  --outdir "$REPORT_DIR" 2>&1 | tee "$REPORT_DIR/run.log"

echo ""
echo "Artifacts: $REPORT_DIR/"

#!/bin/bash
# T8.31 — Trade Diff Analyzer: export indicadors + anàlisi matched/unmatched
#
# 1. Export indicadors LAB (si no existeix o --force)
# 2. Executa trade_diff_analyzer
#
# Ús: ./scripts/run_t831_trade_diff.sh [--force-export]
# Prerequisit: historical_datalayer (per export) o indicators_LAB_full.csv preexistent

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
INDICATORS="$OUT/indicators_LAB_full.csv"
LAB_TRADES="$OUT/contract_open_i_mt4_baropen/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01/trades.csv"
USE_DOCKER="${USE_DOCKER:-1}"
IMAGE="python:3.11-slim"
NETWORK="brokerageservice_trading"
BASE_URL_DOCKER="http://datalayer-proxy:8081"

FORCE_EXPORT=0
[ "${1:-}" = "--force-export" ] && FORCE_EXPORT=1

# 1. Export indicadors si cal
if [ ! -f "$INDICATORS" ] || [ "$FORCE_EXPORT" = "1" ]; then
  echo "[T8.31] Exportant indicadors LAB 2003-05 → 2026-01..."
  if [ "$USE_DOCKER" = "1" ]; then
    docker run --rm --network "$NETWORK" -v "$PROJECT_ROOT:/app" -w /app "$IMAGE" \
      bash -c "
        pip install -q pyyaml pandas numpy 2>/dev/null
        export PYTHONPATH=/app:\$PYTHONPATH
        python3 -m application.tools.export_indicators_csv \
          --symbol EURUSD --from 2003-05-05 --to 2026-01-01 \
          --base-url $BASE_URL_DOCKER --warmup-bars 300 --day-offset-h 5 \
          --mt4-like --out $INDICATORS
      "
  else
    python3 -m application.tools.export_indicators_csv \
      --symbol EURUSD --from 2003-05-05 --to 2026-01-01 \
      --base-url "${BASE_URL:-http://localhost:8081}" --warmup-bars 300 --day-offset-h 5 \
      --mt4-like --out "$INDICATORS"
  fi
else
  echo "[T8.31] Indicadors existents: $INDICATORS (usa --force-export per regenerar)"
fi

if [ ! -f "$LAB_TRADES" ]; then
  echo "ERROR: LAB trades no trobat: $LAB_TRADES"
  echo "  Executa primer: ./scripts/oneshot/run_t830_contract_grid.sh"
  exit 1
fi

# 2. Trade diff analyzer (només stdlib, no cal Docker)
echo ""
echo "[T8.31] Executant trade_diff_analyzer..."
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
python3 lab/runner/out_compare/trade_diff_analyzer.py \
  --mt4-csv "$OUT/simpleexample_out_MT4.csv" \
  --lab-trades "$LAB_TRADES" \
  --indicators "$INDICATORS" \
  --out-dir "$OUT"

echo ""
echo "Artifacts: $OUT/trade_diff_report.json  $OUT/trade_diff_report.csv"

#!/bin/bash
# T8.37 — Apply t836_best signal_def (RSI ema_gains sobre typical) + end-to-end trade diff
#
# 1. Export indicadors LAB amb --signal-def t836_best
# 2. Backtest amb signal_def=t836_best (mateix contracte best: open_i + mt4_baropen)
# 3. Trade diff amb LAB trades + indicadors t836_best
#
# Ús: ./scripts/run_t837_t836_best_e2e.sh [--force-export]
# Prerequisit: historical_datalayer, MT4 CSV

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
INDICATORS_BEST="$OUT/indicators_LAB_full_t836_best.csv"
LAB_TRADES_BASELINE="$OUT/contract_open_i_mt4_baropen/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01/trades.csv"
ARTIFACTS_T837="$OUT/artifacts/T8.37/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01"
LAB_TRADES_T837="$ARTIFACTS_T837/trades.csv"
REPORT_T837="$OUT/artifacts/T8.37/trade_diff_report.json"
USE_DOCKER="${USE_DOCKER:-1}"
IMAGE="python:3.11-slim"
NETWORK="brokerageservice_trading"
BASE_URL_DOCKER="http://datalayer-proxy:8081"
BASE_URL="${BASE_URL:-http://localhost:8081}"
STRATEGY=eurusd_ema200_rsi35_atr_d1
FROM=2006-12-01
TO=2026-01-01
WARMUP=250

FORCE_EXPORT=0
[ "${1:-}" = "--force-export" ] && FORCE_EXPORT=1

# 1. Export indicadors t836_best
if [ ! -f "$INDICATORS_BEST" ] || [ "$FORCE_EXPORT" = "1" ]; then
  echo "[T8.37] Exportant indicadors LAB signal_def=t836_best..."
  if [ "$USE_DOCKER" = "1" ]; then
    docker run --rm --network "$NETWORK" -v "$PROJECT_ROOT:/app" -w /app "$IMAGE" \
      bash -c "
        pip install -q pyyaml pandas numpy 2>/dev/null
        export PYTHONPATH=/app:\$PYTHONPATH
        python3 -m application.tools.export_indicators_csv \
          --symbol EURUSD --from 2003-05-05 --to 2026-01-01 \
          --base-url $BASE_URL_DOCKER --warmup-bars 300 --day-offset-h 5 \
          --mt4-like --signal-def t836_best --out $INDICATORS_BEST
      "
  else
    python3 -m application.tools.export_indicators_csv \
      --symbol EURUSD --from 2003-05-05 --to 2026-01-01 \
      --base-url "$BASE_URL" --warmup-bars 300 --day-offset-h 5 \
      --mt4-like --signal-def t836_best --out "$INDICATORS_BEST"
  fi
  echo "  → $INDICATORS_BEST"
else
  echo "[T8.37] Indicadors t836_best existents: $INDICATORS_BEST (usa --force-export per regenerar)"
fi

# 2. Backtest amb signal_def=t836_best (mateix contracte best: open_i + mt4_baropen)
echo ""
echo "[T8.37] Backtest signal_def=t836_best..."
mkdir -p "$ARTIFACTS_T837"
if [ "$USE_DOCKER" = "1" ]; then
  docker run --rm --network "$NETWORK" -v "$PROJECT_ROOT:/app" -w /app "$IMAGE" \
    bash -c "
      pip install -q pyyaml pandas numpy 2>/dev/null
      export PYTHONPATH=/app:\$PYTHONPATH
      python3 lab/runner/backtest/run_backtest.py \
        --strategy $STRATEGY --symbol EURUSD --tf 1d --from $FROM --to $TO \
        --base-url $BASE_URL_DOCKER --warmup-bars $WARMUP --artifacts-dir $OUT/artifacts/T8.37 \
        --indicator-mode mt4_like --ema-seed sma --signal-def t836_best \
        --entry-fill open_i --signal-contract mt4_baropen
    "
else
  python3 lab/runner/backtest/run_backtest.py \
    --strategy "$STRATEGY" --symbol EURUSD --tf 1d --from "$FROM" --to "$TO" \
    --base-url "$BASE_URL" --warmup-bars "$WARMUP" --artifacts-dir "$OUT/artifacts/T8.37" \
    --indicator-mode mt4_like --ema-seed sma --signal-def t836_best \
    --entry-fill open_i --signal-contract mt4_baropen
fi

if [ ! -f "$LAB_TRADES_T837" ]; then
  echo "ERROR: trades.csv no trobat: $LAB_TRADES_T837"
  exit 1
fi

# 3. Trade diff amb LAB trades t836_best + indicadors t836_best
echo ""
echo "[T8.37] Trade diff (LAB t836_best vs MT4)..."
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
python3 lab/runner/out_compare/trade_diff_analyzer.py \
  --mt4-csv "$OUT/simpleexample_out_MT4.csv" \
  --lab-trades "$LAB_TRADES_T837" \
  --indicators "$INDICATORS_BEST" \
  --out-dir "$OUT/artifacts/T8.37"

echo ""
echo "[T8.37] RESULTAT"
echo "  Report t836_best: $REPORT_T837"
echo "  Comparar amb baseline: $OUT/trade_diff_report.json"
echo "  Comanda: diff <(jq .matched $OUT/trade_diff_report.json) <(jq .matched $REPORT_T837)"

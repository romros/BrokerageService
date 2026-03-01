#!/bin/bash
# T8.38 — MT4 Entry Gating Inference + Apply + e2e
#
# 1. Infer cadència MT4 + grid gating → best_gating_profile.json
# 2. Export indicadors (baseline o t836_best)
# 3. Backtest amb --entry-gating-profile
# 4. Trade diff
#
# Ús: ./scripts/run_t838_entry_gating_e2e.sh [--signal-def baseline|t836_best] [--force-export]
# Prerequisit: historical_datalayer, MT4 CSV, indicators existents o --force-export

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
ARTIFACTS_T838="$OUT/artifacts/T8.38"
STRATEGY=eurusd_ema200_rsi35_atr_d1
FROM=2006-12-01
TO=2026-01-01
WARMUP=250
USE_DOCKER="${USE_DOCKER:-1}"
IMAGE="python:3.11-slim"
NETWORK="brokerageservice_trading"
BASE_URL_DOCKER="http://datalayer-proxy:8081"
BASE_URL="${BASE_URL:-http://localhost:8081}"

SIGNAL_DEF=baseline
FORCE_EXPORT=0

for arg in "$@"; do
  case "$arg" in
    --signal-def=*) SIGNAL_DEF="${arg#*=}" ;;
    --signal-def) shift; SIGNAL_DEF="$1" ;;
    --force-export) FORCE_EXPORT=1 ;;
  esac
done

if [ "$SIGNAL_DEF" = "t836_best" ]; then
  INDICATORS="$OUT/indicators_LAB_full_t836_best.csv"
else
  INDICATORS="$OUT/indicators_LAB_full.csv"
fi

# 1. Inferència + grid
echo "[T8.38] Inferència cadència MT4 + grid gating..."
mkdir -p "$ARTIFACTS_T838"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
python3 lab/runner/out_compare/entry_gating_infer.py \
  --mt4-csv "$OUT/simpleexample_out_MT4.csv" \
  --indicators "$INDICATORS" \
  --out-dir "$ARTIFACTS_T838"

BEST_PROFILE="$ARTIFACTS_T838/best_gating_profile.json"
if [ ! -f "$BEST_PROFILE" ]; then
  echo "ERROR: best_gating_profile.json no trobat"
  exit 1
fi

# 2. Export indicadors (si cal)
if [ ! -f "$INDICATORS" ] || [ "$FORCE_EXPORT" = "1" ]; then
  echo "[T8.38] Exportant indicadors signal_def=$SIGNAL_DEF..."
  if [ "$USE_DOCKER" = "1" ]; then
    docker run --rm --network "$NETWORK" -v "$PROJECT_ROOT:/app" -w /app "$IMAGE" \
      bash -c "
        pip install -q pyyaml pandas numpy 2>/dev/null
        export PYTHONPATH=/app:\$PYTHONPATH
        python3 -m application.tools.export_indicators_csv \
          --symbol EURUSD --from 2003-05-05 --to 2026-01-01 \
          --base-url $BASE_URL_DOCKER --warmup-bars 300 --day-offset-h 5 \
          --mt4-like --signal-def $SIGNAL_DEF --out $INDICATORS
      "
  else
    python3 -m application.tools.export_indicators_csv \
      --symbol EURUSD --from 2003-05-05 --to 2026-01-01 \
      --base-url "$BASE_URL" --warmup-bars 300 --day-offset-h 5 \
      --mt4-like --signal-def "$SIGNAL_DEF" --out "$INDICATORS"
  fi
  echo "  → $INDICATORS"
fi

# 3. Backtest amb gating
LAB_TRADES="$ARTIFACTS_T838/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/${FROM}_${TO}/trades.csv"
mkdir -p "$(dirname "$LAB_TRADES")"
echo ""
echo "[T8.38] Backtest signal_def=$SIGNAL_DEF + entry_gating..."
if [ "$USE_DOCKER" = "1" ]; then
  docker run --rm --network "$NETWORK" -v "$PROJECT_ROOT:/app" -w /app "$IMAGE" \
    bash -c "
      pip install -q pyyaml pandas numpy 2>/dev/null
      export PYTHONPATH=/app:\$PYTHONPATH
      python3 lab/runner/backtest/run_backtest.py \
        --strategy $STRATEGY --symbol EURUSD --tf 1d --from $FROM --to $TO \
        --base-url $BASE_URL_DOCKER --warmup-bars $WARMUP --artifacts-dir $ARTIFACTS_T838 \
        --indicator-mode mt4_like --ema-seed sma --signal-def $SIGNAL_DEF \
        --entry-fill open_i --signal-contract mt4_baropen \
        --entry-gating-profile $BEST_PROFILE
    "
else
  python3 lab/runner/backtest/run_backtest.py \
    --strategy "$STRATEGY" --symbol EURUSD --tf 1d --from "$FROM" --to "$TO" \
    --base-url "$BASE_URL" --warmup-bars "$WARMUP" --artifacts-dir "$ARTIFACTS_T838" \
    --indicator-mode mt4_like --ema-seed sma --signal-def "$SIGNAL_DEF" \
    --entry-fill open_i --signal-contract mt4_baropen \
    --entry-gating-profile "$BEST_PROFILE"
fi

if [ ! -f "$LAB_TRADES" ]; then
  echo "ERROR: trades.csv no trobat: $LAB_TRADES"
  exit 1
fi

# 4. Trade diff
echo ""
echo "[T8.38] Trade diff (LAB + gating vs MT4)..."
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
python3 lab/runner/out_compare/trade_diff_analyzer.py \
  --mt4-csv "$OUT/simpleexample_out_MT4.csv" \
  --lab-trades "$LAB_TRADES" \
  --indicators "$INDICATORS" \
  --out-dir "$ARTIFACTS_T838"

echo ""
echo "[T8.38] RESULTAT"
echo "  Report: $ARTIFACTS_T838/trade_diff_report.json"
echo "  Best profile: $BEST_PROFILE"
echo "  Comparar: jq '.n_matched, .category_counts' $ARTIFACTS_T838/trade_diff_report.json"

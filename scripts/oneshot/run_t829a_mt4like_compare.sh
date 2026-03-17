#!/bin/bash
# T8.29A — Run 2 backtests (SMA seed vs first seed) + compare_trades vs MT4
#
# Executa: backtest mt4_like sma → backtest mt4_like first → compare_trades ×2
# Decideix guanyador per entry_match_rate. Si no millora → report "next required".
#
# Ús: ./scripts/run_t829a_mt4like_compare.sh
# Prerequisit: historical_datalayer amb dades M1 (base_url)

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
MT4_CSV="$OUT/simpleexample_out_MT4.csv"
BASE_URL="${BASE_URL:-http://localhost:8081}"
STRATEGY=eurusd_ema200_rsi35_atr_d1
FROM=2006-12-01
TO=2026-01-01
WARMUP=250

if [ ! -f "$MT4_CSV" ]; then
  echo "ERROR: MT4 trades CSV no trobat: $MT4_CSV"
  exit 1
fi

echo "[T8.29A] 1/2 Backtest mt4_like ema_seed=sma..."
mkdir -p "$OUT/mt4like_sma"
python3 lab/runner/backtest/run_backtest.py \
  --strategy "$STRATEGY" \
  --symbol EURUSD \
  --tf 1d \
  --from "$FROM" \
  --to "$TO" \
  --base-url "$BASE_URL" \
  --warmup-bars "$WARMUP" \
  --artifacts-dir "$OUT/mt4like_sma" \
  --indicator-mode mt4_like \
  --ema-seed sma

echo ""
echo "[T8.29A] 2/2 Backtest mt4_like ema_seed=first..."
mkdir -p "$OUT/mt4like_first"
python3 lab/runner/backtest/run_backtest.py \
  --strategy "$STRATEGY" \
  --symbol EURUSD \
  --tf 1d \
  --from "$FROM" \
  --to "$TO" \
  --base-url "$BASE_URL" \
  --warmup-bars "$WARMUP" \
  --artifacts-dir "$OUT/mt4like_first" \
  --indicator-mode mt4_like \
  --ema-seed first

# Paths als trades (artifacts-dir canvia l'estructura?)
LAB_SMA="$OUT/mt4like_sma/$STRATEGY/EURUSD/1d/${FROM}_${TO}/trades.csv"
LAB_FIRST="$OUT/mt4like_first/$STRATEGY/EURUSD/1d/${FROM}_${TO}/trades.csv"

if [ ! -f "$LAB_SMA" ]; then
  LAB_SMA=$(find "$OUT/mt4like_sma" -name "trades.csv" | head -1)
fi
if [ ! -f "$LAB_FIRST" ]; then
  LAB_FIRST=$(find "$OUT/mt4like_first" -name "trades.csv" | head -1)
fi

echo ""
echo "[T8.29A] 3/4 compare_trades SMA..."
python3 lab/runner/out_compare/compare_trades.py \
  --inputs-dir "$OUT" \
  --lab-trades "$LAB_SMA" \
  --ref MT4 \
  --tol 1D \
  --out-dir "$OUT/mt4like_sma"
cp "$OUT/mt4like_sma/report.json" "$OUT/report_after_mt4like_sma.json"

echo ""
echo "[T8.29A] 4/4 compare_trades first..."
python3 lab/runner/out_compare/compare_trades.py \
  --inputs-dir "$OUT" \
  --lab-trades "$LAB_FIRST" \
  --ref MT4 \
  --tol 1D \
  --out-dir "$OUT/mt4like_first"
cp "$OUT/mt4like_first/report.json" "$OUT/report_after_mt4like_first.json"

echo ""
echo "[T8.29A] Decisió..."
python3 -c "
import json
sma = json.load(open('$OUT/report_after_mt4like_sma.json'))
first = json.load(open('$OUT/report_after_mt4like_first.json'))
lab_sma = sma.get('engines', {}).get('LAB', {})
lab_first = first.get('engines', {}).get('LAB', {})
rate_sma = lab_sma.get('entry_match_rate')
rate_first = lab_first.get('entry_match_rate')
target = 70
print(f'  SMA seed:   entry_match_rate={rate_sma}%  n_trades={lab_sma.get(\"n_trades\")}')
print(f'  first seed: entry_match_rate={rate_first}%  n_trades={lab_first.get(\"n_trades\")}')
if (rate_sma or 0) >= target or (rate_first or 0) >= target:
    winner = 'sma' if (rate_sma or 0) >= (rate_first or 0) else 'first'
    print(f'  → GUANYADOR: {winner} (target {target}% assolit)')
else:
    print(f'  → STOP: cap millora (target {target}%). Next: oracle indicadors CSV o revisar shift/warmup.')
"

echo ""
echo "Artifacts: $OUT/report_after_mt4like_sma.json, report_after_mt4like_first.json"

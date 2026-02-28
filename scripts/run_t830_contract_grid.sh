#!/bin/bash
# T8.30 — Contract grid: entry_fill × signal_contract vs MT4
#
# Executa backtest per cada combinació, compare_trades, tria millor per entry_match_rate
# i n_trades proper a 22. Sense passes manuals.
#
# Ús: ./scripts/run_t830_contract_grid.sh
# Prerequisit: historical_datalayer amb dades M1, MT4 CSV a out_compare

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
MT4_CSV="$OUT/simpleexample_out_MT4.csv"
BASE_URL="${BASE_URL:-http://localhost:8081}"
STRATEGY=eurusd_ema200_rsi35_atr_d1
FROM=2006-12-01
TO=2026-01-01
WARMUP=250
MT4_N_TRADES=22

if [ ! -f "$MT4_CSV" ]; then
  echo "ERROR: MT4 trades CSV no trobat: $MT4_CSV"
  exit 1
fi

ENTRY_FILLS="open_i open_i1"
SIGNAL_CONTRACTS="mt4_baropen v2"
: > "$OUT/contract_grid_raw.txt"

for ef in $ENTRY_FILLS; do
  for sc in $SIGNAL_CONTRACTS; do
    LABEL="${ef}_${sc}"
    DIR="$OUT/contract_$LABEL"
    mkdir -p "$DIR"
    echo ""
    echo "[T8.30] Backtest entry_fill=$ef signal_contract=$sc → $DIR"
    python3 lab/runner/backtest/run_backtest.py \
      --strategy "$STRATEGY" \
      --symbol EURUSD \
      --tf 1d \
      --from "$FROM" \
      --to "$TO" \
      --base-url "$BASE_URL" \
      --warmup-bars "$WARMUP" \
      --artifacts-dir "$DIR" \
      --indicator-mode mt4_like \
      --ema-seed sma \
      --entry-fill "$ef" \
      --signal-contract "$sc"

    LAB_TRADES=$(find "$DIR" -name "trades.csv" | head -1)
    if [ -z "$LAB_TRADES" ]; then
      echo "ERROR: trades.csv no trobat a $DIR"
      exit 1
    fi

    echo ""
    echo "[T8.30] compare_trades $LABEL vs MT4..."
    python3 lab/runner/out_compare/compare_trades.py \
      --inputs-dir "$OUT" \
      --lab-trades "$LAB_TRADES" \
      --ref MT4 \
      --tol 1D \
      --out-dir "$DIR"

    # Extreu mètriques del report
    RATE=$(python3 -c "
import json
r = json.load(open('$DIR/report.json'))
lab = r.get('engines', {}).get('LAB', {})
print(lab.get('entry_match_rate', 0) or 0)
")
    N=$(python3 -c "
import json
r = json.load(open('$DIR/report.json'))
lab = r.get('engines', {}).get('LAB', {})
print(lab.get('n_trades', 0) or 0)
")
    echo "  $LABEL: entry_match_rate=$RATE%  n_trades=$N"
    echo "$ef|$sc|$RATE|$N" >> "$OUT/contract_grid_raw.txt"
  done
done

# Genera contract_grid_report.json i best_contract
echo ""
echo "[T8.30] Generant contract_grid_report.json i best_contract.txt..."
python3 lab/runner/out_compare/contract_grid_report.py \
  --raw "$OUT/contract_grid_raw.txt" \
  --out "$OUT" \
  --mt4-n "$MT4_N_TRADES"
rm -f "$OUT/contract_grid_raw.txt"

BEST=$(cat "$OUT/best_contract.txt" 2>/dev/null || echo "none")
echo ""
echo "[T8.30] RESULTAT"
echo "  best_contract: $BEST"
echo "  contract_grid_report.json → $OUT/"
echo "  best_contract.txt → $OUT/"
python3 -c "
import json
r = json.load(open('$OUT/contract_grid_report.json'))
b = r.get('best')
rate = b.get('entry_match_rate', 0) if b else 0
target = 60
if b and rate >= target:
    print(f'  → OK: entry_match_rate >= {target}% assolit')
elif b:
    print(f'  → STOP: cap combinació >= {target}%. Oracle indicadors CSV necessari per tancar.')
else:
    print('  → STOP: cap combinació. Oracle necessari.')
"

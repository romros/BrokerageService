#!/bin/bash
# T8.39 — Paritat M1 candles + reproducció exacta 17 trades (MT4/SQ)
#
# Harness de paritat "de baix a dalt":
#   - Export candles LAB (Dukascopy BI5 o API)
#   - Candle parity (si mt4_oracle/candles_*.csv existeix)
#   - RSI Wilder + simulació trades (RSI[1]<35, exit 60 bars)
#   - Trade parity vs MT4 (17 trades)
#
# Prerequisits:
#   - MT4 trades: lab/runner/out_compare/mt4_oracle/trades_*.csv
#     o fallback lab/ostium/out_ind/rsi/output.rsi1m.csv
#   - MT4 candles (opcional): mt4_oracle/candles_*.csv
#
# Ús: ./scripts/run_t839_mt4_m1_parity.sh [--no-api] [--docker]
#   --no-api: no provar API, només BI5 (útil sense historical_datalayer)
#   --docker: executa dins contenidor (pip install + xarxa BI5)

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
ARTIFACTS="$OUT/artifacts/T8.39/EURUSD/1m/2026-02-01_2026-02-02"
MT4_TRADES="$OUT/mt4_oracle/trades_EURUSD_M1_UTCMinus05_20260201_20260202.csv"
FALLBACK_TRADES="lab/ostium/out_ind/rsi/output.rsi1m.csv"

USE_DOCKER="${USE_DOCKER:-0}"
NO_API=0
for arg in "$@"; do
  case "$arg" in
    --no-api) NO_API=1 ;;
    --docker) USE_DOCKER=1 ;;
  esac
done

mkdir -p "$ARTIFACTS"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

# Còpia MT4 trades a mt4_oracle si fallback existeix i oracle no
if [ ! -f "$MT4_TRADES" ] && [ -f "$FALLBACK_TRADES" ]; then
  mkdir -p "$OUT/mt4_oracle"
  cp "$FALLBACK_TRADES" "$MT4_TRADES"
  echo "[T8.39] Copiat $FALLBACK_TRADES → $MT4_TRADES"
fi

EXTRA=""
[ "$NO_API" = "1" ] && EXTRA="--no-api"

echo "[T8.39] Executant paritat M1 RSI35 exit60..."
if [ "$USE_DOCKER" = "1" ]; then
  docker run --rm -v "$PROJECT_ROOT:/app" -w /app python:3.11-slim \
    bash -c "pip install -q pandas numpy pyarrow 2>/dev/null; export PYTHONPATH=/app:\$PYTHONPATH; python3 $OUT/mt4_m1_rsi35_exit60_parity.py --base-url ${BASE_URL:-http://localhost:8081} $EXTRA" \
    2>&1 | tee "$ARTIFACTS/run.log"
else
  python3 "$OUT/mt4_m1_rsi35_exit60_parity.py" \
    --base-url "${BASE_URL:-http://localhost:8081}" \
    $EXTRA \
    2>&1 | tee "$ARTIFACTS/run.log"
fi

EXIT=${PIPESTATUS[0]}
echo ""
echo "Report: $ARTIFACTS/t839_report.json"
[ $EXIT -eq 0 ] && echo "PASS" || echo "FAIL (exit $EXIT)"
exit $EXIT

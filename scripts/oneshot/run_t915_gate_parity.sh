#!/usr/bin/env bash
# T9.15 — Gate paritat SQ sobre Parquet v2 ticks
#
# Executa backtest BS (source=dukascopy = ticks) + compara amb oracle SQ.
# Estratègia: RSI(14)[1]<35, exit 60 bars, M1 EURUSD.
#
# Ús: ./scripts/oneshot/run_t915_gate_parity.sh [--docker] [--base-url URL]
#
# Prerequisits:
#   - DUKASCOPY_PARQUET_ACTIVE=ticks al historical_datalayer
#   - expected_trades.csv (oracle SQ) a lab/gold/cases/rsi35_exit60_m1_oracle/

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
# lab/out/artifacts pot ser root-owned; lab/out és accessible
OUT="${BS_T915_OUT:-$PROJECT_ROOT/lab/out/BS.T9.15}"
SQ_ORACLE="$PROJECT_ROOT/lab/gold/cases/rsi35_exit60_m1_oracle/expected_trades.csv"

cd "$PROJECT_ROOT"
mkdir -p "$OUT"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

BASE_URL="${BASE_URL:-http://localhost:8081}"
USE_DOCKER=0
for arg in "$@"; do
  case "$arg" in
    --docker) USE_DOCKER=1 ;;
    --base-url=*) BASE_URL="${arg#*=}" ;;
  esac
done

if [ ! -f "$SQ_ORACLE" ]; then
  echo "[T9.15] Oracle missing: $SQ_ORACLE"
  exit 1
fi

echo "[T9.15] Gate paritat SQ — RSI35 exit60 M1 EURUSD 2026-02-01→03"
echo "  base_url: $BASE_URL"
echo "  oracle: $SQ_ORACLE"
echo ""

if [ "$USE_DOCKER" = "1" ]; then
  SQ_REL="lab/gold/cases/rsi35_exit60_m1_oracle/expected_trades.csv"
  OUT_REL="lab/out/BS.T9.15"
  docker run --rm --network host -v "$PROJECT_ROOT:/app" -w /app python:3.11-slim \
    bash -c "pip install -q pandas 2>/dev/null; python3 scripts/oneshot/run_t915_gate_parity.py --base-url $BASE_URL --sq-trades $SQ_REL --out-dir $OUT_REL 2>&1" | tee "$OUT/run.log"
else
  python3 scripts/oneshot/run_t915_gate_parity.py \
    --base-url "$BASE_URL" \
    --sq-trades "$SQ_ORACLE" \
    --out-dir "$OUT" 2>&1 | tee "$OUT/run.log"
fi

EXIT=${PIPESTATUS[0]:-$?}
echo ""
if [ $EXIT -eq 0 ]; then
  echo "PASS — match_rate >= 95%"
else
  echo "FAIL — revisar $OUT/trade_diff_report.json"
fi
exit $EXIT

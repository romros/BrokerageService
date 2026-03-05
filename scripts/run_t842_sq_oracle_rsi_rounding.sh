#!/bin/bash
# T8.42 — SQ Oracle Candles + RSI exacta SQ (getRounded + warmup) fins 17/17
#
# 1. Export oracle candles via sqcli (si falten)
# 2. Executa harness amb --lab-source oracle --round-sweep
# 3. Escriu t842_report.json, rounding_sweep.csv, lab_trades_round_*.csv
#
# Prerequisits: sqcli-docker en marxa
#
# Ús: ./scripts/run_t842_sq_oracle_rsi_rounding.sh [--skip-export]

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
OUT=lab/runner/out_compare
ARTIFACTS="$OUT/artifacts/T8.42/EURUSD/1m/2026-02-01_2026-02-02"
ORACLE_CANDLES="$OUT/mt4_oracle/candles_EURUSD_M1_UTCMinus05_20260120_20260203.csv"

SKIP_EXPORT=0
for arg in "$@"; do
  case "$arg" in
    --skip-export) SKIP_EXPORT=1 ;;
  esac
done

cd "$PROJECT_ROOT"
mkdir -p "$ARTIFACTS"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

if [ "$SKIP_EXPORT" = "0" ] && [ ! -f "$ORACLE_CANDLES" ]; then
  echo "[T8.42] Exportant oracle candles via sqcli..."
  "$SCRIPT_DIR/run_t842_sqcli_export_candles.sh" || {
    echo "[T8.42] AVÍS: Export fallit. Continuant si ja existeix CSV..."
  }
fi

if [ ! -f "$ORACLE_CANDLES" ]; then
  echo "[T8.42] ERROR: No hi ha candles oracle. Executa run_t842_sqcli_export_candles.sh"
  exit 1
fi

echo "[T8.42] Executant harness oracle + rounding sweep..."
python3 "$OUT/mt4_m1_rsi35_exit60_parity.py" --t842 \
  --lab-source oracle \
  --round-sweep \
  --artifacts-dir "$ARTIFACTS" \
  2>&1 | tee "$ARTIFACTS/run.log"

EXIT=${PIPESTATUS[0]}
echo ""
echo "Report: $ARTIFACTS/t842_report.json"
echo "Rounding sweep: $ARTIFACTS/rounding_sweep.csv"
[ $EXIT -eq 0 ] && echo "PASS (17/17)" || echo "FAIL (exit $EXIT)"
exit $EXIT

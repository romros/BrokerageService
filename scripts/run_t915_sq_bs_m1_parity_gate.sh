#!/usr/bin/env bash
# T9.15 — Gate SQ↔BS M1 parity (candles 1:1 a nivell d'API)
#
# Compara candles M1 SQ (CSV) vs BS (GET /data/ohlcv). No mira parquet — només el servei.
# PASS: missing_in_bs=0, mismatches=0, extra_in_bs=0.
#
# Ús:
#   Smoke 1 mes:
#     ./scripts/run_t915_sq_bs_m1_parity_gate.sh --symbol EURUSD --from 2025-03-01 --to 2025-04-01
#   Full range (amb resume):
#     ./scripts/run_t915_sq_bs_m1_parity_gate.sh --symbol EURUSD --from 2003-01-01 --to 2026-03-04 --resume
#
# Prerequisits:
#   - DUKASCOPY_PARQUET_ACTIVE=ticks al historical_datalayer
#   - SQ export CSV (ex: /mnt/volume-SQ/user/t842_oracle_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv)

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

# Defaults
SQ_INPUT="${SQ_INPUT:-/mnt/volume-SQ/user/t842_oracle_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv}"
BASE_URL="${BASE_URL:-http://localhost:8081}"
SYMBOL="${SYMBOL:-EURUSD}"
FROM="${FROM:-2025-03-01}"
TO="${TO:-2025-04-01}"
POLICY="${POLICY:-exact}"
EXPORT_METHOD="${EXPORT_METHOD:-unknown}"
RESUME=""
MONTHS=""

prev=""
for arg in "$@"; do
  if [ -n "$prev" ]; then
    case "$prev" in
      --from) FROM="$arg" ;;
      --to) TO="$arg" ;;
      --symbol) SYMBOL="$arg" ;;
      --months) MONTHS="--months $arg" ;;
      --policy) POLICY="$arg" ;;
      --export-method) EXPORT_METHOD="$arg" ;;
      --sq-input) SQ_INPUT="$arg" ;;
      --base-url) BASE_URL="$arg" ;;
    esac
    prev=""
  else
    case "$arg" in
      --resume) RESUME="--resume" ;;
      --months=*) MONTHS="--months ${arg#*=}" ;;
      --symbol=*) SYMBOL="${arg#*=}" ;;
      --from=*) FROM="${arg#*=}" ;;
      --to=*) TO="${arg#*=}" ;;
      --policy=*) POLICY="${arg#*=}" ;;
      --export-method=*) EXPORT_METHOD="${arg#*=}" ;;
      --sq-input=*) SQ_INPUT="${arg#*=}" ;;
      --base-url=*) BASE_URL="${arg#*=}" ;;
      --from|--to|--symbol|--months|--policy|--export-method|--sq-input|--base-url) prev="$arg" ;;
    esac
  fi
done

# Construir outdir canònic (lab/out accessible; artifacts pot ser root-owned)
FROM_CLEAN=$(echo "$FROM" | tr -d '-')
TO_CLEAN=$(echo "$TO" | tr -d '-')
OUTDIR="${BS_T915_OUTDIR:-$PROJECT_ROOT/lab/out/BS.T9.15_sq_bs_m1/$SYMBOL/1m/${FROM_CLEAN}_${TO_CLEAN}}"
mkdir -p "$OUTDIR"

echo "[T9.15] Gate SQ↔BS M1 parity — candles 1:1"
echo "POLICY=$POLICY"
echo "  symbol: $SYMBOL"
echo "  sq_input: $SQ_INPUT"
echo "  base_url: $BASE_URL"
echo "  from: $FROM → to: $TO"
echo "  outdir: $OUTDIR"
echo ""

{ echo "POLICY=$POLICY"; python3 lab/datalayer/sq_bs_m1_parity_gate.py \
  --symbol "$SYMBOL" \
  --sq-input "$SQ_INPUT" \
  --base-url "$BASE_URL" \
  --from "$FROM" \
  --to "$TO" \
  --source dukascopy \
  --policy "$POLICY" \
  --outdir "$OUTDIR" \
  --export-method "${EXPORT_METHOD:-unknown}" \
  $RESUME $MONTHS 2>&1; } | tee "$OUTDIR/run.log"

EXIT=${PIPESTATUS[0]:-$?}
echo ""
if [ $EXIT -eq 0 ]; then
  echo "PASS — policy=$POLICY"
else
  echo "FAIL — revisar $OUTDIR/gate_summary.json"
fi
exit $EXIT

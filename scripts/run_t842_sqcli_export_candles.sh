#!/bin/bash
# T8.42 — Export candles oracle SQ via sqcli
#
# Exporta candles M1 des de SQ (.dat) a CSV amb warmup.
# warmup_from=2026-01-20, eval_from=2026-02-01, eval_to=2026-02-03 (exclusiu)
#
# Output: lab/runner/out_compare/mt4_oracle/candles_EURUSD_M1_UTCMinus05_20260120_20260203.csv
#
# Prerequisits: sqcli-docker en marxa, /mnt/volume-SQ/user muntat
#
# Ús: ./scripts/run_t842_sqcli_export_candles.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
OUT=lab/runner/out_compare/mt4_oracle
SQ_USER=/mnt/volume-SQ/user
EXPORT_SUBDIR=t842_oracle_export

WARMUP_FROM="2026.01.20"
EVAL_FROM="2026.02.01"
EVAL_TO="2026.02.03"
SYMBOL="EURUSD_M1_dukas_M1_UTCMinus05"
OUTPUT_FNAME="candles_EURUSD_M1_UTCMinus05_20260120_20260203.csv"

mkdir -p "$PROJECT_ROOT/$OUT"
mkdir -p "$SQ_USER/$EXPORT_SUBDIR"

# sqcli escriu a /home/squser/SQ/user (mapat a /mnt/volume-SQ/user)
OUTPUTDIR_CONTAINER="/home/squser/SQ/user/$EXPORT_SUBDIR"

echo "[T8.42] Exportant candles SQ via sqcli (warmup $WARMUP_FROM → eval $EVAL_TO)..."
docker exec sqcli-docker /home/squser/SQ/sqcli -data action=export \
  symbols="$SYMBOL" \
  timeframe=M1 \
  datefrom="$WARMUP_FROM" \
  dateto="$EVAL_TO" \
  outputdir="$OUTPUTDIR_CONTAINER" \
  2>&1 | grep -v "^[0-9][0-9]:[0-9][0-9]:[0-9][0-9]\.[0-9]* \[main\] DEBUG" || true

# sqcli pot generar un nom diferent; buscar el CSV
SRC=$(ls "$SQ_USER/$EXPORT_SUBDIR"/*.csv 2>/dev/null | head -1)
if [ -z "$SRC" ]; then
  echo "[T8.42] ERROR: No s'ha trobat cap CSV a $SQ_USER/$EXPORT_SUBDIR"
  echo "  Verifica que sqcli-docker estigui en marxa i que el símbol $SYMBOL tingui dades."
  exit 1
fi

cp "$SRC" "$PROJECT_ROOT/$OUT/$OUTPUT_FNAME"
echo "[T8.42] Copiat: $OUT/$OUTPUT_FNAME ($(wc -l < "$PROJECT_ROOT/$OUT/$OUTPUT_FNAME") lines)"

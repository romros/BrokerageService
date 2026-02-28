#!/bin/bash
# T8.25 — Evidence pack post-BI5: delta -10.1% + Gate C recheck + flat ratio
#
# Executa tots els passos de l'evidence pack. Requereix:
#   - Parquet EURUSD a DATAFILES_ROOT/historical_parquet (per missing_months amb nums reals)
#   - Ostium candle_store amb dades (per compat 1440m)
#
# Ús:
#   ./scripts/run_t825_evidence_pack.sh
#   DATAFILES_ROOT=/path/to/datafiles ./scripts/run_t825_evidence_pack.sh
#
# Artifacts:
#   lab/out/artifacts/parity/missing_months_EURUSD_m1.json
#   lab/out/artifacts/parity/bi5_spot_checks_EURUSD.json
#   datafiles/realtime_datalayer/artifacts/compat/latest_*.json
#   lab/out/artifacts/aggregation/EURUSD_*_aggregation_report.json

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

DATAFILES_ROOT="${DATAFILES_ROOT:-./datafiles}"
OUT_PARITY="${OUT_PARITY:-./lab/out/artifacts/parity}"
OUT_AGG="${OUT_AGG:-./lab/out/artifacts/aggregation}"
OSTIUM_ROOT="${OSTIUM_ROOT:-$DATAFILES_ROOT/realtime_datalayer}"

mkdir -p "$OUT_PARITY" "$OUT_AGG" "$OSTIUM_ROOT/artifacts/compat"

echo "[T8.25] 1/4 Missing months report + BI5 spot-checks..."
python3 -m application.tools.missing_months_report \
  --symbol EURUSD \
  --from 2003-05-01 --to 2026-02-28 \
  --sq-rows 8499508 \
  --datafiles-root "$DATAFILES_ROOT" \
  --spot-check-months 2007-07 2008-03 2010-06 \
  --out "$OUT_PARITY" || echo "[WARN] missing_months_report failed (permisos? xarxa?)"

echo ""
echo "[T8.25] 2/4 Gate C compat recheck (1440m rolling)..."
OSTIUM_COMPAT_WINDOW_MINUTES=1440 ./scripts/run_compat.sh ostium EURUSD
OSTIUM_COMPAT_WINDOW_MINUTES=1440 ./scripts/run_compat.sh ostium XAUUSD

echo ""
echo "[T8.25] 3/4 Aggregation reports (2004 i 2020)..."
python3 -m application.tools.aggregation_report \
  --symbol EURUSD --from 2004-01-01 --to 2005-01-01 \
  --datafiles-root "$DATAFILES_ROOT" --out "$OUT_AGG" || true
python3 -m application.tools.aggregation_report \
  --symbol EURUSD --from 2020-01-01 --to 2021-01-01 \
  --datafiles-root "$DATAFILES_ROOT" --out "$OUT_AGG" || true

echo ""
echo "[T8.25] 4/4 Done. Artifacts:"
echo "  parity: $OUT_PARITY/*.json"
echo "  compat: $OSTIUM_ROOT/artifacts/compat/latest_*.json"
echo "  aggregation: $OUT_AGG/*.json"

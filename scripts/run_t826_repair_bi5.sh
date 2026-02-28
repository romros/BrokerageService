#!/bin/bash
# T8.26 — Repair 55 mesos buits Parquet via BI5
#
# Flux:
#   1. Dry-run (detecta mesos)
#   2. Fix (rebaixa BI5 + reescriu Parquet + rebuild coverage)
#   3. Parity vs SQ report (parity_EURUSD_M1_vs_SQ.json)
#
# Ús:
#   ./scripts/run_t826_repair_bi5.sh
#   DATAFILES_ROOT=/path ./scripts/run_t826_repair_bi5.sh
#
# Artifacts:
#   lab/out/artifacts/parity/eurusd_m1_bad_months.json
#   lab/out/artifacts/parity/repair_missing_months_report.json
#   lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

DATAFILES_ROOT="${DATAFILES_ROOT:-./datafiles}"
OUT_PARITY="${OUT_PARITY:-./lab/out/artifacts/parity}"
mkdir -p "$OUT_PARITY"

echo "[T8.26] 1/2 Dry-run..."
python3 -m application.tools.repair_missing_months_bi5 \
  --symbol EURUSD \
  --datafiles-root "$DATAFILES_ROOT" \
  --out "$OUT_PARITY" \
  --dry-run

echo ""
if [[ "${T826_SKIP_PROMPT:-0}" != "1" ]]; then
  read -p "Continuar amb --fix? (s/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[sS]$ ]]; then
    echo "Aturat. Executa manualment amb --fix quan vulguis."
    exit 0
  fi
fi

echo "[T8.26] 2/2 Fix (rebaixa BI5 + reescriu)..."
python3 -m application.tools.repair_missing_months_bi5 \
  --symbol EURUSD \
  --datafiles-root "$DATAFILES_ROOT" \
  --out "$OUT_PARITY" \
  --fix

echo ""
echo "[T8.26] 3/3 Parity vs SQ report..."
python3 -m application.tools.generate_parity_vs_sq_report \
  --symbol EURUSD \
  --datafiles-root "$DATAFILES_ROOT" \
  --out "$PROJECT_ROOT/lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json"

echo ""
echo "[T8.26] Done. Artifacts:"
echo "  - $OUT_PARITY/eurusd_m1_bad_months.json"
echo "  - $OUT_PARITY/repair_missing_months_report.json"
echo "  - lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json"
echo ""
echo "Següent (manual): export indicadors LAB + MT4, run compare_indicators (T8.21)."

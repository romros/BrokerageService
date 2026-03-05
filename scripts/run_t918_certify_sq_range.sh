#!/usr/bin/env bash
# T9.18 — Certificar rang real SQ vs BS (source=dukascopy) i congelar contracte pel runner.
#
# 1) Export SQCLI del rang (SQ_FROM → SQ_TO exclusive)
# 2) Gate --policy exact en el mateix rang
# 3) Si PASS: rang certificat (documentar a ESTAT; opcional env DUKASCOPY_CERTIFIED_FROM/TO)
#
# Ús:
#   ./scripts/run_t918_certify_sq_range.sh --from 2023-06-15 --to 2026-01-28
#   (Omet --from/--to per usar valors per defecte de constants.)
#
# Prerequisits: sqcli disponible (docker exec o SQCLI_COMPOSE), historical_datalayer amb source=dukascopy.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

# Rang real SQ (ajustar segons GUI; per defecte el contracte T9.18)
SQ_FROM="${SQ_FROM:-2023-06-15}"
SQ_TO="${SQ_TO:-2026-01-28}"
SQ_USER="${SQ_USER:-/mnt/volume-SQ/user}"
EXPORT_DIR="$SQ_USER/t915_export"

prev=""
for arg in "$@"; do
  if [ -n "$prev" ]; then
    case "$prev" in
      --from) SQ_FROM="$arg" ;;
      --to)   SQ_TO="$arg" ;;
    esac
    prev=""
  else
    case "$arg" in
      --from|--to) prev="$arg" ;;
    esac
  fi
done

echo "[T9.18] Certificar rang SQ→BS (source=dukascopy): [$SQ_FROM, $SQ_TO)"
echo "  1) Export SQCLI $SQ_FROM → $SQ_TO"
echo "  2) Gate exact mateix rang"
echo ""

# 1) Export
"$SCRIPT_DIR/run_t9152_export_sq_complete.sh" --from "$SQ_FROM" --to "$SQ_TO" || exit $?

# 2) Gate exact
"$SCRIPT_DIR/run_t915_sq_bs_m1_parity_gate.sh" \
  --symbol EURUSD \
  --from "$SQ_FROM" --to "$SQ_TO" \
  --policy exact \
  --sq-input "$EXPORT_DIR" \
  --export-method sqcli \
  --resume

EXIT=$?
if [ $EXIT -eq 0 ]; then
  echo ""
  echo "[T9.18] PASS — Afegeix a docs/ESTAT.md:"
  echo "  **T9.18 certified:** EURUSD dukascopy API parity vs SQCLI [$SQ_FROM, $SQ_TO) exact PASS. Runner supported range = same. Env: DUKASCOPY_CERTIFIED_FROM=$SQ_FROM DUKASCOPY_CERTIFIED_TO=$SQ_TO"
  echo ""
  echo "  (Opcional) Runner/config: export DUKASCOPY_CERTIFIED_FROM=$SQ_FROM DUKASCOPY_CERTIFIED_TO=$SQ_TO"
fi
exit $EXIT

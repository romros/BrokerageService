#!/bin/bash
# BS.T9.03 — Gate 5 anys M1 BID: comparar BS vs SQCLI (read-only, chunk mensual)
#
# Read-only: GET /data/ohlcv + lectura CSV SQ. No reprocess, no sync.
# Default: --dry-run (imprimeix mesos i paths). --apply: executa i desa run.log.
#
# Ús:
#   ./scripts/run_t903_bs_sq_m1_gate.sh                  # dry-run
#   ./scripts/run_t903_bs_sq_m1_gate.sh --apply           # 5 anys (rang descobert des de cobertura BS)
#   ./scripts/run_t903_bs_sq_m1_gate.sh --apply --months 1 # 1 mes (smoke)
#   ./scripts/run_t903_bs_sq_m1_gate.sh --apply --no-auto-range  # rang FROM_DATE/TO_DATE manual
#
# Primer pas (per defecte): el gate obté GET /data/coverage/EURUSD i tria 60 mesos consecutius "done".
# Prerequisits: BS en marxa, CSV export SQ accessible (veure lab/datalayer/README.md).

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

ARTIFACTS_DIR="${ARTIFACTS_DIR:-$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.03}"
SQ_CSV="${SQ_CSV:-}"
BASE_URL="${BASE_URL:-http://localhost:8081}"
FROM_DATE="${FROM_DATE:-2020-01-01}"
TO_DATE="${TO_DATE:-2025-01-01}"

# Default path si SQ_CSV no està definit (export 5y típic)
if [ -z "$SQ_CSV" ]; then
  for candidate in \
    "/mnt/volume-SQ/user/t903_5y_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv" \
    "$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.03/sq_export_5y.csv"
  do
    if [ -f "$candidate" ]; then
      SQ_CSV="$candidate"
      break
    fi
  done
fi

DRY_RUN=1
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --apply) DRY_RUN=0 ;;
    *)       EXTRA_ARGS+=("$arg") ;;
  esac
done
# Passar --months N etc. a Python; no passar --apply
EXTRA_ARGS=("${EXTRA_ARGS[@]}")

log() { echo "[T9.03] $*"; }

if [ $DRY_RUN -eq 1 ]; then
  log "DRY-RUN: mesos i paths (sense crides API)"
  if [ -z "$SQ_CSV" ] || [ ! -f "$SQ_CSV" ]; then
    log "  SQ_CSV: no definit o fitxer inexistent. Export 5y: lab/datalayer/README.md"
    log "  Exemple: SQ_CSV=/path/to/EURUSD_M1_dukas_M1_UTCMinus05-M1-No\\ Session.csv $0 --apply"
    log "  BASE_URL: $BASE_URL FROM: $FROM_DATE TO: $TO_DATE"
    exit 0
  fi
  python3 -m lab.datalayer.bs_sq_m1_parity_gate \
    --sq-csv "$SQ_CSV" \
    --base-url "$BASE_URL" \
    --from "$FROM_DATE" --to "$TO_DATE" \
    --no-auto-range \
    --dry-run "${EXTRA_ARGS[@]}"
  exit 0
fi

if [ -z "$SQ_CSV" ] || [ ! -f "$SQ_CSV" ]; then
  log "ERROR: SQ_CSV no definit o fitxer no existeix. Export 5y: lab/datalayer/README.md"
  exit 1
fi

mkdir -p "$ARTIFACTS_DIR"
log "Rang: descobert des de BS (o FROM/TO si --no-auto-range)"
log "  sq_csv=$SQ_CSV base_url=$BASE_URL"

python3 -m lab.datalayer.bs_sq_m1_parity_gate \
  --sq-csv "$SQ_CSV" \
  --base-url "$BASE_URL" \
  --from "$FROM_DATE" --to "$TO_DATE" \
  --out-dir "$ARTIFACTS_DIR" \
  "${EXTRA_ARGS[@]}" 2>&1 | tee "$ARTIFACTS_DIR/run.log"

exit "${PIPESTATUS[0]}"

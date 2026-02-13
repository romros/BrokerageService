#!/bin/bash
# Soak smoke: 10–15 minuts, venue=lighter, mode=PAPER.
# Log guardat a datafiles/smoke_runs/soak_<timestamp>.log
#
# Recorda: docker compose build brokerage si has canviat codi.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

DURATION=${1:-600}   # default 10 min (600s); passar 900 per 15 min
TS=$(date +%Y%m%d_%H%M%S)
LOG_PATH="/datafiles/smoke_runs/soak_${TS}.log"
LOG_HOST="${PROJECT_ROOT}/datafiles/smoke_runs/soak_${TS}.log"

echo "Soak smoke: ${DURATION}s (venue=lighter, mode=PAPER)"
echo "Log (host): ${LOG_HOST}"
echo ""
echo "--- Instruccions ---"
echo "  Refresca: reconcile cada RECONCILE_INTERVAL_S (default 60s). Cada ~60s veuràs un tick al log."
echo "  Seguir log en temps real: tail -f ${LOG_HOST}"
echo "  OK si al final: SMOKE_RESULT status=OK errors=0 i SMOKE_SUMMARY failed=0"
echo ""

mkdir -p "${PROJECT_ROOT}/datafiles/smoke_runs"

docker compose run --rm brokerage python3 -m application.smoke \
  --venue lighter \
  --mode PAPER \
  --seconds "${DURATION}" \
  --log-path "${LOG_PATH}"

echo ""
echo "Soak completat. Log: ${LOG_HOST}"
echo "  Comprovar OK: grep -E 'SMOKE_RESULT|SMOKE_SUMMARY' ${LOG_HOST}"

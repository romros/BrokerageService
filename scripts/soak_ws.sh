#!/bin/bash
# WS Soak: 15 min (default) o N segons. Valida pipeline ticks→candles→store→WS.
# Log guardat a datafiles/ws_soak/<ts>_ws_soak_<N>m.log
#
# Ús:
#   ./scripts/soak_ws.sh           # 15 min (900s)
#   ./scripts/soak_ws.sh 900       # 15 min
#   ./scripts/soak_ws.sh 120       # 2 min (test curt)
#
# Requereix: broker corrent (docker compose up) amb VENUE=lighter MODE=paper
# Opcional: USE_FAKE_PRICE_FEED=1 per soak sense xarxa.
#
# Recorda: docker compose build brokerage si has canviat codi.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

DURATION_S=${1:-900}   # default 15 min (900s)
MINUTES=$((DURATION_S / 60))
TS=$(date +%Y%m%d_%H%M%S)
LOG_PATH="/datafiles/ws_soak/${TS}_ws_soak_${MINUTES}m.log"
LOG_HOST="${PROJECT_ROOT}/datafiles/ws_soak/${TS}_ws_soak_${MINUTES}m.log"

echo "WS Soak: ${DURATION_S}s (~${MINUTES} min)"
echo "Log (host): ${LOG_HOST}"
echo ""
echo "--- Instruccions ---"
echo "  Broker ha d'estar en marxa: docker compose up (o docker compose run brokerage ...)"
echo "  WS URL: ws://localhost:8000/api/v1/ws (o ws://brokerage:8000 des de dins xarxa)"
echo "  OK si: WS_SOAK_RESULT status=OK, candles>=1, reconnects<=allow, max_gap_s<=120"
echo "  Seguir log: tail -f ${LOG_HOST}"
echo ""

mkdir -p "${PROJECT_ROOT}/datafiles/ws_soak"

# Des de dins Docker (docker compose run): connectar al broker = brokerage:8000
# Des de host (python directe): localhost:8000
WS_URL="${WS_SOAK_URL:-ws://brokerage:8000/api/v1/ws}"

docker compose run --rm brokerage python3 -m application.tools.ws_soak \
  --minutes "${MINUTES}" \
  --ws-url "${WS_URL}" \
  --topic "candle:ETH:1m" \
  --allow-reconnects 3 \
  --max-gap-seconds 120 \
  --log-path "${LOG_PATH}"

EXIT=$?
echo ""
echo "WS Soak completat. Log: ${LOG_HOST}"
echo "  Comprovar: grep -E 'WS_SOAK_RESULT|WS_SOAK_SUMMARY' ${LOG_HOST}"
exit $EXIT

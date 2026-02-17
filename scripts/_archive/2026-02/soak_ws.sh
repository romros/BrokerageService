#!/bin/bash
# WS Soak: 15 min (default) o N segons. Valida pipeline ticks→candles→store→WS.
# Log guardat a datafiles/ws_soak/<ts>_ws_soak_<N>m.log
#
# Ús:
#   ./scripts/soak_ws.sh           # 15 min (900s)
#   ./scripts/soak_ws.sh 900       # 15 min
#   ./scripts/soak_ws.sh 60        # 1 min (test curt)
#
# Broker amb pipeline candles (ETH,BTC):
#   docker compose -f docker-compose.yml -f docker-compose.soak.yml up -d
#   ./scripts/soak_ws.sh 900
#
# Recorda: docker compose build brokerage si has canviat codi.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

DURATION_S=${1:-900}   # default 15 min (900s)
MINUTES=$((DURATION_S / 60))
if [ "$MINUTES" -lt 1 ]; then MINUTES=1; fi
TS=$(date +%Y%m%d_%H%M%S)
LOG_PATH="/datafiles/ws_soak/${TS}_ws_soak_${MINUTES}m.log"
LOG_HOST="${PROJECT_ROOT}/datafiles/ws_soak/${TS}_ws_soak_${MINUTES}m.log"

echo "WS Soak: ${DURATION_S}s (~${MINUTES} min)"
echo "Log (host): ${LOG_HOST}"
echo ""
echo "--- Instruccions ---"
echo "  Broker amb pipeline candles (ETH):"
echo "    docker compose -f docker-compose.yml -f docker-compose.soak.yml up -d"
echo "  Test ràpid (60s): ./scripts/soak_ws_quick.sh"
echo "  OK si: WS_SOAK_RESULT status=OK, candles>=1, reconnects<=allow, max_gap_s<=120"
echo "  Seguir log: tail -f ${LOG_HOST}"
echo ""

# El directori ws_soak es crea dins el container (ws_soak.py) — evita Permission denied al host
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

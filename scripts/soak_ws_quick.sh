#!/bin/bash
# WS Soak ràpid (~60s): arrenca broker amb fake feed i executa soak.
# Per provar que tot funciona abans del soak llarg (15 min).
#
# Ús: ./scripts/soak_ws_quick.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

echo "WS Soak Quick: arrencant broker (fake feed) + soak 60s..."
echo ""

# Arrencar broker amb pipeline candles (fake)
docker compose -f docker-compose.yml -f docker-compose.soak.yml up -d brokerage

# Esperar health
echo "Esperant broker..."
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/api/v1/broker/health >/dev/null 2>&1; then
    echo "✓ Broker ready"
    break
  fi
  sleep 2
done

# Soak 60s
TS=$(date +%Y%m%d_%H%M%S)
LOG_PATH="/datafiles/ws_soak/${TS}_ws_soak_1m.log"
docker compose run --rm brokerage python3 -m application.tools.ws_soak \
  --minutes 1 \
  --ws-url "ws://brokerage:8000/api/v1/ws" \
  --topic "candle:ETH:1m" \
  --allow-reconnects 3 \
  --max-gap-seconds 120 \
  --log-path "${LOG_PATH}"

EXIT=$?
echo ""
echo "Comprovar: grep -E 'WS_SOAK_RESULT|WS_SOAK_SUMMARY' ${PROJECT_ROOT}/datafiles/ws_soak/${TS}_ws_soak_1m.log"
exit $EXIT

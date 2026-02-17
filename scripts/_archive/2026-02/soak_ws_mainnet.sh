#!/bin/bash
# WS Soak MAINNET: 15 min amb Lighter real feed (P2.2)
#
# Requereix: .env amb LIGHTER_L1_ADDRESS, LIGHTER_L1_PRIVATE_KEY, LIGHTER_API_PRIVATE_KEY
# Ús: ./scripts/soak_ws_mainnet.sh [seconds] [eurusd|xau]
# Default: 900s (15 min), autodetect (ETH/BTC/EURUSD/XAU)
# eurusd|xau: usa docker-compose.mainnet-eurusd.yml i --topic candle:EURUSD:1m o candle:XAU:1m
#
# Log: datafiles/ws_soak/<ts>_ws_soak_15m_mainnet.log
# OK si: WS_SOAK_RESULT status=OK, candles>=15, missing_minutes=0

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

DURATION_S=${1:-900}
SYMBOL_OVERRIDE=${2:-}
MINUTES=$((DURATION_S / 60))
if [ "$MINUTES" -lt 1 ]; then MINUTES=1; fi
TS=$(date +%Y%m%d_%H%M%S)
LOG_PATH="/datafiles/ws_soak/${TS}_ws_soak_15m_mainnet.log"
LOG_HOST="${PROJECT_ROOT}/datafiles/ws_soak/${TS}_ws_soak_15m_mainnet.log"

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.mainnet.yml"
SOAK_EXTRA_ARGS=()

if [ "$SYMBOL_OVERRIDE" = "eurusd" ] || [ "$SYMBOL_OVERRIDE" = "xau" ]; then
  COMPOSE_FILES="${COMPOSE_FILES} -f docker-compose.mainnet-eurusd.yml"
  TOPIC="candle:${SYMBOL_OVERRIDE^^}:1m"
  SOAK_EXTRA_ARGS=(--topic "$TOPIC")
  echo "Mode: ${SYMBOL_OVERRIDE^^} (Lighter forex/metals)"
fi

echo "WS Soak MAINNET: ${DURATION_S}s (~${MINUTES} min)"
echo "Log (host): ${LOG_HOST}"
echo ""
echo "--- Requereix ---"
echo "  .env amb LIGHTER_L1_ADDRESS, LIGHTER_L1_PRIVATE_KEY, LIGHTER_API_PRIVATE_KEY"
echo "  Broker: docker compose ${COMPOSE_FILES} up -d"
echo "  Test ràpid (60s): ./scripts/soak_ws_mainnet.sh 60"
echo "  EURUSD: ./scripts/soak_ws_mainnet.sh 60 eurusd"
echo ""

# Arrencar broker amb mainnet (si no està up)
docker compose ${COMPOSE_FILES} up -d brokerage

# Esperar health
echo "Esperant broker..."
for i in $(seq 1 20); do
  if curl -sf http://localhost:8000/api/v1/broker/health >/dev/null 2>&1; then
    echo "✓ Broker ready"
    break
  fi
  sleep 2
done

# Soak amb autodetect symbols (o --topic si eurusd/xau)
WS_URL="${WS_SOAK_URL:-ws://brokerage:8000/api/v1/ws}"
docker compose ${COMPOSE_FILES} run --rm brokerage python3 -m application.tools.ws_soak \
  --minutes "${MINUTES}" \
  --ws-url "${WS_URL}" \
  --autodetect-symbols \
  --broker-url "http://brokerage:8000" \
  --allow-reconnects 3 \
  --max-gap-seconds 120 \
  --log-path "${LOG_PATH}" \
  "${SOAK_EXTRA_ARGS[@]}"

EXIT=$?
echo ""
echo "WS Soak MAINNET completat. Log: ${LOG_HOST}"
echo "  Comprovar: grep -E 'WS_SOAK_RESULT|WS_SOAK_SUMMARY' ${LOG_HOST}"
exit $EXIT

#!/bin/bash
# T5.22/T5.23 — Script canònic: start/continue stack + smoke Ostium LIVE.
#
# Aixeca el stack split amb serveis explícits (mai up global).
# Compose: docker-compose.yml + split + ostium-live-trading.
#
# Regles crítiques:
#   - MAI up -d sense llista de serveis.
#   - MAI prune/remove/stop de realtime-datalayer.
#   - realtime_datalayer: up només si no està running.
#   - historical_datalayer: up només si cal.
#   - datalayer-proxy: sempre up.
#   - trading_service: recreate via smoke.
#
# Requereix: lab/ostium/.env amb RPC_URL, PRIVATE_KEY.
#
# Ús:
#   ./scripts/up_ostium_live.sh

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

COMPOSE_FILES=(
  -f docker-compose.yml
  -f deploy/compose/docker-compose.split.yml
  -f deploy/compose/overrides/ostium-live-trading.yml
)

# Carregar lab/ostium/.env
ENV_FILE="$PROJECT_ROOT/lab/ostium/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "✗ $ENV_FILE no trobat. Crea'l des de lab/ostium/.env.example"
  exit 1
fi
set -a
source "$ENV_FILE"
set +a

export OSTIUM_RPC_URL="${OSTIUM_RPC_URL:-$RPC_URL}"
export OSTIUM_PRIVATE_KEY="${OSTIUM_PRIVATE_KEY:-$PRIVATE_KEY}"

if [ -z "$OSTIUM_RPC_URL" ] || [ -z "$OSTIUM_PRIVATE_KEY" ]; then
  echo "✗ RPC_URL i PRIVATE_KEY obligatoris a $ENV_FILE"
  exit 1
fi

echo "=== Up Ostium LIVE stack (serveis explícits) ==="
echo ""

# 1) realtime_datalayer: up només si no està running
REALTIME_STATUS=$(docker inspect -f '{{.State.Status}}' realtime-datalayer 2>/dev/null || echo "none")
if [ "$REALTIME_STATUS" = "running" ]; then
  echo "  realtime_datalayer: Running → skip (no tocar)"
else
  echo "  realtime_datalayer: Estat=$REALTIME_STATUS → up -d realtime_datalayer"
  docker compose "${COMPOSE_FILES[@]}" up -d realtime_datalayer
fi
echo ""

# 2) historical_datalayer: up només si no està running
HISTORICAL_STATUS=$(docker inspect -f '{{.State.Status}}' historical-datalayer 2>/dev/null || echo "none")
if [ "$HISTORICAL_STATUS" = "running" ]; then
  echo "  historical_datalayer: Running → skip"
else
  echo "  historical_datalayer: Estat=$HISTORICAL_STATUS → up -d historical_datalayer"
  docker compose "${COMPOSE_FILES[@]}" up -d historical_datalayer
fi
echo ""

# 3) trading_service: up (smoke farà --force-recreate després)
echo "  trading_service: up -d trading_service"
docker compose "${COMPOSE_FILES[@]}" up -d trading_service
echo ""

# 4) datalayer-proxy: sempre up
echo "  datalayer-proxy: up -d datalayer-proxy"
docker compose "${COMPOSE_FILES[@]}" up -d datalayer-proxy
echo ""

echo "  Esperant 5s per arrencada..."
sleep 5
echo ""

"$SCRIPT_DIR/run_ostium_live_smoke.sh" --recreate --clean

#!/bin/bash
# T5.22 — Script canònic: start/continue stack + smoke Ostium LIVE.
#
# Aixeca el stack split (proxy + realtime si cal + trading_service) amb ostium-live-trading,
# després executa smoke --recreate --clean.
#
# Regles crítiques:
#   - MAI prune/remove/stop de realtime-datalayer.
#   - Si realtime-datalayer ja corre: NO recrear-lo.
#   - Si no existeix o està aturat: arrencar-lo (up -d) sense rebuild.
#   - trading_service sí que es recrea.
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

echo "=== Up Ostium LIVE stack ==="
echo ""

# 1) Detectar estat realtime-datalayer (sense dependències)
REALTIME_STATUS=$(docker inspect -f '{{.State.Status}}' realtime-datalayer 2>/dev/null || echo "none")

if [ "$REALTIME_STATUS" = "running" ]; then
  echo "  realtime-datalayer: Running → skip (no tocar)"
elif [ "$REALTIME_STATUS" = "exited" ] || [ "$REALTIME_STATUS" = "created" ] || [ "$REALTIME_STATUS" = "none" ]; then
  echo "  realtime-datalayer: Aturat/inexistent → arrencar (up -d, sense rebuild)"
  docker compose "${COMPOSE_FILES[@]}" up -d realtime_datalayer
else
  echo "  realtime-datalayer: Estat=$REALTIME_STATUS → arrencar"
  docker compose "${COMPOSE_FILES[@]}" up -d realtime_datalayer
fi
echo ""

# 2) Assegurar datalayer-proxy Running (depèn de realtime, historical, trading)
echo "  datalayer-proxy: assegurar Running"
docker compose "${COMPOSE_FILES[@]}" up -d datalayer-proxy
echo ""

# 3) Smoke: recreate trading + clean + run
echo "  trading_service: recreate (via smoke --recreate)"
echo ""
echo "  Esperant 5s per arrencada..."
sleep 5
echo ""

"$SCRIPT_DIR/run_ostium_live_smoke.sh" --recreate --clean

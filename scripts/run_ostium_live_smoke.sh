#!/bin/bash
# Ostium LIVE E2E smoke — wrapper canònic.
#
# Requereix: lab/ostium/.env amb RPC_URL, PRIVATE_KEY (o MODE=live VENUE=ostium ENABLE_LIVE_TRADING=1).
# Servidor: trading_service ha d'estar en mode LIVE Ostium (ostium-live-trading override).
#
# Ús:
#   ./scripts/run_ostium_live_smoke.sh              # només smoke (trading_service ja configurat)
#   ./scripts/run_ostium_live_smoke.sh --recreate   # recrea trading_service (NO realtime) i smoke
#
# IMPORTANT: --recreate només toca trading_service. Mai atura ni recrea realtime_datalayer.
# Veure deploy/compose/overrides/README.md § Ostium LIVE.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

RECREATE=0
if [ "${1:-}" = "--recreate" ]; then
  RECREATE=1
fi

# Carregar lab/ostium/.env
ENV_FILE="$PROJECT_ROOT/lab/ostium/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "✗ $ENV_FILE no trobat. Crea'l des de lab/ostium/.env.example"
  exit 1
fi
set -a
source "$ENV_FILE"
set +a

# Mapear RPC_URL/PRIVATE_KEY → OSTIUM_* (smoke i compose)
export OSTIUM_RPC_URL="${OSTIUM_RPC_URL:-$RPC_URL}"
export OSTIUM_PRIVATE_KEY="${OSTIUM_PRIVATE_KEY:-$PRIVATE_KEY}"

if [ -z "$OSTIUM_RPC_URL" ] || [ -z "$OSTIUM_PRIVATE_KEY" ]; then
  echo "✗ RPC_URL i PRIVATE_KEY (o OSTIUM_RPC_URL, OSTIUM_PRIVATE_KEY) obligatoris a $ENV_FILE"
  exit 1
fi

BASE_URL="${BASE_URL:-http://127.0.0.1:8081/trade}"

if [ "$RECREATE" -eq 1 ]; then
  echo "=== Recreant només trading_service (NO realtime) ==="
  docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml \
    -f deploy/compose/overrides/ostium-live-trading.yml up -d trading_service
  echo "  Esperant 3s..."
  sleep 3
  echo ""
fi

echo "=== Ostium LIVE E2E smoke ==="
echo "  BASE_URL=$BASE_URL"
echo ""

export BASE_URL
export MODE=live
export VENUE=ostium
export ENABLE_LIVE_TRADING=1

export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
python3 application/tools/ostium_live_e2e_smoke.py
EXIT=$?

if [ $EXIT -eq 0 ]; then
  echo ""
  echo "✓ Ostium LIVE smoke OK"
else
  echo ""
  echo "✗ Ostium LIVE smoke FAILED (exit=$EXIT)"
fi

exit $EXIT

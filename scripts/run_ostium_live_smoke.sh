#!/bin/bash
# Ostium LIVE E2E smoke — wrapper canònic.
#
# Requereix: lab/ostium/.env amb RPC_URL, PRIVATE_KEY (o MODE=live VENUE=ostium ENABLE_LIVE_TRADING=1).
# Servidor: trading_service ha d'estar en mode LIVE Ostium (ostium-live-trading override).
#
# Ús:
#   ./scripts/run_ostium_live_smoke.sh                    # només smoke (trading_service ja configurat)
#   ./scripts/run_ostium_live_smoke.sh --recreate           # recrea trading_service (NO realtime) i smoke
#   ./scripts/run_ostium_live_smoke.sh --recreate --clean   # recomanat: clean-slate + smoke
#
# --clean: tanca totes les posicions obertes abans del smoke (evita POSITION_ALREADY_OPEN).
# IMPORTANT: --recreate només toca trading_service. Mai atura ni recrea realtime_datalayer.
# Veure deploy/compose/overrides/README.md § Ostium LIVE.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

RECREATE=0
CLEAN=0
for arg in "$@"; do
  case "$arg" in
    --recreate) RECREATE=1 ;;
    --clean)    CLEAN=1 ;;
  esac
done

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

# T5.16: directe a 8010 evita nginx 504 (proxy_read 60s); open Ostium pot trigar >60s
BASE_URL="${BASE_URL:-http://127.0.0.1:8010}"

# T5.20/T5.26: --clean tanca posicions obertes abans del smoke (evita POSITION_ALREADY_OPEN).
# Executem dins del container per garantir imports (foundation/lifecycle).
if [ "$CLEAN" -eq 1 ]; then
  echo "=== Clean-slate: tancant posicions obertes ==="
  CONTAINER="trading-service-split"
  if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
    echo "✗ Container $CONTAINER no està running. Executa ./scripts/up_ostium_live.sh abans."
    exit 1
  fi
  docker exec -e OSTIUM_RPC_URL="$OSTIUM_RPC_URL" -e OSTIUM_PRIVATE_KEY="$OSTIUM_PRIVATE_KEY" \
    -e PRIVATE_KEY="${OSTIUM_PRIVATE_KEY:-$PRIVATE_KEY}" \
    "$CONTAINER" python3 lab/ostium/scripts/close_open_position.py --all
  echo ""
fi

if [ "$RECREATE" -eq 1 ]; then
  echo "=== Recreant només trading_service (NO realtime) ==="
  docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml \
    -f deploy/compose/overrides/ostium-live-trading.yml up -d --force-recreate trading_service
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
# T5.17: server retorna 202 en <=15s; smoke fa polling fins 480s
export HTTP_TIMEOUT_S="${HTTP_TIMEOUT_S:-30}"
export SMOKE_TOTAL_TIMEOUT_S="${SMOKE_TOTAL_TIMEOUT_S:-480}"

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

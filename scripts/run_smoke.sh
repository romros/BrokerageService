#!/bin/bash
# Smoke operatiu canònic. Profile determina compose override i tipus de smoke.
#
# Ús:
#   ./scripts/run_smoke.sh [profile]
#
# Profiles: data-layer (default), smoke
#   data-layer: Data Layer smoke (3 min, prefetch+writer+gates)
#   smoke: Smoke reconcile (venue=lighter, 10 min)
#
# Compose: docker compose -f docker-compose.yml -f deploy/compose/overrides/<profile>.yml

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

PROFILE=${1:-data-layer}
# Permisos: data-layer/ostium escriuen datafiles amb UID/GID host (compat_reports writable)
export UID=${UID:-$(id -u 2>/dev/null || echo 0)}
export GID=${GID:-$(id -g 2>/dev/null || echo 0)}
OVERRIDES_DIR="$PROJECT_ROOT/deploy/compose/overrides"
BROKER_URL="${BROKER_URL:-http://localhost:8000}"
HEALTH_URL="${BROKER_URL}/api/v1/broker/health"

# Resoldre compose override per profile
case "$PROFILE" in
  data-layer)
    OVERRIDE="$OVERRIDES_DIR/data-layer.yml"
    ;;
  smoke)
    OVERRIDE="$OVERRIDES_DIR/soak.yml"
    ;;
  ostium)
    OVERRIDE="$OVERRIDES_DIR/ostium.yml"
    ;;
  *)
    echo "Profile desconegut: $PROFILE (data-layer, smoke, ostium)"
    exit 1
    ;;
esac

if [ ! -f "$OVERRIDE" ]; then
  echo "Override no trobat: $OVERRIDE"
  exit 1
fi

COMPOSE_FILES="-f docker-compose.yml -f $OVERRIDE"

echo "Smoke (profile=$PROFILE)"
echo "  Build + up..."
docker compose $COMPOSE_FILES build brokerage 2>/dev/null || true
docker compose $COMPOSE_FILES up -d brokerage

echo "  Waiting for broker..."
for i in $(seq 1 30); do
  if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
    echo "  ✓ Broker ready"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "✗ Broker not ready after 30s"
    exit 6
  fi
  sleep 1
done

echo ""
export BROKER_URL
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

case "$PROFILE" in
  data-layer)
    python3 -m application.tools.data_layer_smoke
    ;;
  smoke)
    DURATION=${SMOKE_SECONDS:-600}
    TS=$(date +%Y%m%d_%H%M%S)
    LOG_PATH="/datafiles/smoke_runs/soak_${TS}.log"
    mkdir -p "${PROJECT_ROOT}/datafiles/smoke_runs"
    docker compose $COMPOSE_FILES run --rm brokerage python3 -m application.smoke \
      --venue lighter --mode PAPER --seconds "$DURATION" --log-path "$LOG_PATH"
    ;;
  ostium)
    python3 -m application.tools.data_layer_smoke
    ;;
  *)
    exit 1
    ;;
esac
exit $?

#!/bin/bash
# Data Layer smoke (2–5 min). Preflight + wait 3 min + eval + artifact.
#
# Ús:
#   ./scripts/run_data_layer_smoke.sh
#
# Requereix: docker compose -f docker-compose.yml -f docker-compose.data-layer.yml up
# Aquest script fa build+up si cal, espera health, i executa smoke.
#
# Exit: 0 OK, 2 DEGRADED, 3 missing/gap, 4 dupes/ts_step, 5 stale, 6 health fail

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.data-layer.yml"
BROKER_URL="${BROKER_URL:-http://localhost:8000}"
HEALTH_URL="${BROKER_URL}/api/v1/broker/health"

echo "Data Layer smoke"
echo "  Build + up (Data Layer override)..."
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
python3 scripts/run_data_layer_smoke.py
exit $?

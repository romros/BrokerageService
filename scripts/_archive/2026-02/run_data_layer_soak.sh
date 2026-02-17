#!/bin/bash
# Data Layer soak (30–120 min). Loop cada 60s, artifact al final.
#
# Ús:
#   ./scripts/run_data_layer_soak.sh 30   # 30 min
#   ./scripts/run_data_layer_soak.sh 60  # 60 min
#
# Requereix: broker amb Data Layer up (docker compose -f docker-compose.yml -f docker-compose.data-layer.yml up -d)
# Si el broker no està up, aquest script el puja.
#
# Exit: 0 OK, 2 DEGRADED, 3 missing/gap, 4 dupes/ts_step, 5 stale, 6 health fail

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

MINUTES=${1:-30}
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.data-layer.yml"
BROKER_URL="${BROKER_URL:-http://localhost:8000}"
HEALTH_URL="${BROKER_URL}/api/v1/broker/health"

# Ensure broker up
if ! curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Broker not up. Starting..."
  docker compose $COMPOSE_FILES build brokerage 2>/dev/null || true
  docker compose $COMPOSE_FILES up -d brokerage
  echo "Waiting for broker..."
  for i in $(seq 1 30); do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
      echo "✓ Broker ready"
      break
    fi
    if [ "$i" -eq 30 ]; then
      echo "✗ Broker not ready"
      exit 6
    fi
    sleep 1
  done
fi

echo ""
export BROKER_URL
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
python3 scripts/run_data_layer_soak.py "$MINUTES"
exit $?

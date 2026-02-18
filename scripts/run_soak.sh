#!/bin/bash
# Soak operatiu canònic. Profile determina compose override i tipus de soak.
#
# Ús:
#   ./scripts/run_soak.sh <minutes> [profile] [post-compat]
#
# Profiles: data-layer (default), ws, ostium
#   post-compat: només per profile ostium; executa compat al final del soak
#   data-layer: Data Layer soak (loop data_status cada 60s)
#   ws: WS soak (candle:ETH:1m, pipeline fake feed)
#
# Compose: docker compose -f docker-compose.yml -f deploy/compose/overrides/<profile>.yml

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

MINUTES=${1:-30}
PROFILE=${2:-data-layer}
POST_COMPAT=${3:-}
# Permisos: data-layer/ostium escriuen datafiles amb UID/GID host (compat_reports writable)
export DOCKER_UID=${DOCKER_UID:-$(id -u 2>/dev/null || echo 0)}
export DOCKER_GID=${DOCKER_GID:-$(id -g 2>/dev/null || echo 0)}
# Pre-flight: datafiles/logs han de ser writable quan contenidor corre com a host user
# (user DOCKER_UID per compat_reports; set_host_readable_permissions fa 0o644/755 per llegir)
if [ "$DOCKER_UID" != "0" ] 2>/dev/null; then
  mkdir -p "$PROJECT_ROOT/datafiles" "$PROJECT_ROOT/logs"
  if [ ! -w "$PROJECT_ROOT/datafiles" ] || [ ! -w "$PROJECT_ROOT/logs" ]; then
    echo "⚠ datafiles o logs no són writable. Una vegada: sudo chown -R \$(id -u):\$(id -g) datafiles logs"
    exit 1
  fi
fi
OVERRIDES_DIR="$PROJECT_ROOT/deploy/compose/overrides"
BROKER_URL="${BROKER_URL:-http://localhost:8000}"
HEALTH_URL="${BROKER_URL}/api/v1/broker/health"

# Resoldre compose override per profile
case "$PROFILE" in
  data-layer)
    OVERRIDE="$OVERRIDES_DIR/data-layer.yml"
    ;;
  ws)
    OVERRIDE="$OVERRIDES_DIR/soak.yml"
    ;;
  ostium)
    OVERRIDE="$OVERRIDES_DIR/ostium.yml"
    ;;
  *)
    echo "Profile desconegut: $PROFILE (data-layer, ws, ostium)"
    exit 1
    ;;
esac

if [ ! -f "$OVERRIDE" ]; then
  echo "Override no trobat: $OVERRIDE"
  exit 1
fi

COMPOSE_FILES="-f docker-compose.yml -f $OVERRIDE"

# Ensure broker up
if ! curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Broker not up. Starting (profile=$PROFILE)..."
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
# data-layer/ostium: corre dins Docker per tenir dukascopy-python i deps (post-compat)
# BROKER_URL dins xarxa Docker = brokerage:8000
export BROKER_URL
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

case "$PROFILE" in
  data-layer|ostium)
    SOAK_ARGS="$MINUTES"
    if [ "$POST_COMPAT" = "post-compat" ] && [ "$PROFILE" = "ostium" ]; then
      SOAK_ARGS="$SOAK_ARGS --post-compat 1"
    fi
    if [ "$PROFILE" = "ostium" ]; then
      SOAK_ARGS="$SOAK_ARGS --profile ostium"
    fi
    # Dins Docker: BROKER_URL=brokerage:8000 (xarxa Docker), DATAFILES_ROOT=/datafiles (muntat)
    docker compose $COMPOSE_FILES run --rm \
      -e BROKER_URL="http://brokerage:8000" \
      -e DATAFILES_ROOT=/datafiles \
      brokerage python3 -m application.tools.data_layer_soak $SOAK_ARGS
    ;;
  ws)
    MINUTES=$((MINUTES < 1 ? 1 : MINUTES))
    TS=$(date +%Y%m%d_%H%M%S)
    LOG_PATH="/datafiles/ws_soak/${TS}_ws_soak_${MINUTES}m.log"
    WS_URL="${WS_SOAK_URL:-ws://brokerage:8000/api/v1/ws}"
    docker compose $COMPOSE_FILES run --rm brokerage python3 -m application.tools.ws_soak \
      --minutes "$MINUTES" \
      --ws-url "$WS_URL" \
      --topic "candle:ETH:1m" \
      --allow-reconnects 3 \
      --max-gap-seconds 120 \
      --log-path "$LOG_PATH"
    ;;
  *)
    exit 1
    ;;
esac
exit $?

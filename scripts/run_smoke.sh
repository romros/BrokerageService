#!/bin/bash
# Smoke operatiu canònic. Profile determina compose override i tipus de smoke.
#
# Ús:
#   ./scripts/run_smoke.sh [profile]
#
# Profiles: data-layer (default), smoke, ostium, realtime_datalayer
#   data-layer: Data Layer smoke (3 min, prefetch+writer+gates)
#   smoke: Smoke reconcile (venue=lighter, 10 min)
#   ostium: Ostium override
#   realtime_datalayer: Realtime DataLayer split (up -d, checks /health /status /symbols /docs, artifact)
#
# Compose: docker compose -f docker-compose.yml -f deploy/compose/overrides/<profile>.yml
#   realtime_datalayer: deploy/compose/docker-compose.split.yml

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

PROFILE=${1:-data-layer}
# Permisos: data-layer/ostium escriuen datafiles amb UID/GID host (compat_reports writable)
export DOCKER_UID=${DOCKER_UID:-$(id -u 2>/dev/null || echo 0)}
export DOCKER_GID=${DOCKER_GID:-$(id -g 2>/dev/null || echo 0)}
# Pre-flight: datafiles/logs han de ser writable quan contenidor corre com a host user
# (user DOCKER_UID per compat_reports; set_host_readable_permissions fa 0o644/755 per llegir)
if [ "$DOCKER_UID" != "0" ] 2>/dev/null; then
  mkdir -p "$PROJECT_ROOT/datafiles" "$PROJECT_ROOT/logs" "$PROJECT_ROOT/datafiles/realtime_datalayer/runs"
  if [ ! -w "$PROJECT_ROOT/datafiles" ] || [ ! -w "$PROJECT_ROOT/logs" ]; then
    echo "⚠ datafiles o logs no són writable. Una vegada: sudo chown -R \$(id -u):\$(id -g) datafiles logs"
    exit 1
  fi
fi
OVERRIDES_DIR="$PROJECT_ROOT/deploy/compose/overrides"
BROKER_URL="${BROKER_URL:-http://localhost:8000}"
HEALTH_URL="${BROKER_URL}/api/v1/broker/health"

# Resoldre compose override per profile
REALTIME_SMOKE=0
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
  realtime_datalayer)
    OVERRIDE="$PROJECT_ROOT/deploy/compose/docker-compose.split.yml"
    REALTIME_SMOKE=1
    ;;
  *)
    echo "Profile desconegut: $PROFILE (data-layer, smoke, ostium, realtime_datalayer)"
    exit 1
    ;;
esac

if [ "$REALTIME_SMOKE" -eq 1 ]; then
  # Smoke Realtime DataLayer (split compose)
  REALTIME_URL="${REALTIME_URL:-http://localhost:8001}"
  echo "Smoke realtime_datalayer"
  echo "  Build + up..."
  docker compose -f docker-compose.yml -f "$OVERRIDE" build realtime_datalayer 2>/dev/null || true
  docker compose -f docker-compose.yml -f "$OVERRIDE" up -d realtime_datalayer

  echo "  Waiting for /health..."
  for i in $(seq 1 30); do
    if curl -sf "$REALTIME_URL/health" >/dev/null 2>&1; then
      echo "  ✓ Realtime ready"
      break
    fi
    if [ "$i" -eq 30 ]; then
      echo "✗ Realtime not ready after 30s"
      exit 6
    fi
    sleep 1
  done

  TS=$(date +%Y%m%d_%H%M%S)
  RUNS_DIR="$PROJECT_ROOT/datafiles/realtime_datalayer/runs"
  if ! mkdir -p "$RUNS_DIR" 2>/dev/null; then
    RUNS_DIR="$PROJECT_ROOT/datafiles/realtime_datalayer_runs"
    mkdir -p "$RUNS_DIR"
    echo "  ⚠ datafiles/realtime_datalayer/runs no writable, using datafiles/realtime_datalayer_runs"
  fi
  ARTIFACT="$RUNS_DIR/${TS}_smoke.json"

  echo "  Checking /status, /symbols, /docs..."
  STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$REALTIME_URL/status")
  SYMBOLS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$REALTIME_URL/symbols")
  DOCS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$REALTIME_URL/docs")
  OPENAPI_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$REALTIME_URL/openapi.json")
  UI_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$REALTIME_URL/ui")

  OK=1
  [ "$STATUS_CODE" = "200" ] || { echo "✗ /status: $STATUS_CODE"; OK=0; }
  [ "$SYMBOLS_CODE" = "200" ] || { echo "✗ /symbols: $SYMBOLS_CODE"; OK=0; }
  [ "$DOCS_CODE" = "200" ] || { echo "✗ /docs: $DOCS_CODE"; OK=0; }
  [ "$OPENAPI_CODE" = "200" ] || { echo "✗ /openapi.json: $OPENAPI_CODE"; OK=0; }
  [ "$UI_CODE" = "200" ] || { echo "✗ /ui: $UI_CODE"; OK=0; }

  PASSED_VAL="false"; [ "$OK" -eq 1 ] && PASSED_VAL="true"
  cat > "$ARTIFACT" << EOF
{
  "ts": "$TS",
  "profile": "realtime_datalayer",
  "url": "$REALTIME_URL",
  "checks": {
    "status": $STATUS_CODE,
    "symbols": $SYMBOLS_CODE,
    "docs": $DOCS_CODE,
    "openapi.json": $OPENAPI_CODE,
    "ui": $UI_CODE
  },
  "passed": $PASSED_VAL
}
EOF
  echo "  Artifact: $ARTIFACT"
  [ "$OK" -eq 1 ] && echo "✓ Smoke realtime_datalayer OK" || { echo "✗ Smoke failed"; exit 7; }
  exit 0
fi

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
    # --user host UID:GID per evitar root-owned files
    docker compose $COMPOSE_FILES run --rm --user "$(id -u):$(id -g)" brokerage python3 -m application.smoke \
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

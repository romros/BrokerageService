#!/bin/bash
# T7.3.1 — Activar trading_service en mode LIVE Ostium.
#
# Aplica override ostium-live-trading.yml (ENABLE_LIVE_TRADING=1, MODE=live, VENUE=ostium)
# i fa --force-recreate ONLY de trading_service.
# MAI toca realtime_datalayer ni historical_datalayer.
#
# Requereix: lab/ostium/.env amb RPC_URL, PRIVATE_KEY.
#
# Ús:
#   ./scripts/live_on.sh
#   ./scripts/live_on.sh --base-url http://localhost:8081   # verificar via gateway (default)
#   ./scripts/live_on.sh --base-url http://127.0.0.1:8010  # verificar directe al servei
#
# Exit codes:
#   0 = OK, mode confirmat LIVE
#   1 = prerequisits fallits (env, serveis)
#   2 = docker compose fallat
#   3 = verificació mode fallada (servei no reporta LIVE)

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

BASE_URL="${BASE_URL:-http://localhost:8081}"
for arg in "$@"; do
  case "$arg" in
    --base-url=*) BASE_URL="${arg#*=}" ;;
    --base-url)   shift; BASE_URL="$1" ;;
  esac
done

COMPOSE_FILES=(
  -f docker-compose.yml
  -f deploy/compose/docker-compose.split.yml
  -f deploy/compose/overrides/ostium-live-trading.yml
)

echo "=== LIVE ON: activant trading_service mode LIVE Ostium ==="
echo "  Override: deploy/compose/overrides/ostium-live-trading.yml"
echo "  Serveis afectats: trading_service ONLY (no toca realtime_datalayer)"
echo ""

# ── 1) Precheck: lab/ostium/.env ──
ENV_FILE="$PROJECT_ROOT/lab/ostium/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "✗ $ENV_FILE no trobat."
  echo "  Crea'l des de lab/ostium/.env.example amb RPC_URL i PRIVATE_KEY."
  exit 1
fi
set -a
source "$ENV_FILE"
set +a

export OSTIUM_RPC_URL="${OSTIUM_RPC_URL:-$RPC_URL}"
export OSTIUM_PRIVATE_KEY="${OSTIUM_PRIVATE_KEY:-$PRIVATE_KEY}"

if [ -z "${OSTIUM_RPC_URL:-}" ] || [ -z "${OSTIUM_PRIVATE_KEY:-}" ]; then
  echo "✗ RPC_URL i PRIVATE_KEY obligatoris a $ENV_FILE"
  exit 1
fi
echo "  ENV: RPC_URL=*** PRIVATE_KEY=*** (carregats)"

# ── 2) Precheck: gateway/proxy up ──
GATEWAY_OK=0
if curl -sf --max-time 3 "$BASE_URL/nginx-health" >/dev/null 2>&1 \
   || curl -sf --max-time 3 "$BASE_URL/trade/api/v1/broker/health" >/dev/null 2>&1; then
  GATEWAY_OK=1
  echo "  Gateway: OK ($BASE_URL)"
else
  echo "  WARN: Gateway no respon a $BASE_URL — continuant igualment (trading_service pot estar reiniciant)"
fi
echo ""

# ── 3) Precheck: realtime_datalayer running (mai tocar) ──
REALTIME_STATUS=$(docker inspect -f '{{.State.Status}}' realtime-datalayer 2>/dev/null || echo "none")
if [ "$REALTIME_STATUS" = "running" ]; then
  echo "  realtime_datalayer: Running → OK (no tocar)"
else
  echo "  WARN: realtime_datalayer no running (status=$REALTIME_STATUS)"
  echo "  ⚠ Considera aixecar-lo separadament si cal data quality per LIVE."
fi
echo ""

# ── 4) Apply override → recreate trading_service ONLY ──
echo "  Aplicant override LIVE + recreant trading_service..."
if ! docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate trading_service; then
  echo "✗ docker compose fallat. Revisa logs: docker logs trading-service-split"
  exit 2
fi
echo ""

# ── 5) Wait health ──
echo "  Esperant 5s per arrencada de trading_service..."
sleep 5

# Retry health fins a 20s
HEALTH_OK=0
for i in 1 2 3 4; do
  if curl -sf --max-time 3 "${BASE_URL}/trade/api/v1/broker/health" >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  echo "  Health check $i/4 no OK, reintentant..."
  sleep 3
done

if [ "$HEALTH_OK" -eq 0 ]; then
  echo "  WARN: /health no respon, continuant verificació de mode..."
fi

# ── 6) Verificació: preflight → live_enabled + mode ──
PREFLIGHT_URL="${BASE_URL}/trade/api/v1/broker/preflight?venue=ostium&symbol=EURUSD"
PREFLIGHT_RESP=$(curl -sf --max-time 5 "$PREFLIGHT_URL" 2>/dev/null || echo "")

if [ -z "$PREFLIGHT_RESP" ]; then
  echo "  WARN: preflight no respon a $PREFLIGHT_URL"
  echo "  Verifica manualment: curl '$PREFLIGHT_URL' | python3 -m json.tool"
  echo ""
  echo "LIVE ON aplicat (sense confirmació de mode via preflight)"
  exit 3
fi

# Extreure mode i live_enabled del JSON
MODE_VAL=$(echo "$PREFLIGHT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode','?'))" 2>/dev/null || echo "?")
LIVE_ENABLED=$(echo "$PREFLIGHT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('live_enabled','?'))" 2>/dev/null || echo "?")

echo "  Preflight → mode=$MODE_VAL live_enabled=$LIVE_ENABLED"

if [ "$MODE_VAL" = "live" ] && [ "$LIVE_ENABLED" = "True" ]; then
  echo ""
  echo "✓ Mode confirmed: LIVE (mode=live live_enabled=True)"
  echo ""
  echo "  Ara pots executar:"
  echo "  python3 -m application.tools.run_live_smoke_trade \\"
  echo "    --venue ostium --symbol EURUSD --side long --collateral 1.5 --leverage 2 --wait-s 10"
  echo ""
  echo "  python3 -m application.tools.run_live_ttl_trade \\"
  echo "    --venue ostium --symbol EURUSD --side long --collateral 1.5 --leverage 2 --ttl-s 60"
  exit 0
else
  echo ""
  echo "✗ Mode NO confirmat: mode=$MODE_VAL live_enabled=$LIVE_ENABLED (esperat mode=live live_enabled=True)"
  echo "  Revisa: docker logs trading-service-split | tail -30"
  echo "  Rollback segur: ./scripts/live_off.sh"
  exit 3
fi

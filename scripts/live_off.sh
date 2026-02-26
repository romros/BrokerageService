#!/bin/bash
# T7.3.1 — Desactivar LIVE: tornar trading_service a mode PAPER (kill-switch).
#
# Aplica override live.off.yml (ENABLE_LIVE_TRADING=0, MODE=paper, VENUE=paper)
# i fa --force-recreate ONLY de trading_service.
# MAI toca realtime_datalayer ni historical_datalayer.
#
# Ús:
#   ./scripts/live_off.sh
#   ./scripts/live_off.sh --base-url http://localhost:8081
#
# Exit codes:
#   0 = OK, mode confirmat PAPER
#   1 = prerequisits fallits
#   2 = docker compose fallat
#   3 = verificació mode fallada

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
  -f deploy/compose/overrides/live.off.yml
)

echo "=== LIVE OFF: tornant trading_service a mode PAPER ==="
echo "  Override: deploy/compose/overrides/live.off.yml"
echo "  Serveis afectats: trading_service ONLY (no toca realtime_datalayer)"
echo ""

# ── 1) Precheck: override existeix ──
if [ ! -f "$PROJECT_ROOT/deploy/compose/overrides/live.off.yml" ]; then
  echo "✗ live.off.yml no trobat a deploy/compose/overrides/"
  exit 1
fi

# ── 2) Precheck: realtime_datalayer (no tocar) ──
REALTIME_STATUS=$(docker inspect -f '{{.State.Status}}' realtime-datalayer 2>/dev/null || echo "none")
if [ "$REALTIME_STATUS" = "running" ]; then
  echo "  realtime_datalayer: Running → OK (no tocar)"
else
  echo "  INFO: realtime_datalayer no running (status=$REALTIME_STATUS) — no és bloquejant per live_off"
fi
echo ""

# ── 3) Apply override → recreate trading_service ONLY ──
echo "  Aplicant override PAPER + recreant trading_service..."
if ! docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate trading_service; then
  echo "✗ docker compose fallat. Revisa logs: docker logs trading-service-split"
  exit 2
fi
echo ""

# ── 4) Wait health ──
echo "  Esperant 5s per arrencada de trading_service..."
sleep 5

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

# ── 5) Verificació: preflight → mode=paper live_enabled=False ──
PREFLIGHT_URL="${BASE_URL}/trade/api/v1/broker/preflight?venue=paper&symbol=EURUSD"
PREFLIGHT_RESP=$(curl -sf --max-time 5 "$PREFLIGHT_URL" 2>/dev/null || echo "")

if [ -z "$PREFLIGHT_RESP" ]; then
  echo "  WARN: preflight no respon a $PREFLIGHT_URL"
  echo "  Verifica manualment: curl '$PREFLIGHT_URL' | python3 -m json.tool"
  echo ""
  echo "LIVE OFF aplicat (sense confirmació de mode via preflight)"
  exit 3
fi

MODE_VAL=$(echo "$PREFLIGHT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode','?'))" 2>/dev/null || echo "?")
LIVE_ENABLED=$(echo "$PREFLIGHT_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('live_enabled','?'))" 2>/dev/null || echo "?")

echo "  Preflight → mode=$MODE_VAL live_enabled=$LIVE_ENABLED"

if [ "$MODE_VAL" = "paper" ] && [ "$LIVE_ENABLED" = "False" ]; then
  echo ""
  echo "✓ Mode confirmed: PAPER (mode=paper live_enabled=False)"
  echo "  Sistema en mode segur. Cap transacció real possible."
  exit 0
else
  echo ""
  echo "✗ Mode NO confirmat: mode=$MODE_VAL live_enabled=$LIVE_ENABLED (esperat mode=paper live_enabled=False)"
  echo "  ATENCIÓ: verifica manualment si hi ha posicions obertes."
  echo "  Revisa: docker logs trading-service-split | tail -30"
  exit 3
fi

#!/bin/bash
# T7.3.1/T7.3.3 — Activar trading_service en mode LIVE Ostium.
#
# Aplica override ostium-live-trading.yml (ENABLE_LIVE_TRADING=1, MODE=live, VENUE=ostium)
# i fa --force-recreate ONLY de trading_service.
# MAI toca realtime_datalayer ni historical_datalayer.
#
# Requereix: lab/ostium/.env amb RPC_URL, PRIVATE_KEY.
#
# Ús:
#   ./scripts/live_on.sh
#   ./scripts/live_on.sh --base-url http://localhost:8081     # gateway (default)
#   ./scripts/live_on.sh --base-url http://127.0.0.1:8010    # directe al servei
#
# Exit codes:
#   0 = OK, mode confirmat LIVE
#   1 = prerequisits fallits (env, fitxers)
#   2 = docker compose fallat
#   3 = verificació mode fallada (servei no reporta LIVE)

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

log()  { echo "  $*"; }
die()  { echo "✗ $*" >&2; exit "${2:-1}"; }

# Imprimir hints de diagnòstic (logs de trading_service)
debug_hints() {
  echo ""
  echo "── DEBUG HINTS ──────────────────────────────"
  echo "  docker compose ps:"
  docker compose \
    -f docker-compose.yml \
    -f deploy/compose/docker-compose.split.yml \
    -f deploy/compose/overrides/ostium-live-trading.yml \
    ps 2>/dev/null || echo "  (docker compose ps fallat)"
  echo ""
  echo "  docker compose logs trading_service --tail 80:"
  docker compose \
    -f docker-compose.yml \
    -f deploy/compose/docker-compose.split.yml \
    -f deploy/compose/overrides/ostium-live-trading.yml \
    logs trading_service --tail 80 2>/dev/null || echo "  (logs no disponibles)"
  echo "─────────────────────────────────────────────"
}

# Poll /health fins OK o timeout
wait_health() {
  local url="$1/trade/api/v1/broker/health"
  local max_s="${2:-25}"
  local interval=3
  local elapsed=0
  printf "  Waiting for /health "
  while [ "$elapsed" -lt "$max_s" ]; do
    if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
      echo " OK (${elapsed}s)"
      return 0
    fi
    printf "."
    sleep "$interval"
    elapsed=$((elapsed + interval))
  done
  echo " TIMEOUT (${max_s}s)"
  return 1
}

# Extreure camp d'un JSON via python3
json_field() {
  local json="$1" field="$2"
  echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$field','?'))" 2>/dev/null || echo "?"
}

# ─────────────────────────────────────────────
# Parsing d'arguments (robust)
# ─────────────────────────────────────────────

BASE_URL="${BASE_URL:-http://localhost:8081}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      [[ $# -ge 2 ]] || die "--base-url requereix un valor"
      BASE_URL="$2"; shift 2 ;;
    --base-url=*)
      BASE_URL="${1#*=}"; shift ;;
    *)
      die "Argument desconegut: $1. Ús: $0 [--base-url URL]" 2 ;;
  esac
done

COMPOSE_FILES=(
  -f docker-compose.yml
  -f deploy/compose/docker-compose.split.yml
  -f deploy/compose/overrides/ostium-live-trading.yml
)

echo "=== LIVE ON: activant trading_service mode LIVE Ostium ==="
log "Override: deploy/compose/overrides/ostium-live-trading.yml"
log "Serveis afectats: trading_service ONLY (no toca realtime_datalayer)"
log "BASE_URL: $BASE_URL"
echo ""

# ── 1) Precheck: lab/ostium/.env ──
ENV_FILE="$PROJECT_ROOT/lab/ostium/.env"
[ -f "$ENV_FILE" ] || die "$ENV_FILE no trobat. Crea'l des de lab/ostium/.env.example amb RPC_URL i PRIVATE_KEY."

set -a
source "$ENV_FILE"
set +a

export OSTIUM_RPC_URL="${OSTIUM_RPC_URL:-${RPC_URL:-}}"
export OSTIUM_PRIVATE_KEY="${OSTIUM_PRIVATE_KEY:-${PRIVATE_KEY:-}}"

[ -n "${OSTIUM_RPC_URL:-}" ]     || die "RPC_URL obligatori a $ENV_FILE"
[ -n "${OSTIUM_PRIVATE_KEY:-}" ] || die "PRIVATE_KEY obligatori a $ENV_FILE"
log "ENV: RPC_URL=*** PRIVATE_KEY=*** (carregats)"

# ── 2) Precheck: realtime_datalayer (mai tocar) ──
echo ""
REALTIME_STATUS=$(docker inspect -f '{{.State.Status}}' realtime-datalayer 2>/dev/null || echo "none")
if [ "$REALTIME_STATUS" = "running" ]; then
  log "realtime_datalayer: Running → OK (no tocar)"
else
  log "WARN: realtime_datalayer no running (status=$REALTIME_STATUS)"
  log "  ⚠ Considera aixecar-lo separadament si cal data quality per LIVE."
fi

# ── 3) Apply override → recreate trading_service ONLY ──
echo ""
log "Aplicant override LIVE + recreant trading_service..."
if ! docker compose "${COMPOSE_FILES[@]}" up -d --force-recreate trading_service; then
  debug_hints
  die "docker compose fallat." 2
fi

# ── 4) Wait health (amb timeout explícit i hints si falla) ──
echo ""
if ! wait_health "$BASE_URL" 25; then
  log "WARN: /health no respon en 25s"
  debug_hints
  die "trading_service no ha arrancat correctament (health timeout)." 3
fi

# ── 5) Verificació: preflight → live_enabled + mode ──
PREFLIGHT_URL="${BASE_URL}/trade/api/v1/broker/preflight?venue=ostium&symbol=EURUSD"
log "Verificant preflight: $PREFLIGHT_URL"
PREFLIGHT_RESP=$(curl -sf --max-time 5 "$PREFLIGHT_URL" 2>/dev/null || echo "")

if [ -z "$PREFLIGHT_RESP" ]; then
  log "WARN: preflight no respon"
  debug_hints
  die "Preflight sense resposta. Verifica manualment: curl '$PREFLIGHT_URL' | python3 -m json.tool" 3
fi

MODE_VAL=$(json_field "$PREFLIGHT_RESP" "mode")
LIVE_ENABLED=$(json_field "$PREFLIGHT_RESP" "live_enabled")
log "Preflight → mode=$MODE_VAL live_enabled=$LIVE_ENABLED"

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
  echo ""
  echo "  Rollback: ./scripts/live_off.sh"
  exit 0
else
  echo ""
  echo "✗ Mode NO confirmat: mode=$MODE_VAL live_enabled=$LIVE_ENABLED (esperat mode=live live_enabled=True)"
  debug_hints
  echo ""
  echo "  Rollback segur: ./scripts/live_off.sh"
  exit 3
fi

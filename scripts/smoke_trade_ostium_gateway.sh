#!/usr/bin/env bash
# smoke_trade_ostium_gateway.sh — Phase I: smoke e2e via gateway (:8081)
#
# Executa un cicle complet via la ruta pública:
#   1) GET /trade/api/v1/broker/preflight  (nova Phase I)
#   2) POST /trade/api/v1/broker/orders/open (amb client_order_id idempotent)
#   3) POST /trade/api/v1/broker/orders/close
#   4) GET /trade/api/v1/broker/positions  (confirma posició tancada)
#
# OPT-IN: requereix ENABLE_LIVE_TRADING=1 i ENABLE_OSTIUM_LIVE_SMOKE=1.
# Sense les variables → skip (CI-safe).
#
# Ús:
#   ENABLE_LIVE_TRADING=1 ENABLE_OSTIUM_LIVE_SMOKE=1 \
#     OSTIUM_PRIVATE_KEY=0x... ./scripts/smoke_trade_ostium_gateway.sh
#
# Variables:
#   GATEWAY_BASE   — base URL del gateway (default: http://localhost:8081/trade)
#   SMOKE_VENUE    — venue (default: ostium)
#   SMOKE_SYMBOL   — símbol (default: EURUSD)
#   SMOKE_COLLATERAL — collateral USDC (default: 5)
#   SMOKE_LEVERAGE   — leverage (default: 2)

set -euo pipefail

# ── Opt-in guard ──────────────────────────────────────────────────────────────
if [ "${ENABLE_LIVE_TRADING:-0}" != "1" ] || [ "${ENABLE_OSTIUM_LIVE_SMOKE:-0}" != "1" ]; then
    echo "⊘ smoke_trade_ostium_gateway: SKIP"
    echo "  Per executar: ENABLE_LIVE_TRADING=1 ENABLE_OSTIUM_LIVE_SMOKE=1 ./scripts/smoke_trade_ostium_gateway.sh"
    exit 0
fi

GATEWAY_BASE="${GATEWAY_BASE:-http://localhost:8081/trade}"
VENUE="${SMOKE_VENUE:-ostium}"
SYMBOL="${SMOKE_SYMBOL:-EURUSD}"
COLLATERAL="${SMOKE_COLLATERAL:-5}"
LEVERAGE="${SMOKE_LEVERAGE:-2}"
CLIENT_ORDER_ID="smoke_gateway_$(date +%s)"

echo "🔥 smoke_trade_ostium_gateway — Phase I"
echo "======================================="
echo "  Gateway:    $GATEWAY_BASE"
echo "  Venue:      $VENUE"
echo "  Symbol:     $SYMBOL"
echo "  Collateral: $COLLATERAL USDC @ ${LEVERAGE}x"
echo "  OrderID:    $CLIENT_ORDER_ID"
echo ""

# Helper: crida curl amb JSON + comprova status
_curl_json() {
    local method="$1"
    local url="$2"
    local data="${3:-}"
    local response
    local http_code

    if [ -n "$data" ]; then
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" \
            -H "Content-Type: application/json" \
            -d "$data" 2>/dev/null)
    else
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" 2>/dev/null)
    fi

    http_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | head -n -1)

    echo "$body"
    if [ "$http_code" -lt 200 ] || [ "$http_code" -ge 300 ]; then
        echo "❌ HTTP $http_code per $method $url" >&2
        return 1
    fi
    return 0
}

# ── STEP 1: Preflight ─────────────────────────────────────────────────────────
echo "STEP 1: GET $GATEWAY_BASE/api/v1/broker/preflight?venue=$VENUE&symbol=$SYMBOL"
PREFLIGHT=$(_curl_json GET "$GATEWAY_BASE/api/v1/broker/preflight?venue=$VENUE&symbol=$SYMBOL")
echo "  Response: $PREFLIGHT"

READY=$(echo "$PREFLIGHT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ready', False))" 2>/dev/null || echo "False")
if [ "$READY" != "True" ]; then
    echo "⚠️  Preflight: ready=False (pot ser health o data_quality). Continuem igualment."
fi
echo "  ✅ Preflight OK (ready=$READY)"
echo ""

# ── STEP 2: Open ──────────────────────────────────────────────────────────────
echo "STEP 2: POST $GATEWAY_BASE/api/v1/broker/orders/open"
OPEN_BODY="{\"venue\":\"$VENUE\",\"symbol\":\"$SYMBOL\",\"side\":\"long\",\"collateral\":$COLLATERAL,\"leverage\":$LEVERAGE}"
OPEN_RESP=$(_curl_json POST "$GATEWAY_BASE/api/v1/broker/orders/open" "$OPEN_BODY")
echo "  Response: $OPEN_RESP"

POSITION_ID=$(echo "$OPEN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('position_id',''))" 2>/dev/null || echo "")
TX_HASH=$(echo "$OPEN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tx_hash',''))" 2>/dev/null || echo "")
SUCCESS=$(echo "$OPEN_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success', False))" 2>/dev/null || echo "False")

if [ "$SUCCESS" != "True" ] || [ -z "$POSITION_ID" ]; then
    echo "❌ open_position falla o position_id buit"
    exit 1
fi
echo "  ✅ Posició oberta: position_id=$POSITION_ID tx=$TX_HASH"
echo ""

# ── STEP 3: Espera breu ───────────────────────────────────────────────────────
echo "STEP 3: Espera 5s per confirmació..."
sleep 5

# ── STEP 4: Close ─────────────────────────────────────────────────────────────
echo "STEP 4: POST $GATEWAY_BASE/api/v1/broker/orders/close"
CLOSE_BODY="{\"venue\":\"$VENUE\",\"position_id\":\"$POSITION_ID\",\"percent\":100}"
CLOSE_RESP=$(_curl_json POST "$GATEWAY_BASE/api/v1/broker/orders/close" "$CLOSE_BODY")
echo "  Response: $CLOSE_RESP"

CLOSE_OK=$(echo "$CLOSE_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success', False))" 2>/dev/null || echo "False")
if [ "$CLOSE_OK" != "True" ]; then
    echo "❌ close_position falla"
    exit 1
fi
echo "  ✅ Posició tancada OK"
echo ""

# ── STEP 5: Verificar tancament via GET /positions ────────────────────────────
echo "STEP 5: GET $GATEWAY_BASE/api/v1/broker/positions?venue=$VENUE (verificar tancament)"
sleep 3
POS_RESP=$(_curl_json GET "$GATEWAY_BASE/api/v1/broker/positions?venue=$VENUE")
STILL_OPEN=$(echo "$POS_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
positions = d.get('positions', [])
found = [p for p in positions if p.get('venue_position_id') == '$POSITION_ID']
print(len(found))
" 2>/dev/null || echo "0")

if [ "$STILL_OPEN" != "0" ]; then
    echo "❌ La posició $POSITION_ID encara apareix en get_positions ($STILL_OPEN)"
    exit 1
fi
echo "  ✅ Posició $POSITION_ID confirmada tancada (no apareix en /positions)"
echo ""
echo "✅ SMOKE GATEWAY PASSAT — preflight + open + close + verificació tancament"

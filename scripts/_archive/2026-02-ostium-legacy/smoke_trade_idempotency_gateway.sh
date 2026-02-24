#!/usr/bin/env bash
# smoke_trade_idempotency_gateway.sh — Phase J: smoke idempotència via gateway (:8081)
#
# Verifica que enviar el mateix client_order_id dues vegades retorna el mateix
# position_id (idempotència end-to-end via HTTP → TradingCore → OstiumExecutionAdapter).
#
# Flux:
#   1) POST /trade/api/v1/broker/orders/open  (client_order_id=smoke_idem_XXX)
#   2) POST /trade/api/v1/broker/orders/open  (same client_order_id)
#   3) Assert position_id(1) == position_id(2)
#   4) POST /trade/api/v1/broker/orders/close (tanca la posició)
#
# OPT-IN: requereix ENABLE_LIVE_TRADING=1 i ENABLE_OSTIUM_LIVE_SMOKE=1.
# Sense les variables → skip (CI-safe).
#
# Ús:
#   ENABLE_LIVE_TRADING=1 ENABLE_OSTIUM_LIVE_SMOKE=1 \
#     OSTIUM_PRIVATE_KEY=0x... ./scripts/smoke_trade_idempotency_gateway.sh
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
    echo "⊘ smoke_trade_idempotency_gateway: SKIP"
    echo "  Per executar: ENABLE_LIVE_TRADING=1 ENABLE_OSTIUM_LIVE_SMOKE=1 ./scripts/smoke_trade_idempotency_gateway.sh"
    exit 0
fi

GATEWAY_BASE="${GATEWAY_BASE:-http://localhost:8081/trade}"
VENUE="${SMOKE_VENUE:-ostium}"
SYMBOL="${SMOKE_SYMBOL:-EURUSD}"
COLLATERAL="${SMOKE_COLLATERAL:-5}"
LEVERAGE="${SMOKE_LEVERAGE:-2}"
CLIENT_ORDER_ID="smoke_idem_$(date +%s)"

echo "🔁 smoke_trade_idempotency_gateway — Phase J"
echo "============================================="
echo "  Gateway:        $GATEWAY_BASE"
echo "  Venue:          $VENUE"
echo "  Symbol:         $SYMBOL"
echo "  Collateral:     $COLLATERAL USDC @ ${LEVERAGE}x"
echo "  ClientOrderID:  $CLIENT_ORDER_ID"
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

# ── STEP 1: Primera crida open ────────────────────────────────────────────────
echo "STEP 1: POST orders/open (primera crida)"
OPEN_BODY="{\"venue\":\"$VENUE\",\"symbol\":\"$SYMBOL\",\"side\":\"long\",\"collateral\":$COLLATERAL,\"leverage\":$LEVERAGE,\"client_order_id\":\"$CLIENT_ORDER_ID\"}"
OPEN_RESP_1=$(_curl_json POST "$GATEWAY_BASE/api/v1/broker/orders/open" "$OPEN_BODY")
echo "  Response: $OPEN_RESP_1"

PID_1=$(echo "$OPEN_RESP_1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('position_id',''))" 2>/dev/null || echo "")
SUCCESS_1=$(echo "$OPEN_RESP_1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success', False))" 2>/dev/null || echo "False")

if [ "$SUCCESS_1" != "True" ] || [ -z "$PID_1" ]; then
    echo "❌ Primera crida open falla o position_id buit"
    exit 1
fi
echo "  ✅ Posició oberta: position_id=$PID_1"
echo ""

# ── STEP 2: Espera breu ───────────────────────────────────────────────────────
echo "STEP 2: Espera 3s..."
sleep 3

# ── STEP 3: Segona crida open amb SAME client_order_id ───────────────────────
echo "STEP 3: POST orders/open (MATEIXA crida — idempotència)"
OPEN_RESP_2=$(_curl_json POST "$GATEWAY_BASE/api/v1/broker/orders/open" "$OPEN_BODY")
echo "  Response: $OPEN_RESP_2"

PID_2=$(echo "$OPEN_RESP_2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('position_id',''))" 2>/dev/null || echo "")
SUCCESS_2=$(echo "$OPEN_RESP_2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success', False))" 2>/dev/null || echo "False")

if [ "$SUCCESS_2" != "True" ] || [ -z "$PID_2" ]; then
    echo "❌ Segona crida open falla"
    exit 1
fi

if [ "$PID_1" != "$PID_2" ]; then
    echo "❌ IDEMPOTÈNCIA VIOLADA: position_id canvia entre crides!"
    echo "   Primera:  $PID_1"
    echo "   Segona:   $PID_2"
    exit 1
fi
echo "  ✅ Idempotència OK: position_id=$PID_2 (igual que primera crida)"
echo ""

# ── STEP 4: Tancar posició ────────────────────────────────────────────────────
echo "STEP 4: POST orders/close (tanca posició $PID_1)"
sleep 3
CLOSE_BODY="{\"venue\":\"$VENUE\",\"position_id\":\"$PID_1\",\"percent\":100}"
CLOSE_RESP=$(_curl_json POST "$GATEWAY_BASE/api/v1/broker/orders/close" "$CLOSE_BODY")
echo "  Response: $CLOSE_RESP"

CLOSE_OK=$(echo "$CLOSE_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success', False))" 2>/dev/null || echo "False")
if [ "$CLOSE_OK" != "True" ]; then
    echo "❌ close_position falla"
    exit 1
fi
echo "  ✅ Posició tancada OK"
echo ""

echo "✅ SMOKE IDEMPOTÈNCIA PASSAT — 2× open same client_order_id → same position_id + close OK"

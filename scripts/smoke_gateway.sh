#!/usr/bin/env bash
# smoke_gateway.sh — Phase D: smoke tests del gateway single-port (:8081)
#
# Comprova que el proxy nginx routeja correctament tots els prefixos:
#   /nginx-health  → proxy OK
#   /realtime/*    → realtime_datalayer
#   /data/*        → historical_datalayer
#   /trade/*       → trading_service
#   /backtests/*   → trading_service (alias)
#
# Ús:
#   ./scripts/smoke_gateway.sh [HOST] [PORT]
#   ./scripts/smoke_gateway.sh           # per defecte localhost:8081
#   ./scripts/smoke_gateway.sh 10.0.0.1 8081
#
# Requereix: els serveis en marxa via docker-compose.split.yml

set -euo pipefail

HOST="${1:-localhost}"
PORT="${2:-8081}"
BASE="http://${HOST}:${PORT}"

PASS=0
FAIL=0

_check() {
    local label="$1"
    local url="$2"
    local expected_status="${3:-200}"
    local http_status
    http_status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
    if [[ "$http_status" == "$expected_status" ]]; then
        echo "  ✓ ${label} → HTTP ${http_status}"
        PASS=$((PASS + 1))
    else
        echo "  ✗ ${label} → HTTP ${http_status} (esperat ${expected_status})"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Smoke Gateway ${BASE} ==="
echo ""

echo "-- Proxy nginx --"
_check "nginx-health"           "${BASE}/nginx-health"

echo ""
echo "-- Realtime DataLayer (/realtime/*) --"
_check "realtime /health"       "${BASE}/realtime/health"
_check "realtime /status"       "${BASE}/realtime/status"

echo ""
echo "-- Historical DataLayer (/data/*) --"
_check "data /health"           "${BASE}/data/health"
_check "data /status"           "${BASE}/data/status"

echo ""
echo "-- Trading Service (/trade/*) --"
_check "trade /health"          "${BASE}/trade/api/v1/broker/health"
_check "trade /data_status"     "${BASE}/trade/api/v1/broker/data_status"

echo ""
echo "-- Backtests alias (/backtests/*) --"
# GET /backtests/runs llista les runs existents (pot ser llista buida, és 200)
_check "backtests /runs"        "${BASE}/backtests/runs"

echo ""
if [[ $FAIL -eq 0 ]]; then
    echo "✓ Smoke OK (${PASS} checks passed)"
    exit 0
else
    echo "✗ ${FAIL} check(s) fallats (${PASS} ok)"
    exit 1
fi

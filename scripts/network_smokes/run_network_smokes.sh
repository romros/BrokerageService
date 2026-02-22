#!/usr/bin/env bash
# run_network_smokes.sh — Orquestrador de network smokes (opt-in, NO CI)
#
# Executa els dos nivells de smoke:
#   1. smoke_connectivity.py  — Connectivity & Config (0 transaccions)
#   2. smoke_gateway_readonly.py — Gateway read-only via BASE_URL
#
# Ús:
#   ./scripts/network_smokes/run_network_smokes.sh [--only-connectivity] [--only-gateway]
#
# Variables d'entorn:
#   BASE_URL          Base del gateway (default: http://localhost:8081)
#   SMOKE_TIMEOUT     Timeout per check en segons (default: 5)
#
# Exit codes:
#   0 — tot PASS
#   1 — algun FAIL
#
# IMPORTANT: Opt-in. NO integrar a CI ni a suites 0-network.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ONLY_CONNECTIVITY=0
ONLY_GATEWAY=0

for arg in "$@"; do
    case "$arg" in
        --only-connectivity) ONLY_CONNECTIVITY=1 ;;
        --only-gateway)      ONLY_GATEWAY=1 ;;
        --help|-h)
            echo "Ús: $0 [--only-connectivity] [--only-gateway]"
            echo ""
            echo "  --only-connectivity  Executa només smoke_connectivity.py"
            echo "  --only-gateway       Executa només smoke_gateway_readonly.py"
            echo ""
            echo "Variables d'entorn:"
            echo "  BASE_URL=http://localhost:8081   (default)"
            echo "  SMOKE_TIMEOUT=5                  (default, en segons)"
            exit 0
            ;;
    esac
done

PASS_TOTAL=0
FAIL_TOTAL=0
EXIT_CODE=0

_run_smoke() {
    local label="$1"
    local script="$2"
    echo ""
    echo "══════════════════════════════════════════════════"
    echo "  ${label}"
    echo "══════════════════════════════════════════════════"
    if python3 "${SCRIPT_DIR}/${script}"; then
        PASS_TOTAL=$((PASS_TOTAL + 1))
    else
        FAIL_TOTAL=$((FAIL_TOTAL + 1))
        EXIT_CODE=1
    fi
}

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Network Smokes — BrokerageService             ║"
echo "║   Opt-in / Read-only / No CI                    ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "  BASE_URL     : ${BASE_URL:-http://localhost:8081}"
echo "  SMOKE_TIMEOUT: ${SMOKE_TIMEOUT:-5}s"
echo "  Data/hora    : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

if [[ $ONLY_GATEWAY -eq 0 ]]; then
    _run_smoke "Smoke 1: Connectivity & Config" "smoke_connectivity.py"
fi

if [[ $ONLY_CONNECTIVITY -eq 0 ]]; then
    _run_smoke "Smoke 2: Gateway Read-only" "smoke_gateway_readonly.py"
fi

echo ""
echo "══════════════════════════════════════════════════"
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "  ✓ Tots els smokes PASS"
else
    echo "  ✗ ${FAIL_TOTAL} smoke(s) FAIL — revisa el report anterior"
fi
echo "══════════════════════════════════════════════════"
echo ""

exit $EXIT_CODE

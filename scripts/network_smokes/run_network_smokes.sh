#!/usr/bin/env bash
# run_network_smokes.sh — Orquestrador de network smokes (opt-in, NO CI)
#
# Executa els nivells de smoke:
#   1. smoke_connectivity.py          — Connectivity & Config (0 transaccions)
#   2. smoke_gateway_readonly.py      — Gateway read-only via BASE_URL
#   3. smoke_ostium_readonly.py       — Ostium RPC + subgraph read-only (opt-in)
#   4. smoke_ostium_preflight_call.py — Ostium eth_call → getOpenTrade (view, 0 TX)
#
# Ús:
#   ./scripts/network_smokes/run_network_smokes.sh [FLAGS]
#
# Flags:
#   --only-connectivity       Executa només smoke_connectivity.py
#   --only-gateway            Executa només smoke_gateway_readonly.py
#   --only-ostium             Executa només smoke_ostium_readonly.py
#   --only-ostium-preflight   Executa només smoke_ostium_preflight_call.py
#   --require-subgraph        Passat a smoke_ostium_readonly: subgraph FAIL → exit 1
#
# Variables d'entorn:
#   BASE_URL                  Base del gateway (default: http://localhost:8081)
#   SMOKE_TIMEOUT             Timeout per check en segons (default: 5)
#   OSTIUM_RPC_URL            RPC Arbitrum (requerit per smokes Ostium)
#   OSTIUM_CHAIN_ID           Chain ID esperat (recomanat; 421614=testnet, 42161=mainnet)
#   OSTIUM_SUBGRAPH_URL       URL subgraph (opcional; absent → SKIP subgraph probe)
#   OSTIUM_CONTRACT_ADDRESS   Adreça contract trading (optional; default testnet)
#   OSTIUM_WALLET_ADDRESS     Adreça wallet (opcional; absent → 0x0 dummy)
#   OSTIUM_MARKET_SYMBOL      Símbol a usar per preflight (default: EURUSD)
#
# Exit codes:
#   0 — tot PASS (INFO no és FAIL)
#   1 — algun FAIL
#
# IMPORTANT: Opt-in. NO integrar a CI ni a suites 0-network.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ONLY_CONNECTIVITY=0
ONLY_GATEWAY=0
ONLY_OSTIUM=0
ONLY_OSTIUM_PREFLIGHT=0
REQUIRE_SUBGRAPH=""

for arg in "$@"; do
    case "$arg" in
        --only-connectivity)     ONLY_CONNECTIVITY=1 ;;
        --only-gateway)          ONLY_GATEWAY=1 ;;
        --only-ostium)           ONLY_OSTIUM=1 ;;
        --only-ostium-preflight) ONLY_OSTIUM_PREFLIGHT=1 ;;
        --require-subgraph)      REQUIRE_SUBGRAPH="--require-subgraph" ;;
        --help|-h)
            echo "Ús: $0 [--only-connectivity] [--only-gateway] [--only-ostium] [--only-ostium-preflight] [--require-subgraph]"
            echo ""
            echo "  --only-connectivity      Executa només smoke_connectivity.py"
            echo "  --only-gateway           Executa només smoke_gateway_readonly.py"
            echo "  --only-ostium            Executa només smoke_ostium_readonly.py"
            echo "  --only-ostium-preflight  Executa només smoke_ostium_preflight_call.py"
            echo "  --require-subgraph       Subgraph no-OK → FAIL (default: INFO)"
            echo ""
            echo "Variables d'entorn:"
            echo "  BASE_URL=http://localhost:8081             (default)"
            echo "  SMOKE_TIMEOUT=5                            (default, en segons)"
            echo "  OSTIUM_RPC_URL=https://...                 (requerit per smokes Ostium)"
            echo "  OSTIUM_CHAIN_ID=421614                     (recomanat; 42161=mainnet)"
            echo "  OSTIUM_SUBGRAPH_URL=https://...            (opcional)"
            echo "  OSTIUM_CONTRACT_ADDRESS=0x...              (opcional; default testnet)"
            echo "  OSTIUM_WALLET_ADDRESS=0x...                (opcional; default 0x0 dummy)"
            echo "  OSTIUM_MARKET_SYMBOL=EURUSD                (opcional; default EURUSD)"
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
    shift 2
    echo ""
    echo "══════════════════════════════════════════════════"
    echo "  ${label}"
    echo "══════════════════════════════════════════════════"
    if python3 "${SCRIPT_DIR}/${script}" "$@"; then
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

# Mode --only-ostium: executa NOMÉS el smoke Ostium read-only
if [[ $ONLY_OSTIUM -eq 1 ]]; then
    _run_smoke "Smoke: Ostium read-only" "smoke_ostium_readonly.py" ${REQUIRE_SUBGRAPH}
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
fi

# Mode --only-ostium-preflight: executa NOMÉS el smoke eth_call preflight
if [[ $ONLY_OSTIUM_PREFLIGHT -eq 1 ]]; then
    _run_smoke "Smoke: Ostium eth_call preflight (0 TX)" "smoke_ostium_preflight_call.py"
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
fi

# Mode normal: connectivity + gateway (+ ostium si no hi ha --only-*)
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

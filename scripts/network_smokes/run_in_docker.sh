#!/usr/bin/env bash
# run_in_docker.sh — Executa run_network_smokes.sh dins el contenidor brokerage.
#
# Ús: ./scripts/network_smokes/run_in_docker.sh [FLAGS del runner]
# Exemple: ./scripts/network_smokes/run_in_docker.sh --only-ostium
#
# Les env vars del host es passen al contenidor (BASE_URL, OSTIUM_*, etc.).
# No s'imprimeixen secrets.
#
# Exemples d'ús (des de l'arrel del repo):
#   1) Gateway read-only contra host real:
#      BASE_URL=http://host.docker.internal:8081 ./scripts/network_smokes/run_in_docker.sh --only-gateway
#   2) Ostium read-only:
#      OSTIUM_RPC_URL=https://... OSTIUM_CHAIN_ID=421614 ./scripts/network_smokes/run_in_docker.sh --only-ostium
#   3) Trade-cycle testnet:
#      OSTIUM_ENABLE_TX=1 OSTIUM_NETWORK=testnet OSTIUM_PRIVATE_KEY=0x... OSTIUM_MAX_COLLATERAL_USDC=1 OSTIUM_COLLATERAL_USDC=0.5 OSTIUM_LEVERAGE=5 ./scripts/network_smokes/run_in_docker.sh --only-ostium-trade-cycle

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if ! command -v docker &>/dev/null; then
    echo "Error: docker no trobat. Instal·la Docker." >&2
    exit 1
fi

cd "$ROOT_DIR"
if ! docker compose config -q 2>/dev/null; then
    echo "Error: docker compose config ha fallat o no hi ha compose vàlid." >&2
    exit 1
fi

if ! docker compose config --services 2>/dev/null | grep -qx brokerage; then
    echo "Error: servei 'brokerage' no definit al compose." >&2
    exit 1
fi

# Passa envs al contenidor sense imprimir valors
ENV_OPTS=()
for var in \
    BASE_URL \
    SMOKE_TIMEOUT \
    OSTIUM_RPC_URL \
    OSTIUM_CHAIN_ID \
    OSTIUM_SUBGRAPH_URL \
    OSTIUM_CONTRACT_ADDRESS \
    OSTIUM_WALLET_ADDRESS \
    OSTIUM_FROM_ADDRESS \
    OSTIUM_MARKET_SYMBOL \
    OSTIUM_ENABLE_TX \
    OSTIUM_NETWORK \
    OSTIUM_PRIVATE_KEY \
    OSTIUM_MAX_COLLATERAL_USDC \
    OSTIUM_COLLATERAL_USDC \
    OSTIUM_LEVERAGE \
    OSTIUM_CLOSE_PRICE_MODE \
    OSTIUM_POST_OPEN_SLEEP_S \
; do
    ENV_OPTS+=( -e "$var" )
done

exec docker compose run --rm "${ENV_OPTS[@]}" brokerage /app/scripts/network_smokes/run_network_smokes.sh "$@"

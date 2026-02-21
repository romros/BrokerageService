#!/usr/bin/env bash
# smoke_ostium_exec.sh — Phase G: smoke test OstiumExecutionAdapter (live testnet)
#
# Executa un cicle complet open → close en Ostium testnet (Arbitrum Sepolia).
# Requereix fons testnet USDC i ETH.
#
# OPT-IN: només s'executa si ENABLE_OSTIUM_LIVE_SMOKE=1
# Sense la variable → surt sense error (skip), adequat per CI.
#
# Ús:
#   ENABLE_OSTIUM_LIVE_SMOKE=1 ./scripts/smoke_ostium_exec.sh
#   ENABLE_OSTIUM_LIVE_SMOKE=1 OSTIUM_NETWORK=testnet ./scripts/smoke_ostium_exec.sh
#
# Variables requerides (si ENABLE_OSTIUM_LIVE_SMOKE=1):
#   OSTIUM_PRIVATE_KEY  — clau privada wallet (0x...)
#   OSTIUM_NETWORK      — "testnet" (default) | "mainnet"
#
# Variables opcionals:
#   OSTIUM_RPC_URL      — RPC URL override
#   SMOKE_SYMBOL        — símbol a fer servir (default: EURUSD)
#   SMOKE_COLLATERAL    — collateral USDC (default: 5.0)
#   SMOKE_LEVERAGE      — leverage (default: 2)

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

# ── Opt-in guard ──────────────────────────────────────────────────────────────
if [ "${ENABLE_OSTIUM_LIVE_SMOKE:-0}" != "1" ]; then
    echo "⊘ smoke_ostium_exec: SKIP (ENABLE_OSTIUM_LIVE_SMOKE != 1)"
    echo "  Per executar: ENABLE_OSTIUM_LIVE_SMOKE=1 ./scripts/smoke_ostium_exec.sh"
    exit 0
fi

echo "🔥 smoke_ostium_exec — Phase G (live testnet)"
echo "================================================"

# ── Checks previs ─────────────────────────────────────────────────────────────
if [ -z "${OSTIUM_PRIVATE_KEY:-}" ]; then
    if [ -f .env ]; then
        # Intentar llegir del .env
        OSTIUM_PRIVATE_KEY=$(grep -E '^OSTIUM_PRIVATE_KEY=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
        # Fallback: PRIVATE_KEY (com al lab)
        if [ -z "${OSTIUM_PRIVATE_KEY:-}" ]; then
            OSTIUM_PRIVATE_KEY=$(grep -E '^PRIVATE_KEY=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
            if [ -n "${OSTIUM_PRIVATE_KEY:-}" ]; then
                echo "  ℹ️  Usant PRIVATE_KEY del .env com a OSTIUM_PRIVATE_KEY"
                export OSTIUM_PRIVATE_KEY
            fi
        fi
    fi
fi

if [ -z "${OSTIUM_PRIVATE_KEY:-}" ]; then
    echo "❌ ERROR: OSTIUM_PRIVATE_KEY no configurat"
    echo "   Afegeix OSTIUM_PRIVATE_KEY=0x... al .env o a l'entorn"
    exit 1
fi

NETWORK="${OSTIUM_NETWORK:-testnet}"
SYMBOL="${SMOKE_SYMBOL:-EURUSD}"
COLLATERAL="${SMOKE_COLLATERAL:-5.0}"
LEVERAGE="${SMOKE_LEVERAGE:-2}"

echo "  Network:    $NETWORK"
echo "  Symbol:     $SYMBOL"
echo "  Collateral: $COLLATERAL USDC @ ${LEVERAGE}x"
echo ""

# ── Script Python inline ──────────────────────────────────────────────────────
ENV_ARGS=""
if [ -f .env ]; then
    ENV_ARGS="--env-file .env"
fi

docker run --rm \
    -v "$(pwd):/app" \
    -w /app \
    $ENV_ARGS \
    -e OSTIUM_PRIVATE_KEY="${OSTIUM_PRIVATE_KEY}" \
    -e OSTIUM_NETWORK="${NETWORK}" \
    ${OSTIUM_RPC_URL:+-e OSTIUM_RPC_URL="${OSTIUM_RPC_URL}"} \
    python:3.11-slim \
    bash -c "
        echo '📦 Instal·lant dependencies...'
        pip install --quiet -r requirements.txt 2>&1 | tail -1

        echo '🧪 Executant smoke test...'
        export PYTHONPATH=/app:\$PYTHONPATH
        python3 - <<'PYEOF'
import asyncio
import sys
import os

sys.path.insert(0, '/app')

from infrastructure.venues.ostium.ostium_execution_adapter import OstiumExecutionAdapter

SYMBOL = '${SYMBOL}'
COLLATERAL = float('${COLLATERAL}')
LEVERAGE = float('${LEVERAGE}')

async def main():
    print()
    print('STEP 1: Inicialitzar adapter...')
    adapter = OstiumExecutionAdapter()
    await adapter.start()
    if adapter._client is None:
        print('❌ Client no inicialitzat (OSTIUM_PRIVATE_KEY no configurat?)')
        sys.exit(1)
    print('   ✅ Adapter inicialitzat')

    print()
    print('STEP 2: Health check...')
    healthy = await adapter.health_check()
    if not healthy:
        print('⚠️  Health check falla (pot ser connexió o preu API)')
        # No sortim: continuem per si és un problema puntual
    else:
        print('   ✅ Health OK')

    print()
    print(f'STEP 3: Obrir posició {SYMBOL} LONG {COLLATERAL} USDC @ {LEVERAGE}x...')
    result = await adapter.open_position(
        symbol=SYMBOL,
        is_long=True,
        collateral=COLLATERAL,
        leverage=LEVERAGE,
    )
    if not result.success:
        print(f'❌ open_position falla: {result.error_message}')
        sys.exit(1)
    position_id = result.position_id
    print(f'   ✅ Posició oberta: {position_id}')
    print(f'   TX: {result.tx_hash}')
    print(f'   Preu executat: {result.executed_price}')

    print()
    print(f'STEP 4: Tancar posició {position_id}...')
    import asyncio as _asyncio
    await _asyncio.sleep(5)  # Espera breu per confirmació bloc

    ok = await adapter.close_position(position_id)
    if not ok:
        print(f'❌ close_position falla per {position_id}')
        sys.exit(1)
    print(f'   ✅ Posició tancada!')

    print()
    print('✅ SMOKE TEST PASSAT — cicle open/close complet en testnet Ostium')

asyncio.run(main())
PYEOF
    "

echo ""
echo "✅ smoke_ostium_exec completat"

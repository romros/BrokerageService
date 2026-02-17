#!/bin/bash
# Script per executar la comparació completa demà
# Requereix: docker compose amb brokerage rebuillt

set -e

RUN_DIR="lab/out/ostium_prices/20260217_080232"

echo ""
echo "════════════════════════════════════════════════════════"
echo "🔬 OSTIUM vs DUKASCOPY — COMPAT ANALYSIS"
echo "════════════════════════════════════════════════════════"
echo ""

# Check if collector finished
if tmux has-session -t ostium_24h 2>/dev/null; then
    echo "⚠️  ATENCIÓ: Collector encara està corrent!"
    echo "   Espera que finalitzi abans d'executar aquest script."
    echo ""
    exit 1
fi

# Check current time (UTC)
CURRENT_HOUR=$(date -u +%H)
if [ $CURRENT_HOUR -lt 12 ]; then
    echo "⏰ ATENCIÓ: Són les $(date -u +%H:%M) UTC"
    echo ""
    echo "⚠️  Dukascopy delay: Recomanat esperar fins 12:00-14:00 UTC"
    echo "   (Les dades de Dukascopy arriben amb ~1-4h de retard)"
    echo ""
    read -p "Vols continuar igualment? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "⏸️  Anàlisi pausada. Torna a executar després de les 12:00 UTC."
        exit 0
    fi
fi

echo "🔧 Reconstruint container amb scripts nous..."
docker compose build brokerage

echo ""
echo "🔬 Executant comparació EURUSD (24h)..."
echo ""

docker exec brokerage-service \
    python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
        --symbol EURUSD \
        --ostium-dir $RUN_DIR \
        --minutes 1440

echo ""
echo "════════════════════════════════════════════════════════"
echo "✅ Comparació completada!"
echo ""
echo "📁 Artifact: lab/out/ostium_compat_EURUSD_1440m.json"
echo ""
echo "🎯 Busca el VERDICT al output anterior:"
echo "   • ✅ PASS → Dukascopy OK per backtest"
echo "   • ⚠️ PARTIAL → Compatible amb precaució"
echo "   • ❌ FAIL → Massa diferències"
echo ""
echo "════════════════════════════════════════════════════════"
echo ""

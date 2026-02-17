#!/bin/bash
# Full Analysis Script — Executar DESPRÉS de 24h captura
# 
# Pas 1 (Demà 08:00-10:00 UTC): Probes qualitat Ostium
# Pas 2 (Demà 12:00+ UTC): Compat vs Dukascopy

RUN_DIR="lab/out/ostium_prices/20260217_080232"

echo "=========================================="
echo "🔬 OSTIUM FULL ANALYSIS"
echo "=========================================="
echo ""

# Check if collection is complete
if tmux has-session -t ostium_24h 2>/dev/null; then
    echo "⚠️  ATENCIÓ: Collector encara està corrent!"
    echo "   Espera que finalitzi abans d'executar aquest script."
    echo "   Check: tmux attach -t ostium_24h"
    exit 1
fi

echo "✅ Collector finalitzat. Començant anàlisi..."
echo ""

# Check candles count
echo "📊 Comptant candles capturades..."
for symbol in EURUSD XAUUSD GBPUSD; do
    if [ -f "$RUN_DIR/${symbol}.jsonl" ]; then
        COUNT=$(wc -l < "$RUN_DIR/${symbol}.jsonl")
        echo "   ${symbol}: $COUNT candles"
        
        if [ $COUNT -lt 1400 ]; then
            echo "      ⚠️  Menys de 1400 candles (esperat ~1440)"
        else
            echo "      ✅ OK"
        fi
    else
        echo "   ${symbol}: ❌ Fitxer no trobat"
    fi
done
echo ""

# PHASE 1: Quality probes
echo "=========================================="
echo "PHASE 1: OSTIUM QUALITY PROBES"
echo "=========================================="
echo ""

for symbol in EURUSD XAUUSD GBPUSD; do
    echo "🔍 Probe $symbol..."
    python3 lab/ostium/scripts/rest_price_probe.py \
        --symbol $symbol \
        --indir $RUN_DIR \
        --check-trading-hours \
        --outfile lab/out/ostium_price_probe_${symbol}.json
    echo ""
done

# PHASE 2: Compat vs Dukascopy
echo "=========================================="
echo "PHASE 2: COMPAT VS DUKASCOPY"
echo "=========================================="
echo ""

# Check current time
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

echo "🔬 Executant compat probes..."
echo ""

# EURUSD (sempre disponible a Dukascopy)
echo "📊 EURUSD vs Dukascopy..."
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
    --symbol EURUSD \
    --ostium-dir $RUN_DIR \
    --minutes 1440
echo ""

# XAUUSD (si disponible)
echo "📊 XAUUSD vs Dukascopy..."
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
    --symbol XAUUSD \
    --ostium-dir $RUN_DIR \
    --minutes 1440 \
    2>&1 | tee /tmp/xauusd_compat.log

if grep -q "Error\|FAIL" /tmp/xauusd_compat.log; then
    echo "⚠️  XAUUSD compat failed (pot ser que Dukascopy no tingui les dades encara)"
fi
echo ""

# Summary
echo "=========================================="
echo "✅ ANÀLISI COMPLETADA"
echo "=========================================="
echo ""
echo "📁 Artifacts generats:"
echo "   Probes:  lab/out/ostium_price_probe_*.json"
echo "   Compat:  lab/out/ostium_compat_*.json"
echo ""
echo "📊 Revisa els verdicts als outputs anteriors:"
echo "   • PASS = Dukascopy compatible per backtest"
echo "   • PARTIAL = Compatible amb precaució"
echo "   • FAIL = Massa diferències"
echo ""

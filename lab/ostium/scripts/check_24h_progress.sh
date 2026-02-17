#!/bin/bash
# Quick check script per veure el progrés de la captura 24h

RUN_DIR="lab/out/ostium_prices/20260217_080232"

echo "=================================="
echo "🔍 OSTIUM 24H COLLECTION PROGRESS"
echo "=================================="
echo ""

# Check if tmux session is running
if tmux has-session -t ostium_24h 2>/dev/null; then
    echo "✅ Collector actiu (tmux session: ostium_24h)"
    echo "   Poll interval: 2 segons per asset (1.5 req/s total)"
    echo "   Timezone: NY time (ET, UTC-5)"
else
    echo "⚠️  Collector no està corrent (sessió tmux no trobada)"
fi
echo ""

# Candles count per symbol
echo "📊 Candles capturades per símbol:"
for symbol in EURUSD XAUUSD GBPUSD; do
    if [ -f "$RUN_DIR/${symbol}.jsonl" ]; then
        CANDLES=$(wc -l < "$RUN_DIR/${symbol}.jsonl")
        echo "   ${symbol}: $CANDLES / ~1440 ($(echo "scale=1; $CANDLES * 100 / 1440" | bc)%)"
    else
        echo "   ${symbol}: 0 (esperant primer minut)"
    fi
done
echo ""

# Show STATUS.md
if [ -f "$RUN_DIR/STATUS.md" ]; then
    echo "📄 STATUS.md:"
    cat "$RUN_DIR/STATUS.md"
else
    echo "⏳ STATUS.md encara no disponible"
fi
echo ""

# Last candles per symbol
echo "📈 Últimes candles:"
for symbol in EURUSD XAUUSD GBPUSD; do
    if [ -f "$RUN_DIR/${symbol}.jsonl" ] && [ -s "$RUN_DIR/${symbol}.jsonl" ]; then
        echo "   ${symbol}:"
        tail -1 "$RUN_DIR/${symbol}.jsonl" | jq -c '.' | sed 's/^/     /'
    fi
done
echo ""

echo "=================================="
echo "Comandes útils:"
echo "  - Veure output real-time:  tmux attach -t ostium_24h"
echo "  - Aturar collector:        tmux kill-session -t ostium_24h"
echo "  - Aquest script:           ./lab/ostium/scripts/check_24h_progress.sh"
echo "  - Probe (després 24h):     python3 lab/ostium/scripts/rest_price_probe.py --symbol EURUSD --indir $RUN_DIR"
echo "=================================="

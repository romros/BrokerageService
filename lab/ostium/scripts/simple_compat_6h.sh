#!/bin/bash
# Simple compatibility check: Ostium (6h) vs expectativa
# Sense dependencies Python pesades

OSTIUM_DIR="lab/out/ostium_prices/20260217_080232"

echo ""
echo "════════════════════════════════════════════════════════"
echo "🔬 OSTIUM 6H — QUALITY CHECK"
echo "════════════════════════════════════════════════════════"
echo ""

for SYMBOL in EURUSD XAUUSD GBPUSD; do
    FILE="$OSTIUM_DIR/${SYMBOL}.jsonl"
    
    if [ ! -f "$FILE" ]; then
        echo "⚠️  $SYMBOL: File not found"
        continue
    fi
    
    echo "📊 $SYMBOL"
    echo "────────────────────────────────────────────────────────"
    
    # Count candles
    COUNT=$(wc -l < "$FILE")
    echo "   Candles: $COUNT"
    
    # First and last timestamp
    FIRST_TS=$(head -1 "$FILE" | jq -r '.ts')
    LAST_TS=$(tail -1 "$FILE" | jq -r '.ts')
    
    FIRST_TIME=$(date -u -d "@$FIRST_TS" "+%Y-%m-%d %H:%M UTC" 2>/dev/null || echo "N/A")
    LAST_TIME=$(date -u -d "@$LAST_TS" "+%Y-%m-%d %H:%M UTC" 2>/dev/null || echo "N/A")
    
    echo "   Inici:   $FIRST_TIME"
    echo "   Fi:      $LAST_TIME"
    
    # Duration
    DURATION_MIN=$(( ($LAST_TS - $FIRST_TS) / 60 ))
    EXPECTED=$(( $DURATION_MIN + 1 ))
    MISSING=$(( $EXPECTED - $COUNT ))
    
    echo "   Duració: $DURATION_MIN min (${DURATION_MIN/60}h)"
    echo "   Expected: $EXPECTED"
    echo "   Missing:  $MISSING"
    
    # Check gaps
    GAPS=$(jq -s '[.[]] | [range(length-1)] | map(.[. as $i | .+1] as $j | .[. | {"prev": .[$i].ts, "next": .[$j].ts, "diff": (.[$j].ts - .[$i].ts)}] | select(.diff != 60)) | length' "$FILE")
    echo "   Gaps:     $GAPS"
    
    # Check zero range
    ZERO_RANGE=$(jq -s '[.[]] | map(select(.h == .l)) | length' "$FILE")
    ZERO_PCT=$(awk "BEGIN {printf \"%.1f\", ($ZERO_RANGE / $COUNT) * 100}")
    echo "   Zero range: $ZERO_RANGE ($ZERO_PCT%)"
    
    # Price range
    MIN_PRICE=$(jq -s '[.[]] | map(.c) | min' "$FILE")
    MAX_PRICE=$(jq -s '[.[]] | map(.c) | max' "$FILE")
    MEAN_PRICE=$(jq -s '[.[]] | map(.c) | add / length' "$FILE")
    
    echo "   Preus:    \$$MIN_PRICE - \$$MAX_PRICE (mean: \$$MEAN_PRICE)"
    
    # Verdict
    echo ""
    if [ $MISSING -le 2 ] && [ $GAPS -eq 0 ] && [ $(echo "$ZERO_PCT < 30" | bc -l) -eq 1 ]; then
        echo "   ✅ QUALITAT EXCEL·LENT"
    elif [ $MISSING -le 5 ] && [ $GAPS -le 2 ]; then
        echo "   ⚠️  QUALITAT ACCEPTABLE"
    else
        echo "   ❌ PROBLEMES DE QUALITAT"
    fi
    
    echo ""
done

echo "════════════════════════════════════════════════════════"
echo "✅ Check completat!"
echo ""
echo "💡 Per comparació amb Dukascopy (després 24h + delay):"
echo "   python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \\"
echo "     --symbol EURUSD \\"
echo "     --ostium-dir $OSTIUM_DIR \\"
echo "     --minutes 1440"
echo ""
echo "════════════════════════════════════════════════════════"
echo ""

# RSI SQ-exact — Spec certificat

## Fórmula

- **gain[i]** = max(close[i] - close[i-1], 0)
- **loss[i]** = max(close[i-1] - close[i], 0)
- **Seed:** SMA dels primers `period` gains i loss
- **Wilder:** avg_new = (avg_prev * (period-1) + current) / period
- **RSI** = 100 - 100/(1 + avgGain/avgLoss); si avgLoss=0 → 100; si avgGain=0 → 50

## Fonts

- RSICalculator.java (SQ decompilat)
- `lab/ostium/output/SQ_RSI_MT4_EXTRACT.md`

## Contracte de comparació (MT4 parity)

- **round_decimals=None:** MT4 usa NormalizeDouble(6), no arrodoneix a 1 decimal.
- Comparació directa `rsi_raw < threshold`.

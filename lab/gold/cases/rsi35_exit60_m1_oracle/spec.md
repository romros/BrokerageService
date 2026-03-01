# rsi35_exit60_m1_oracle — Gold case

## Dataset

- Oracle SQ export: `EURUSD_M1_dukas_M1_UTCMinus05` M1
- Format: CSV (Date,Time,O,H,L,C) sense header

## Indicador

- RSI(14) PRICE_CLOSE [1] < 35
- Implementació: `indicators/rsi_sq_exact.py`

## Execució

- ExitAfterBars=60
- Same-bar reentry permès
- Implementació: `execution/exit_after_bars.py`

## Resultat esperat

- 17 trades al rang 2026-02-01 → 2026-02-03
- `expected_trades.csv` conté els 17 trades validats

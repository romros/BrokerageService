# Gold Suite — Màquina d'estats

## Estats (ordenats)

| # | Estat | Input | Output | Artifact |
|---|-------|-------|--------|----------|
| 0 | **DATA_ORACLE_READY** | Oracle CSV path | df candles, gap_report | oracle_report.json, gap_report.json |
| 1 | **INDICATOR_PARITY_PASS** | df | RSI calculat (rsi_sq_exact) | indicator_report.json |
| 2 | **SIGNAL_PARITY_PASS** | df + RSI | signal_events (ts on RSI[1]<35) | signal_events.csv |
| 3 | **EXECUTION_PARITY_PASS** | df + signal | trades (entry/exit) | trades.csv |
| 4 | **TRADES_PARITY_PASS** | trades vs expected | matched count | parity_report.json |

## Flux

1. Carregar oracle CSV → validar format, row count, gaps
2. Calcular RSI (rsi_sq_exact, PRICE_CLOSE)
3. Generar signal_events (implícit dins simulate_trades)
4. Simular trades (exit 60 bars, same-bar reentry)
5. Comparar trades vs expected_trades.csv

## Fail-fast

Si un estat falla, es para i es retorna el report. No es continua.

## Artifacts path

`lab/gold/artifacts/<case>/<symbol>/<tf>/<range>/`

- oracle_report.json
- gap_report.json
- indicator_report.json
- signal_events.csv
- trades.csv
- parity_report.json
- run.log (opcional)

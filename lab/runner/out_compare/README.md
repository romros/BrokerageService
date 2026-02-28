# out_compare — Comparador SQ-engines vs LAB

## Descripció

`compare_trades.py` normalitza exports de trades de StrategyQuant (MT4, MT5H, MT5N, JForex)
i el `trades.csv` del LAB runner, i genera mètriques de similitud:

- Entry/exit match-rate amb tolerància configurable (±1D per D1, ±4H per H4, etc.)
- PnL total per engine i diferència vs referència
- Breakdown de reasons (tp/sl)
- Artifacts: `report.json` + `report.csv`

## Fitxers

```
out_compare/
  compare_trades.py            # script principal
  simpleexample_out_MT4.csv    # export SQ/MT4
  simpleexample_out_MT5H.csv   # export SQ/MT5 (Historial)
  simpleexample_out_MT5N.csv   # export SQ/MT5 (Netting)
  simpleexample_out_JFOREX.csv # export SQ/JForex
  report.json                  # output (generat)
  report.csv                   # output (generat)
```

## Format SQ exports

- Delimiter: `;`
- Dates: `YYYY.MM.DD HH:MM:SS` en **UTC-5** (Dukascopy `UTCMinus05`)
- Columnes rellevants:
  - `Open time` / `Close time` — timestamps entrada/sortida
  - `Open price` / `Close price` — preus
  - `Profit/Loss` — PnL en $
  - `Close type` — `PT` (take profit) / `SL` (stop loss)

El comparador converteix automàticament les dates a UTC (+5h).

## Format LAB trades.csv

```
entry_ts,entry_price,exit_ts,exit_price,pnl_pct,reason
1352246400,1.28053,...
```
- `entry_ts` / `exit_ts`: epoch UTC
- `pnl_pct`: PnL en % (sense $ — cal equity base per convertir)
- `reason`: `tp`, `sl`, `friday_exit`, `ttl`, `end_of_range`

## Ús

### Comparació SQ engines entre si (sense LAB)

```bash
python3 lab/runner/out_compare/compare_trades.py \
    --inputs-dir lab/runner/out_compare \
    --ref MT4 \
    --tol 1D
```

### Comparació SQ + LAB

```bash
python3 lab/runner/out_compare/compare_trades.py \
    --inputs-dir lab/runner/out_compare \
    --lab-trades lab/out/artifacts/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01/trades.csv \
    --ref MT4 \
    --tol 1D
```

### Args disponibles

| Arg | Default | Descripció |
|---|---|---|
| `--inputs-dir` | `lab/runner/out_compare` | Directori amb exports SQ |
| `--lab-trades` | — | Path al `trades.csv` del LAB (opcional) |
| `--ref` | `MT4` | Engine de referència (`MT4`, `MT5H`, `MT5N`, `JFOREX`, `LAB`) |
| `--tol` | `1D` | Tolerància: `1M`,`5M`,`15M`,`30M`,`1H`,`4H`,`1D`,`2D`,`1W` |
| `--out-dir` | `--inputs-dir` | Directori de sortida dels reports |

## Resultat de referència (T8.10 — EURUSD D1 EMA200+RSI35)

```
ref=MT4  tol=1D

Engine     N   EntryMR%  ExitMR%   PnL($)   PnL(%)   Δ PnL($)  Δ PnL(%)  Med hold
JFOREX    22    100.0%    100.0%   258.88    10.86%     +1.60     +0.07%    389.5h
MT4  ←REF 22    100.0%    100.0%   257.28    10.79%      0.00      0.00%    389.5h
MT5H      22    100.0%    100.0%   257.28    10.79%      0.00      0.00%    389.5h
MT5N      22    100.0%    100.0%   257.28    10.79%      0.00      0.00%    389.5h
LAB       19     31.6%     42.1%      n/a     2.22%       n/a     -8.57%    312.0h
```

### Conclusions

**MT4 = MT5H = MT5N**: 100% match — mateixos timestamps, mateixos preus, PnL idèntic.
MT5N té tickets parells (internament compta ordres oposades), però les posicions netes son idèntiques.

**JForex vs MT4**: 100% match en timestamps. Close price lleugerament diferent (spread JForex
diferent); PnL difereix +$1.60 total. Comportament esperat.

**LAB vs MT4** (31.6% entry match, ±1D):
- LAB: 19 trades vs SQ: 22 trades (−3 trades)
- 6/19 entries LAB coincideixen amb MT4 dins ±1D (els altri 13 entren en dates que MT4 no té,
  o MT4 entra en dates que LAB no pren)
- Net PnL LAB +2.22% vs MT4 +10.79% (en $: MT4 usa lot fix 0.021 EURUSD; LAB usa % sense lot)
- La diferència de match-rate és esperada: ATR rolling vs Wilder canvia SL/TP i pot fer que
  alguns trades entrin o sortin de la finestra de la condició RSI<35

### Per millorar el match-rate LAB↔SQ

1. Alinear ATR: usar ewm Wilder al LAB (alpha=1/period en lloc de rolling mean)
2. Fer indicator parity check (comparar EMA/RSI punt a punt entre Python i MT4)
3. Usar `--tol 2D` per ser menys estricte en la comparació

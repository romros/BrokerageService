# lab/runner — Strategy Backtest LAB

## Propòsit

LAB per validar estratègies (SQ import o manuals) sobre dades canòniques de BrokerageService
(Dukascopy via historical_datalayer) **sense tocar producció**.

> Regla LAB: els artifacts aquí no impliquen "ready for live". Cal graduació explícita.

---

## Estructura

```
lab/runner/
├── README.md               ← aquest fitxer
├── strategies/
│   ├── smoke.yaml          ← SmokeStrategy (sempre LONG, tanca per TTL)
│   ├── smoke.py            ← implementació generate_signals()
│   ├── sq_0423850.yaml     ← Estratègia SQ 0.423850 (Bollinger+ATR)
│   └── sq_0423850.py       ← implementació generate_signals()
├── backtest/
│   └── run_backtest.py     ← runner LAB
└── artifacts/
    └── <strategy>/<symbol>/<tf>/<from>_<to>/
        ├── summary.json    (inclou execution_contract + coverage)
        ├── trades.csv
        └── equity.csv
```

---

## Execution Contract v2 (T8.8)

**Regla canònica — tot el codi ha de seguir exactament aquest contracte:**

| Paràmetre | Valor |
|-----------|-------|
| Senyals | Calculats a barra `i` usant dades `[0..i-1]` (cap lookahead) |
| Entrada | MARKET a `open[i+1]` (barra que obre just després del senyal) |
| SL/TP | Comprovat intra-barra: `low[j] <= SL` o `high[j] >= TP` |
| SL-first | Si SL i TP toquen al mateix bar → SL guanya (conservador) |
| Fill SL/TP | A preu exacte `sl_price` / `tp_price` (MVP, no slippage) |
| TTL | Exit a `open[entry_bar + ttl_bars]` |
| Divendres exit | Exit a `open` de la primera barra en zona no-trade (Div 17h NY) |
| Posicions | `max_open_trades=1`, LONG only (SHORT = NotImplemented) |

**String auditoria (guardat a summary.json `execution_contract`):**
```
v2: signals at bar i using data[0..i-1]; entry at open[i+1]; SL/TP intra-bar (high/low), SL-first if both hit; TTL exit at open[entry+ttl_bars]; friday exit at open of next available bar after Fri 17h NY
```

> Nota: la versió anterior (v1/MVP) usava `close[i]` per entrada i `close` per SL/TP.
> V2 és més realista i evita lookahead.

---

## API d'estratègia

Cada estratègia ha de tenir dos fitxers:

**`<nom>.yaml`** — configuració i metadades:
```yaml
name: nom_estrategia
symbol: XAUUSD          # símbol per defecte
timeframe: 4h
ttl_bars: 0             # 0 = sense TTL (usa SL/TP)
sl_atr_coef: 2.0        # multiplicador ATR per SL (0 = desactivat)
tp_atr_coef: 3.0        # multiplicador ATR per TP (0 = desactivat)
atr_period: 10
no_trade_weekend: true  # divendres 17h NY → diumenge 17h NY
exit_on_friday: true
exit_on_friday_hour_ny: 17
```

**`<nom>.py`** — lògica de senyal:
```python
def generate_signals(df: pd.DataFrame) -> pd.Series:
    """
    Entrada: DataFrame amb index DatetimeIndex UTC, columnes open/high/low/close/volume
    Sortida: pd.Series d'enters: +1 (long), 0 (flat), mateixos índexs
    IMPORTANT: No usar dades de la barra actual (df.iloc[i]) per generar signal[i].
               Usar dades fins df.iloc[i-1] com a màxim.
    """
```

---

## Artifacts

Per cada run es generen 3 fitxers sota:
`artifacts/<strategy>/<symbol>/<tf>/<from>_<to>/`

- **`summary.json`**: rang, symbol, tf, n_trades, net_pnl_pct, max_drawdown_pct,
  win_rate_pct, avg_trade_pct, `execution_contract`, `coverage_from`, `coverage_to`,
  `sync_job_id`, `months_missing_in_range`
- **`trades.csv`**: entry_ts, entry_price, exit_ts, exit_price, pnl_pct,
  reason (ttl|sl|tp|friday_exit|end_of_range)
- **`equity.csv`**: ts, equity (base 100)

---

## Demo run canònic

### SQ_0423850 XAUUSD H4 2016→2026 (run de referència, T8.8)

Des de l'host (gateway :8081):
```bash
cd /mnt/volume-SQ/dev/BrokerageService
python3 lab/runner/backtest/run_backtest.py \
    --strategy sq_0423850 \
    --symbol XAUUSD \
    --tf 4h \
    --from 2016-01-01 \
    --to 2026-01-01 \
    --ensure-sync \
    --base-url http://localhost:8081
```

Des del contenidor (base-url directa, artifacts al volum muntat):
```bash
docker exec historical-datalayer python3 lab/runner/backtest/run_backtest.py \
    --strategy sq_0423850 \
    --symbol XAUUSD \
    --tf 4h \
    --from 2016-01-01 \
    --to 2026-01-01 \
    --ensure-sync \
    --base-url http://datalayer-proxy:8081 \
    --artifacts-dir /app/lab/out/artifacts
```

Artifacts: `lab/runner/artifacts/sq_0423850/XAUUSD/4h/2016-01-01_2026-01-01/`
(o `lab/out/artifacts/...` quan s'usa `--artifacts-dir /app/lab/out/artifacts`)

**Resultat referència T8.8** (Execution Contract v2):
- n_trades=45, net_pnl=14.84%, win_rate=57.78%, max_drawdown=4.42%, avg_trade=0.33%

### SmokeStrategy (pipeline-first, TTL only)

```bash
cd /mnt/volume-SQ/dev/BrokerageService
python3 lab/runner/backtest/run_backtest.py \
    --strategy smoke \
    --symbol EURUSD \
    --tf 1h \
    --from 2020-01-01 \
    --to 2021-01-01 \
    --base-url http://localhost:8081
```

---

## --ensure-sync i coverage fail-fast

El flag `--ensure-sync` fa:
1. `POST /data/sync {symbol, tf=1m, from, to}` → poll fins `DONE`
2. `POST /data/coverage/{symbol}/rebuild` → verifica cobertura
3. **Fail-fast** si `coverage_to < requested_to` o hi ha gaps dins rang

```bash
# Sync explícit (útil si les dades poden ser incompletes)
python3 lab/runner/backtest/run_backtest.py ... --ensure-sync

# Sense sync (dades ja sincronitzades)
python3 lab/runner/backtest/run_backtest.py ...
```

---

## Afegir una nova estratègia SQ

1. Crear `strategies/<nom>.yaml` amb paràmetres
2. Crear `strategies/<nom>.py` amb `generate_signals(df) -> pd.Series`
3. Córrer: `python3 lab/runner/backtest/run_backtest.py --strategy <nom> ...`

No cal tocar `run_backtest.py`.

---

## Notes

- Les dades vénen via `GET /data/ohlcv/{symbol}` (gateway `/data/*` → historical_datalayer)
- Timeframe: el runner agrega 1m → tf sol·licitat (ex. 4h = 240 candles 1m)
- Artifacts a `lab/runner/artifacts/` (organitzats per estratègia/símbol/tf/rang)
- El `summary.json` inclou `execution_contract` per auditoria i reproductibilitat

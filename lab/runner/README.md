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
│   └── run_backtest.py     ← runner LAB (wrapper sobre pipeline existent)
└── artifacts/
    └── <strategy>/<symbol>/<tf>/<from>_<to>/
        ├── summary.json
        ├── trades.csv
        └── equity.csv
```

---

## Execution Contract (MVP)

| Paràmetre | Valor |
|-----------|-------|
| Decisions | A cada candle tancat (On Bar Open, com SQ) |
| Entrada | Preu `close` de la candle del senyal (simulació market a `next_open` simplificada) |
| Sortida | Per TTL (en bars), SL o TP si definits |
| Posicions | Màxim 1 oberta alhora (`max_open_trades=1`) |
| Direcció MVP | LONG only (SHORT = NotImplemented) |

---

## API d'estratègia

Cada estratègia ha de tenir dos fitxers:

**`<nom>.yaml`** — configuració i metadades:
```yaml
name: nom_estrategia
symbol: XAUUSD          # símbol per defecte
timeframe: 1h
ttl_bars: 5             # tanca per TTL si no hi ha SL/TP
sl_atr_coef: 2.0        # multiplicador ATR per SL (0 = desactivat)
tp_atr_coef: 3.0        # multiplicador ATR per TP (0 = desactivat)
atr_period: 10
```

**`<nom>.py`** — lògica de senyal:
```python
def generate_signals(df: pd.DataFrame) -> pd.Series:
    """
    Entrada: DataFrame amb index DatetimeIndex UTC, columnes open/high/low/close/volume
    Sortida: pd.Series d'enters: +1 (long), -1 (short), 0 (flat), mateixos índexs
    """
```

---

## Artifacts

Per cada run es generen 3 fitxers sota:
`artifacts/<strategy>/<symbol>/<tf>/<from>_<to>/`

- **`summary.json`**: rang, symbol, tf, n_trades, net_pnl_pct, max_drawdown_pct, win_rate_pct, avg_trade_pct
- **`trades.csv`**: entry_ts, entry_price, exit_ts, exit_price, pnl_pct, reason (ttl|sl|tp)
- **`equity.csv`**: ts, equity (base 100)

---

## Demo run

### SmokeStrategy (pipeline-first, TTL only)

```bash
cd /mnt/volume-SQ/dev/BrokerageService
python3 lab/runner/backtest/run_backtest.py \
    --strategy smoke \
    --symbol EURUSD \
    --tf 1h \
    --from 2019-01-01 \
    --to 2020-01-01 \
    --base-url http://localhost:8081
```

Output esperat (run real 2020-01-02 → 2020-01-31):
```
CONFIG strategy=smoke symbol=EURUSD tf=1h from=2020-01-02 to=2020-01-31 ttl_bars=3 sl=0.0 tp=0.0
candles_loaded_1m=30213
candles_loaded_1h=504
trades=165
artifacts → lab/runner/artifacts/smoke/EURUSD/1h/2020-01-02_2020-01-31/
  summary.json  (n_trades=165, net_pnl=-1.5639%, win_rate=50.91%, max_dd=1.8334%)
  trades.csv
  equity.csv
OK
```

### Estratègia SQ 0.423850 (Bollinger+ATR, EURUSD pilot)

```bash
./scripts/run_lab_backtest.sh --strategy sq_0423850 --symbol EURUSD \
    --tf 1h --from 2020-01-02 --to 2020-01-31
```

Output real:
```
CONFIG strategy=sq_0423850 symbol=EURUSD tf=1h from=2020-01-02 to=2020-01-31 ttl_bars=0 sl=2.0 tp=3.0
candles_loaded_1m=30213
candles_loaded_1h=504
trades=1
artifacts → lab/runner/artifacts/sq_0423850/EURUSD/1h/2020-01-02_2020-01-31/
  summary.json  (n_trades=1, net_pnl=0.1424%, win_rate=100.0%, max_dd=0.0%)
OK
```

> Nota: SQ 0.423850 és dissenyada per XAUUSD. Per backtests llargs necessites
> descarregar dades: `./scripts/run_historical_backfill.sh --symbol XAUUSD --from 2016-01-01`

---

## Afegir una nova estratègia SQ

1. Crear `strategies/<nom>.yaml` amb paràmetres
2. Crear `strategies/<nom>.py` amb `generate_signals(df) -> pd.Series`
3. Córrer: `python3 lab/runner/backtest/run_backtest.py --strategy <nom> ...`
4. Artifact generat automàticament

No cal tocar `run_backtest.py`.

---

## Prerequisit: dades sincronitzades

Abans de fer un backtest llarg cal tenir el dataset Dukascopy sincronitzat:

```bash
# Comprova i/o llança sync (idempotent)
./scripts/sync_xauusd_full.sh

# Comprova coverage
curl -s http://localhost:8081/data/coverage/XAUUSD | python3 -c \
  "import sys,json; d=json.load(sys.stdin); s=d['summary']; \
   print(f'done={s[\"months_done\"]} rows={s[\"total_rows\"]}')"
```

El sync baixa ~278 mesos (2003→avui) en ~20-25 minuts i és idempotent (re-executar salta mesos ja descarregats).

---

## Notes

- Les dades vénen via `GET /data/ohlcv/{symbol}` (gateway `/data/*` → historical_datalayer)
- Timeframe: el runner agrega 1m → tf sol·licitat (ex. 1h = 60 candles 1m)
- Si el servei no és accessible: `SKIP candles_loaded=0` (no FAIL)
- Artifacts a `lab/runner/artifacts/` (no a `lab/out/` per separar per estratègia)

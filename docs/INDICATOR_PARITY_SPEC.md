# T8.27 — Indicator Parity Spec: EMA / RSI / ATR (MT4/SQ compatible)

**Data:** 2026-02-28  
**Font:** MQL4 docs, comunitat MT4, Welles Wilder RSI/ATR, SQTradingLib (pendent decompilació)

---

## 1. EMA(period) — iMA MODE_EMA

### Fórmula MT4

- **Seed:** SMA(period) dels primers `period` valors (close).
- **Recursiu (i ≥ period):**
  ```
  mult = 2 / (period + 1)
  EMA[i] = close[i] * mult + EMA[i-1] * (1 - mult)
  ```

### Diferència vs pandas

- **pandas** `ewm(span=period, adjust=False).mean()`: seed = **primer close** (no SMA).
- Això provoca divergència creixent si el primer valor és atípic o si hi ha gaps de dades.

### Pseudocodi

```
EMA(close, period):
  if len(close) < period: return NaN array
  ema = zeros(len(close))
  ema[0:period-1] = NaN
  ema[period-1] = sum(close[0:period]) / period   // SMA seed
  mult = 2.0 / (period + 1)
  for i = period to len(close)-1:
    ema[i] = close[i] * mult + ema[i-1] * (1 - mult)
  return ema
```

### Rounding

MT4 presenta 5 decimals (Digits). Per comparació barra-a-barra, usar `round(x, 5)` o 6 decimals.

---

## 2. RSI(period) — iRSI Wilder

### Fórmula MT4 (Wilder)

- **Delta:** `delta[i] = close[i] - close[i-1]`
- **Gain/Loss:** `gain[i] = max(0, delta[i])`, `loss[i] = max(0, -delta[i])` (loss com a valor positiu)
- **First Average:** SMA dels primers `period` gains i losses (indices 1..period inclusiu, donant `period` valors)
  - `avg_gain[period] = sum(gain[1:period+1]) / period`
  - `avg_loss[period] = sum(loss[1:period+1]) / period`
- **Wilder smoothing (i > period):**
  ```
  avg_gain[i] = (avg_gain[i-1] * (period-1) + gain[i]) / period
  avg_loss[i] = (avg_loss[i-1] * (period-1) + loss[i]) / period
  ```
- **RSI:** `RSI[i] = 100 - 100 / (1 + avg_gain[i] / avg_loss[i])`  
  Si `avg_loss == 0`: RSI = 100.

### Barres NaN

- RSI[0..period-1] = NaN (calen almenys `period+1` barres per al primer RSI).
- Primer valor vàlid: index `period`.

### Pseudocodi

```
RSI(close, period):
  n = len(close)
  delta = close.diff()  // delta[0]=NaN
  gain = max(0, delta); loss = max(0, -delta)
  rsi = [NaN] * n
  if n < period+1: return rsi
  avg_g = sum(gain[1:period+1]) / period
  avg_l = sum(loss[1:period+1]) / period
  if avg_l == 0: rsi[period] = 100.0
  else: rsi[period] = 100 - 100/(1 + avg_g/avg_l)
  for i = period+1 to n-1:
    avg_g = (avg_g * (period-1) + gain[i]) / period
    avg_l = (avg_l * (period-1) + loss[i]) / period
    if avg_l == 0: rsi[i] = 100.0
    else: rsi[i] = 100 - 100/(1 + avg_g/avg_l)
  return rsi
```

---

## 3. ATR(period) — iATR Wilder

### Fórmula MT4

- **True Range:**
  ```
  TR[i] = max(high[i] - low[i], |high[i] - close[i-1]|, |low[i] - close[i-1]|)
  ```
  Per i=0, `close[-1]` no existeix → típicament `TR[0] = high[0] - low[0]`.

- **Seed:** SMA dels primers `period` TRs.
  - `ATR[period-1] = sum(TR[0:period]) / period`

- **Wilder smoothing (i ≥ period):**
  ```
  ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period
  ```

### Pseudocodi

```
ATR(high, low, close, period):
  n = len(close)
  prev_close = close.shift(1)
  tr = max(high-low, abs(high-prev_close), abs(low-prev_close))
  tr[0] = high[0] - low[0]  // no prev_close
  atr = [NaN] * n
  if n < period: return atr
  atr[period-1] = sum(tr[0:period]) / period
  for i = period to n-1:
    atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
  return atr
```

---

## 4. SQTradingLib.jar — Decompilat (2026-02-28)

**JAR:** `lab/runner/out_compare/sq_decompiled/internal/libs/SQTradingLib.jar`  
**Codi decompilat:** `lab/runner/out_compare/sq_decompiled/src/sources/`

**Conclusió de la decompilació:**
- SQ **no** implementa EMA/RSI/ATR en Java. Els indicadors MT4 es carreguen dinàmicament:
  - `IndicatorsLoader` → `CustomClassesLoader("Blocks/Indicators")` carrega blocs per engine
  - Per Stock Picking: `TALibIndicators` usa TA-Lib (C library)
  - Per MT4: els blocs són MQL4 compilats / generats; el càlcul es fa al runtime MT4
- `MetaTrader4Simulator` extend `MetaTraderSimulatorHedging`; no conté lògica d’indicadors
- Les fórmules de la secció 1–3 (MQL4: EMA seed SMA, RSI/ATR Wilder) són la referència correcta

---

## 5. Ús al LAB

- `lab/runner/indicators/mt4_like_indicators.py` implementa les fórmules anteriors.
- `export_indicators_csv.py` pot usar `mt4_like_indicators` per produir indicadors compatibles MT4.
- `eurusd_ema200_rsi35_atr_d1.py` i `run_backtest.py` poden canviar a aquestes funcions per millorar entry_match_rate vs MT4.

---

## 6. Validació

- `compare_indicators.py`: LAB (mt4_like) vs MT4 CSV → max diff < 1 pip (EMA/ATR), < 0.1 (RSI).
- `compare_trades.py`: entry_match_rate esperat > 70% (actual ~50% amb pandas ewm).
- T8.30: exploració contracte senyal/entrada (`--entry-fill open_i|open_i1`, `--signal-contract`) via `scripts/oneshot/run_t830_contract_grid.sh`.

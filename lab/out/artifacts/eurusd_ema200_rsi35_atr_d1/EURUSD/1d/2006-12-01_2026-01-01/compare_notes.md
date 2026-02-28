# Comparació SQ vs LAB — eurusd_ema200_rsi35_atr_d1

## Estratègia
- Instrument: EURUSD D1 LONG-only
- Entry: Close[1] > EMA(200)[1] AND RSI(14)[1] < 35
- SL = 2 x ATR(14), TP = 3 x ATR(14)
- Filtres: weekends Fri 17:00-Sun 17:00 NY; EOD OFF

## KPIs comparats (après alineament T8.11)

| Mètrica          | SQ (MT4/SQX)   | LAB v1 (T8.9)  | LAB v2 (T8.11)  | Delta v2 vs SQ      |
|------------------|----------------|----------------|-----------------|---------------------|
| # Trades         | 22             | 19             | 18              | -4 (-18%)           |
| Net profit       | 57.28        | +2.22%         | +1.96%          | signe OK (positiu)  |
| Win rate         | 54.55%         | 42.11%         | 44.44%          | -10pp               |
| Profit Factor    | 1.75           | 1.19           | 1.08            | menor (ATR Wilder)  |
| Max Drawdown     | 03.74        | 3.65%          | 4.39%           | escala diferent     |
| Entry match-rate | --             | 31.6% (±1D)    | 50.0% (±1D)     | +18pp millorat      |

## Evolució del match-rate (compare_trades.py, ref=MT4, tol=1D)

| Versió   | Canvis actius                         | Entry match-rate |
|----------|---------------------------------------|------------------|
| LAB v1   | ATR rolling, no warmup, offset=0h     | 31.6%            |
| LAB v2   | ATR Wilder, warmup=250, offset=5h UTC | 50.0%            |

## Canvis implementats a T8.11

### 1. ATR Wilder (impacte: principal)
- Anterior: tr.rolling(14).mean() (simple rolling)
- Nou: tr.ewm(alpha=1/14, adjust=False).mean() (Wilder, equivalent MT4 iATR)
- Efecte: nivells SL/TP ara equivalents als de MT4; canvia quines barres toquen RSI<35

### 2. Day boundary offset D1 (impacte: 7-24h per trade)
- Anterior: barres D1 del LAB comencen a 00:00 UTC
- Nou: day_offset_h=5 -> barres D1 comencen a 05:00 UTC (=00:00 UTC-5, MT4 Dukascopy)
- Efecte: entry timestamps del LAB ara alineats a 05:00 UTC (±7h vs MT4)

### 3. Warmup EMA200 (impacte: qualitat indicadors als primers senyals)
- Anterior: no warmup; EMA200 fred als primers 200 bars del rang
- Nou: warmup_bars=250; fetch des de from_date-251 dies; filtra trades del warmup
- Efecte: EMA200 i RSI estabilitzats des del primer senyal real

## Anàlisi trades NO-MATCH (9/18 trades)

Els 9 trades que NO coincideixen amb MT4 (diff > 1D) corresponen a:
- LAB genera senyal quan RSI<35 amb ATR Wilder; MT4 en barra diferent
- Diferències de 3-26 dies -> no es poden explicar per timezone
- Causa probable: valor d'ATR Wilder diferent canvia SL/TP -> quan un trade MT4
  s'atura per SL, el RSI pot baixar a<35 en una barra diferent que al LAB

## Desfasament residual als 9 trades que SÍ coincideixen

Tots 9 trades matched tenen diff de 7h o 24h:
- diff=24h: MT4 entra a 00:00 UTC-5 = 05:00 UTC del dia N; LAB a 05:00 UTC del dia N-1
  -> LAB entra 1 barra D1 ABANS que MT4 (el senyal LAB es genera 1 dia mes aviat)
- diff=7h: MT4 entra a 17:00 UTC-5 = 22:00 UTC dia N; LAB a 05:00 UTC dia N+1
  -> LAB entra a la primera barra D1 despres (22:00 UTC del N = final de la barra del dia N)

Conclusio: el desfasament residual de 7-24h es normal per D1 i es deu a la granularitat
de la barra. No es pot eliminar sense canviar la logica de signaling.

## Mapping SQ vs LAB (contracte i assumptions)

| Aspecte          | SQ/MT4                        | LAB v2 (T8.11)                       |
|------------------|-------------------------------|--------------------------------------|
| Entry timing     | On Bar Open (next bar)        | open[i+1] -- equivalent              |
| Signal lookahead | Indicadors fins barra tancada | data[0..i-1] -- equivalent           |
| EMA              | iMA(MODE_EMA)                 | ewm(span=200, adjust=False)          |
| RSI              | iRSI (Wilder)                 | ewm(alpha=1/14, adjust=False)        |
| ATR              | ATR Wilder (iATR)             | ewm(alpha=1/14, adjust=False) OK v2  |
| SL/TP fill       | Ticks reals intrabar          | high/low conservador (SL-first)      |
| Weekend filter   | Fri 17:00 NY                  | no_trade_weekend=true                |
| EOD close        | OFF                           | exit_on_friday=false                 |
| D1 bar opens     | 00:00 UTC-5 = 05:00 UTC       | 05:00 UTC (day_offset_h=5) OK v2     |
| Warmup           | indicadors sempre calents     | warmup_bars=250 des de YAML OK v2    |

## Accions recomanades (futur)

- Indicator parity check: comparar EMA/RSI/ATR punt a punt entre Python i MT4
  per identificar per quines barres el valor d'ATR divergeix
- Provar tol=2D al compare_trades per mesurar si el desfasament residual 7-24h
  reduiria el recompte de NO-MATCH
- Millora potencial: si alguna barra D1 d'entrada MT4 es a 17:00 UTC-5 (= 22:00 UTC),
  podria ser que el LAB hauria d'entrar a la mateixa barra (no la seguent)
  -> caldria revisar la granularitat del filtre weekend

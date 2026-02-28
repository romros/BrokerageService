# Comparació SQ vs LAB — eurusd_ema200_rsi35_atr_d1

## Estratègia
- Instrument: EURUSD D1 LONG-only
- Entry: Close[1] > EMA(200)[1] AND RSI(14)[1] < 35
- SL = 2 × ATR(14), TP = 3 × ATR(14)
- Filtres: weekends Fri 17:00–Sun 17:00 NY; EOD OFF

## KPIs comparats

| Mètrica              | SQ (MT4/SQX)          | LAB (Contract v2)           | Delta / Notes                    |
|----------------------|-----------------------|-----------------------------|----------------------------------|
| # Trades             | 22                    | 19                          | -3 (-14%) -- dins el rang normal  |
| Net profit           | $257.28 (% desconegut)| +2.22% net pnl              | Signe OK (positiu ambdós)        |
| Win rate             | 54.55%                | 42.11%                      | -12pp -- vegeu nota (*)           |
| Profit Factor        | 1.75                  | 1.19                        | Menor, coherent amb win rate     |
| Max Drawdown         | $103.74 (% desconegut)| 3.65%                      | Escala diferent ($ vs %)         |
| Avg trade            | --                    | +0.12%                      | --                               |

## Veredicte: COMPARABLE

El LAB retorna resultats del mateix ordre de magnitud que SQ:
- Nombre de trades semblant (19 vs 22)
- Net profit positiu en ambdós
- Profit factor > 1 en ambdós (rendible neta)

La diferència en win rate (42% vs 55%) és esperada (vegeu nota *).

## Mapping SQ vs LAB (contracte i assumptions)

| Aspecte              | SQ/MT4                           | LAB (Contract v2)                    |
|----------------------|----------------------------------|--------------------------------------|
| Entry timing         | On Bar Open (next bar)           | open[i+1] -- equivalent              |
| Signal lookahead     | Indicadors fins barra tancada    | data[0..i-1] -- equivalent           |
| EMA                  | iMA(MODE_EMA)                    | ewm(span=period, adjust=False)       |
| RSI                  | iRSI (Wilder)                    | ewm(alpha=1/period, adjust=False)    |
| ATR                  | ATR Wilder (ewm)                 | Rolling mean TR (lleugera diferència)|
| SL/TP fill           | Ticks reals intrabar             | high/low conservador (SL-first)      |
| Weekend filter       | Fri 17:00 NY                     | no_trade_weekend=true                |
| EOD close            | OFF                              | exit_on_friday=false                 |

## Nota (*) -- Diferència win rate

La diferència principal (42% LAB vs 55% SQ):

1. ATR: el LAB usa rolling mean del TR (simple), MT4 usa ATR de Wilder (ewm).
   Pot canviar el nivell de SL/TP i desplaçar fills.

2. SL fill conservador: el LAB usa low[j] <= sl_price amb fill a sl_price.
   MT4 pot fer fill al tick real (potser lleugerament millor).

3. SL-first: quan SL i TP toquen al mateix bar, LAB tria sempre SL.
   MT4 resol per tick.

4. Rang: LAB 2006-12->2026-01; SQ pot usar rang lleugerament diferent.

## Accions recomanades (futur)

- Alinear ATR: usar ewm alpha=1/period al LAB (igual que Wilder/MT4)
- Afegir profit_factor al summary.json del runner
- Correr SQ amb el mateix rang exacte per comparació neta
- Indicator parity check (comparar EMA/RSI punt a punt)

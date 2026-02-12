A continuació tens el **pla complet reescrit** incorporant:

* **TZ canònica = New York (NY close style)** com a convenció de storage
* Històrics en **CSV 1m tancades**, sense gaps, amb backfill periòdic
* **Testing simple amb scripts Python** (sense pytest): unitari + integració + smoke d’endpoints
* **SOLID + DI “tipus Java” però minimalista**, sense palla
* Estructura perquè **cada agent/tasca** pugui començar–acabar i **tancar amb tests** del que ha fet

---

# AGENTS_PLA.md — gTrade BrokerageService (Freqtrade Adapter Ready)

**Data:** 2026-02-08
**Objectiu:** BrokerageService extensible (gTrade primer) amb REST + WebSocket i 3 modes (LIVE / PAPER / BACKTEST), dissenyat per consumir-se des d’un adapter de Freqtrade.
**Scope inicial:** `XAUUSD` i `EURUSD`, **candles 1m only**, **TZ canònica = America/New_York**.

---

## 1) Objectius del MVP

### 1.1 Funcionalitats mínimes

El servei ha de permetre:

* **Market data**

  * Ticker/mark actual per símbol
  * OHLCV 1m històric i recent

* **Trading position-based**

  * Obrir posició **market** (long/short)
  * Tancar posició
  * Consultar posicions
  * Actualitzar SL/TP (si el venue o mode ho suporta)

* **Account**

  * Balance
  * Trade history (recomanat)

* **Resiliència**

  * Reconnect WS (servei intern)
  * Backfill periòdic per omplir gaps
  * Idempotència a l’obertura/tancament (client_order_id)

### 1.2 No objectius del MVP (evitar dispersió)

* Multi-timeframe natiu (només 1m)
* Limit orders
* Orderbook
* Forks de CCXT o Freqtrade

---

## 2) Principis d’arquitectura i estil

### 2.1 SOLID + DI minimalista (tipus “Java”, però curt)

* Interfícies petites i clares (ports)
* Implementacions concretes a `infrastructure/`
* Injecció per constructor a `application/` (sense frameworks pesats)
* Cap classe “god object”; cada classe amb responsabilitat única
* Només afegir abstraccions quan realment calgui (evitar palla)

### 2.2 Cada tasca d'agent ha de tancar cicle complet

Per cada feature/target:

* Implementació
* Integració (wired up)
* **Testing (scripts)** que demostri que funciona

### 2.3 Regla de constants i valors hardcoded (ZERO TOLERANCE)

**Principi:** **NO hardcoded values** — Tot valor màgic ha de ser configurable i traçable.

**Classificació de constants:**

1. **Constants locals del fitxer/classe** (comportament propi):
   - Definides com a constants a la **capçalera del fitxer** (abans de la classe)
   - Format: `UPPERCASE_WITH_UNDERSCORES`
   - Exemple: `DEFAULT_BUFFER_SIZE = 1000`, `MAX_RETRIES = 3`
   - Ús: Comportament intern del mòdul que no necessita configuració externa

2. **Constants del projecte** (configuració global):
   - Definides en **fitxer de configuració centralitzat** (e.g., `config.py`)
   - Font única de veritat per tot el projecte
   - Exemple: `infrastructure/venues/gtrade/config.py` per gTrade
   - Importades explícitament: `from .config import DEFAULT_TIMEOUT`

3. **Constants d'entorn** (deployment/runtime):
   - Llegides de `.env` via `os.getenv()` o `pydantic-settings`
   - Valors per defecte definits a `.env.example`
   - Exemple: `MODE`, `SYMBOLS`, `GTRADE_PRICE_WS_URL`

**Regles estrictes:**

✅ **CORRECTE:**
```python
# infrastructure/venues/gtrade/config.py (font de veritat)
DEFAULT_GTRADE_PRICE_WS_URL = "wss://backend-arbitrum.gains.trade"
GTRADE_PAIR_ID_TO_SYMBOL = {0: "XAUUSD", 2: "EURUSD"}
DEFAULT_RECONNECT_DELAY_SECONDS = 5.0

# infrastructure/venues/gtrade/price_feed_ws_client.py
from .config import DEFAULT_GTRADE_PRICE_WS_URL, DEFAULT_RECONNECT_DELAY_SECONDS

# Constants locals del fitxer
MAX_QUEUE_SIZE = 1000  # Comportament intern del WebSocket client

class GTradePriceFeedWSClient:
    def __init__(self, ws_url: str = DEFAULT_GTRADE_PRICE_WS_URL):
        self._tick_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
```

❌ **INCORRECTE:**
```python
# Hardcoded URL (no traçable)
ws_url = "wss://backend-arbitrum.gains.trade"

# Magic number (no semàntica)
queue = asyncio.Queue(maxsize=1000)

# Constant duplicada (múltiples fonts de veritat)
RECONNECT_DELAY = 5.0  # També definit a un altre fitxer
```

**Detecció de violacions:**

- **Code review:** Buscar literals numèrics/strings sense context
- **Grep check:** `grep -r "wss://" --include="*.py"` → Ha de retornar NOMÉS config files
- **Magic numbers:** Qualsevol literal numeric > 1 fora de tests ha de tenir nom
- **Duplicats:** `grep -r "= 1000" --include="*.py"` → Validar que són contextos diferents

**Excepcions permeses:**

- **Tests:** Fixtures amb valors literals (però preferiblement importats de config)
- **Constants matemàtiques:** `PI = 3.14159`, `DEGREES_IN_CIRCLE = 360`
- **Booleans òbvies:** `enabled = True`, `is_valid = False`
- **Índexs i increments:** `i + 1`, `range(0, 10)`

**Refactoring de codi legacy:**

1. Identificar tots els hardcoded values
2. Classificar: local vs projecte vs entorn
3. Extraure a constants amb noms semàntics
4. Crear config.py si no existeix
5. Verificar: `git grep -E '"[^"]{10,}"' | grep -v test | grep -v config`

---

## 3) Modes d’operació

### 3.1 LIVE

* Data: gTrade live feeds (ticker/mark) via backend/SDK
* Execució: real al venue (obrir/tancar posició)
* Candles: construcció 1m des de live + persistència a CSV
* Backfill: periòdic (si hi ha endpoint històric disponible) per garantir “no gaps”

### 3.2 PAPER

* Data: live real (igual que LIVE)
* Execució: simulada (fills + fees + slippage modelats)
* Candles: igual que LIVE (persistència + backfill) per tenir dataset consistent

### 3.3 BACKTEST

* Data: històric 1m de Dukascopy (o storage existent)
* Execució: simulada amb backtest engine (fills OHLC, SL/TP intrabar amb high/low)
* Candles: llegeix CSV canònic del dataset (mateix format que live)

---

## 4) Decisió de dades i storage (CANÒNIC)

### 4.1 Timezone canònica

**TZ canònica de storage: `America/New_York`**.

* Totes les candles guardades i servides per `/ohlcv` estan en aquesta TZ.
* Timestamps representen l’**inici del minut** (`ts` = start-of-minute).
* Candle representa `[ts, ts+60s)` i només s’escriu quan està **tancada**.

> Nota: NY té DST. Per mantenir la invariant “no gaps” i increments de 60s, es defineix que:
>
> * l’índex temporal canònic intern és **epoch UTC**,
> * i la representació i particionat a fitxer és per “timezone NY”.
>   Això evita discontinuïtats lògiques però manté convenció NY a nivell d’arxius i API.

### 4.2 Layout de fitxers (CSV 1m)

```
datafiles/
  {broker}/
    {asset}/
      {timezone}/
        {YYYY}/
          {MM}.csv
```

Exemple:

```
datafiles/gtrade/XAUUSD/America_New_York/2026/02.csv
datafiles/gtrade/EURUSD/America_New_York/2026/02.csv
```

Format CSV:

* `ts,open,high,low,close,volume`
* `volume` = 0 quan no existeix volum real

### 4.3 Invariant “NO GAPS”

* El dataset d’un rang demanat ha de ser contigu a nivell de minuts.
* El sistema sempre sap si toca:

  * **append** (nou minut)
  * **patch** (finestra correctiva N minuts)
  * **backfill** (si detecta forat)
* Mai es considera “complet” fins que s’ha validat seqüència.

### 4.4 Regles d’escriptura

* **Single-writer per símbol** (evita corrupció)
* Escriure atòmicament: `tmp + rename`
* Lock per fitxer (file lock o Redis lock)

### 4.5 Backfill periòdic (restart + cada 10 min)

* En startup:

  * calcula `from = last_ts - corrective_window`
  * `to = last_closed_minute`
  * demana històric (si existeix) i patch
* Cada 10 minuts:

  * repeteix patch per garantir integritat
* Si no hi ha històric disponible:

  * registra estat “NEEDS_BACKFILL”
  * manté dataset amb WS i marca el gap com a pendent

**Corrective window (MVP):** N=3..5 minuts (decisió fixa al config).

---

## 5) Contracte REST (Endpoints)

### 5.1 Core

* `GET /health`
* `GET /mode`
* `GET /capabilities`

### 5.2 Instruments

* `GET /pairs`

  * XAUUSD, EURUSD (precisions, min size/notional, leverage min/max)

### 5.3 Market Data

* `GET /ticker/{symbol}`

  * bid/ask/mid(or mark), spread, ts

**5.4 OHLCV (1m only)** (al final del punt)

**Política de completitud de dades (`/ohlcv`):**

* L’endpoint `/ohlcv` **mai** retornarà un rang que contingui gaps.
* Si es detecta un gap i **no es pot omplir** en aquell moment, el servei respon amb **HTTP 409 (Conflict)** i un payload que inclou `reason="DATA_GAP"` i `missing_ranges=[...]`.
* Això reforça la invariant “NO GAPS” i evita consum de dades incompletes.

### 5.5 Trading (market-only, position-based)

* `POST /positions`
* `GET /positions`
* `GET /positions/{position_id}`
* `DELETE /positions/{position_id}`
* `PATCH /positions/{position_id}/sl`
* `PATCH /positions/{position_id}/tp`

**Idempotència obligatòria:** `client_order_id`.

### 5.6 Account

* `GET /balance`
* `GET /trade-history?since&limit`

### 5.7 Backtest controls (només BACKTEST)

* `POST /backtest/load`
* `POST /backtest/reset`
* `POST /backtest/play?speed=...`
* `POST /backtest/pause`
* `POST /backtest/seek?ts=...`
* `GET /backtest/state`

---

## 6) WebSocket (WS)

### 6.1 Endpoint únic

* `WS /ws`

### 6.2 Canals

* `ticker:XAUUSD`
* `ticker:EURUSD`
* `candle:XAUUSD:1m`
* `candle:EURUSD:1m`
* `positions`
* `balance`
* `execution`

### 6.3 Seq + resume + resync

* Cada event té `seq`.
* Client pot enviar `resume(last_seq)`.
* Si no es pot replay, el servei envia `resync_required`.
* Client refà estat amb REST.

---

## 7) Componentització (classes i responsabilitats)

### 7.1 Domain (models + interfaces)

**Models:** Candle, PriceData, Position, OrderRequest/Result, Balance, TradeHistory, TradingPair.

**Interfaces (ports):**

* `IVenueAdapter`

  * get_pairs, get_latest_price, open_position, close_position, update_sl/tp, get_positions, get_balance, get_trade_history
* `ICandleStore`

  * read_range(symbol, start, end), append(candle), patch(range)
* `ICandleBuilder`

  * on_tick → updates; finalize_minute → candle tancada
* `IBackfillProvider`

  * fetch_ohlcv(symbol, start, end) (si el venue ho permet)
* `IExecutionEngine`

  * paper/backtest execution logic
* `IClock`

  * real clock (live/paper), virtual clock (backtest)

### 7.2 Application (orquestració)

* `BrokerFacade` (façana)

  * rep requests API/WS
  * crida adapters/engines
  * aplica idempotència
* `MarketDataService`

  * ticker + candles + backfill scheduler
* `TradingService`

  * open/close + positions + reconcile
* `BacktestService`

  * controls + virtual clock + feed de candles

### 7.3 Infrastructure

* `venues/gtrade/` (nou)
* `data/dukascopy/` (lector/importer)
* `storage/csv_candlestore/` (writer/reader per layout definit)
* `ws/hub/` (broadcast + seq)
* `locks/` (file/redis lock)

---

## 8) Docker i instal·lació

### 8.1 Components a docker-compose

* `brokerage-service` (FastAPI+WS)
* `redis` (recomanat per seq buffer + locks + idempotència; opcional en MVP però molt útil)

**Model de desplegament (per broker):**

* Cada instància del servei opera **un únic broker/venue actiu** (ex. `broker-gtrade`).
* Si en el futur volem Ostium en paral·lel, aixequem **una segona instància** (`broker-ostium`) amb el seu `.env` i volums separats.
* El `broker` dins del path `datafiles/{broker}/...` es manté com a *namespace* de storage, però en runtime el servei treballa amb un sol `BROKER_ID` (p.ex. `gtrade`).

### 8.2 Volums

* `./datafiles:/datafiles` (candles)
* `./logs:/logs`

### 8.3 Config via `.env`

* `MODE=paper|live|backtest`
* `SYMBOLS=XAUUSD,EURUSD`
* `CANONICAL_TZ=America/New_York`
* `DATAFILES_ROOT=/datafiles`
* `BACKFILL_INTERVAL_SECONDS=600`
* `CORRECTIVE_WINDOW_MINUTES=5`
* `WS_TICK_INTERVAL_MS=200` (si aplica)
* Secrets live (wallet/rpc) només en LIVE

### 8.4 Instal·lació simple

* `cp .env.example .env`
* `docker compose up -d`
* validar `GET /health`



---

## 9) gTrade Specifics (Fees + Price Feed)

### 9.1 Market Data Source

**Recomanat per integradors - Pricing Backend:**
- **REST**: `https://backend-pricing.eu.gains.trade/charts`
- **WebSocket**: `wss://backend-pricing.eu.gains.trade`
- **Purpose**: Optimitzat per pricing, menys càrrega, recomanat per integradors

**Alternatiu/Resiliència - Network-specific Backend:**
- Pattern: `https://backend-<network>.gains.trade` i `wss://backend-<network>.gains.trade`
- Networks: `arbitrum`, `polygon`, `base`, `sepolia`
- **Purpose**: Per resilience, failover, o si necessites dades específiques de network

**Endpoints clau (ambdós backends):**
- `GET /trading-variables` - Fee parameters, pair configs, open interest
- `GET /open-trades/<address>` - Active positions per address (checksummed)
- `GET /charts` - Historical OHLC data (REST, rate limited)

**WebSocket data format:**
- **Price updates**: `[pairId, price, pairId, price, ...]` every ~25ms
- **Ping messages**: `[<timestamp_ms>]` every ~1000ms
- No authentication required, but rate limiting applies to REST

**Integration approach:**
- **LIVE mode**: WS feed → tick stream → CandleBuilder → CSVCandleStore (1m, TZ=NY)
- **Primary WS**: `wss://backend-pricing.eu.gains.trade` (recomanat)
- **Fallback WS**: `wss://backend-arbitrum.gains.trade` (si primary falla)
- **REST `/charts`**: Support per backfill (si és útil per omplir micro-gaps o startup)
  - Format: `{ time, opens: [], highs: [], lows: [], closes: [] }` (array indexat per pairId)
  - ⚠️ Rate limiting: prefer WS stream per real-time updates

### 9.2 Cost Model (Fees + Spread)

**Càlcul base:** Fees s'apliquen sobre `position_size = collateral × leverage`

**Fee structure per asset class (Fixed fees):**

| Asset       | Class      | Spread (Fixed) | Open Fee | Close Fee | Notes                          |
|-------------|------------|----------------|----------|-----------|--------------------------------|
| EURUSD      | Forex Major| 0.01%          | 0.012%   | 0.012%    | Total cost: ~0.034% per trade |
| XAUUSD      | Commodity T1| 0.01%         | 0.05%    | 0.05%     | Total cost: ~0.11% per trade  |

**⚠️ Dynamic Spread / Price Impact (MVP: placeholder):**
- gTrade aplica **Dynamic Spread** addicional al fixed spread
- Factors: OI ratio (longOi/shortOi), position size, market conditions
- Obtingut de `/trading-variables` (pair-level i group-level)
- **MVP approach**: Ignorat a Fase 4 (paper trading amb fixed spread només)
- **Fase 6**: Integrar dynamic spread calculation via SDK o `/trading-variables`

**Configuració de referència (MVP - fixed fees només):**

```yaml
cost_model:
  EURUSD:
    spread_pct: 0.01      # Applied at execution (bid/ask)
    open_fee_pct: 0.012   # Charged on position_size at open
    close_fee_pct: 0.012  # Charged on position_size at close
    asset_class: "forex_major"

  XAUUSD:
    spread_pct: 0.01
    open_fee_pct: 0.05
    close_fee_pct: 0.05
    asset_class: "commodity_tier1"
```

**Breakdown en API responses:**

```json
{
  "fees_breakdown": {
    "open_fee": 12.0,         // collateral × leverage × open_fee_pct
    "close_fee": 12.0,        // collateral × leverage × close_fee_pct
    "spread_cost": 10.0,      // position_size × fixed_spread_pct
    "dynamic_spread": 0.0,    // MVP: placeholder (Fase 6)
    "borrowing_cost": 0.0     // MVP: placeholder (Fase 6)
  },
  "pnl_gross": 150.0,         // Price movement PnL
  "pnl_net": 116.0            // pnl_gross - all fees
}
```

### 9.3 Borrowing Fees (Placeholder per futures fases)

**Formula oficial:** `feePerBlock × (abs(longOi - shortOi) / maxOi) ** feeExponent`

**Key parameters (obtinguts de `/trading-variables`):**
- `feePerBlock`: Base fee rate (denominated in 1e10)
- `longOi` / `shortOi`: Open interest per side
- `maxOi`: Maximum open interest capacity
- `feeExponent`: Exponent aplicat al OI ratio (típicament 1)

**Per-block to time-based conversion:**
- Fees acumulen **per block** mentre la posició està oberta
- Conversió a hourly/daily: `feePerBlock × blocks_per_timeunit × OI_ratio`
- Block rate és **network-dependent** (configurable via backend data, no hardcoded)

**MVP approach:**
- ✅ Add `borrowing_cost: 0.0` field to API responses (reservat)
- ⏸️ **Not implemented** in Fase 4 Paper Trading
- 🔜 Implement in Fase 6 (Live adapter) amb real-time OI data from `/trading-variables`

**Data source (Fase 6):**
- `GET /trading-variables` provides:
  - Pair-level and group-level OI windows
  - Fee parameters (`feePerBlock`, `feeExponent`, block timing)
  - Current longOi/shortOi values
- **Greater of pair-level or group-level fee applies** (never combined)
- **Only the side with higher OI pays fees**

### 9.4 Liquidation Price (Future Integration)

**SDK function:** `getLiquidationPrice(trade, fees, initialAccFees, context)`

**How fees affect liquidation:**
- Accumulated borrowing fees erode collateral buffer
- Higher fees → closer liquidation price
- Formula incorporates:
  - Open/close fee percentages
  - Spread parameters
  - Current borrowing costs (pair + group level)

**MVP:**
- ⏸️ Liquidation calculation not critical for paper trading
- 🔜 Implement in Fase 6 using `@gainsnetwork/sdk` helpers

### 9.5 Implementation Phases

**Fase 4 (Paper Trading) — Fees MVP:**
- ✅ Implement `CostModel` class (configurable per symbol)
- ✅ Apply spread + open_fee + close_fee to PaperExecutionEngine
- ✅ Return `fees_breakdown` in API responses
- ⏸️ `borrowing_cost: 0.0` (placeholder)
- Result: Realistic PnL calculations immediately

**Fase 6 (Live Adapter) — Full Integration:**
- 🔜 Integrate WS pricing backend (`wss://backend-arbitrum.gains.trade`)
  - Price updates → tick stream → CandleBuilder
  - Ping/pong handling (~1s interval)
- 🔜 Optional: REST `/charts` for startup OHLC backfill
- 🔜 Fetch `/trading-variables` for real fee parameters
- 🔜 Implement borrowing fee calculation (per-block → hourly)
- 🔜 Use `@gainsnetwork/sdk` for:
  - `transformGlobalTradingVariables()`
  - `getLiquidationPrice()`
  - `convertFees()`

### 9.6 Configuration Example

```bash
# .env
MODE=paper
VENUE=gtrade
ARBITRUM_RPC_URL=https://arb1.arbitrum.io/rpc  # Only for LIVE mode

# Cost model (defaults match official docs)
GTRADE_EURUSD_SPREAD_PCT=0.01
GTRADE_EURUSD_OPEN_FEE_PCT=0.012
GTRADE_EURUSD_CLOSE_FEE_PCT=0.012

GTRADE_XAUUSD_SPREAD_PCT=0.01
GTRADE_XAUUSD_OPEN_FEE_PCT=0.05
GTRADE_XAUUSD_CLOSE_FEE_PCT=0.05
```

**Notes:**
- Fee percentages expressen-se sobre `position_size = collateral × leverage`
- Spread s'aplica al preu d'execució (adverse slippage simulat)
- Borrowing fees són **time-based** i acumulen mentre la posició està oberta
- Source of truth per paper/backtest: BrokerageService CostModel
- Source of truth per live: gTrade smart contracts + `/trading-variables`

---

## 10) Testing simple (sense pytest) — scripts Python

### 9.1 Filosofia de testing

* **Unit tests**: scripts que testen classes “pures” (store, builder, gaps validator).
* **Integration tests**: scripts que aixequen components (en memòria o docker) i validen fluxos.
* **API smoke tests**: scripts que fan requests HTTP/WS i validen respostes.

Tot plegat “simple”: `python testing/run_all.py` i retorna exit code 0/1.

### 9.2 Estructura de testing

```
testing/
  unit/
    test_candle_store.py
    test_gap_validator.py
    test_candle_builder.py
    test_idempotency.py
  integration/
    test_backfill_patch_flow.py
    test_live_to_store_flow.py
    test_reconcile_positions.py
  api/
    test_rest_smoke.py
    test_ws_smoke.py
  run_all.py
  README.md
```

### 9.3 Regles

* Sense pytest.
* Cada script:

  * té `main()`
  * fa asserts
  * imprimeix resum
  * retorna exit code (0 ok / 1 fail)
* `run_all.py` executa tot en ordre i falla al primer error (o acumula i reporta).

### 9.4 “Done” per cada tasca d’agent

Cap tasca es considera feta si no inclou:

* com a mínim 1 unit test o 1 integration test que valida la nova peça
* si toca API: 1 smoke test de l’endpoint

---

## 11) Roadmap per fases (cada fase amb "tanca amb tests")

### Fase 1 — Storage CSV + Gap invariant + OHLCV read

* Implementar `CSVCandleStore` + reader/writer atòmic + lock
* Implementar `GapValidator`
* Endpoint `/ohlcv/{symbol}` (backtest data)
* Tests:

  * unit: store read/write, gap validator
  * api: smoke `/ohlcv`

### Fase 2 — Live ingestion → CandleBuilder → store

* Implementar `CandleBuilder` (tick → 1m candle tancada)
* “Writer loop” que escriu candles tancades
* Tests:

  * unit: candle builder
  * integration: tick replay → store → ohlcv range sense gaps

### Fase 3 — Backfill scheduler + patch policy

* Implementar `BackfillProvider` (si gTrade ho permet; sinó stub)
* Startup backfill + cada 10 min
* Corrective window patch
* Tests:

  * integration: injectar “forat” → backfill omple → gap validator OK

### Fase 4 — Trading service (paper) + idempotència + positions endpoints + Cost Model

* **Core endpoints:**
  * `POST /positions` (paper execution)
  * `GET /positions` (list amb unrealized PnL)
  * `DELETE /positions/{id}` (close position)
  * `PATCH /positions/{id}/sl` i `/tp` (update stops)
  * `GET /balance` (account balance + margin usage)

* **Idempotència:**
  * `client_order_id` obligatori per open/close
  * IdempotencyStore amb TTL (in-memory o Redis)

* **Cost Model (fees realistes):**
  * Implementar `CostModel` class amb configuració per símbol
  * Spread: 0.01% (EURUSD, XAUUSD)
  * Open fee: 0.012% (EURUSD), 0.05% (XAUUSD)
  * Close fee: 0.012% (EURUSD), 0.05% (XAUUSD)
  * Càlcul sobre `position_size = collateral × leverage`
  * API response inclou `fees_breakdown` detallat
  * `borrowing_cost: 0.0` (placeholder per futures fases)

* **Tests:**
  * unit: idempotency store, cost model calculations
  * integration: open/close flow amb fees, duplicate request handling
  * api: complete positions flow (open → update SL/TP → close)

### Fase 5 — WS hub (ticker/candle/positions) + seq/resync

* WS subscribe + seq increments
* resync_required behaviour
* Tests:

  * api/ws smoke: connect, subscribe, receive messages

### Fase 6 — gTrade live adapter + reconcile loop (LIVE) + Real Fees

* **Price feed integration:**
  * WS connection a `wss://backend-arbitrum.gains.trade`
  * Parse price updates format: `[pairId, price, pairId, price, ...]`
  * Ping/pong handling (~1s interval)
  * Tick stream → CandleBuilder → CSVCandleStore

* **Fee integration:**
  * Fetch `/trading-variables` per real fee parameters
  * Implement borrowing fee calculation:
    * Formula: `feePerBlock × (abs(longOi - shortOi) / maxOi) ** feeExponent`
    * Arbitrum: 12,000 blocks/hour
    * Greater of pair-level or group-level applies
  * Update API responses amb `borrowing_cost` real

* **SDK integration:**
  * Use `@gainsnetwork/sdk` helpers:
    * `transformGlobalTradingVariables()`
    * `getLiquidationPrice()`
    * `convertFees()`

* **Execució real:**
  * Integrar smart contract calls per open/close
  * Transaction handling + confirmations
  * Reconcile loop cada N segons (compare local vs blockchain state)

* **Optional: REST backfill:**
  * `GET /charts` per startup OHLC recovery
  * Rate limiting awareness (prefer WS stream)

* **Tests:**
  * integration: mock venue adapter + reconcile repairs state
  * integration: fee calculation accuracy (vs known scenarios)
  * api: health + open/close flow (live or mocked)

---

## 12) Decisions tancades (de la conversa)

* Timeframe únic: **1m**
* Assets inicials: **XAUUSD, EURUSD**
* Storage CSV per minuts tancats, layout: `broker/asset/tz/year/month.csv`
* TZ canònica per storage i API: **America/New_York**
* Live WS escriu i crea històric propi; backfill en restart i cada 10 min si hi ha històric
* Invariant: **no gaps** (validat i corregit)
* Testing: scripts simples Python, sense pytest
* Cada tasca d’agent: implementació + integració + testing final
* **Deployment:** **una instància per broker** (gTrade ara; Ostium futur en un altre container), per simplicitat, seguretat i garantia del model “single-writer/no gaps”.

Copia/enganxa aquests 3 blocs tal qual (són els únics afegits que jo faria):


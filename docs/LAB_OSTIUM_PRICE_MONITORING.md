# LAB — Price Monitoring Feasibility (Ostium)

**TASK:** Investigar com monitoritzar preus mainnet d'Ostium per backtest/data layer, similar al que tenim per Lighter.

**Data investigació:** 2026-02-17

---

## 🔍 Descobriments

### ❌ No disponible a Ostium

| Funcionalitat | Disponibilitat | Notes |
|---------------|----------------|-------|
| **Historical Candles API** | ❌ NO | Només REST `/latest-price` (preu actual) |
| **WebSocket price feed** | ❌ NO | Cap WS públic per streaming |
| **Subgraph mainnet** | ⚠️ BUIT | Funciona (0.22s response) però 0 trades/prices indexats (validat 2026-02-17) |
| **Subgraph testnet** | ⚠️ BUIT | Funciona (0.23s response) però 0 trades/prices indexats (validat 2026-02-17) |

### ✅ Disponible a Ostium

| Funcionalitat | URL/Mètode | Notes |
|---------------|------------|-------|
| **Latest price (single)** | `https://metadata-backend.ostium.io/PricePublish/latest-price?asset=EURUSD` | REST GET, preu actual |
| **Latest prices (all)** | `https://metadata-backend.ostium.io/PricePublish/latest-prices` | REST GET, tots els parells |
| **Trading hours** | `https://metadata-backend.ostium.io/trading-hours/asset-schedule?asset=EURUSD` | REST GET, horari RWA |

**SDK Python (`ostium-python-sdk`):**
```python
from ostium_python_sdk import OstiumSDK, NetworkConfig

sdk = OstiumSDK(NetworkConfig.mainnet(), private_key)
price, timestamp, _ = await sdk.price.get_price("EUR", "USD")
```

---

## 📊 Comparativa amb Lighter

| Criteri | Lighter | Ostium |
|---------|---------|--------|
| **Historical candles** | ✅ REST `/candlestick` (resolution=1m, paginated 500/req) | ❌ NO disponible |
| **WebSocket feed** | ✅ Sí (`candle:EURUSD:1m` topic) | ❌ NO disponible |
| **Subgraph mainnet** | N/A (no usen subgraph) | ❌ Broken ("Not found") |
| **Latest price** | ✅ REST + WS | ✅ REST només |
| **Coverage probe** | ✅ 72h EURUSD/XAU OK | ⚠️ No aplicable (sense històric) |

---

## 🎯 Opcions per Monitoritzar Ostium Mainnet

### Opció 1: Polling REST + Build Candles (RECOMANAT)

**Approach:**
1. Polling cada N segons (e.g. 5s, 10s, 30s) al REST `/latest-price`
2. Acumular ticks en memòria
3. Construir candles 1m agregant ticks (OHLC + first/last timestamp)
4. Persistir a JSONL (format compatible amb ws_candle_collector.py)

**Pros:**
- ✅ Funciona amb infraestructura actual d'Ostium
- ✅ Dades "reals" de mainnet (oracle prices que usa Ostium)
- ✅ Restartable (state.json amb last_ts)
- ✅ Multi-symbol (EURUSD, XAUUSD, etc.)

**Contras:**
- ❌ Només captura des de "ara endavant" (no històric anterior)
- ❌ Depèn de polling frequency (gaps si polling massa lent o downtime)
- ❌ Pot tenir rate limits (TBD: verificar amb tests)

**Scripts a crear:**
- `rest_price_collector.py` — Collector principal (similar a ws_candle_collector.py)
- `rest_price_probe.py` — Validació coverage/qualitat

---

### Opció 2: Usar Font Externa (Dukascopy) per EUR/USD

**Approach:**
- Usar DukascopyBackfillProvider (ja implementat) per EUR/USD històric
- Ostium usa oracles (probablement Chainlink) que tenen font similar

**Pros:**
- ✅ Ja implementat i validat (P6, P8 compat reports)
- ✅ Històric complet (anys de dades)
- ✅ Zero dependència d'Ostium API

**Contras:**
- ⚠️ No és el preu "real" d'Ostium (pot haver diferències oracle vs market)
- ⚠️ Només EUR/USD; altres RWA (XAU, índexs) cal verificar disponibilitat Dukascopy

**Ús recomanat:**
- **Backtest**: Dukascopy per històric pre-Ostium
- **Live/Paper**: Ostium REST latest-price

---

### Opció 3: Blockchain Events (NO recomanat)

**Approach:**
- Llegir events `OrderOpened`, `OrderClosed` del contracte Ostium
- Construir price history a partir de trades d'usuaris

**Pros:**
- ✅ Dades 100% on-chain

**Contras:**
- ❌ Molt costós (RPC calls massives)
- ❌ Només tenim trades individuals (no necessàriament cobreix tots els timestamps)
- ❌ Complex d'implementar i mantenir
- ❌ No tenim "oracle price" directe, només execution prices

**Conclusió:** Descartat per cost/complexitat.

---

## 🚀 Recomanació Final

### Per a MVP (Data Layer + Backtest)

**Combinació d'opcions:**

1. **Històric (pre-now):** Usar **Dukascopy** per EUR/USD
   - Ja validat (P8 compat reports)
   - Cobertura completa
   
2. **Monitorització mainnet (now → futur):** Crear **REST polling collector**
   - Captura preus Ostium reals des d'ara endavant
   - Valida que oracle prices Ostium són compatibles amb Dukascopy
   - Artifact: `lab/out/ostium_prices/<run_id>/EURUSD.jsonl`

3. **Compat verification:** Executar **compat_probe** Ostium vs Dukascopy
   - Validar correlació, direction agreement, offset
   - Decisió: Si corr >0.7 → Dukascopy viable per backtest

---

## 📁 Scripts a Crear

### 1. `rest_price_collector.py`

**Funcionalitat:**
- Poll `/latest-price?asset=EURUSD` cada N segons (configurable)
- Acumular ticks en memòria (timestamp, price)
- Cada 60s: construir candle 1m (open=first, high=max, low=min, close=last)
- Persistir a JSONL: `<symbol>.jsonl` (format: `{"ts": 1234567890, "o": 1.1, "h": 1.11, "l": 1.09, "c": 1.1, "v": 0}`)
- State file: `state.json` (last_ts per símbol, restartable)
- Status report: `STATUS.md` (taula amb symbol/candles/gaps/last_ts/status)

**Comanda:**
```bash
python3 lab/ostium/scripts/rest_price_collector.py \
  --symbols EURUSD,XAUUSD \
  --poll-interval-s 10 \
  --hours 72 \
  --outdir lab/out/ostium_prices \
  --resume 1
```

**Config:**
- `OSTIUM_PRICE_API_BASE`: `https://metadata-backend.ostium.io`
- `OSTIUM_POLL_INTERVAL_S`: 10 (default)
- Rate limit handling: retry + backoff si 429

**Artifacts:**
- `lab/out/ostium_prices/<run_id>/EURUSD.jsonl`
- `lab/out/ostium_prices/<run_id>/state.json`
- `lab/out/ostium_prices/<run_id>/STATUS.md`

**Test (0 network):**
- `testing/unit/test_ostium_rest_collector.py` (mock responses, build candles logic)

---

### 2. `rest_price_probe.py`

**Funcionalitat:**
- Validar coverage temporal d'un símbol
- Calcular gap stats (missing_minutes, max_gap_s, duplicates)
- Comparar vs expected (e.g. RWA trading hours: Mo-Fr 04:00-20:00 ET)

**Comanda:**
```bash
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol EURUSD \
  --minutes 180 \
  --check-trading-hours
```

**Output:** `lab/out/ostium_price_probe_EURUSD_180m.json`

**Mètriques:**
- `expected_minutes` (considering trading hours)
- `candles_collected`
- `missing_minutes`
- `max_gap_s`
- `duplicates_after_dedup`
- `ts_step_errors`

---

### 3. `ostium_vs_dukascopy_compat.py`

**Funcionalitat:**
- Executar compat_probe Ostium (REST collector) vs Dukascopy
- Mateix engine que P8 compat reports (Lighter vs Dukascopy)
- Decidir si Dukascopy és viable per backtest d'Ostium

**Comanda:**
```bash
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
  --symbol EURUSD \
  --minutes 1440
```

**Output:** `lab/out/ostium_compat_EURUSD_1440m.json`

**Mètriques (P8.1):**
- `corr_at_lag0`, `best_lag_minutes`, `dir_agree_pct`
- `zero_range_ratio` (A=Ostium, B=Dukascopy)
- `mean_diff_close`, `p95_abs_diff_close`

**Verdict:**
- PASS si `corr >0.7`, `dir_agree >65%`, `zero_range <30%`
- PARTIAL si dins marges acceptables
- FAIL si diferències massa grans

---

## 📅 Roadmap Proposta

### P9.0 — Ostium REST Price Collector (MVP)

**Deliverables:**

| Component | Path |
|-----------|------|
| Collector script | `lab/ostium/scripts/rest_price_collector.py` |
| Probe script | `lab/ostium/scripts/rest_price_probe.py` |
| Compat script | `lab/ostium/scripts/ostium_vs_dukascopy_compat.py` |
| Unit test | `testing/unit/test_ostium_rest_collector.py` (0 network) |
| Docs | `docs/LAB_OSTIUM_PRICE_MONITORING.md` (aquest fitxer) |

**DoD (Definition of Done):**

| Àrea | Criteri |
|------|---------|
| **Code** | Collector funciona: polling REST, build candles 1m, JSONL + state.json + STATUS.md |
| **Code** | Probe funciona: gap stats, trading hours aware |
| **Code** | Rate limit handling: retry 429 + backoff |
| **Tests** | Unit test (0 network): mock REST responses, candle aggregation logic OK |
| **Evidència** | Artifact 3h EURUSD mainnet: `missing_minutes <=2`, `ts_step_errors ==0` |
| **Docs** | 1 sol fitxer nou: `docs/LAB_OSTIUM_PRICE_MONITORING.md` |

---

### P9.1 — Ostium vs Dukascopy Compat

**Deliverables:**

| Component | Path |
|-----------|------|
| Compat runner | `lab/ostium/scripts/ostium_vs_dukascopy_compat.py` |
| Artifact | `lab/out/ostium_compat_EURUSD_<N>m.json` |

**DoD:**

| Àrea | Criteri |
|------|---------|
| **Evidència** | Compat report EURUSD 24h: corr, dir_agree, zero_range, offset |
| **Decisió** | Documentar PASS/PARTIAL/FAIL per usar Dukascopy en backtest Ostium |

---

## 🧪 Comandes Ràpides

```bash
# Collector 3h EURUSD mainnet (polling cada 10s)
python3 lab/ostium/scripts/rest_price_collector.py \
  --symbols EURUSD \
  --poll-interval-s 10 \
  --hours 3 \
  --outdir lab/out/ostium_prices

# Probe 3h collected data
python3 lab/ostium/scripts/rest_price_probe.py \
  --symbol EURUSD \
  --indir lab/out/ostium_prices/<run_id> \
  --check-trading-hours

# Compat Ostium vs Dukascopy (24h)
python3 lab/ostium/scripts/ostium_vs_dukascopy_compat.py \
  --symbol EURUSD \
  --minutes 1440 \
  --ostium-dir lab/out/ostium_prices/<run_id>
```

---

## 📊 Invariants Esperats

### Collector (3h EURUSD)

| Metric | Expected | Notes |
|--------|----------|-------|
| `candles_collected` | ~180 | 3h × 60 min |
| `missing_minutes` | ≤2 | Acceptable gaps (polling jitter, downtime) |
| `duplicates_after_dedup` | 0 | Dedup per ts |
| `ts_step_errors` | 0 | Candles cada 60s |
| `max_gap_s` | ≤300 | Max 5 min gap acceptable |

### Compat vs Dukascopy (24h EURUSD)

| Metric | Expected | Notes |
|--------|----------|-------|
| `corr_at_lag0` | >0.7 | Correlació preus |
| `dir_agree_pct` | >65% | Mateixa direcció (up/down/flat) |
| `zero_range_ratio_ostium` | <30% | Candles flat H==L |
| `mean_diff_close` | <0.001 | Offset preu mitjà |

---

## ⚠️ Limitacions Conegudes

1. **No històric anterior:** Collector només captura des de "ara endavant"
   - **Solució:** Usar Dukascopy per pre-now
   
2. **Rate limits desconeguts:** `/latest-price` pot tenir límits
   - **Mitigació:** Polling conservador (10s default), retry + backoff
   
3. **RWA trading hours:** EUR/USD només opera Mo-Fr 04:00-20:00 ET
   - **Mitigació:** `rest_price_probe.py --check-trading-hours` descarta weekends/holidays
   
4. **Polling jitter:** Gap inevitable entre polls (10s interval → max 10s old)
   - **Acceptable:** Per candles 1m, jitter <10s és OK
   
5. **Oracle vs market price:** Ostium usa oracles (Chainlink, etc.), no necessàriament preu de mercat "real"
   - **Verificació:** Compat probe vs Dukascopy per validar offset acceptable

---

## 🎓 Workflow Recomanat

### Fase 1: Implementar Collector (P9.0)
1. Crear `rest_price_collector.py` (polling + candle build + persist)
2. Unit test (0 network, mock responses)
3. Run 3h EURUSD mainnet → artifact
4. Verificar `missing_minutes <=2`, `ts_step_errors ==0`

### Fase 2: Validar Coverage (P9.0)
1. Crear `rest_price_probe.py` (gap stats + trading hours)
2. Run sobre artifact 3h
3. Verificar invariants

### Fase 3: Compat Dukascopy (P9.1)
1. Crear `ostium_vs_dukascopy_compat.py` (reuse P8 engine)
2. Run 24h EURUSD
3. Decisió: PASS/PARTIAL/FAIL per backtest

### Fase 4: Producció Data Layer (futur)
- Si P9.1 PASS → integrar DukascopyBackfillProvider per Ostium EUR/USD
- Si P9.1 PARTIAL → decidir offset correction
- Si P9.1 FAIL → buscar altra font o descartar Ostium per backtest

---

## 🔬 ANNEX: Validació Subgraph (2026-02-17)

### Test Executats

**Scripts utilitzats (read-only, no wallet):**
- `lab/ostium/scripts/test_subgraph_quick.py` — Test connectivitat bàsic
- `lab/ostium/scripts/test_subgraph_historical.py` — Exploració exhaustiva entities

### Resultats Testnet (Arbitrum Sepolia)

**URL:** `https://api.studio.thegraph.com/query/53927/ostium-arbitrum-sepolia/v0.1.0`

```
✅ Connection: OK
⏱️  Response time: 0.23s (excellent)
📊 Open trades: 0
📊 Historical trades: 0
```

**Conclusió:** Funciona però buit.

### Resultats Mainnet (Arbitrum One)

**URL:** `https://api.studio.thegraph.com/query/53927/ostium-arbitrum-one/v0.1.0`

```
✅ Connection: OK
⏱️  Response time: 0.22s (excellent)
📊 Open trades: 0
📊 Historical trades: 0
📊 Price updates: 0
```

**Queries provades:**
```graphql
# Query 1: Recent trades
query GetRecentTrades {
  trades(first: 10, orderBy: blockTimestamp, orderDirection: desc) {
    id
    pairId
    openPrice
    blockTimestamp
  }
}
# Result: { "trades": [] }

# Query 2: Price updates
query GetPriceUpdates {
  priceUpdates(first: 10, orderBy: timestamp, orderDirection: desc) {
    id
    pairId
    price
    timestamp
  }
}
# Result: { "priceUpdates": [] }
```

**Conclusió:** Funciona tècnicament però completament buit. No conté cap trade, price update ni event indexat.

### Per què està buit?

**Hipòtesis més probable:** Baixa activitat mainnet

- Ostium és relativament nou (2024-2025)
- Focus en testnet per desenvolupadors
- Fees competitius però encara no mainstream
- Documentació oficial se centra en REST API, no subgraph

### Verdict Final

**❌ Subgraph NO viable per històric de preus**

Ambdós (testnet i mainnet) funcionen correctament però estan completament buits. No es poden utilitzar per extreure dades històriques.

**✅ Confirmació:** REST polling continua sent l'única opció viable.

---

**Última actualització:** 2026-02-17  
**Status:** Investigació completada + Subgraph validat (mainnet + testnet) → BUITS

# P3.3 — Architecture Review (Data Layer Readiness)

**Objectiu:** Deixar el codi preparat perquè P4 (Durable Recorder v0) entri net, amb responsabilitats clares.

**Data:** 2026-02

---

## 1) Mapa ràpid d’arquitectura

### Mòduls: quin fa què

| Mòdul | Responsabilitat |
|-------|-----------------|
| **application/api** | REST routes (`broker_routes`, `ws_routes`), candle_helpers (read_range, resolve_candle_range) |
| **application/main** | Lifespan, config, wiring DI via `set_broker_deps` |
| **application/services** | LiveMarketDataService (ticks→candles→store), BackfillService (no wired), reconcile, bootstrap, live_guards |
| **domain** | Models (Candle, Tick, etc.), interfaces (ICandleStore, IBackfillProvider, IPriceFeedClient, etc.) |
| **infrastructure/storage** | CSVCandleStore, GapValidator, sltp_store |
| **infrastructure/venues/lighter** | LighterPriceFeedClient, LighterMarketDataClient, CandleBuilder (a builders/) |
| **infrastructure/builders** | lighter_di (DI), candle_builder (ticks→Candle) |
| **infrastructure/data** | MockBackfillProvider (tests) |

### Punts d’entrada i wiring

- **Lifespan** (`application/main.py`): `load_config()` → `CSVCandleStore` → `build_lighter_paper_market_data(candle_store, ...)` → `LiveMarketDataService.start()` → `set_broker_deps(candle_store=..., adapter_factory=...)`
- **set_broker_deps** injecta: `_candle_store`, `_adapter_factory`, `_mode`, `_venue`, `_market_data_env`, `_market_data_source`
- **Broker routes** llegeixen via `_require_candle_store()` → `store.read_range()`

### Candle write path (avui)

```
LighterPriceFeedClient (polling) / FakeLighterPriceFeedClient
    → LiveMarketDataService._process_ticks_loop()
    → CandleBuilder.on_tick(tick) → Candle tancada
    → LiveMarketDataService._handle_completed_candle()
    → candle_store.append(candle)   ← ÚNIC ESCRIPTOR RUNTIME
    → _broadcast_candle (WS)
```

**CSVCandleStore** és read+write: `read_range`, `append`, `patch`, `get_last_timestamp`. L’escriptura és atòmica (tmp+rename), amb lock per fitxer, i control de duplicats (existing_timestamps).

### Data contracts (spec)

| Contracte | Regla |
|-----------|-------|
| **Candle timestamp canònic** | `ts` = start-of-minute UTC epoch seconds (validat amb time_semantics_probe) |
| **Close semantics** | Lighter retorna només candles tancades (`latest = now_floor_utc - 60`) |
| **Normalització** | Qualsevol font (WS/live/backfill) ha d’entrar al store amb aquest contracte |

### Duplicats: append vs patch

- **append():** dedup per `ts` (existing_timestamps) abans d’escriure. OK.
- **patch():** ha de deduplicar amb la mateixa clau (`ts`) i mateixa normalització que append. Contracte explícit per evitar inconsistències quan entri LighterCandlestickProvider. *(TODO P4: verificar que patch usa ts com a clau única; merge strategy: prefer new)*

### On viu el timezone canònic?

El **store i la persistència són TZ-agnòstics** (UTC epoch). El timezone `America/New_York` només afecta: queries from/to de l’API, particionat (paths) i visualització. Evita conversions TZ dins del dataset.

### Seam futur: LiveMarketDataService

LiveMarketDataService avui barreja: ingest (ticks), build, persist, broadcast. P4 podria extreure un **CandleSink** (append + broadcast) si cal desacoblar recorder / socket reconciliation. Només una nota; no és tasca ara.

---

## 2) Checklist P4 (respostes avui)

### A) Què escriu candles?

| Pregunta | Resposta |
|----------|----------|
| Hi ha un sol lloc que escriu a CSV? | **Sí.** Només `LiveMarketDataService` crida `candle_store.append()`. `BackfillService` crida `store.patch()` però **no està wired** al lifespan. |
| L’escriptura és atòmica i controla duplicats? | **Sí.** CSVCandleStore: tmp+rename, lock, check `existing_timestamps` abans append. |
| CandleStore és read-only i el writer està fora? | **No.** CSVCandleStore implementa ICandleStore (read + append + patch). El “writer” és qui crida append/patch. Ideal: CandleStore = storage; Recorder = orquestració. Avui LiveMarketDataService fa d’orquestrador i escriu directament. |

### B) On viviran P4 classes?

| P4 classe | Ubicació proposada | Estat avui |
|-----------|--------------------|------------|
| MarketDataRecorderService | `application/services/market_data_recorder_service.py` | **No existeix.** LiveMarketDataService fa part del rol (append + broadcast). P4 pot encapsular startup_backfill + append_closed_candle. |
| HistoricalBackfillService | `application/services/historical_backfill_service.py` | **BackfillService** existeix a `application/services/backfill_service.py`. No wired. Pot ser base per P4. |
| GapDetector (puro) | `domain/services/gap_detector.py` | **GapValidator** a `infrastructure/storage/gap_validator.py`. Lògica pura (find_gaps, validate). P4 pot moure a domain o crear wrapper. |
| LighterCandlestickClient | `infrastructure/venues/lighter/lighter_candlestick_client.py` | **No existeix.** Lab `fetch_historical_candles.py` usa Candlestick API directament. P4 ha de crear client reutilitzable. |

### C) Ports & adapters

| Port | Implementació | Notes |
|------|---------------|-------|
| ICandleStore | CSVCandleStore | Read + write. P4: mantenir; writer ha de ser únic (Recorder). |
| IBackfillProvider | MockBackfillProvider | Només tests. P4: afegir LighterCandlestickBackfillProvider. |
| IPriceFeedClient | LighterPriceFeedClient, FakeLighterPriceFeedClient | OK. |
| ICandleBuilder | CandleBuilder | OK. |

### D) Evitar sobreenginyeria

- **ICandleStore** té 1 implementació (CSVCandleStore). Tests usen CSVCandleStore amb tmpdir. **Keep.**
- **IBackfillProvider** té MockBackfillProvider. P4 afegirà Lighter. **Keep.**
- **GapValidator** és pur; no cal interfície si només hi ha 1 implementació. **Keep**; opcional moure a domain si es vol “GapDetector” puro.

---

## 3) Classes / fitxers: keep / merge / delete

### ✅ Keep (necessàries)

| Fitxer / classe | Motiu |
|-----------------|-------|
| `infrastructure/storage/csv_store.py` (CSVCandleStore) | Storage canònic; atomic, lock, dedup. |
| `domain/interfaces/candle_store.py` (ICandleStore) | Port. |
| `application/services/live_marketdata_service.py` | Únic writer runtime; ticks→candles→append. |
| `infrastructure/builders/candle_builder.py` | Agregació 1m. |
| `infrastructure/storage/gap_validator.py` | Lògica pura gaps; usat per BackfillService. |
| `application/services/backfill_service.py` | Base per P4 HistoricalBackfillService; no wired. |
| `domain/interfaces/backfill_provider.py` | Port per historical fetch. |
| `infrastructure/data/mock_provider.py` | Tests. |
| `application/api/candle_helpers.py` | Read_range, resolve_candle_range. |
| `application/api/broker_routes.py` | API REST. |

### 🟡 Merge / rename (candidats)

| Actual | Acció | Notes |
|-------|-------|-------|
| `BackfillService` | Rename a `HistoricalBackfillService` en P4 | Mateix contracte; P4 afegirà Lighter provider. |
| `GapValidator` | Opcional: moure `find_gaps` a `domain/services/gap_detector.py` | Si es vol GapDetector “puro” a domain. Refactor mínim: no obligatori ara. |

### ❌ Delete (unused / dead)

| Candidat | Verificació |
|----------|-------------|
| Cap fitxer complet mort detectat | BackfillService és usat per test_backfill_patch_flow. MockBackfillProvider per tests. |

---

## 4) Refactor mínim (P3.3)

**Constraints:** No breaking, behavior-preserving. Només el que ajuda P4 seams.

### 4.1 Eliminar codi mort / duplicacions

- **No s’ha detectat** codi mort crític. BackfillService no wired però és base per P4.

### 4.2 Seams per P4

1. **Writer:** LiveMarketDataService ja crida `candle_store.append()`. P4 MarketDataRecorderService pot encapsular: `append_closed_candle(symbol, candle)` delegant a store.append. **No cal canvi ara.**

2. **Historical fetcher:** IBackfillProvider existeix. Falta implementació Lighter (P4). **Seam OK.**

3. **GapDetector:** GapValidator.find_gaps és pur. BackfillService el fa servir. **Seam OK.** Opcional: crear `domain/services/gap_detector.py` que reexporti o wrapi GapValidator.find_gaps. **Refactor mínim: no fer ara** (evitar sobreenginyeria).

4. **SRP per fitxer:** Revisar si algun fitxer barreja IO + decisions + mapping. `live_marketdata_service.py` fa: ticks, build, append, broadcast. Acceptable; P4 pot extreure “recorder” si cal.

### 4.3 Accions concretes P3.3 (mínimes)

- **Documentar** (aquest fitxer) el mapa i els seams.
- **No eliminar** BackfillService (serà base P4).
- **No moure** GapValidator a domain ara (opcional P4).
- **Garantir** que `run_all` passa.

---

## 5) Resum per P4

| Component | Estat | Acció P4 |
|----------|-------|----------|
| CandleStore (read) | ✅ | Mantenir. |
| CandleStore (write) | ✅ append/patch atòmic | Recorder cridarà append. Single-writer via Recorder. |
| LiveMarketDataService | ✅ writer actual | P4: Recorder orquestra backfill + rep candles de LiveMarketDataService (o WS) i append. |
| BackfillService | 🟡 existeix, no wired | P4: wiring + LighterCandlestickBackfillProvider. |
| GapValidator | ✅ pur | P4: usar find_gaps per GapDetector. |
| Lighter Candlestick | ❌ no existeix | P4: crear LighterCandlestickClient (lab fetch_historical_candles com a referència). |

---

## 6) Quality gate

```bash
./test.sh testing/run_all.py
```

**Criteri DONE P3.3:** run_all passa; documentació ARCH_REVIEW_P4_READY.md creada; sense refactors breaking.

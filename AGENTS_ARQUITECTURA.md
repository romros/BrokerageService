# AGENTS_ARQUITECTURA.md — BrokerageService (Reference)

**Data:** 2026-02-17  
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`  
**Modes:** LIVE / PAPER / BACKTEST  
**Timeframe:** 1m only  
**TZ canònica (config):** `CANONICAL_TZ=America/New_York` (NY close style)  
**TZ container (runtime/logs):** `TZ=America/New_York`  
**API canònica:** REST `/api/v1/broker/*` (POST body únic per ordres)  
**Objectiu:** servei multi-venue amb **Data Layer canònic** (candles 1m fiables) i execució desacoblada.  
**Operativa diària i evidència:** `docs/ESTAT.md`

---

## Split vNext (3 serveis)

**Propòsit:** Desacoblament arquitectònic per operar en producció amb menys acoblament. Pivot cap a Ostium com a font realtime (recording 24/7) i Dukascopy com a històric.

### Què fa cada servei

| Servei | Funció |
|--------|--------|
| **realtime_datalayer** | Ostium recorder 24/7; serve candles/ticks recents; font primària per trading |
| **historical_datalayer** | Dukascopy/backfill/compat/export; consumeix dades del realtime; stitching gated |
| **trading_service** | Broker/execució (orders, balance, positions); consumeix Data Layer |

### Contractes mínims

- **realtime → trading:** `GET /candles`, `GET /ohlcv/{symbol}`, `GET /data_status`, `GET /coverage`
- **historical → trading:** candles històrics, stitching (rang travessa cutover)
- **historical → realtime:** consumeix candles recents per compat/gaps (opcional)

### Graduation path

- **LAB:** validació, probes, compat. Artifacts a `lab/out/`.
- **prod-ish:** integrat, activable via env; compose override. Encara no primary.
- **primary:** declarat authoritative quan passi gates (soak + compat).

### Regla de docs

- **ESTAT** és operatiu (comandes, evidència, runs).
- **AGENTS** és graduation/design (arquitectura, contractes, invariants).

### Mapping de l'estat actual → vNext

| Actual | vNext (quan migrem) |
|--------|---------------------|
| `application/` (monolític) | `apps/realtime_datalayer/`, `apps/historical_datalayer/`, `apps/trading_service/` |
| OstiumCandleIngestService, tick recorder | realtime_datalayer |
| DukascopyBackfillProvider, compat | historical_datalayer |
| broker_routes, IVenueAdapter | trading_service |
| `foundation/`, `domain/` | `packages/shared/` (compartit) |

### Role boundaries (Phase 1)

- **realtime_datalayer:** Ostium ingest + Data Layer prod; NO adapter, NO trading routes
- **historical_datalayer:** Data Layer backfill_only (Dukascopy); NO Ostium ingest, NO adapter
- **trading_service:** adapter + trading routes; NO ingest, NO Data Layer writer

### Realtime DataLayer v1 (runtime)

- Servei autònom: `docker compose -f ... up -d realtime_datalayer`
- Storage: `datafiles/realtime_datalayer/candles/`, `ticks/`
- API: GET /health, GET /status, GET/PUT /symbols (hot-reload), /docs, /ui, /api/v1/broker/ohlcv, data_status, coverage
- Docs: `apps/realtime_datalayer/realtime_datalayer_arquitectura.md`, `realtime_datalayer_estat.md`
- Tests curts: `./test.sh testing/run_realtime.py`

### Phase 2 (futur)

- Migració de paquets/codi a `apps/*`
- Refactor de `foundation/`, `domain/` → `packages/shared/`
- No inclòs en Phase 1

---

## 0) TL;DR

- **Multi-venue per disseny:** un venue pot aportar **execució**, **market data**, o totes dues coses.
- **Data Layer és canònic:** candles 1m es serveixen **sense venue** via `candle_store` + policy (primary/fallback/mixed).
- **Primary (authoritative):** dades gravades pel servei (recorder). Exemple actual: Data Layer prod v0 sobre Lighter backfill provider. Ostium està integrat com a **prod-ish opt-in recorder** (`OSTIUM_ENABLED=1`), però **NO es declara primary** fins passar gates (soak + compat).
- **Fallback històric:** **Dukascopy** (read-only) amb stitching **gated** per compat.
- **Exec venue (actual):** Lighter està implementat i "execution-ready". El canvi d'execució (p.ex. Ostium) ve després.
- ✅ **Normes de codi:** imports a capçalera + zero hardcode.
- ✅ **Testing:** scripts Python (sense pytest), runner únic `testing/run_all.py`.
- ✅ **LAB-first:** exploració abans de tocar arquitectura; LAB no és producció; evidència a `docs/ESTAT.md`.

---

## 1) Decisions tancades (invariants)

1. **Timeframe únic:** `1m`
2. **Candles sense venue:** `GET /candles` i `GET /ohlcv/{symbol}` venen del `candle_store`
3. **TZ canònica:** `America/New_York` (partició/queries/display; *no* re-etiqueta `ts`)
4. **`ts` canònic:** epoch UTC (start-of-minute); interval `[ts, ts+60)`
5. **API Broker:** prefix `/api/v1/broker`; POST body only per ordres
6. **Errors:** `{"detail": "...", "code": "..."}` amb 503/422/404
7. **Single-writer** per símbol al storage
8. **Data Layer separada de Trade Layer:** l'API de dades és estable independentment del venue d'execució
9. **LAB no és producció:** conclusions de LAB només "graduen" a arquitectura quan hi ha evidència i tests
10. **Normes:** imports a capçalera + zero hardcode (veure §6)

---

## 2) Arquitectura (vista alta)

### 2.1 Capes

**A) Broker API (contracte estable)**  
Rutes primes: validate → serveis → map response.

**B) Data Layer (canònic)**  
Responsable de:
- obtenir/capturar ticks o candles
- construir candles 1m "closed-only"
- persistir en `candle_store`
- servir queries amb transparència (`X-Data-*`)
- stitching primary/fallback/mixed (gated)

**C) Trade Layer (execució)**  
Responsable de:
- open/close/sltp/balance/positions/trades via `IVenueAdapter`
- reconcile/guards/idempotència
- *No defineix* la font canònica de candles

> Regla: **Trade "menja" Data Layer** quan necessita preu/candles per decisions, PnL, close paths o paper simulation.

---

## 3) Data Layer — Fonts i política (canònic)

### 3.1 Fonts

- **Primary (authoritative):** dades gravades pel servei (recorder).  
  Exemple actual: **Data Layer prod v0** sobre Lighter backfill provider. Ostium està integrat com a **prod-ish opt-in recorder** (`OSTIUM_ENABLED=1`), però **NO es declara primary** fins passar gates (soak + compat).
- **Fallback (read-only):** vendor extern per prehistòria o gaps.  
  Exemple: **Dukascopy 1m**

### 3.2 Stitching policy (primary/fallback/mixed)

Definicions:
- `cutover_ts(symbol)` = primer `ts` existent al primary (recorded). `cutover_ts` es calcula només sobre el primary store (no sobre fallback).
- Query candles sempre en rang sobre **bar starts** `[since, to)`.

Resposta:
- `to <= cutover_ts` → **fallback**
- `since >= cutover_ts` → **primary**
- travessa `cutover_ts` → **mixed** només si `compat_check(symbol)=PASS`; si no → 422 `MIXED_SOURCE_NOT_ALLOWED`

Regles "mixed":
- prioritat al primary en solapament
- cap minut duplicat
- frontera neta (bar start semantics)

### 3.3 Transparència al client (headers)

A totes les respostes OHLCV:
- `X-Data-Source: primary|fallback|mixed`
- `X-Data-Coverage-From`, `X-Data-Coverage-To`
- `X-Data-Missing-Minutes`, `X-Data-Max-Gap-S`
- `X-Data-Repair`, `X-Data-Repair-Filled` (si aplica)
- `X-Data-Cutover-Ts` (si `mixed`)

---

## 4) Compat gates (habilitar mixed i protegir backtest)

**Gate A (integritat) — hard fail**
- duplicates=0
- ts_step_errors=0 (60s)
- missing_fallback_ratio ≤ 0.1%

**Gate B (similaritat de mercat) — strategy-level**
- corr(ret) ≥ llindar
- direction mismatch ≤ llindar
- ratios de volatilitat/range dins banda

**Regla:**
- mixed ON només si Gate A PASS i Gate B PASS
- si Gate A PASS però Gate B FAIL → fallback-only per prehistòria, mixed OFF

---

## 5) Broker API — Contracte v0 (estable)

**Base URL:** `http://localhost:8000/api/v1/broker`

### 5.1 Market data (sense venue per candles)

- `GET /candles?symbol=...&timeframe=1m&limit=...&since?&to?`
- `GET /ohlcv/{symbol}?tf=1m&limit=...&since?&to?`

**Nota:** no accepten `venue`. La font real és Data Layer (primary/fallback/mixed) i queda reflectida als headers.

### 5.2 Trading / account (amb venue)

- `GET /pairs?venue=...`
- `GET /balance?venue=...`
- `GET /positions?venue=...`
- `GET /trades?venue=...`
- `POST /orders/open` (body: venue, symbol, side, collateral, leverage, sl/tp…)
- `POST /orders/close` (body: venue, position_id, percent)

> El `venue` aquí és el **d'execució**, no el de dades.

---

## 6) Coding standards (invariants)

### 6.1 Imports a la capçalera (regla general)

- **Tots els imports han d'anar a la capçalera** del fitxer.
- **Prohibit** fer imports dins de funcions "per estil".

**Excepcions permeses (han d'estar documentades a la línia de l'import):**
- Evitar imports circulars: `# local import to avoid circular dependency`
- Lazy import per cost d'arrencada: `# lazy import to reduce startup cost`

**No és una excepció vàlida:** "evitar pol·luir namespace" per mòduls stdlib lleugers (`traceback`, `asyncio`, `shutil`, `tempfile`, `os`, `io`). Aquests **han d'anar a la capçalera**.

**Regla obligatòria:** si un import no compleix la regla, cal un comentari **a la mateixa línia** explicant per què. Sense comentari = violació.

### 6.2 Zero hardcode (regla general)

- Prohibit posar valors màgics (strings, ints, floats, paths, timeouts, limits) dins la lògica.
- Tot valor "policy/protocol" ha d'estar en:
  1. constants de mòdul
  2. constants de classe
  3. config (`foundation/config/...` o `application/config/...`) si és compartible/overrideable per env

**Exemples de hardcode no permès:**
- TZ ("America/New_York") repetit a mà
- timeframe ("1m") repetit
- codis d'error repetits
- llistes de venues repetides
- sleep/retry/backoff sense constants

**Exemples permesos:**
- literals en tests (fixtures)
- strings de log no-crítics
- literals ultra locals que no són policy (`side_lower in ("long","short")`)

**Fonts canòniques:**
- `foundation/config/constants.py` — TZ/timeframe/limits/venues/paths
- `application/api/error_codes.py` — codis d'error Broker API

### 6.3 Disseny de mòduls (regla pràctica)

- Rutes (API) primes; lògica en serveis.
- Ports a `domain/*`; adapters a `infrastructure/*`.
- No crear una abstracció si només hi ha 1 implementació, excepte si és un seam clar per test.

---

## 7) Testing (sense pytest) — estàndard del projecte

### 7.1 Filosofia

- Tests són **scripts Python** amb `main()` + `assert`.
- **Regla: NO pytest.** Tots els tests són scripts executables via `run_all.py`.
- Si falla, peta l'`assert` i el test retorna exit code != 0.
- Cap feature és "DONE" sense:
  - mínim 1 test nou (unit o integration)
  - si toca API, mínim 1 test `testing/api/*`

### 7.2 Estructura

```
testing/
  unit/           # 0 network, tot en memòria
  integration/    # wiring/serveis, pot usar fakes/mocks
  api/            # smoke contra localhost (HTTP)
  helpers/        # utilitats comunes per tests
  apps/           # tests migrats per servei (realtime_datalayer, historical_datalayer, trading_service, core)
  suites/         # definicions de suite (*.txt amb paths)
  run_all.py      # runner canònic del projecte (full suite)
```

### 7.2.1 Operational surface area de tests (vNext)

**Comandes canòniques per servei:**
- `./scripts/run_tests.sh smoke` — mínim viable (instal·lació + imports)
- `./scripts/run_tests.sh core` — foundation/shared
- `./scripts/run_tests.sh realtime_datalayer` — Data Layer + Ostium
- `./scripts/run_tests.sh historical_datalayer` — Dukascopy/compat
- `./scripts/run_tests.sh trading_service` — execució/venue

**Regla:** Suites curtes per focus; `run_all.py` per full suite (CI).

### 7.3 Plantilla canònica d'un test

```python
import sys

def main() -> int:
    # arrange
    # act
    # assert
    print("OK test_xxx")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### 7.4 Execució canònica

```bash
# Suites per focus (curtes)
./scripts/run_tests.sh smoke
./scripts/run_tests.sh core
./scripts/run_tests.sh realtime_datalayer
./scripts/run_tests.sh historical_datalayer
./scripts/run_tests.sh trading_service

# Full suite (CI-friendly)
./test.sh testing/run_all.py

# Un test concret
./test.sh testing/unit/test_example.py
./test.sh testing/apps/core/test_candle_store.py
```

### 7.5 Regles d'opt-in (xarxa / credencials)

- Tests que requereixen xarxa/.env han de ser **opt-in** (ex: flags `--include-...`).
- Si no hi ha entorn, el test ha de **SKIP amb motiu** (no FAIL per "0 candles").
- Default `run_all.py` ha de passar sense xarxa.

---

## 8) LAB — estàndard d'ús (abans d'implementar)

### 8.1 Propòsit

LAB és per:
- validar disponibilitat de dades (WS/REST/històric)
- validar semàntica temporal i qualitat (gaps, zero_range, duplicates)
- fer probes comparatives (compat) abans de tocar producció

LAB **no** és producció. No es trenca arquitectura per un "resultat parcial" de LAB.

### 8.2 Regles

- Scripts a `lab/<topic>/scripts/*.py`
- Outputs a `lab/out/...` (artifacts: JSON/JSONL/CSV/STATUS.md)
- Cada LAB conclou amb:
  - evidència mínima (artifact guardat)
  - 2–5 línies a `docs/ESTAT.md` (què s'ha provat i conclusió)
- Si una conclusió de LAB passa a "policy":
  - s'afegeix un test (unit/integration/api) que la protegeixi

### 8.3 Quan una idea de LAB "gradua"

"Gradua" quan:
1. hi ha artifact replicable (`lab/out/...`)
2. hi ha test que evita regressió
3. hi ha decisió escrita a `docs/ESTAT.md`

### 8.4 Graduation path: LAB → prod-ish opt-in → primary recorder

Per fonts de dades (ex. Ostium):

1. **LAB:** validació, probes, compat. Artifacts a `lab/out/`.
2. **prod-ish opt-in:** integrat al codi, activable via env (`OSTIUM_ENABLED=1`), scripts canònics (`run_smoke.sh ostium`), compose override. **Encara no primary**.
3. **primary recorder:** declarat authoritative quan passi gates (soak + compat). Fins llavors, no es declara primary.

**Regla (Data Layer / graduation):** Només si **compat PASS** (Ostium vs Dukascopy) per un símbol → es pot declarar Ostium primary per aquell símbol. Font de veritat: `ostium_compat_registry.json` via `get_ostium_primary_allowed(symbol)`. Si no PASS: el servei continua en mode "opt-in experimental" sense declarar primary.

**Regla:** `docs/ESTAT.md` és la font d'operativa diària; `AGENTS_ARQUITECTURA.md` reflecteix l'estat de graduació (LAB / prod-ish opt-in / primary).

**Regla (LAB monitors):** Els monitors LAB s'executen via `scripts/run_lab.sh <monitor> start|stop|status|logs` i viuen sota `deploy/compose/lab/`. No tmux manual per defecte.

**Regla (Tick store forense):** El tick recorder Ostium (`OSTIUM_TICK_RECORDER_ENABLED`) és **forense** — per investigar desajustos (spot/perp, offsets, dupes) sense contaminar el camí canònic. No bloqueja prod-ish: si el tick write falla, el recorder de candles continua.

---

## 9) Wiring i DI (minimalista)

- `set_broker_deps(candle_store, adapter_factory, mode, venue)` al lifespan.
- Data Layer (recorder/backfill/gap repair) arrenca al lifespan i escriu a `candle_store`.
- `adapter_factory` exposa `IVenueAdapter` per execució.

---

## 10) Storage i semàntica temporal (canònic)

- CSV: `ts,open,high,low,close,volume`
- `ts` = epoch UTC start-of-minute
- candle = interval `[ts, ts+60)`
- només candles tancades ("closed-only")

`CANONICAL_TZ` és per partició/display/queries; el dataset canònic continua sent UTC epoch.

---

## 11) Docker / Runtime (normes operatives)

**Recorda:** execucions dins Docker usen la imatge construïda; si canvies codi:
`docker compose build brokerage`

### 11.1 TZ del container

`TZ=America/New_York` i `CANONICAL_TZ=America/New_York` al compose.

Verificació:
```bash
docker compose run --rm brokerage date
docker compose run --rm brokerage python3 -c "import time, datetime; print(datetime.datetime.now()); print(time.tzname)"
```

### 11.2 Volums (host-accessible)

Regla: tot el persistent ha de ser accessible des del host.
```yaml
volumes:
  - ./datafiles:/datafiles
  - ./logs:/app/logs
```

### 11.3 Operational Surface Area (regles per no créixer caos)

- **No crear scripts nous ad-hoc** per cada cas. Entrypoints: `application/tools/*.py` (lògica) + `scripts/*.sh` (wrappers mínims).
- **Docker compose overrides** a `deploy/compose/overrides/` amb convenció de noms (data-layer.yml, soak.yml, ostium.yml).
- **El que ja no és camí principal** → `_archive/` amb README (què era, per què arxivat, reemplaçament canònic).
- **Scripts canònics:** `run_smoke.sh [profile]`, `run_soak.sh <minutes> [profile]`. Profile = data-layer | ws | ostium.

---

## 12) Maturity model (per venue)

Un venue pot ser "ready" a diferents nivells:
- **Execution-ready:** open/close/sltp/balance/positions/trades + idempotència + reconcile
- **Data-ready:** candles 1m fiables (recorder/coverage/soak) + compat PASS vs fallback
- **Backtest-ready:** històric suficient o stitching coherent (gated)

Decisió de "venue principal" sempre és en 2 eixos:
- **exec principal**
- **data primary**

---

## 13) Quality gates (projecte)

- `./test.sh testing/run_all.py` passa (default)
- Opt-ins (xarxa/venue) sempre poden SKIP amb motiu clar (mai "0 candles fail")
- Evidència i runs operatives → `docs/ESTAT.md`

---

## 14) Estat actual (2026-02-17)

### Execution
- **Lighter:** ✅ Execution-ready (MVP 100%, paper testnet validat)
- **Ostium:** 🧪 LAB (testnet validat, mainnet pendent)

### Data Layer
- **Primary recorder (Lighter):** ✅ Data Layer prod v0 sobre Lighter backfill provider
- **Ostium recorder:** ✅ prod-ish opt-in (`OSTIUM_ENABLED=1`)
  - OstiumCandleIngestService: poll REST `/latest-price`, build candles 1m, persist `candle_store`
  - `DATA_LAYER_WRITE_MODE=realtime_plus_backfill` → Ostium ingest ON + Dukascopy backfill; `backfill_only` → ingest OFF
  - Històric/gaps: DukascopyBackfillProvider
  - **NO es declara primary** fins passar gates (soak + compat)
- **Fallback:** ✅ Dukascopy implementat i validat
- **Compat:** ✅ Ostium vs Dukascopy — Corr 0.976, Dir 92.7% (PARTIAL, 388c)
  - Amb 1440c esperat PASS
- **Stitching gated:** ✅ Implementat (P7 mixed)

### Backtest
- ⛔ Pipeline pendent (contracte previst)

**Operativa diària:** Vegeu `docs/ESTAT.md`

---

## 15) Changelog

- **2026-02-18** — Split vNext Phase 2: trading_service consumeix realtime_datalayer via HTTP (RealtimeDataLayerClient, IDataLayerReader, REALTIME_DATALAYER_BASE_URL). OHLCV/coverage/data_status forward quan env set.
- **2026-02-18** — Realtime DataLayer hot-reload: GET/PUT /symbols per canviar símbols sense restart; config persistent a `{REALTIME_DATALAYER_ROOT}/config/symbols.json`; instrument resolution (spot/perp) amb override.
- **2026-02-18** — Split vNext Phase 1: SERVICE_ROLE, entrypoints per servei (apps/*/app.py), create_app(role), role boundaries, compose amb entrypoints reals.
- **2026-02-18** — Split vNext: scaffold monorepo (apps/, packages/), compose 3 serveis, plantilla_tasca.md, mapping actual→vNext.
- **2026-02-17** — Ostium prod-ish opt-in: graduation path (§8.4); Ostium integrat com a recorder opt-in (no primary fins gates). Data Layer canònic; fallback Dukascopy; exec desacoblat. Normes (§6), Testing sense pytest (§7), LAB (§8), Docker (§11).
- **2026-02-14** — API canònica `/api/v1/broker/*`, candles sense venue, semàntica 1m (UTC start-of-minute).
- **2026-02-13** — Lighter execution MVP (smoke/e2e) i quality gates base.

---

**Nota:** Aquest document és la **referència arquitectònica estable**. Per evidència, runs, i tasques operatives, vegeu `docs/ESTAT.md`.

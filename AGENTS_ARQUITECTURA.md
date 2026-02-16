# AGENTS_ARQUITECTURA.md — BrokerageService (Reference)

**Data:** 2026-02-14  
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`  
**Venue principal:** **Lighter** — MVP 100% per Lighter. Altres DEX (p.ex. gTrade) s’incorporaran en el futur.  
**Modes:** LIVE / PAPER / BACKTEST  
**Timeframe:** 1m only  
**TZ canònica (config):** `CANONICAL_TZ=America/New_York` (NY close style)  
**TZ container (runtime/logs):** `TZ=America/New_York`  
**API canònica:** REST `/api/v1/broker/*` (POST body únic per ordres)  
**Objectiu:** Font única de referència estable. Operativa diària → [docs/ESTAT.md](docs/ESTAT.md).

---

## 0) TL;DR

- **MVP 100% Lighter:** tot el desenvolupament prioritari és per Lighter; altres DEX (gTrade, etc.) s’incorporaran en el futur
- ✅ **API Broker canònica** a `broker_routes.py` (prefix `/api/v1/broker`)
- ✅ **Candles**: candle_store (sense venue), 1m only, OHLCV unificat
- ✅ **Lighter**: open/close + SL/TP + balance + reconcile + guards + restart-safety + smoke + e2e → **DONE**
- ✅ **Quality gates**: run_all passa; evidència 3× smoke real + 3× e2e real (paper testnet)
- 🟡 **gTrade**: existent (paper OK); no prioritzat per MVP; futur
- ⛔ **Backtest**: pendent

---

## 1) Decisions tancades (invariants)

1. **Timeframe únic:** `1m`
2. **Candles sense venue:** `GET /candles` i `GET /ohlcv/{symbol}` venen del `candle_store`
3. **TZ canònica:** `America/New_York` (rang/particionat, NY close style)
4. **`ts` canònic:** epoch UTC (start-of-minute); interval `[ts, ts+60)`; convenció Dukascopy-like — veure §5.1
5. **API Broker:** prefix `/api/v1/broker`; decorators sense duplicar `/broker`
6. **Ordres:** només POST body (`/orders/open`, `/orders/close`); sense query legacy
7. **Errors:** `{"detail": "...", "code": "..."}` amb 503/422/404
8. **Single-writer** per símbol al storage CSV

---

## 2) Estat implementat

### 2.0 Symbol universe (venue/env)

| Venue / Env | Symbols (market data) | Notes |
|-------------|------------------------|-------|
| **Lighter testnet** | ETH, BTC | Limitats |
| **Lighter mainnet** | ETH, BTC, EURUSD, XAU | Confirmat via soak 15 min + `GET /pairs` (evidència 2026-02-14) |
| **gTrade** | XAUUSD, EURUSD, etc. | No prioritzat ara |

**Regles:**
- `GET /pairs?venue=lighter` és la font de veritat del què és suportat.
- `ws_soak --autodetect-symbols --venue lighter` ha d’usar aquesta font.

**Symbol normalization mapping (RWA / fallback):**
- **Canonical:** XAUUSD, EURUSD (ús intern, stitching, compat_probe)
- **Lighter:** XAU → canonical XAUUSD
- **Dukascopy:** XAUUSD → canonical XAUUSD (directe)
Evita comparar símbols diferents a stitching/compat_probe.

### Lighter (principal — MVP 100%)
✅ paper-ready · ✅ live-hardening complet · ⛔ backtest pendent  
Market data, open/close, SL/TP, balance, reconcile, guards, bootstrap, smoke, e2e. **Tot el MVP es fa per Lighter.**

### gTrade (existent — futur)
✅ paper-ready · 🟡 live-hardening pendent · ⛔ backtest pendent  
S’incorporarà en el futur; no prioritzat per MVP. Nota: `openPrice`/oracle zona sensible (veure §10 AGENTS si cal).

### BACKTEST
Contracte previst, però pipeline no implementada encara.

### 2.2 Mode PAPER amb market data MAINNET (Freqtrade-first)

Freqtrade es provarà primer en **PAPER**, però amb **market data real de MAINNET** perquè:
- testnet no té tots els assets
- testnet pot tenir preus "fake" o desalineats
- volem candles/WS realistes per validar l'edge i el pipeline

**Decisió:** PAPER = **mainnet market data** + **paper execution** (sense transaccions reals).

**Invariants:**
- market data = mainnet (per defecte en PAPER)
- execution = paper (simulada)
- zero tx reals en paper

**Variables de config:**
- `MODE=PAPER` — execució simulada
- `MARKET_DATA_ENV=mainnet` — font de preus (mainnet|testnet; default mainnet)
- `ENABLE_LIVE_TRADING=0` — kill switch (paper sempre 0)

**Nota explícita:** paper ≠ testnet. PAPER pot usar mainnet per market data i paper per execució.

### 2.3 Principis d’arquitectura (SOLID + DI minimalista)

- **SOLID / SRP:** rutes primes (validate → deps → call → map response). Lògica i mapping en helpers/serveis petits.
- **Ports & adapters:** `domain/*` defineix models + interfaces (ports); `infrastructure/*` implementa venue adapters i storage.
- **DI minimalista (estil Java, sense framework):**
  - Injecció per constructor/on-startup (FastAPI lifespan).
  - `set_broker_deps(...)` injecta dependències globals de rutes (candle_store, adapter_factory, mode, venue).
- **Evitar palla:** només abstraure quan hi ha 2 implementacions o un seam clar per testing.

### 2.4 Coding standards (invariants)

Imports sempre a capçalera; zero hardcode (constants a `foundation/config` o locals de mòdul). Excepcions documentades.

#### A) Imports a la capçalera (regla general)
- Tots els imports han d'anar a la capçalera del fitxer.
- Prohibit fer imports dins de funcions per estil.

**Excepcions permeses (documentades):**
- Evitar imports circulars (amb comentari `# local import to avoid circular dependency`).
- Lazy import per evitar càrrega pesada (p.ex. llibreria molt costosa) amb comentari `# lazy import to reduce startup cost`.
- Aquestes excepcions han de ser rares i justificades.

**No és excepció vàlida:** "evitar pol·luir namespace" per mòduls de la stdlib lleugers (`traceback`, `asyncio`, `shutil`, `tempfile`, `os`, `io`). Aquests han d'anar a la capçalera.

**Regla obligatòria:** Si un import no compleix la regla (p.ex. és dins d'una funció o mòdul), cal posar un comentari **a la línia de l'import** explicant el motiu (p.ex. `# local import to avoid circular dependency`, `# lazy import to reduce startup cost`). Sense comentari, es considera violació.

#### B) Zero hardcode (regla general)
- No posar valors màgics (strings, ints, floats, paths, timeouts, limits) dins la lògica.
- Tot valor "policy" o "protocol" ha d'estar en:
  1) Constants de mòdul (p.ex. `DEFAULT_LIMIT`, `MAX_LIMIT`)
  2) Constants de classe (si té sentit)
  3) Config (`foundation/config/...` o `application/config/...`) si pot ser compartit o sobreescrit per env.

**Exemples de què és hardcode no permès:**
- TZ ("America/New_York") repetit a mà
- Timeframe ("1m") i rangs de limit repetits
- Codis d'error repetits
- Llistes de venues ("lighter","gtrade") repetides

**Exemples permesos:**
- literals en tests (fixtures)
- strings de log no-crítics
- literals ultra locals (p.ex. `side_lower in ("long","short")`) si no és policy de configuració

**Fonts canòniques:**
- `foundation/config/constants.py` — CANONICAL_TIMEZONE_NAME, SUPPORTED_TIMEFRAME, DEFAULT_*_LIMIT, MAX_*_LIMIT, KNOWN_VENUES
- `application/api/error_codes.py` — codis d'error Broker API

### 2.5 Objectiu final i ordre de lliurament (Roadmap canònic)

> Aquesta secció defineix l'objectiu real del projecte i l'ordre de treball.
> **No canvia** el contracte actual ni el que ja està implementat; només fixa el "camí".

#### Objectiu final del projecte

Construir un servei únic ("BrokerageService") que permeti:

1. **PAPER (Freqtrade-first)**: paper trading sobre **market data MAINNET** (realista), amb execució paper i contracte d'API estable.
2. **DATA LAYER**: convertir el servei en una **font fiable de dades 1m** (candles + WS), amb persistència, backfill i garanties d'integritat.
3. **BACKTEST MODE**: simular el servei "com si fos real" (clock intern), servint candles i executant paper sobre el dataset guardat, a velocitat accelerada.

> Filosofia: primer tanquem "consumer real" (Freqtrade) → després fem "fonament" (data layer) → després fem "simulació" (backtest).

---

### 2.6 Definició "PAPER DONE" (Freqtrade-first)

PAPER no vol dir "testnet". PAPER vol dir **mainnet-data + paper execution**, amb zero tx reals.

**PAPER DONE** quan es compleix:

* **Market data MAINNET**:
  * WS i/o polling/candles proveeixen **1m closed candles** sense gaps durant una execució prolongada.
  * `missing_minutes=0` en soak.
* **Paper execution coherent amb l'API**:
  * `/orders/open` i `/orders/close` creen/tanquen posicions en paper amb `position_id` estable.
  * `positions_after=0` després de tancar (invariant de cleanup).
* **P3.0 Bracket + liquidation (paper):**
  * `POST /orders/open` amb `sl_price` i `tp_price` (bracket). Execució automàtica TP/SL quan el preu toca el nivell.
  * Liquidation simulation: equity ≤ notional × maintenance_margin_ratio → liquidació.
  * `GET /positions` retorna `sl_price`, `tp_price`, `liquidation_price`. `GET /trades` inclou `close_reason`.
* **Freqtrade handshake**:
  * Un "freqtrade-like runner" (o Freqtrade real) pot:
    * llegir `/ohlcv/{symbol}` i `/price/latest`
    * obrir/tancar posicions paper via API
    * sobreviure 15–30 min sense errors
* **Evidència**:
  * logs guardats (soak + runner) i punts de verificació clars al `docs/ESTAT.md`.

> Nota: el que ja hi ha (smoke/e2e/soak) és "core sanity". PAPER DONE és "freqtrade-first product sanity".

---

### 2.7 DATA LAYER (planificació, sense implementar encara)

Objectiu: que el servei pugui funcionar com a **"capa de dades 1m"** robusta i repetible.

**Time semantics (validated):** Lighter Candlestick `t` = UTC start-of-minute; returns closed-only (`latest = now_floor-60`). Dataset keeps `ts` epoch UTC; `CANONICAL_TZ` only affects queries/partition/display.

**P4.0:** BackfillService wired in lifespan; LighterCandlestickBackfillProvider (IBackfillProvider); gap repair via Candlestick API.

**P4.1:** Consistency gate — WS-built candles vs Candlestick REST; test_ws_vs_candlestick_consistency (opt-in).

#### 2.7.1 Requisits canònics del Data Layer

* **Continuïtat**: cada minut, o hi ha candle tancada, o es marca explícitament com a gap (i s'intenta reparar).
* **Backfill controlat**:
  * En startup: detectar "últim ts escrit" per símbol i recuperar el que falta fins "ara".
  * Durant execució: si WS cau, recuperar el forat amb fetch històric.
* **Integritat**:
  * `ts` start-of-minute (UTC) invariant.
  * cap duplicat, cap regressió temporal, escrit atòmic, single-writer.
* **Observabilitat mínima**:
  * counters: candles_written, gaps_detected, gaps_repaired, ws_reconnects.
  * logs de "gap window" i "repair result".
* **Criteri de "data-ready"**:
  * Soak 24h (o N hores) amb `missing_minutes` ≈ 0 i repairs controlats.
  * CSV consistent i endpoints responen amb latència acceptable.

#### 2.7.2 Arquitectura proposada del Data Layer (mòduls)

Sense canviar l'API actual, s'afegeixen serveis interns:

* **MarketDataRecorderService**
  * start/stop al lifespan
  * per símbol: subscripció WS (si existeix) → agregació 1m → persistència
* **HistoricalBackfillService**
  * `backfill(symbol, from_ts, to_ts)` amb rate limits
  * usat en startup i en gap repair
* **GapDetector** + **GapRepairCoordinator**
  * detecta minuts perduts (seqüència)
  * decideix si: backfill, o marcar com "unrepaired gap" (si no hi ha font)
* **CandleStore**
  * ja existeix com a font d'endpoints; el Data Layer el converteix en "durable".

#### 2.7.3 Política de gravació (startup backfill + runtime gap repair)

* **Sempre gravar mentre el servei està en marxa** (writer únic).
* En startup:
  1. carregar `last_ts` per símbol
  2. fer backfill fins `now_floor_minute - safety_lag`
  3. començar WS i gravació incremental
* Durant runtime:
  * si detecta gap: backfill immediat del forat (amb límit), i log.

> Important: els endpoints de candles ja existeixen; Data Layer és fer-los "fiables" i "continuats".

#### 2.7.4 Fonts de dades (primary vs fallback) + transparència al client

* **Fonts**
  * **primary**: dades gravades pel servei (authoritative a partir de `cutover_ts`).
  * **fallback**: vendor extern (p.ex. Dukascopy), només per prehistòria o gaps no reparables.

* **Stitch policy (mixed range)**
  * Definir `cutover_ts` per símbol: primer `ts` existent al primary.
  * Si una query demana `[since,to]` que travessa `cutover_ts`, la resposta pot ser "mixed", però:
    * **no duplicar minuts**
    * **prioritat sempre al primary** quan hi ha solapament
    * "join" net a la frontera (off-by-one controlat)

* **Com ho sap el client (pro però àgil)**
  1. **Headers (sempre disponibles, zero breaking change)**
     * `X-Data-Source: primary|fallback|mixed`
     * `X-Data-Cutover-Ts: <epoch_utc>` (obligatori si `X-Data-Source=mixed`; opcional en primary/fallback)
     * `X-Data-Gaps: <int>` = minuts absents al rang retornat (post-repair)
     * `X-Data-Repair: none|partial|full` (opcional)
  2. **Endpoint opcional de coverage (per clients avançats)**
     * Proposar: `GET /coverage?symbol=...&tf=1m` (sota `/api/v1/broker`)
     * Retorna: rang primary disponible (`primary_from_ts`, `primary_to_ts`), rang fallback disponible (`fallback_from_ts`), `cutover_ts`, notes.
     * **No és necessari per l'MVP**, però es documenta com a futur.
  3. **Meta "on-demand" (opt-in)**
     * Si el client passa `meta=1` a `/candles` o `/ohlcv/{symbol}`, el server pot afegir un bloc `meta` al JSON (sense afectar la resposta normal).
     * Ex: `{"candles":[...], "meta":{"source":"mixed","cutover_ts":...}}`
     * Per defecte `meta=0` → resposta com ara.

* **Invariant important**
  * El dataset canònic (primary) **no depèn** del fallback.
  * El fallback no s'escriu dins els CSV primary; s'emmagatzema separadament o s'usa "read-through" (decidir-ho més tard).

* **Quality gate abans d'habilitar fallback**
  * Afegir "compat check" en lab: comparativa primary vs fallback en un període de solapament (p50/p95/max del diff de close, gaps, timezone semantics).
  * Si falla el compat check → fallback deshabilitat per aquell símbol.

#### 2.7.5 Fallback provider (Dukascopy) — scope i contracte

**Objectiu:** proveir candles 1m read-only per XAUUSD i EURUSD, i en el futur més RWA.

**Contracte canònic:**
- Entrada/Sortida sempre en `ts` epoch UTC start-of-minute
- Rangs `[since_ts, to_ts)` sobre starts
- Retorna candles tancades (cap parcial)
- **Symbol normalization:** canonical XAUUSD, EURUSD; Lighter XAU→XAUUSD; Dukascopy XAUUSD→XAUUSD (veure §2.0)

**Regla d'or:** fallback no escriu mai al primary.

#### 2.7.6 Compat check "strategy-level" (primary vs fallback) — sense estratègia concreta

**Idea:** una eina (CLI `compat_probe`) compara primary vs Dukascopy en un rang on existeixen tots dos. Mètriques estratègia-agnòstiques que són proxies de si una estratègia típica (momentum, mean reversion, breakout) veurà el mateix mercat.

**Finestra del probe:** 72h (capta sessions diferents, manejable). **Borderline:** FAIL (conservador i segur).

**Semantics:** `ts` és start-of-minute; rangs `[since, to)` sobre starts.

---

**A) Gate d'integritat (hard fail)** — binari: si falla, no hi ha conversa.

- `duplicate_minutes == 0`
- `ts_step_errors == 0` (cada delta és 60s)
- `missing_fallback_minutes / total_minutes <= 0.1%` → **≤ 4 minutes per 72h window** (4320 min × 0.001)

Si falla: fallback disabled per aquell símbol (o només "fallback-only" sense mixed).

---

**B) Gate de "similaritat de mercat" (estratègia-agnòstic)**

Features per minut (per cada font) — per cada candle:
- `ret` = log(close/open) o (close/open - 1)
- `range` = (high-low)/close
- `body` = abs(close-open)/close
- `upper_wick` = (high-max(open,close))/close
- `lower_wick` = (min(open,close)-low)/close

Mètriques de comparació (per rang T, 72h):

| Mètrica | Proxy | Target |
|---------|-------|--------|
| `direction_mismatch_rate` | % minuts on sign(ret) difereix | EURUSD/XAUUSD ≤ 1.0% |
| `vol_ratio` | std(ret)_fallback / std(ret)_primary | dins [0.9, 1.1] |
| `range_ratio` | median(range)_fallback / median(range)_primary | dins [0.9, 1.1] |
| `p95_range_diff` | EURUSD: p95(abs(range_points_diff)); XAUUSD: p95(abs(range_usd_diff)) | veure thresholds |
| `corr(ret_primary, ret_fallback)` | Pearson (per simplicitat); Spearman opcional | ≥ 0.98 FX/metalls |

**Thresholds (inicials, conservadors):**

| Asset | direction_mismatch | corr(ret) | vol_ratio | range_ratio | p95_range_diff |
|-------|-------------------|-----------|-----------|-------------|----------------|
| **EURUSD** | ≤ 1.0% | ≥ 0.985 | [0.92, 1.08] | [0.92, 1.08] | ≤ 0.8 pip (absolut) |
| **XAUUSD** | ≤ 1.0% | ≥ 0.98 | [0.90, 1.10] | [0.90, 1.10] | ≤ 0.10 USD (10 cèntims absolut) |

Unitats: EURUSD en pips/points absoluts; XAUUSD en dòlars absoluts.

> Nota: thresholds són "primer tall"; ajustar després de 1–2 probes reals.

---

**Política activació Mixed:**
- **mixed** només s'activa si Gate A PASS **i** Gate B PASS
- Si Gate A PASS però Gate B FAIL: fallback es permet només com a **fallback-only** per rangs anteriors a `cutover_ts`; no barregem (evitem backtests travessant fonts amb comportament diferent)

Això protegeix que el backtest sigui indiferent a nivell d'estratègia.

#### 2.7.7 Stitching policy (mixed range) — cutover_ts i "no duplicates"

- **cutover_ts** per símbol = primer `ts` existent al primary.

Quan un client demana `[since, to)`:
- Si `to <= cutover_ts` → `X-Data-Source: fallback` (fallback-only ok)
- Si `since >= cutover_ts` → `X-Data-Source: primary`
- Si travessa → mixed només si `compat_check` PASS per aquell símbol; si no → 422 `MIXED_SOURCE_NOT_ALLOWED`

**Policy when mixed disabled:**
- Si `since < cutover_ts` i `to <= cutover_ts` → `fallback-only` ok (retornem 100% fallback)
- Si el rang travessa `cutover_ts` i mixed OFF → 422 `MIXED_SOURCE_NOT_ALLOWED` (no retornem parcial)
- Altra "truncate" (retornar només primary i amagar el forat) → **descartada explícitament** (evita backtests incomplets sense voler)

**Regles "mixed":**
- Prioritat a primary en solapament
- Cap minut duplicat
- Frontera neta: treballar sempre amb bar starts, evitar off-by-one

#### 2.7.8 Roadmap per fases (P4→P8) — DONE + gates

| Fase | Descripció | DONE |
|------|------------|------|
| **P4** | Primary durable recorder v0: startup backfill + runtime gap repair (mateixa font) | soak 2h amb `missing_minutes<=1`, duplicats=0, ts monotònic |
| **P5** | Transparència + coverage: headers `X-Data-Source`, `X-Data-Gaps`, `X-Data-Repair`, i `/coverage` opcional | tests API validen headers + coverage coherent |
| **P6** | Dukascopy provider + `compat_probe` v2 (strategy-level): read-only provider + CLI que calcula Gate A + Gate B | probe imprimeix mètriques i PASS/FAIL; artifact: `datafiles/compat_probe/<ts>_compat_probe_EURUSD_72h.log` |
| **P7** | Mixed gated stitching: mixed ON només si compat_probe PASS; headers reflecteixen primary\|fallback\|mixed | tests stitching "no duplicates" + tests que mixed es denega si FAIL |
| **P8** (futur) | Read-through gap serving (sense contaminar primary): servir gaps via fallback en lectura, no escriure al primary | evidència "gap served by fallback" + compat gate encara més estricte |

---

### 2.8 BACKTEST MODE (planificació, MVP)

El backtest té dues capes diferents (i no s'han de confondre):

1. **Data query backtest (simple)**: demanar candles d'un rang històric (`since/to`) i que el client simuli.
2. **Service simulation backtest (canònic)**: el servei simula temps intern i es comporta com "real":
   * serveix candles del dataset com si arribessin en streaming
   * accepta ordres i les executa en paper sobre el mateix dataset
   * velocitat accelerada (p.ex. x100)

#### 2.8.1 MVP recomanat

* Primer, només **Service simulation backtest** (perquè és el que més s'assembla al real i valida millor).
* Requisits MVP:
  * `MODE=BACKTEST`
  * `BACKTEST_FROM`, `BACKTEST_TO`, `BACKTEST_SPEED`
  * clock intern que "avança minuts"
  * `/ohlcv` i `/candles` responen del dataset local
  * `/orders/open|close` paper sobre preus del minut (mid o OHLC policy)

---

### 2.9 Lab-first (abans de cada fase gran)

Regla de treball:

* Abans d'implementar una fase (PAPER DONE → DATA LAYER → BACKTEST), fem **LAB exploration** per Lighter:
  * què pots obtenir per WS / històric
  * latències i limitacions (symbols, feeds, precisió)
  * quina estratègia de backfill és viable

Això evita construir una arquitectura que després no encaixa amb el venue real.

**coverage_probe (QA lab):** `lab/lighter/scripts/coverage_probe.py` — per símbol (EURUSD, XAU) troba `earliest_ts` i `latest_ts` 1m amb binary search, valida finestra 72h. Invariants: `duplicates_after_dedup==0`, `candles_in_window==expected_minutes`, `missing_minutes==0`, `ts_step_errors==0`. Paginació cursor (next_since=last_ts+60). Fallback httpx amb `Accept-Encoding: identity` si brotli. Rate limit: [Volume Quota](https://apidocs.lighter.xyz/docs/volume-quota-program) (SendTx); candlestick ~60 req/min. Output: `lab/out/coverage_mainnet_<symbol>.json`.

**Decisió (evidència 2026-02):** Lighter recent viable (72h OK) per EURUSD i XAU; Dukascopy per històric pre-Lighter. Evidència: `earliest_ts`, `latest_ts`, `raw_count`, `unique_count`, `duplicates_after_dedup=0`.

---

## 3) Broker API — Contracte v0 (canònic)

**Base URL:** `http://localhost:8000/api/v1/broker`

### 3.1 Paths

| Mètode | Path | Descripció |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/mode` | Mode actual |
| GET | `/venues` | Llista venues disponibles |
| GET | `/pairs` | Llista pairs (requereix `venue`) |
| GET | `/price/latest` | Preu actual (requereix `venue`, `symbol`) |
| GET | `/candles` | Candles OHLCV (sense venue) |
| GET | `/ohlcv/{symbol}` | Candles OHLCV path style (sense venue) |
| GET | `/balance` | Balance compte (requereix `venue`) |
| GET | `/positions` | Posicions obertes (requereix `venue`) |
| GET | `/trades` | Trade history (fills) — CCXT/Freqtrade compatible |
| POST | `/orders/open` | Obrir posició (JSON body) |
| POST | `/orders/close` | Tancar posició (JSON body) |

### 3.2 Endpoints detallats

**Health i meta**

| Path | Params | Response |
|------|--------|----------|
| `GET /health` | - | status, mode, venue, timestamp |
| `GET /mode` | - | mode, is_live, is_paper, is_backtest, venue, market_data_env |
| `GET /venues` | - | venues: string[] |

**Market data**

| Path | Params | Notes |
|------|--------|-------|
| `GET /pairs` | `venue` (required) | Requereix venue; per aquesta instància, només `lighter` |
| `GET /price/latest` | `venue`, `symbol` | bid, ask, mid, timestamp |
| `GET /candles` | `symbol`, `timeframe=1m`, `limit`, `since?`, `to?` | Sense venue. Només 1m |
| `GET /ohlcv/{symbol}` | `tf=1m`, `since?`, `to?`, `limit` | Sense venue. Només 1m |

**Nota:** els endpoints `/candles` i `/ohlcv/{symbol}` poden indicar la font via headers (`X-Data-Source`) i opcionalment `meta=1`.

**Account / Trading**

| Path | Params/Body | Notes |
|------|-------------|-------|
| `GET /balance` | `venue` | usdc, available_margin, used_margin, total_equity, margin_usage_percent |
| `GET /positions` | `venue` | positions[] |
| `GET /trades` | `venue`, `symbol?`, `since?`, `to?`, `limit` (1–5000) | trades[] (trade_id, symbol, side, price, size, fee, timestamp ISO8601) |
| `POST /orders/open` | JSON body | venue, symbol, side (long\|short), collateral, leverage, sl_price?, tp_price? |
| `POST /orders/close` | JSON body | venue, position_id, percent (0, 100] |

### 3.3 Invariants

- **Candles:** no accepten venue; només `timeframe/tf=1m` → si ≠1m: 422 `TIMEFRAME_NOT_SUPPORTED`
- **Adapter:** `/pairs`, `/price/latest`, `/balance`, `/positions`, `/trades`, `/orders/open`, `/orders/close` requereixen `adapter_factory`; si no wired → 503 `ADAPTER_NOT_AVAILABLE`; venue incorrecte → 422 `VENUE_NOT_CONFIGURED`

### 3.4 Errors

Format: `{"detail": "...", "code": "..."}`

| code | status | Descripció |
|------|--------|-------------|
| `ADAPTER_NOT_AVAILABLE` | 503 | adapter_factory no configurat |
| `CANDLE_STORE_NOT_AVAILABLE` | 503 | candle_store no disponible |
| `VENUE_NOT_CONFIGURED` | 422 | venue no configurat en aquesta instància |
| `TIMEFRAME_NOT_SUPPORTED` | 422 | timeframe != "1m" |
| `INVALID_SIDE` | 422 | side no és long ni short |
| `INVALID_PERCENT` | 422 | percent fora de (0, 100] |
| `POSITION_NOT_FOUND` | 404 | position_id no existeix |
| `SYMBOL_NOT_FOUND` | 404 | symbol no existeix |

### 3.5 Samples

**POST /orders/open**

```json
{
  "venue": "lighter",
  "symbol": "ETH",
  "side": "long",
  "collateral": 100,
  "leverage": 20,
  "sl_price": null,
  "tp_price": null
}
```

Response 200: `{ "success": true, "position_id": "lighter:0", "order_id": "...", "executed_price": 3950.0, "executed_size": 0.506, "tx_hash": "0x..." }`

**POST /orders/close**

```json
{
  "venue": "lighter",
  "position_id": "lighter:0",
  "percent": 100
}
```

Response 200: `{"success": true}`

---

## 4) Wiring (main.py / set_broker_deps / VENUE)

- `set_broker_deps(candle_store, adapter_factory, mode, venue)` s’executa al startup (lifespan)
- `GET /venues` reflecteix wiring: `[]` si no hi ha adapter_factory, `["lighter"]` si wired
- **VENUE=lighter:** crea `LighterVenueAdapter`, `adapter.start()`, injecta `adapter_factory`, `adapter.stop()` al shutdown
- **VENUE=lighter + USE_FAKE_PRICE_FEED=1:** sense adapter (broker arrenca sense xarxa); market data usa fake
- **VENUE≠lighter** (o buit): `adapter_factory=None` → endpoints adapter retornen 503; venue incorrecte en query → 422

---

## 5) Data / Storage (TZ NY + ts epoch UTC + 1m only)

- **TZ canònica:** `America/New_York` (partició, queries, NY close style)
- **Layout CSV:** `datafiles/{broker}/{asset}/{timezone}/{YYYY}/{MM}.csv`
- **Format:** `ts,open,high,low,close,volume`; `volume=0` si no existeix
- **Invariant NO GAPS:** seqüència validada; single-writer + escriptura atòmica

### 5.1 Candle semantics (1m) — canònic

- **Timeframe:** només 1m
- **`ts`** és epoch UTC i representa el **start-of-minute** de la candle
- La candle representa l’interval **`[ts, ts+60s)`**
- **Close time** = `ts+60` (no inclòs)
- Una candle és **"tancada/complete"** quan el sistema ja ha passat el boundary `ts+60` i s’ha consolidat l’OHLCV
- Això és la convenció que fa que l’algorisme sàpiga si està operant sobre l’última candle parcial o sobre l’última candle tancada

**Exemple clar:**
- Si `ts=12:34:00`, la candle és de 12:34:00 fins 12:34:59.xxx, i el close és el darrer tick abans de 12:35:00
- `ts = 1739460300` (epoch) → interval `[1739460300, 1739460360)`

**Implicacions:**
- No usar timestamps de "close time" (evita off-by-one minute)
- `since`/`to` en queries han d’interpretar-se respecte el bar start (rang sobre starts)

**Nota "Dukascopy-like":** aquí vol dir start-of-minute timestamp + interval `[ts, ts+60)` i candle tancada a boundary, no necessàriament el mateix calendari/feeds exactes.

**Lighter (evidència P0.3b):** `lab/lighter/scripts/time_semantics_probe.py` — t és UTC start-of-minute. L'API retorna només tancades (latest = now_floor - 60). NO hi ha conversió de TZ al dataset; ts epoch UTC. TZ NY a AGENTS és per particions/display, no per re-etiquetar candles.

**Data contracts (P4):** Candles persistits com UTC start-of-minute epoch; validat per `test_lighter_candles_time_semantics`, `test_lighter_backfill_pagination_dedup`, `test_gap_repair_flow`.

---

## 6) Quality Gates

- **Gate A (bloquejador):** `./test.sh testing/run_all.py` passa (default: MVP Lighter, sense gTrade). gTrade tests opt-in amb `--include-gtrade`.
- **Gate B (bloquejador):** Integration mock SL/TP + Balance passa
- **Gate C (post-milestone):** 3× smoke real OK; 3× e2e trade real OK (`positions_after=0`)
- **WS preflight integration (real broker):** `test_ws_preflight_integration_real.py` — fake feed, no network

Evidència concreta (logs, timestamps) → [docs/ESTAT.md](docs/ESTAT.md)

### 6.0 Env vars (market data)

| Var | Descripció |
|-----|------------|
| `USE_FAKE_PRICE_FEED=1` | Usa FakeLighterPriceFeedClient (sense xarxa). Per tests d'integració. |

### 6.1 Testing (TDD scripts, sense pytest)

**Filosofia:** tests simples en scripts Python (no pytest). Cada test té `main()`, fa `assert`, imprimeix resum, i retorna exit code.

**On són els tests:**

```
testing/
  unit/           # tests purament en memòria (0 network)
  integration/    # fluxos de components (normalment mock)
  api/            # smoke REST/WS contra localhost
  run_all.py      # runner: executa i falla si hi ha errors
```

**Com executar:**

```bash
# Suite MVP Lighter (core+Lighter; default, sense gTrade)
./test.sh testing/run_all.py

# Suite amb gTrade (opt-in; pot fallar sense .env Arbitrum)
./test.sh testing/run_all.py --include-gtrade

# Un test concret
./test.sh testing/unit/test_broker_api.py
./test.sh testing/integration/test_lighter_adapter_sltp.py
```

**"Done" per feature (regla):** Cap feature es considera feta si no inclou: mínim 1 unit/integration test nou, i si toca API: smoke test de l'endpoint.

### 6.2 Plantilla de test (sense pytest)

Exemple de test unitari mínim:

```python
# testing/unit/test_example.py
import sys

def main() -> int:
    x = 2 + 2
    assert x == 4
    print("OK test_example")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Regla: si el test falla, `assert` peta i el runner ho marca com FAILED.

---

## 7) Docker / Runtime (TZ del container)

**Recorda:** Si has canviat codi, reconstruir abans: `docker compose build brokerage`.

Per coherència (logs, display, NY close style):

**docker-compose.yml** — al servei `brokerage`:
```yaml
environment:
  - TZ=America/New_York
  - CANONICAL_TZ=America/New_York
  # ... resta
```

**Dockerfile** (base `python:3.11-slim`):
```dockerfile
RUN apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*
ENV TZ=America/New_York
```

**Verificació:**
```bash
docker compose run --rm brokerage date
docker compose run --rm brokerage python3 -c "import time, datetime; print(datetime.datetime.now()); print(time.tzname)"
```
Hora NY i `('EST','EDT')` quan toca → OK.

> El dataset canònic no depèn del TZ del container: `ts` és epoch UTC. El TZ del container és per display i logs.

### 7.1 Volums Docker — accessibles des del host

**Regla:** Tots els directoris i fitxers persistents dins el container han de ser accessibles des del host. No usar paths que només existeixin dins Docker.

**docker-compose.yml** — volumes amb paths relatius al projecte:
```yaml
volumes:
  - ./datafiles:/datafiles    # Dins container: /datafiles → host: <project>/datafiles
  - ./logs:/app/logs           # Dins container: /app/logs → host: <project>/logs
```

| Path dins container | Path host (relatiu) | Ús |
|---------------------|---------------------|-----|
| `/datafiles` | `./datafiles` | Candles CSV, smoke_runs, ws_soak, freqtrade_runs, e2e_runs, lab_lighter_history |
| `/app/logs` | `./logs` | Logs de l'aplicació |

**Per què:** Evitar que scripts executats des del host (p.ex. `fetch_historical_candles.py`, `run_freqtrade_paper.sh`) no puguin llegir/escriure als mateixos fitxers que el container. Els paths `./` garanteixen que tot està dins l'arrel del projecte i accessible des de host i Docker.

**Si hi ha problemes de permisos:** Els directoris creats per Docker poden quedar amb `root`. Crear-los des del host abans: `mkdir -p datafiles logs`. Si ja hi ha fitxers creats per Docker: `./scripts/fix_datafiles_permissions.sh` (requereix sudo).

**Neteja de logs antics:** Els logs a `datafiles/` (smoke_runs, ws_soak, freqtrade_runs, e2e_runs) es poden acumular. Per eliminar els que ja no calen (conservant evidència ESTAT):
```bash
# Des del host (si tens permisos) o dins Docker:
docker compose run --rm brokerage ./scripts/cleanup_old_logs.sh
```
O manualment: esborrar fitxers a `datafiles/*/` excepte els referenciats a docs/ESTAT.md.

---

## 8) Roadmap curt (no canònic)

- **MVP 100% Lighter:** tot el desenvolupament actual és per Lighter
- ~~Trade history (IVenueAdapter)~~ ✅ P1 DONE
- Maker-first close (opcional)
- Backtest pipeline complet
- **Futur:** gTrade i altres DEX (s’incorporaran després del MVP Lighter)

---

## 9) Changelog curt

* 2026-02-14 — MVP 100% Lighter (documentat); Lighter mainnet FX: Symbol universe (§2.0), Candle semantics 1m canònic (§5.1), Dukascopy-like, evidència WS soak EURUSD
* 2026-02-13 — Unificació API `/api/v1/broker/*`, POST body only, errors consistents, legacy eliminat
* 2026-02-13 — Lighter M1+M2+M3 complet (smoke + e2e evidència a docs/ESTAT.md)
* 2026-02-13 — Docker TZ=America/New_York + tzdata + CANONICAL_TZ

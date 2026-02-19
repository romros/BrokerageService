# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-19
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`
**Venues:** **Lighter (principal — MVP 100%)** · gTrade (futur)
**TZ canònica (config):** `CANONICAL_TZ=America/New_York`
**TZ container (runtime/logs):** `TZ=America/New_York`
**Índex docs:** [docs/INDEX.md](INDEX.md) ← navegació centralitzada
**Doc referència:** [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md)
**Runbook operatiu curt:** [SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md)
**Històric (read-only):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

**Recorda Docker:** Si has canviat codi, reconstruir abans: `docker compose build brokerage`. Vegeu AGENTS §11.

---

## TL;DR

- ✅ **MVP Lighter** DONE: marketdata, SL/TP, balance, reconcile, guards, smoke, e2e
- ✅ **Data Layer** (P4–P7c): backfill, gap repair, headers X-Data, /coverage, /data_status, read-through, stitching gated
- ✅ **Data Layer prod v0** (opt-in): prefetch + writer loop + gates; `DATA_LAYER_ENABLED=1`
- ✅ **Ostium Data Layer prod v0** (opt-in): realtime Ostium (polling) + backfill Dukascopy; `OSTIUM_ENABLED=1`
- ✅ **Broker API** `/api/v1/broker/*` (POST body únic)
- ✅ **Split vNext Phase 1:** 3 serveis autònoms (realtime/historical/trading); entrypoints + role wiring
- ✅ **Split vNext Phase 2:** trading_service → realtime_datalayer via HTTP; QualityGate fail-closed (`application/data/quality_gate.py`)
- 🟡 **gTrade** existent (paper OK); no prioritzat
- ⛔ **Backtest** pendent
- 🧪 **Ostium LAB** — [lab/ostium/README.md](../lab/ostium/README.md); monitor continu via `run_lab.sh ostium-monitor`

> **Focus next:** Trading loop NO_TRADE enforcement quan `quality_gate.is_bad()`.

---

## Arquitectura split vNext — estat de migració

**Estat Phase 1:** Entrypoints reals per servei. Cada servei arrenca només el que li toca (role boundaries).

**Serveis:** `realtime_datalayer`, `historical_datalayer`, `trading_service`. Veure `AGENTS_ARQUITECTURA.md` § Split vNext.

**Què garanteix Phase 1:**
- Cada servei té entrypoint propi: `apps/<servei>/app.py`
- `SERVICE_ROLE` (env) determina què wireja: realtime (ingest), historical (backfill), trading (adapter)
- realtime_datalayer: només data routes (health, data_status, ohlcv, candles); sense /orders
- trading_service: data + trading; sense Ostium ingest ni Data Layer writer
- data_status mai 503 en initializing (realtime)

**Comandes canòniques:**
```bash
# Validar compose split
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml config

# Aixecar els 3 serveis (entrypoints: apps.realtime_datalayer.app, etc.)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer historical_datalayer trading_service

# Realtime DataLayer v1 (servei sol)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer
curl -s http://localhost:8081/health
curl -s http://localhost:8081/status

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build realtime_datalayer

# Phase 2: trading_service consumeix realtime via HTTP (REALTIME_DATALAYER_BASE_URL)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer trading_service
curl -s http://localhost:8010/api/v1/broker/data_status
curl -s "http://localhost:8010/api/v1/broker/coverage?symbol=EURUSD&resolution=1m"
curl -s "http://localhost:8010/api/v1/broker/ohlcv/EURUSD?tf=1m&limit=5"
# Verificar quality gate als logs del trading_service:
docker logs trading_service 2>&1 | grep -E "quality_gate|QUALITY_GATE"
```

**Phase 2 — Quality Gates (fail-closed):**
- `REALTIME_DATALAYER_BASE_URL` set → HTTP reader actiu → `get_ohlcv_with_gate` avalua `X-Data-*` headers
- `QualityGateResult.status`: `ok` (dades netes) | `bad` (gaps/stale/missing headers)
- Trading loop: si `gate.is_bad()` → NO_TRADE, log + reason
- Env override dels llindars: `QUALITY_GATE_MAX_FRESHNESS_SEC` (default 300s), `QUALITY_GATE_MIN_COMPLETENESS` (default 0.95), `QUALITY_GATE_MAX_GAP_S_GATE` (default 180s)
- Fail-closed: si headers `X-Data-Coverage-From/To` absents → `bad/missing_headers`
- Mercat tancat: si `missing_minutes==0` i `max_gap_s==0` → `ok` (no incident, freshness ignorada)

**Estructura:** `apps/<servei>/app.py` (entrypoint), `application/app_factory.py` (create_app role-aware), `packages/shared/realtime_datalayer_client.py` (Phase 2), `application/data/quality_gate.py` (QualityGateEvaluator).

**Docs per subprojecte:**

| Servei | Arquitectura | Estat |
|--------|-------------|-------|
| realtime_datalayer | [arquitectura](../apps/realtime_datalayer/realtime_datalayer_arquitectura.md) | [estat](../apps/realtime_datalayer/realtime_datalayer_estat.md) |
| historical_datalayer | [arquitectura](../apps/historical_datalayer/historical_datalayer_arquitectura.md) | [estat](../apps/historical_datalayer/historical_datalayer_estat.md) |
| trading_service | [arquitectura](../apps/trading_service/trading_service_arquitectura.md) | [estat](../apps/trading_service/trading_service_estat.md) |

**Realtime DataLayer v1 (servei independent):**
- Storage: `datafiles/realtime_datalayer/candles/`, `datafiles/realtime_datalayer/ticks/`
- Retenció: `REALTIME_CANDLES_MAX_HOURS`, `REALTIME_TICKS_MAX_HOURS`
- Docs: `apps/realtime_datalayer/realtime_datalayer_arquitectura.md`, `realtime_datalayer_estat.md`
- Tests curts: `./scripts/run_tests.sh realtime_datalayer`

---

## Tests canònics per focus (vNext)

**Suites curtes:** `./scripts/run_tests.sh <suite>` — focus-driven sense run_all.

| Suite | Comanda | Quan s'usa |
|-------|---------|------------|
| smoke | `./scripts/run_tests.sh smoke` | Validar instal·lació i imports (1 test) |
| core | `./scripts/run_tests.sh core` | foundation/shared (candle_store, gap_validator, etc.) |
| realtime_datalayer | `./scripts/run_tests.sh realtime_datalayer` o `./test.sh testing/run_realtime.py` | Data Layer + Ostium ingest (curt, 0-network) |
| historical_datalayer | `./scripts/run_tests.sh historical_datalayer` | Dukascopy/compat/backfill |
| trading_service | `./scripts/run_tests.sh trading_service` | execució/venue adapters |

**Full suite:** `./test.sh testing/run_all.py` — tot (lent; CI o validació completa).

**Estructura:** `testing/suites/*.txt` (paths), `testing/apps/<servei>/` (tests migrats). La resta a `testing/unit/`, `testing/integration/`, `testing/api/` — pendent de migració.

---

## Data Layer prod v0

**Activar:** `DATA_LAYER_ENABLED=1` (default 0). Prefetch + writer loop + gates.

**Docker prod-ish:** `docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml up -d brokerage`

**Scripts canònics:** `./scripts/run_smoke.sh data-layer` (3 min), `./scripts/run_soak.sh 30 data-layer` (30 min). Artifacts a `datafiles/data_layer_prod_runs/`.

**Startup gate:** `DATA_LAYER_STARTUP_GATE=1` → health=degraded si Data Layer DEGRADED; startup falla si gate ON i prefetch degradat.

**Providers:** LighterCandlestickBackfillProvider (data-layer) | Ostium + DukascopyBackfillProvider (ostium).

**Observabilitat:** `GET /api/v1/broker/data_status` → `symbol_state` + `degrade_reason`.

**Config:** `DATA_LAYER_PREFETCH_MINUTES`, `DATA_LAYER_WARMUP_MINUTES` (default 120), `DATA_LAYER_WRITE_SYMBOLS`, `DATA_LAYER_GATES_MAX_GAP_S`, `DATA_LAYER_GATES_MAX_MISSING_PER_24H`, `DATA_LAYER_STALE_SECONDS`.

**symbol_state:** `ACTIVE` | `DEGRADED`. Si DEGRADED → writer aturat per aquell símbol.

**Perfil Ostium:** `OSTIUM_ENABLED=1` + `DATA_LAYER_WRITE_MODE=realtime_plus_backfill`. Realtime: OstiumCandleIngestService (polling REST); històric/gaps: DukascopyBackfillProvider. `backfill_only` = ingest OFF. Gates market-hours aware: soak en cap de setmana no DEGRADED per stale. `./scripts/run_smoke.sh ostium`, `./scripts/run_soak.sh 30 ostium`.

**Tick recorder (forense):** Opt-in `OSTIUM_TICK_RECORDER_ENABLED=1`. Escriu ticks/snapshots a JSONL (`lab/out/ostium_forensics/daily/YYYYMMDD/<symbol>.jsonl`). Rotació diària + retenció (`OSTIUM_TICK_RETENTION_DAYS`, default 7). Best-effort: no bloqueja candles si el tick write falla. `data_status` inclou `tick_recorder` (enabled, outdir, last_tick_ts, lines_written, dupes_detected per símbol).

**Allowlist + Quarantine (Ostium prod-ish v1):**
- `OSTIUM_SYMBOLS` (default: EURUSD,GBPUSD): allowlist canònica — símbols que Ostium pot ingerir.
- `OSTIUM_QUARANTINE_SYMBOLS` (default: XAUUSD,XAU): símbols en quarantine — no ingest, no primary.
- `ingest_symbols = allowlist - quarantine`. Primary eligibility: `get_ostium_primary_allowed(symbol)` retorna `false` si quarantined (abans de mirar registry).
- `data_status` per símbol: `ingest_allowed`, `primary_eligible`, `quarantined`, `quarantine_reason`.

---

## Ostium ↔ Dukascopy compat (graduation gate)

**Propòsit:** Validar compatibilitat quantitativa Ostium (realtime recorded) vs Dukascopy (fallback històric). Només si **PASS** → `ostium_primary_allowed=true` per aquell símbol.

**Com validar:**
```bash
./scripts/run_compat.sh ostium [symbol]   # default symbol=EURUSD
```

**Artifact path:** `datafiles/compat_reports/<ts>_compat_<symbol>_<Nm>m.json` (ex: `20260217_143022_compat_EURUSD_650m.json`)

**Registry:** `datafiles/compat_reports/ostium_compat_registry.json` — font de veritat per `get_ostium_primary_allowed(symbol)`.

**Permisos (gotcha resolt):** Ostium/data-layer compose usen `user: ${DOCKER_UID}:${DOCKER_GID}` perquè registry i artifacts siguin writable per host. run_smoke.sh i run_soak.sh exporten DOCKER_UID/DOCKER_GID. Si compose manual: `export DOCKER_UID=$(id -u) DOCKER_GID=$(id -g)` abans.

**Execució soak/post-compat:** run_soak data-layer i ostium corre dins Docker (`docker compose run brokerage`) per tenir dukascopy-python i deps (post-compat). run_compat.sh corre al host; si falla import: `pip install dukascopy-python` o executar dins Docker.

**Permisos (user mapping):** Els scripts fan `docker compose run --user "$(id -u):$(id -g)"` per evitar root-owned files a datafiles/compat_reports i artifacts.

**Verdict:** PASS | PARTIAL | FAIL (llindars via `compat_report_service` + constants). PASS → primary allowed; PARTIAL/FAIL → opt-in experimental sense declarar primary.

**PASS ⇒ primary (detall explícit):** Quan `ostium_primary_allowed(symbol)=true` → `primary_source=ostium_recorded`, `mixed_allowed=true`. Headers OHLCV: `X-Data-Source=ostium_recorded` (o `mixed` si rang travessa cutover), `X-Data-Primary-Source=ostium_recorded`. Coverage retorna `source=ostium_recorded`. data_status inclou `primary_allowed_by_symbol[symbol]=true`.

**Estat per símbol (prod-ish v1):**

| Símbol | Compat | Primary allowed | Quarantined |
|--------|--------|-----------------|-------------|
| EURUSD | PASS   | ✅ true         | No          |
| XAUUSD | FAIL   | ❌ false        | Sí (config) |

**Què canvia quan PASS → primary (mini-taula):**

| Aspecte | Sense PASS (opt-in) | Amb PASS (primary) |
|---------|---------------------|--------------------|
| X-Data-Source | `primary` genèric | `ostium_recorded` |
| X-Data-Primary-Source | — | `ostium_recorded` |
| Mixed (rang travessa cutover) | 422 MIXED_SOURCE_NOT_ALLOWED | Stitch fallback + primary |
| coverage source | `primary` | `ostium_recorded` |
| data_status primary_allowed_by_symbol | `false` | `true` |

**Com afecta serving:**
- **Headers:** `X-Data-Source` pot ser `ostium_recorded`, `primary`, `fallback` o `mixed`. `X-Data-Primary-Source: ostium_recorded` quan primary és Ostium.
- **Selecció de font:** Si el rang travessa `cutover_ts`: amb PASS → **mixed** (stitch Dukascopy + Ostium); sense PASS → 422.
- **Read-through:** Fill de gaps requereix compat PASS.
- **Sense PASS:** Mode "opt-in experimental" — es graven dades Ostium però no es declara primary; només primary o fallback per rang.

**Tests:** Unit 0-network: `test_ostium_compat_report_service.py`, `test_compat_registry_ostium_gate.py`, `test_save_ostium_registry_robust.py`. Opt-in real: `./test.sh testing/run_all.py --include-ostium-compat`.

**Graduation run canònic (EURUSD):**
```bash
# 1. Arrancar broker ostium (scripts exporten UID/GID → datafiles writable)
./scripts/run_smoke.sh ostium
# o: ./scripts/run_soak.sh 2 ostium post-compat  # arranca broker si no està up

# 2. Soak + post-compat (2–5 min)
./scripts/run_soak.sh 2 ostium post-compat

# 3. O només compat (si broker ja té dades)
./scripts/run_compat.sh ostium EURUSD
```
Si PASS → `ostium_compat_registry.json` actualitzat, `ostium_primary_allowed=true` per EURUSD. Artifact a `datafiles/data_layer_prod_runs/` i `datafiles/compat_reports/`.

---

## Data Layer readiness gates (prod)

Llindars via env: `DATA_LAYER_GATES_MAX_GAP_S`, `DATA_LAYER_GATES_MAX_MISSING_PER_24H`, `DATA_LAYER_STALE_SECONDS` (defaults a constants.py).

**Gate 0 (core):**
- duplicates=0, ts_step_errors=0
- missing ≤ 1/24h (`DATA_LAYER_GATES_MAX_MISSING_PER_24H`)
- max_gap_s ≤ 180 (`DATA_LAYER_GATES_MAX_GAP_S`)
- stale=0 (`DATA_LAYER_STALE_SECONDS`)

**Cold start / warmup:** Basat en **cobertura recent (24h window)**, no span històric. `observed_open_minutes_24h = expected_open_minutes_24h - missing_minutes_24h` (market-hours aware). Mentre `observed_open_minutes_24h < DATA_LAYER_WARMUP_MINUTES` (default 120), `data_layer_status=warming_up` i no s'aplica gate missing_24h. Soak reporta warming_up (exit 0); no és incident. `data_status` inclou `expected_open_minutes_24h` i `observed_open_minutes_24h` per símbol.

**Market-hours aware (Ostium/profile FX):** Si mercat tancat (cap de setmana, fora d'horari), stale no degrada; missing exclou minuts en intervals tancats. `data_status` inclou `market_open` i `market_state_reason` per símbol.

**Gate 1 (serving):** headers X-Data coherents, coverage coherent, read-through funciona.  
**Gate 2 (ops):** restart safe, data_status 200, logs path, rotació.

| Gate | Criteri | Com validar |
|------|---------|-------------|
| Gate 0 | Data Layer core | `curl data_status` + soak 2m |
| Gate 1 | serving | `curl -I ohlcv \| grep X-Data` |
| Gate 2 | ops | `docker compose down && up` |

```bash
# Docker prod-ish (veure Operativa canònica)
docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml up -d brokerage

# Scripts canònics (profile data-layer)
./scripts/run_smoke.sh data-layer
./scripts/run_soak.sh 30 data-layer

# Manual
curl -s http://localhost:8000/api/v1/broker/data_status
curl -s "http://localhost:8000/api/v1/broker/coverage?symbol=ETH&resolution=1m"
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
./test.sh testing/integration/test_data_layer_soak_metrics.py --minutes 2
```

---

## Evidència recent

| Data | Run | Resultat | Com validar |
|------|-----|----------|-------------|
| 2026-02-17 | `run_all.py` | ✅ passa | `./test.sh testing/run_all.py` |
| 2026-02-17 | Data Layer soak | ✅ 2m: missing=0, dup=0 | `./test.sh testing/integration/test_data_layer_soak_metrics.py --minutes 2` |
| 2026-02-17 | Ostium LAB | 🏃 24h captura en curs | lab/ostium |
| 2026-02-17 | Docs coherents Ostium | ✅ AGENTS + ESTAT + overrides alineats | graduation path, prod-ish opt-in |
| 2026-02-17 | Ostium Recorder prod-ish v1 | ✅ ingest real 1m, gates, data_status ingest_source | write_mode realtime_plus_backfill |
| 2026-02-17 | Ostium compat + graduation gate | ✅ compat report Ostium↔Dukascopy, registry, run_compat.sh | PASS → ostium_primary_allowed |
| 2026-02-17 | Ostium primary serving v1 | ✅ policy per símbol, X-Data-Source=ostium_recorded, data_status primary_allowed_by_symbol | headers + coverage + tests |
| 2026-02-17 | Market-hours aware gates | ✅ is_market_open, closed_intervals; stale/missing ajustats; data_status market_open | soak cap de setmana no DEGRADED |
| 2026-02-17 | Ostium Graduation Loop v1 | ✅ run_soak.sh 30 ostium post-compat; SKIP si no candles; graduation_summary a artifact | `./scripts/run_soak.sh 2 ostium post-compat` (SKIP per falta Dukascopy) |
| 2026-02-18 | Data Layer readiness handshake | ✅ data_status 200 amb initializing; soak wait_for_ready; startup_wait_s a artifact | `./scripts/run_soak.sh 2 ostium post-compat` sense 503 |
| 2026-02-17 | Ostium allowlist + quarantine v1 | ✅ OSTIUM_SYMBOLS, OSTIUM_QUARANTINE_SYMBOLS; EURUSD primary allowed; XAUUSD quarantined | run_soak ostium usa llista canònica |
| 2026-02-18 | run_all.py | ✅ passa (incl. test_ostium_symbol_allowlist, test_data_status_quarantine_flags) | `./test.sh testing/run_all.py` |
| 2026-02-18 | Suites per servei (vNext) | ✅ smoke, core, realtime_datalayer, historical_datalayer, trading_service | `./scripts/run_tests.sh <suite>` |
| 2026-02-18 | Ostium LAB monitor (continuous) | ✅ run_lab.sh ostium-monitor start/stop/status; rotació diària + retenció | `./scripts/run_lab.sh ostium-monitor start` |
| 2026-02-18 | EURUSD graduation (permisos + run canònic) | ✅ user UID:GID a compose; save_ostium_registry atomic; run_compat/run_soak post-compat escriuen registry | `./scripts/run_soak.sh 2 ostium post-compat` |
| 2026-02-18 | Cold-start readiness + permisos | ✅ warmup window (DATA_LAYER_WARMUP_MINUTES); warming_up no DEGRADED; --user a docker run; ESTAT+SAFETY_RUNBOOK | soak cold start reporta warming_up; no root-owned files |
| 2026-02-18 | Warmup basat en cobertura recent 24h | ✅ observed_open_minutes_24h (no span històric); prefetch no falsa warmup; startup gate ignora missing en warmup; warming_up→exit 0 | data_status expected/observed_open_minutes_24h |
| 2026-02-18 | Split vNext scaffold | ✅ apps/, packages/, plantilla_tasca.md, docker-compose.split.yml; AGENTS+ESTAT actualitzats | `docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml config` |
| 2026-02-18 | Split vNext Phase 1 | ✅ SERVICE_ROLE, entrypoints reals, create_app(role), role boundaries; test_service_role_wiring | `./test.sh testing/unit/test_service_role_wiring.py` |
| 2026-02-18 | Split vNext Phase 2 | ✅ trading_service consumeix realtime_datalayer via HTTP (contracte mínim); RealtimeDataLayerClient (packages/shared); IDataLayerReader; REALTIME_DATALAYER_BASE_URL | `./scripts/run_tests.sh trading_service`; `curl -s http://localhost:8010/api/v1/broker/data_status` |
| 2026-02-18 | Realtime DataLayer v1 | ✅ servei autònom; GET /health, /status; storage datafiles/realtime_datalayer/; tests curts run_realtime.py | `./test.sh testing/run_realtime.py`; `curl -s http://localhost:8081/status` |
| 2026-02-18 | Realtime hot-reload | ✅ GET/PUT /symbols; config persistent symbols.json; instrument resolution (spot/perp); add/remove símbols sense restart | `curl -X PUT http://localhost:8081/symbols -d '{"symbols":["EURUSD","XAUUSD"],"apply_mode":"replace"}'` |
| 2026-02-18 | Realtime UI + smoke | ✅ /, /ui, /info, /docs, /openapi.json; auto-refresh 5s/10s/30s; cards per símbol; PUT diff/replace; smoke `./scripts/run_smoke.sh realtime_datalayer` | http://localhost:8081/ ; http://localhost:8081/ui ; http://localhost:8081/docs |
| 2026-02-18 | Realtime market-hours aware | ✅ market_closed no degrada; ingest pausat per símbol; /symbols market_open, market_state_reason, state; dashboard badges+taula; tests test_market_closed_not_degraded, test_pause_resume, test_dashboard_renders_states | `./test.sh testing/run_realtime.py`; XAU closed cap de setmana = OK |
| 2026-02-18 | Realtime Dashboard v2 | ✅ last_price, market_state (open|closed|unknown), state (running|closed|warning|degraded); /status effective_tz, now_utc, now_local; filtres, ordenació, presets FX; test_status_includes_timezone_fields | http://localhost:8081/ui |
| 2026-02-18 | Imports AGENTS compliance | ✅ app_factory: stdlib (datetime, zoneinfo, subprocess, time) a capçalera; lazy imports documentats; tests realtime_datalayer imports a capçalera | AGENTS_ARQUITECTURA.md §6.1 |
| 2026-02-18 | Realtime v2.1 Market-hours Ostium (NY) | ✅ perfils XAU break 16:59–18:10, indices 16:59–18:00, NVDA RTH 09:31–15:59; paused_closed; health no penalitza closed; ages com deltes; next_open_local | apps/realtime_datalayer/market_hours/ |
| 2026-02-18 | Degraded non-blocking + autorecover | ✅ degraded continua polling amb backoff (2s–60s); autorecover quan tick nou; pause només paused_closed; /symbols next_poll_in_s, degrade_reason; UI mostra; tests test_degraded_does_not_stop_polling, test_autorecover_on_new_tick | `./test.sh testing/run_realtime.py` |

**DEGRADED vs CLOSED vs WARNING:** `closed` = mercat tancat (cap de setmana FX/XAU); no és incident. `warning` = market_state=unknown sense dades; no és degraded. `DEGRADED` = errors reals (duplicates, ts_step_errors, stale quan market_open). **Degraded és non-blocking:** continua polling amb backoff (base 2s, max 60s); autorecover quan arriba tick nou; pause només per `paused_closed` (market_closed). `/symbols` inclou `next_poll_in_s`, `degrade_reason`.

**Detall històric:** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

---

## Backlog (properes 48h)

**Objectiu:** activar Data Layer a prod amb prefetch + observability + gates.

**D0 (avui):**
- [ ] Prefetch recent (N hores/dies) a prod env
- [ ] Scheduler (cron/loop) + idempotència
- [ ] Alert mínim: stale>… / missing>… / duplicates>0
- [ ] Rotació artifacts/logs

**D1 (demà):**
- [ ] Soak 6–12h amb prefetch actiu
- [ ] Cutover policy: primary/fallback per símbol (EURUSD especial)
- [ ] Doc "operar data layer" (runbook)

**Com validar:** `curl data_status`; `./scripts/run_soak.sh N data-layer`; `docker compose down && up`.

**Backlog (no compromès):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

**DoD tasca coherència Ostium (2026-02-17):**
- [x] Docs coherents: ESTAT.md i AGENTS_ARQUITECTURA.md no es contradiuen
- [x] Operativa: deploy/compose/overrides/README.md reflecteix profile ostium (opt-in experimental)
- [x] Scripts: run_smoke.sh ostium / run_soak.sh ostium usen override ostium i produeixen artifacts
- [x] Tests: run_all.py passa (default, 0-network); ostium wiring + backfill_only contract

---

## Operativa canònica (scripts + compose profiles)

| Profile | Compose override | Smoke | Soak | Compat |
|---------|------------------|-------|------|--------|
| data-layer | deploy/compose/overrides/data-layer.yml | `run_smoke.sh data-layer` | `run_soak.sh 30 data-layer` | — |
| ws | deploy/compose/overrides/soak.yml | — | `run_soak.sh 15 ws` | — |
| ostium | deploy/compose/overrides/ostium.yml | `run_smoke.sh ostium` | `run_soak.sh 30 ostium` | `run_compat.sh ostium` |

**Graduation loop Ostium:** `./scripts/run_soak.sh 30 ostium post-compat` — soak + compat automàtic al final. Si no hi ha candles suficients o Dukascopy falta → SKIP (exit 0). Artifact inclou `graduation_summary`. Quan acabi la 24h i Dukascopy tingui delay resolt, correr compat 1440: `run_compat.sh ostium` amb `OSTIUM_COMPAT_WINDOW_MINUTES=1440`.

**Readiness handshake:** `data_status` pot estar `initializing` els primers segons; scripts esperen readiness automàticament (`--wait-timeout` default 120s).

**Cold start / warmup:** Durant arrencada freda (coverage < `DATA_LAYER_WARMUP_MINUTES`), `data_layer_status=warming_up` — no és incident. El soak no falla per missing_24h fins superar warmup. Els scripts `run_soak` i `run_smoke` executen dins Docker amb `--user $(id -u):$(id -g)` per evitar root-owned files a datafiles/.

**Regla:** No crear scripts nous ad-hoc. Lògica a `application/tools/*.py`; wrappers a `scripts/*.sh`.

---

## Ostium LAB monitor (continuous)

**Comandes:** `./scripts/run_lab.sh ostium-monitor start|stop|status|logs`

**Rotació diària:** `lab/out/ostium_prices/daily/YYYYMMDD/` + `daily/LATEST_RUN.txt`  
**Retenció:** `OSTIUM_LAB_RETENTION_DAYS=14` (neteja dirs antics)

**Smoke local (documentat, no automatitzat):**
```bash
./scripts/run_lab.sh ostium-monitor start
# esperar 10–20s
./scripts/run_lab.sh ostium-monitor status   # ha de mostrar last_ts per símbol
```

---

## Comandes ràpides

```bash
./test.sh testing/run_all.py
./scripts/run_smoke.sh data-layer
./scripts/run_smoke.sh ostium   # Ostium realtime + Dukascopy backfill
./scripts/run_compat.sh ostium  # Ostium vs Dukascopy compat (graduation gate)
./scripts/run_soak.sh 30 data-layer
./scripts/run_soak.sh 30 ostium
./scripts/run_soak.sh 30 ostium post-compat   # soak + compat automàtic (graduation loop)
./scripts/run_lab.sh ostium-monitor start     # LAB Ostium continuous
./scripts/run_lab.sh ostium-monitor status    # last_ts per símbol
curl -s http://localhost:8000/api/v1/broker/data_status
curl -s "http://localhost:8000/api/v1/broker/coverage?symbol=ETH&resolution=1m"
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml config  # validar
docker compose -f docker-compose.yml -f deploy/compose/overrides/ostium.yml config     # Ostium
docker compose build brokerage
docker compose down && docker compose up -d brokerage
```

**Més comandes:** [_archive/ESTAT_2026Q1.md § Annex](_archive/ESTAT_2026Q1.md)

---

## Notes crítiques

- **EURUSD Lighter REST candlestick: DATA_QUALITY_FAIL** (zero_range alt) → no apte per backtest; no declarar primary històric.
- **WS Candle Collector** és el camí per validar candles WS com a alternativa.
- **XAU PARTIAL** — corr/dir_agree dins llindars; offset acceptable.

---

## Estat per àrees

| Àrea | Estat | Notes |
|------|-------|-------|
| Broker API | ✅ | `/api/v1/broker/*`, POST body |
| Execution (paper/live) | ✅/🟡 | Lighter paper OK; live hardening 90% |
| Data Layer | ✅ | P4–P7c; EURUSD REST candlestick no apte (zero_range) |
| Ostium Data Layer | ✅ | prod v0: Ostium realtime + Dukascopy backfill; `run_smoke.sh ostium` |
| Backtest | ⛔ | Pipeline pendent |
| Ostium LAB | 🧪 | Validació RWA; [lab/ostium/README.md](../lab/ostium/README.md) |


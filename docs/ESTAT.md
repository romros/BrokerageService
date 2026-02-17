# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-17  
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`  
**Venues:** **Lighter (principal — MVP 100%)** · gTrade (futur)  
**TZ canònica (config):** `CANONICAL_TZ=America/New_York`  
**TZ container (runtime/logs):** `TZ=America/New_York`  
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
- 🟡 **gTrade** existent (paper OK); no prioritzat
- ⛔ **Backtest** pendent
- 🧪 **Ostium LAB** — [lab/ostium/README.md](../lab/ostium/README.md)

> **Focus 48h:** Data Layer en producció (prefetch + gates + observability).

---

## Data Layer prod v0

**Activar:** `DATA_LAYER_ENABLED=1` (default 0). Prefetch + writer loop + gates.

**Docker prod-ish:** `docker compose -f docker-compose.yml -f deploy/compose/overrides/data-layer.yml up -d brokerage`

**Scripts canònics:** `./scripts/run_smoke.sh data-layer` (3 min), `./scripts/run_soak.sh 30 data-layer` (30 min). Artifacts a `datafiles/data_layer_prod_runs/`.

**Startup gate:** `DATA_LAYER_STARTUP_GATE=1` → health=degraded si Data Layer DEGRADED; startup falla si gate ON i prefetch degradat.

**Providers:** LighterCandlestickBackfillProvider (data-layer) | Ostium + DukascopyBackfillProvider (ostium).

**Observabilitat:** `GET /api/v1/broker/data_status` → `symbol_state` + `degrade_reason`.

**Config:** `DATA_LAYER_PREFETCH_MINUTES`, `DATA_LAYER_WRITE_SYMBOLS`, `DATA_LAYER_GATES_MAX_GAP_S`, `DATA_LAYER_GATES_MAX_MISSING_PER_24H`, `DATA_LAYER_STALE_SECONDS`.

**symbol_state:** `ACTIVE` | `DEGRADED`. Si DEGRADED → writer aturat per aquell símbol.

**Perfil Ostium:** `OSTIUM_ENABLED=1` + `DATA_LAYER_WRITE_MODE=backfill_only`. Realtime: OstiumCandleIngestService (polling REST); històric/gaps: DukascopyBackfillProvider. `./scripts/run_smoke.sh ostium`, `./scripts/run_soak.sh 30 ostium`.

---

## Data Layer readiness gates (prod)

Llindars via env: `DATA_LAYER_GATES_MAX_GAP_S`, `DATA_LAYER_GATES_MAX_MISSING_PER_24H`, `DATA_LAYER_STALE_SECONDS` (defaults a constants.py).

**Gate 0 (core):**
- duplicates=0, ts_step_errors=0
- missing ≤ 1/24h (`DATA_LAYER_GATES_MAX_MISSING_PER_24H`)
- max_gap_s ≤ 180 (`DATA_LAYER_GATES_MAX_GAP_S`)
- stale=0 (`DATA_LAYER_STALE_SECONDS`)

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

---

## Operativa canònica (scripts + compose profiles)

| Profile | Compose override | Smoke | Soak |
|---------|------------------|-------|------|
| data-layer | deploy/compose/overrides/data-layer.yml | `run_smoke.sh data-layer` | `run_soak.sh 30 data-layer` |
| ws | deploy/compose/overrides/soak.yml | — | `run_soak.sh 15 ws` |
| ostium | deploy/compose/overrides/ostium.yml | `run_smoke.sh ostium` | `run_soak.sh 30 ostium` |

**Regla:** No crear scripts nous ad-hoc. Lògica a `application/tools/*.py`; wrappers a `scripts/*.sh`.

---

## Comandes ràpides

```bash
./test.sh testing/run_all.py
./scripts/run_smoke.sh data-layer
./scripts/run_smoke.sh ostium   # Ostium realtime + Dukascopy backfill
./scripts/run_soak.sh 30 data-layer
./scripts/run_soak.sh 30 ostium
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


# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-17  
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`  
**Venues:** **Lighter (principal — MVP 100%)** · gTrade (futur)  
**TZ canònica (config):** `CANONICAL_TZ=America/New_York`  
**TZ container (runtime/logs):** `TZ=America/New_York`  
**Doc referència:** [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md)  
**Runbook operatiu:** [SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md) (incidents, health checks, kill switches)  
**Històric (read-only):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

**Recorda Docker:** Si has canviat codi, reconstruir abans: `docker compose build brokerage`. Vegeu AGENTS §11.

---

## TL;DR

- ✅ **MVP Lighter** DONE: marketdata, SL/TP, balance, reconcile, guards, smoke, e2e
- ✅ **Data Layer** (P4–P7c): backfill, gap repair, headers X-Data, /coverage, /data_status, read-through, stitching gated
- ✅ **Data Layer prod v0** (opt-in): prefetch + writer loop + gates; `DATA_LAYER_ENABLED=1`
- ✅ **Broker API** `/api/v1/broker/*` (POST body únic)
- 🟡 **gTrade** existent (paper OK); no prioritzat
- ⛔ **Backtest** pendent
- 🧪 **Ostium LAB** en curs — [lab/ostium/README.md](../lab/ostium/README.md)

> **Focus 48h:** Data Layer en producció (prefetch + gates + observability).

---

## Data Layer prod v0

**Activar:** `DATA_LAYER_ENABLED=1` (default 0). Prefetch + writer loop + gates.

**Config:** `DATA_LAYER_PREFETCH_MINUTES`, `DATA_LAYER_WRITE_SYMBOLS`, `DATA_LAYER_GATES_MAX_GAP_S`, `DATA_LAYER_GATES_MAX_MISSING_PER_24H`, `DATA_LAYER_STALE_SECONDS`.

**symbol_state:** `ACTIVE` | `DEGRADED`. Si DEGRADED → writer aturat per aquell símbol; `data_status` mostra `degrade_reason`.

---

## Data Layer readiness gates (prod)

**Gate 0 (core):**
- duplicates=0
- ts_step_errors=0
- missing ≤ 1/24h
- max_gap_s ≤ 180
- stale=0

**Gate 1 (serving):** headers X-Data coherents, coverage coherent, read-through funciona.  
**Gate 2 (ops):** restart safe, data_status 200, logs path, rotació.

| Gate | Criteri | Com validar |
|------|---------|-------------|
| Gate 0 | Data Layer core | `curl data_status` + soak 2m |
| Gate 1 | serving | `curl -I ohlcv \| grep X-Data` |
| Gate 2 | ops | `docker compose down && up` |

```bash
curl -s http://localhost:8000/api/v1/broker/data_status
curl -s "http://localhost:8000/api/v1/broker/coverage?symbol=ETH&resolution=1m"
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
./test.sh testing/integration/test_data_layer_soak_metrics.py --minutes 2
```

---

## Evidència recent

| Data | Run | Resultat | Artifact/Log |
|------|-----|----------|--------------|
| 2026-02-17 | `run_all.py` | ✅ passa | testing/run_all.py |
| 2026-02-17 | Ostium compat (388c) | ✅ PARTIAL — Corr 0.976, Dir 92.7% | lab/out/ostium_compat_EURUSD_388c.json |
| 2026-02-17 | Lab Ostium | 🏃 24h captura en curs | lab/ostium |
| 2026-02-17 | P7 Mixed gated | ✅ stitching primary/fallback/mixed | — |
| 2026-02-17 | Data Layer soak | ✅ 2m: missing=0, dup=0 | test_data_layer_soak_metrics |

**Detall:** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

---

## Backlog (properes 48h)

**Objectiu:** activar Data Layer a prod amb prefetch + observability + gates.

**D0:**
- [ ] Prefetch recent (N hores/dies) a prod env
- [ ] Scheduler (cron/loop) + idempotència
- [ ] Alert mínim: stale>… / missing>… / duplicates>0
- [ ] Rotació artifacts/logs

**D1:**
- [ ] Soak 6–12h amb prefetch actiu
- [ ] Cutover policy: primary/fallback per símbol (EURUSD especial)
- [ ] Doc "operar data layer" (runbook)

**Top 10:** Prefetch job, Scheduler, Gates automàtics, Rotació, Cutover policy, Degradació segura, Soak 6–12h, Doc runbook, Ostium compat 1440c, Backtest pipeline.

**Backlog complet:** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

---

## Comandes ràpides

```bash
./test.sh testing/run_all.py
curl -s http://localhost:8000/api/v1/broker/data_status
curl -s "http://localhost:8000/api/v1/broker/coverage?symbol=ETH&resolution=1m"
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
./test.sh testing/integration/test_data_layer_soak_metrics.py --minutes 2
./test.sh testing/run_all.py --include-data-layer-soak
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
| Backtest | ⛔ | Pipeline pendent |
| Ostium LAB | 🧪 | Validació RWA; [lab/ostium/README.md](../lab/ostium/README.md) |


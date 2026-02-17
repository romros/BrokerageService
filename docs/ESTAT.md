# ESTAT DEL PROJECTE — BrokerageService

**Data:** 2026-02-17  
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`  
**Venues:** **Lighter (principal — MVP 100%)** · gTrade (futur)  
**TZ canònica (config):** `CANONICAL_TZ=America/New_York`  
**TZ container (runtime/logs):** `TZ=America/New_York`  
**Doc referència:** [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md)  
**Runbook operatiu:** [SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md) (incidents, health checks, kill switches)  
**Històric complet (read-only):** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

**Recorda Docker:** Si has canviat codi, reconstruir abans: `docker compose build brokerage`. Vegeu AGENTS §11.

---

## TL;DR

- ✅ **MVP Lighter** DONE: marketdata, SL/TP, balance, reconcile, guards, smoke, e2e
- ✅ **Data Layer** (P4–P7c): backfill, gap repair, headers X-Data, /coverage, /data_status, read-through, stitching gated
- ✅ **Broker API** `/api/v1/broker/*` (POST body únic)
- 🟡 **gTrade** existent (paper OK); no prioritzat
- ⛔ **Backtest** pendent
- 🧪 **Ostium LAB** en curs — [lab/ostium/README.md](../lab/ostium/README.md)

> **Focus 48h:** Data Layer en producció (prefetch + gates + observability).

---

## Focus (48h) — Data Layer en producció

**Objectiu:** activar Data Layer a prod amb **prefetch** + observability + gates, sense afectar execució.

### Pla
- **D0:** Prefetch recent + scheduler + gates/alerts mínims.
- **D1:** Soak 6–12h + cutover policy per símbol + degradació segura.

### Deliverables
- Prefetch job (idempotent) per backfill recent (N hores/dies) + persistència
- Gates automàtics: duplicates/ts_step/missing/max_gap/stale
- Health endpoints: `/data_status`, `/coverage`, headers X-Data-*
- Runbook curt (SAFETY_RUNBOOK) validat

---

## Gates de producció

| Gate | Criteri | Com validar |
|------|---------|-------------|
| **Gate 0 (Data Layer core)** | duplicates=0, ts_step_errors=0, missing≤1/24h, max_gap_s≤180, stale=0 | `curl data_status` + soak 2m |
| **Gate 1 (serving)** | headers X-Data coherents, coverage coherent, read-through funciona | `curl -I ohlcv \| grep X-Data` |
| **Gate 2 (ops)** | restart safe, data_status 200, logs path, rotació | `docker compose down && up` |

```bash
curl -s http://localhost:8000/api/v1/broker/data_status
curl -s "http://localhost:8000/api/v1/broker/coverage?symbol=ETH&resolution=1m"
curl -I "http://localhost:8000/api/v1/broker/ohlcv/ETH?tf=1m&limit=5" | grep X-Data
./test.sh testing/integration/test_data_layer_soak_metrics.py --minutes 2
```

---

## Checklist Avui / Demà

**Avui (D0):**
- [ ] Prefetch recent (N hores/dies) a prod env
- [ ] Scheduler (cron/loop) + idempotència
- [ ] Alert mínim: stale>… / missing>… / duplicates>0
- [ ] Rotació artifacts/logs

**Demà (D1):**
- [ ] Soak 6–12h amb prefetch actiu
- [ ] Cutover policy: primary/fallback per símbol (EURUSD especial)
- [ ] Doc curta "operar data layer" (runbook)

---

## Estat per àrees

| Àrea | Estat | Notes |
|------|-------|-------|
| Broker API | ✅ | `/api/v1/broker/*`, POST body |
| Execution (paper/live) | ✅/🟡 | Lighter paper OK; live hardening 90% |
| Data Layer | ✅ | P4–P7c; EURUSD REST candlestick no apte (zero_range) |
| Backtest | ⛔ | Pipeline pendent |
| Ostium LAB | 🧪 | Validació RWA; [lab/ostium/README.md](../lab/ostium/README.md) |

---

## Evidència recent (5 ítems)

| Run | Resultat |
|-----|----------|
| `run_all.py` | ✅ passa (default) |
| **Ostium compat (388c)** | ✅ PARTIAL — Corr 0.976, Dir 92.7% |
| **Lab Ostium** | 🏃 24h captura en curs (lab/ostium) |
| **P7 Mixed gated** | ✅ stitching primary/fallback/mixed |
| **Data Layer soak** | ✅ 2m testnet: missing=0, dup=0 |

**Detall:** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

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

## Backlog curt (Top 10 — Data Layer prod)

1. Prefetch job (backfill recent + idempotència)
2. Scheduler (cron/loop) per prefetch
3. Gates automàtics (Gate 0 + alerting mínim)
4. Rotació artifacts/logs
5. Cutover policy per símbol (EURUSD)
6. Degradació segura (fallback-only si compat FAIL)
7. Soak 6–12h amb prefetch actiu
8. Doc "operar data layer" (runbook)
9. Ostium compat 1440c (PASS esperat)
10. Backtest pipeline (contracte)

**Backlog complet:** [_archive/ESTAT_2026Q1.md](_archive/ESTAT_2026Q1.md)

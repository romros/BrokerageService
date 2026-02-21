# historical_datalayer — Estat

**Data:** 2026-02-21

---

## Responsabilitat

**Fa:** backfill Dukascopy (mes a mes, idempotent), emmagatzematge Parquet particionat mensual, Coverage API (index per mes), OHLCV long-range via DuckDB, mixed stitching parquet+realtime (policy `HISTORICAL_MIXED_ALLOWED`), cron operatiu (`run_historical_cron.sh`), endpoints `/health` i `/status` (Phase C), cron metadata (`_cron/last_runs.json`).

**Accés extern:** via nginx `datalayer-proxy` → `host:8081/data/*` (strip prefix → port intern 8002).

**No fa:** ingest en temps real (→ realtime_datalayer), execució d'ordres (→ trading_service), market-hours gating (→ realtime_datalayer).

---

## Estat actual

| Aspecte | Estat | Notes |
|---------|-------|-------|
| Servei autònom | ✅ | Port intern 8002; accés extern via nginx :8081/data/* |
| GET /health | ✅ | Phase C: ok/degraded per failed months |
| GET /status | ✅ | Phase C: coverage per símbol + cron metadata |
| Backfill Dukascopy | ✅ | Phase 15: `run_historical_backfill.py` + Parquet particionat mensual, idempotent |
| Parquet storage | ✅ | Phase 15: `infrastructure/storage/parquet_store.py` |
| DuckDB query layer | ✅ | Phase 16: `infrastructure/query/duckdb_query_service.py`; predicate pushdown |
| Coverage index | ✅ | Phase 18: `application/data/coverage_index.py`; done/failed/empty per mes |
| Coverage API | ✅ | Phase 19/C: `GET /coverage/{symbol}?tf=1m` (via nginx: `:8081/data/coverage/{symbol}`) |
| OHLCV long-range | ✅ | Phase 19/C: DuckDB cursor `next_ts`; via nginx: `:8081/data/ohlcv/{symbol}` |
| Mixed stitching | ✅ | Phase 20: `mixed_ohlcv_stitcher.py`; realtime guanya en overlap |
| Cron operatiu | ✅ | Phase 20/C: `scripts/run_historical_cron.sh` daily/retry-failed/gap-repair + escriu metadata |
| Cron metadata | ✅ | Phase C: `application/data/cron_metadata.py`; `_cron/last_runs.json` (atomic) |
| Backfill ops robustos | ✅ | Phase 18: retries/backoff, resume per coverage index, `--dry-run`, `--stop-after` |
| Compat engine | 🟡 | Existent al LAB; pendent integrar al servei |
| Compat registry | 🟡 | `compat_reports/ostium_compat_registry.json` via `run_compat.sh` |
| Tests curts | ✅ | `./scripts/run_tests.sh historical_datalayer` |

---

## Fitxers i directoris canònics

```
infrastructure/storage/parquet_store.py           # ParquetCandleStore (write/read/range/coverage)
infrastructure/query/duckdb_query_service.py      # DuckDB sobre Parquet
application/data/coverage_index.py               # Coverage index JSON per mes
application/data/mixed_ohlcv_stitcher.py         # Stitch Parquet + realtime
application/tools/run_historical_backfill.py     # Runner backfill mes a mes
application/api/data_routes.py                   # GET /ohlcv/{symbol} + /coverage/{symbol}
scripts/run_historical_cron.sh                   # Cron daily/retry-failed/gap-repair

testing/apps/core/test_candle_store.py           # Tests ParquetCandleStore
testing/suites/historical_datalayer.txt          # Suite canònica

datafiles/historical_parquet/
  {SYMBOL}/tf=1m/year={YYYY}/month={MM}/data.parquet
  _coverage/{SYMBOL}_tf1m.json                  # Coverage index
datafiles/compat_reports/                        # Compat Ostium↔Dukascopy (opt-in)
```

---

## Comandes canòniques

```bash
# Arrencar servei (+ nginx proxy per tenir :8081/data/*)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d historical_datalayer datalayer-proxy

# Verificar via nginx (port públic unificat)
curl -s http://localhost:8081/data/health
curl -s http://localhost:8081/data/status
curl -s "http://localhost:8081/data/coverage/EURUSD?tf=1m"
curl -s "http://localhost:8081/data/ohlcv/EURUSD?tf=1m&limit=5"

# Verificar directament al servei (port intern, sense nginx)
curl -s http://localhost:8002/health
curl -s "http://localhost:8002/coverage/EURUSD?tf=1m"

# Backfill (dry-run primer!)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml run --rm \
  historical_datalayer python3 application/tools/run_historical_backfill.py \
  --symbol EURUSD --from 2003-01-01 --to 2024-12-31 --dry-run --stop-after 2

# Backfill real (2 mesos de prova)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml run --rm \
  historical_datalayer python3 application/tools/run_historical_backfill.py \
  --symbol EURUSD --from 2003-01-01 --to 2024-12-31 --stop-after 2 --sleep 1

# Pipeline complet (backfill + backtest)
./scripts/run_full_pipeline.sh --symbol EURUSD --from 2020-01-01 --to 2020-12-31

# Cron operatiu
./scripts/run_historical_cron.sh daily --symbol EURUSD          # backfill d'ahir
./scripts/run_historical_cron.sh retry-failed --symbol EURUSD  # reintentar fallats
./scripts/run_historical_cron.sh gap-repair --days 7 --symbol EURUSD  # repair 7 dies

# Compat Ostium↔Dukascopy (opt-in LAB)
./scripts/run_compat.sh ostium EURUSD

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build historical_datalayer

# Tests
./scripts/run_tests.sh historical_datalayer
```

---

## DoD del servei

- [x] Backfill Dukascopy funcional (Phase 15: Parquet particionat)
- [x] DuckDB query layer sobre Parquet (Phase 16)
- [x] Coverage API (Phase 19)
- [x] OHLCV long-range cursor multi-mes (Phase 19)
- [x] Mixed stitching parquet+realtime (Phase 20)
- [x] Cron operatiu (Phase 20)
- [x] `/health` i `/status` operatius (Phase C)
- [x] Cron metadata persistida `_cron/last_runs.json` (Phase C)
- [x] Nginx proxy `datalayer-proxy` — port 8081 unificat (Phase C)
- [ ] Compat report genera registry correcte (opt-in LAB)
- [ ] Tests de role wiring passen

---

## Què NO entra aquí

- **Ingest en temps real** → `apps/realtime_datalayer/` (OstiumCandleIngestService)
- **Execució d'ordres / SL/TP** → `apps/trading_service/`
- **Market-hours gating (engine)** → `apps/realtime_datalayer/market_hours/`
- **Quality gates fail-closed** → `application/data/quality_gate.py` (trading_service)

---

## Notes

- **Dukascopy:** Via `dukascopy-python`. Suporta EURUSD, XAUUSD (i altres FX majors). GBPJPY i equities limitats.
- **Compat LAB → prod:** Els scripts `lab/ostium/scripts/ostium_vs_dukascopy_compat_v2.py` han validat EURUSD (PASS_BACKTEST corr=0.968) i XAUUSD (PASS_BACKTEST corr=0.977). Pendent integrar lògica al servei.
- **realtime_datalayer independent:** Per disseny, historical_datalayer NO té dependència obligatòria de realtime_datalayer; el stitching és opcional (`HISTORICAL_MIXED_ALLOWED=1`).
- **Mixed policy:** `HISTORICAL_MIXED_ALLOWED=1` (default) → merge parquet+realtime, realtime guanya en overlap → `source=mixed`. Desactivar: `HISTORICAL_MIXED_ALLOWED=0`.

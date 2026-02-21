# trading_service — Estat

**Data:** 2026-02-21

---

## Responsabilitat

**Fa:** execució d'ordres (paper/live) via Lighter, reconcile, guards, balance/positions, consum de candles del realtime_datalayer via HTTP + quality gate fail-closed, backtesting (BacktestMarketDataProvider, runner offline, API REST).

**No fa:** ingest en temps real (→ realtime_datalayer), backfill Dukascopy (→ historical_datalayer), emmagatzematge de candles (→ realtime/historical datalayer).

---

## Estat actual

| Aspecte | Estat | Notes |
|---------|-------|-------|
| Servei autònom | ✅ | `docker compose -f ... up -d trading_service` |
| GET /health | ✅ | Via broker routes |
| GET /balance, /positions, /trades | ✅ | Lighter MVP 100% |
| POST /orders/open, /close | ✅ | Guards + idempotència |
| Reconcile | ✅ | Operatiu |
| Consumeix realtime_datalayer via HTTP | ✅ | Phase 2: HttpDataLayerReader + RealtimeDataLayerClient |
| Quality gate fail-closed | ✅ | Phase 5: gate=BAD → 422 DATA_QUALITY_GATE_BAD; cap venue call |
| NO_TRADE enforçat | ✅ | Phase 5: `_do_order_open` comprova gate via `assert_data_quality_ok()` |
| BacktestMarketDataProvider | ✅ | Phase 10: registry-aware (ostium_local / dukascopy fallback) |
| Backtest runner offline | ✅ | Phase 11: `simple_trend`, KPIs, artifact JSON |
| Backtest API REST | ✅ | Phase 12: `POST /backtests/run` + `GET /backtests/runs/{run_id}` |
| Ingest propi | ✅ N/A | NO té ingest ni writer (per disseny) |
| Tests curts | ✅ | `./scripts/run_tests.sh trading_service` |

---

## Fitxers i directoris canònics

```
apps/trading_service/app.py                         # Entrypoint (SERVICE_ROLE=trading_service)
application/data/
  data_layer_reader.py                              # IDataLayerReader + HttpDataLayerReader + LocalDataLayerReader
  quality_gate.py                                   # QualityGateEvaluator (fail-closed)
  backtest_market_data.py                           # BacktestMarketDataProvider (registry-aware)
application/tools/
  run_backtest.py                                   # Backtest runner offline (simple_trend + KPIs)
application/api/
  backtest_routes.py                               # POST /backtests/run + GET /backtests/runs/{run_id}
  broker_routes.py                                 # /orders/open, /close, /balance, /positions
packages/shared/realtime_datalayer_client.py      # RealtimeDataLayerClient (HTTP)
strategies/simple_trend_df.py                     # Estratègia exemple Freqtrade-style

testing/apps/trading_service/                     # Tests integrats
testing/suites/trading_service.txt                # Suite canònica

datafiles/backtests/                              # Artifacts backtest (JSON)
```

---

## Comandes canòniques

```bash
# Arrencar servei (sol o amb realtime_datalayer)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d trading_service
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer trading_service

# Verificar
curl -s http://localhost:8010/api/v1/broker/health
curl -s http://localhost:8010/api/v1/broker/balance?venue=lighter
curl -s http://localhost:8010/api/v1/broker/positions?venue=lighter

# Quality gate als logs
docker logs trading_service 2>&1 | grep -E "quality_gate|QUALITY_GATE"

# OHLCV via HTTP (si REALTIME_DATALAYER_BASE_URL configurat)
curl -s "http://localhost:8010/api/v1/broker/data_status"
curl -s "http://localhost:8010/api/v1/broker/coverage?symbol=EURUSD&resolution=1m"
curl -s "http://localhost:8010/api/v1/data/ohlcv/EURUSD?tf=1m&limit=5"

# Backtest API
curl -s -X POST http://localhost:8010/api/v1/backtests/run \
  -H 'Content-Type: application/json' \
  -d '{"symbol": "EURUSD", "days": 1}' | python3 -m json.tool

# Backtest offline (sense Docker)
./scripts/run_backtest_offline.sh EURUSD 1

# Rebuild (si has canviat codi)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build trading_service

# Tests
./scripts/run_tests.sh trading_service
```

---

## DoD del servei

- [x] Ordres open/close funcionen amb Lighter (paper mode)
- [x] Consumeix candles del realtime_datalayer via HTTP (Phase 2: HttpDataLayerReader)
- [x] Quality gate fail-closed (Phase 5: gate=BAD → 422, cap venue call)
- [x] NO_TRADE enforçat (`_do_order_open` comprova gate)
- [x] BacktestMarketDataProvider registry-aware (Phase 10)
- [x] Backtest runner offline + KPIs (Phase 11)
- [x] Backtest API REST (Phase 12)
- [ ] Reconcile i guards completament validats
- [ ] Tests de role wiring passen (no /orders en realtime_datalayer)

---

## Què NO entra aquí

- **Ingest Ostium en temps real** → `apps/realtime_datalayer/`
- **Backfill Dukascopy / Parquet** → `apps/historical_datalayer/`
- **Emmagatzematge de candles** → `datafiles/realtime_datalayer/` o `datafiles/historical_parquet/`
- **gTrade exec** → opt-in `--include-gtrade`; no CI

---

## Notes

- **Mode paper:** Per defecte `MODE=paper`. Live trading requereix `ENABLE_LIVE_TRADING=1` explícit.
- **Venue Lighter:** MVP 100% completat. gTrade i Ostium execution pendents.
- **Quality gate env vars:** `QUALITY_GATE_MAX_FRESHNESS_SEC` (default 300s), `QUALITY_GATE_MIN_COMPLETENESS` (default 0.95), `QUALITY_GATE_MAX_GAP_S_GATE` (default 180s).
- **Sense REALTIME_DATALAYER_BASE_URL:** usa `LocalDataLayerReader` (dades locals); quality gate retorna `ok` directament.
- **Phase 2 (completada):** trading_service llegeix candles del realtime_datalayer via HTTP. `HttpDataLayerReader` + `QualityGateEvaluator` fail-closed. Si no configurat, usa data layer local.

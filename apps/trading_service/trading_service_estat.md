# trading_service — Estat

**Data:** 2026-02-21

---

## Responsabilitat

**Fa:** execució d'ordres (paper/live) via Lighter, reconcile, guards, balance/positions, consum de candles del realtime_datalayer via HTTP + quality gate fail-closed, backtesting (BacktestMarketDataProvider, runner offline, API REST).

**Accés extern:** Via nginx `datalayer-proxy` → `host:8081/trade/*` (strip prefix → port intern 8010). `/backtests/*` → `/api/v1/backtests/*` (alias). Accessible directament a `:8010` per debug intern.

**No fa:** ingest en temps real (→ realtime_datalayer), backfill Dukascopy (→ historical_datalayer), emmagatzematge de candles (→ realtime/historical datalayer).

**Phase E (completada):** TradingCore extret de broker_routes. Quality gate + venue dispatch desacoblats de HTTP.
**Phase F (completada):** Paper-first com a default. Venues legacy (lighter, gtrade) opt-in via `ENABLE_LEGACY_VENUES=1`. OstiumExecutionAdapter scaffold wired (exec = NotImplementedError fins Phase G).

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
| TradingCore (Phase E) | ✅ | broker_routes delega a TradingCore; errors domain-level |
| Paper-first (Phase F) | ✅ | VENUE="" → paper adapter per defecte |
| OstiumExecutionAdapter scaffold (Phase F) | ✅ | VENUE=ostium → scaffold wired; exec NotImplementedError |
| Legacy venues opt-in (Phase F) | ✅ | ENABLE_LEGACY_VENUES=1 per lighter/gtrade |

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

# Verificar via gateway (port públic unificat — Phase D)
curl -s http://localhost:8081/trade/api/v1/broker/health
curl -s http://localhost:8081/trade/api/v1/broker/data_status
curl -s http://localhost:8081/backtests/runs

# Verificar directament al servei (port intern, per debug)
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
- [x] TradingCore (Phase E): broker_routes delega, errors domain-level
- [x] Paper-first (Phase F): VENUE="" → paper adapter
- [x] OstiumExecutionAdapter scaffold (Phase F): wired, exec NotImplementedError
- [x] Legacy venues opt-in (Phase F): ENABLE_LEGACY_VENUES=1
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

- **Paper-first (Phase F):** Per defecte `VENUE=""` → paper adapter. Segur i funcional sense config de venue.
- **Legacy venues opt-in:** `VENUE=lighter` o `VENUE=gtrade` requereixen `ENABLE_LEGACY_VENUES=1`. Sense opt-in → 503.
- **Ostium scaffold:** `VENUE=ostium` → OstiumExecutionAdapter wired; exec NotImplementedError fins Phase G.
- **Mode paper:** Per defecte `MODE=paper`. Live trading requereix `ENABLE_LIVE_TRADING=1` explícit.
- **Venue Lighter:** MVP 100% completat. gTrade i Ostium execution pendents.
- **Quality gate env vars:** `QUALITY_GATE_MAX_FRESHNESS_SEC` (default 300s), `QUALITY_GATE_MIN_COMPLETENESS` (default 0.95), `QUALITY_GATE_MAX_GAP_S_GATE` (default 180s).
- **Sense REALTIME_DATALAYER_BASE_URL:** usa `LocalDataLayerReader` (dades locals); quality gate retorna `ok` directament.
- **Phase 2 (completada):** trading_service llegeix candles del realtime_datalayer via HTTP. `HttpDataLayerReader` + `QualityGateEvaluator` fail-closed. Si no configurat, usa data layer local.

---

## Phase G — OstiumExecutionAdapter MVP (2026-02-21)

**Status**: ✅ Implementat (0-network tests verds, smoke opt-in disponible)

### Implementació

| Component | Fitxer | Estat |
|-----------|--------|-------|
| `IOstiumClient` | `infrastructure/venues/ostium/ostium_client.py` | ✅ |
| `OstiumClient` (real) | idem | ✅ (requereix SDK + web3) |
| `FakeOstiumClient` (test stub) | idem | ✅ |
| `OstiumExecutionAdapter` | `infrastructure/venues/ostium/ostium_execution_adapter.py` | ✅ MVP |
| Tests 0-network (23) | `testing/apps/trading_service/test_ostium_execution_adapter_unit.py` | ✅ |
| Smoke opt-in | `scripts/smoke_ostium_exec.sh` | ✅ |

### Capacitats MVP

- ✅ `open_position` → `OstiumClient.open_trade` → `OrderResult(success=True, position_id='ostium:{pair_id}:{trade_index}')`
- ✅ `close_position` → `OstiumClient.close_trade` (obté preu automàticament)
- ✅ `update_sl` / `update_tp` → no-op (SDK testnet no suporta; log WARNING)
- ✅ `get_open_positions` → brute-force `getOpenTrade` (0-9 per pair, 10 RPC calls)
- ✅ `health_check` → `OstiumClient.health()` (fetch EUR/USD price)
- ✅ `get_latest_price` → `OstiumClient.get_price(base, quote)`
- ⚠️ `get_trade_history` → `[]` (subgraph testnet no indexa)
- ⚠️ `get_pairs` → `[]` (subgraph testnet no indexa)
- ⚠️ `get_balance` → `NotImplementedError` (pendent)
- ⚠️ `get_position_metrics` → `NotImplementedError` (pendent)

### Limitacions conegudes

- SL/TP via `update_sl`/`update_tp`: no-op MVP (SDK testnet no exposa endpoint)
- `get_open_positions` requereix conèixer trader_address (disponible en `OstiumClient` real)
- Subgraph testnet buit → `get_trade_history` / `get_pairs` retornen `[]`
- `percent` en `close_position` ignorat MVP (sempre 100%)

### Smoke test (opt-in)

```bash
ENABLE_OSTIUM_LIVE_SMOKE=1 OSTIUM_PRIVATE_KEY=0x... ./scripts/smoke_ostium_exec.sh
```

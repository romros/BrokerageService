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
- **Ostium exec:** `VENUE=ostium` → OstiumExecutionAdapter (Phase H: balance, metrics, idempotència open/close; smoke verifica tancament).
- **Mode paper:** Per defecte `MODE=paper`. Live trading requereix `ENABLE_LIVE_TRADING=1` explícit.
- **Venue Lighter:** MVP 100% completat. gTrade i Ostium execution pendents.
- **Quality gate env vars:** `QUALITY_GATE_MAX_FRESHNESS_SEC` (default 300s), `QUALITY_GATE_MIN_COMPLETENESS` (default 0.95), `QUALITY_GATE_MAX_GAP_S_GATE` (default 180s).
- **Sense REALTIME_DATALAYER_BASE_URL:** usa `LocalDataLayerReader` (dades locals); quality gate retorna `ok` directament.
- **Phase 2 (completada):** trading_service llegeix candles del realtime_datalayer via HTTP. `HttpDataLayerReader` + `QualityGateEvaluator` fail-closed. Si no configurat, usa data layer local.

---

## Phase G + H — OstiumExecutionAdapter MVP i safe live (2026-02-21)

**Status**: ✅ Implementat (0-network tests verds, smoke opt-in amb verificació de tancament)

### Implementació

| Component | Fitxer | Estat |
|-----------|--------|-------|
| `IOstiumClient` | `infrastructure/venues/ostium/ostium_client.py` | ✅ |
| `OstiumClient` (real) | idem | ✅ (requereix SDK + web3) |
| `FakeOstiumClient` (test stub) | idem | ✅ |
| `OstiumExecutionAdapter` | `infrastructure/venues/ostium/ostium_execution_adapter.py` | ✅ Phase H |
| Tests 0-network (23+) | `testing/apps/trading_service/test_ostium_execution_adapter_unit.py` | ✅ |
| Smoke opt-in | `scripts/smoke_ostium_exec.sh` | ✅ (Phase H: STEP 5 verifica tancament) |

### Capacitats MVP (Phase G) + safe live (Phase H)

- ✅ `open_position` → `OstiumClient.open_trade` → `OrderResult` amb position_id; **idempotent** si `client_order_id` (disc `datafiles/trade_ids.jsonl`)
- ✅ `close_position` → `OstiumClient.close_trade`; **idempotent** (si get_trade_info retorna collateral=0 → True sense cridar SDK)
- ✅ `update_sl` / `update_tp` → no-op (SDK testnet no suporta; log WARNING)
- ✅ `get_open_positions` → brute-force `getOpenTrade` (0-9 per pair)
- ✅ `health_check` → `OstiumClient.health()` (fetch EUR/USD price)
- ✅ `get_latest_price` → `OstiumClient.get_price(base, quote)`
- ✅ **`get_balance`** → USDC ERC-20 balanceOf + used_margin (suma collateral posicions obertes)
- ✅ **`get_position_metrics`** → open_price, current_price, pnl manual (o SDK si disponible), liquidation_price
- ⚠️ `get_trade_history` → `[]` (subgraph no funciona (ni testnet ni mainnet))
- ⚠️ `get_pairs` → `[]` (subgraph no funciona (ni testnet ni mainnet))

### Limitacions conegudes

- SL/TP via `update_sl`/`update_tp`: no-op MVP (SDK testnet no exposa endpoint)
- `get_open_positions` requereix trader_address (disponible en `OstiumClient` real)
- Subgraph no disponible → `get_trade_history` / `get_pairs` retornen `[]`
- `percent` en `close_position` ignorat MVP (sempre 100%)

### Smoke test (opt-in, Phase H)

Valida: health → open → close → **get_open_positions confirma que la posició ja no apareix**.

```bash
ENABLE_OSTIUM_LIVE_SMOKE=1 OSTIUM_PRIVATE_KEY=0x... ./scripts/smoke_ostium_exec.sh
```

---

## Phase I — Live Trading Guardrails + Preflight (2026-02-22)

**Status**: ✅ Implementat (0-network tests verds)

### Components nous

| Component | Fitxer | Estat |
|-----------|--------|-------|
| `assert_order_caps_ok` | `application/services/live_guards.py` | ✅ |
| `assert_symbol_allowed` | idem | ✅ |
| `MAX_COLLATERAL_USD`, `MAX_LEVERAGE`, `LIVE_SYMBOL_ALLOWLIST` | `application/config/live_guards_config.py` | ✅ |
| `LIVE_TRADING_DISABLED`, `RISK_LIMIT_EXCEEDED` | `application/api/error_codes.py` | ✅ |
| Integració guards a `TradingCore.open_order()` | `application/trading/trading_core.py` | ✅ |
| `GET /preflight` endpoint | `application/api/broker_routes.py` | ✅ |
| Tests 0-network (15) | `testing/apps/trading_service/test_live_trading_guardrails.py` | ✅ |
| Smoke e2e via gateway | `scripts/smoke_trade_ostium_gateway.sh` | ✅ (opt-in) |

### Guards actius (mode live)

| Guard | Env var | Default | Comportament |
|-------|---------|---------|--------------|
| Kill switch | `ENABLE_LIVE_TRADING` | `0` | `LiveTradingDisabledError` si 0 |
| Max collateral | `MAX_COLLATERAL_USD` | `50.0` | `RiskLimitExceededError` si superat |
| Max leverage | `MAX_LEVERAGE` | `10.0` | `RiskLimitExceededError` si superat |
| Symbol allowlist | `LIVE_SYMBOL_ALLOWLIST` | `"EURUSD,XAUUSD"` | `RiskLimitExceededError` si no a la llista |
| Max posicions | `MAX_OPEN_POSITIONS` | `1` | `RiskLimitExceededError` si superat |

**Mode paper → tots els guards desactivats** (bypass automàtic).

### Endpoint preflight

```
GET /api/v1/broker/preflight?venue=ostium&symbol=EURUSD
```
Retorna: `venue`, `mode`, `live_enabled`, `risk_caps`, `checks` (data_quality, venue_health, live_enabled), `ready` (boolean).

### Smoke via gateway (opt-in)

```bash
ENABLE_LIVE_TRADING=1 ENABLE_OSTIUM_LIVE_SMOKE=1 OSTIUM_PRIVATE_KEY=0x... \
  ./scripts/smoke_trade_ostium_gateway.sh
```
Flux: preflight → open (via `:8081/trade/*`) → close → confirm tancament via `/positions`.

---

## Phase J — client_order_id end-to-end (2026-02-22)

**Status**: ✅ Implementat (0-network tests verds)

### Canvis

| Component | Fitxer | Canvi |
|-----------|--------|-------|
| `OrderOpenRequest` | `application/api/models.py` | Camp `client_order_id: Optional[str] = None` (backward compat) |
| `TradingCore.open_order()` | `application/trading/trading_core.py` | Passa `client_order_id=getattr(req, "client_order_id", None)` al adapter |
| Tests 0-network (5) | `testing/apps/trading_service/test_client_order_id_plumbing.py` | ✅ |
| Smoke idempotència | `scripts/smoke_trade_idempotency_gateway.sh` | opt-in via gateway |

### Per què `client_order_id`

`OstiumExecutionAdapter.open_position()` ja tenia idempotència basada en `client_order_id` (disc `datafiles/trade_ids.jsonl`), però `TradingCore` passava `client_order_id=None` hardcoded. Ara el camp és visible a l'API i flueix fins al venue adapter:

```
POST /orders/open { ..., "client_order_id": "my_order_uuid" }
  → TradingCore.open_order(req)
    → adapter.open_position(..., client_order_id=req.client_order_id)
      → OstiumExecutionAdapter: si ID ja vist → retorna position_id existent (no nova TX)
```

**Sense `client_order_id`** (default None): comportament anterior, sense idempotència.

### Smoke idempotència (opt-in)

```bash
ENABLE_LIVE_TRADING=1 ENABLE_OSTIUM_LIVE_SMOKE=1 OSTIUM_PRIVATE_KEY=0x... \
  ./scripts/smoke_trade_idempotency_gateway.sh
```
Flux: open × 2 amb same `client_order_id` → assert `position_id` igual → close.

---

## Phase K — Canary routing + Single-position guard + Reconciliació (2026-02-22)

**Status**: ✅ Implementat (0-network tests verds)

### Components nous

| Component | Fitxer | Estat |
|-----------|--------|-------|
| `resolve_effective_venue` | `application/services/canary_router.py` | ✅ |
| `assert_no_open_position_for_symbol` | `application/services/position_guard.py` | ✅ |
| `reconcile_open` / `reconcile_close` | `application/services/reconcile.py` | ✅ |
| Integració a `TradingCore` | `application/trading/trading_core.py` | ✅ |
| `POSITION_ALREADY_OPEN` error code | `application/api/error_codes.py` | ✅ |
| Captura 409 a `broker_routes` | `application/api/broker_routes.py` | ✅ |
| Tests 0-network (18) | `testing/apps/trading_service/test_canary_routing.py` | ✅ |

### Canary routing

Env vars:
| Var | Default | Descripció |
|-----|---------|------------|
| `TRADING_CANARY_MODE` | `paper` | `paper` \| `ostium` \| `split` |
| `OSTIUM_CANARY_SYMBOLS` | `""` (tots) | Símbolss que van a ostium en mode `split` |

**Mode `paper`** (default segur): totes les ordres a paper venue.
**Mode `ostium`**: totes les ordres a ostium (live real).
**Mode `split`**: ostium si symbol en `OSTIUM_CANARY_SYMBOLS`, paper altrament.

El canary **no interfereix** si el venue demanat NO és `ostium` (e.g. `venue=paper`).

**Flux open_order** (ordre de guards):
```
1. Quality gate (data quality)
2. Canary routing: resolve_effective_venue(req.venue, req.symbol)
3. Live guards (kill switch + risk caps) — live only
4. Single-position guard: no duplicats per symbol
5. adapter.open_position(...)
6. Reconcile post-open (best-effort)
```

### Single-position guard

`assert_no_open_position_for_symbol(adapter, symbol, venue)`:
- Crida `adapter.get_open_positions()` i comprova si ja n'hi ha per `symbol`
- Si sí → `PositionAlreadyOpenError` → HTTP 409 + `POSITION_ALREADY_OPEN`
- Actiu en **tots els modes** (paper i live)

### Reconciliació mínima (best-effort)

- `reconcile_open`: post-open, confirma que la posició apareix → WARNING si no
- `reconcile_close`: post-close, confirma que desapareix → WARNING si no
- **Mai bloquejant**: qualsevol error → `WARNING` i continua

### Recomanació rollout

```bash
# Pas 1: paper (segur, default)
TRADING_CANARY_MODE=paper

# Pas 2: split — EURUSD a ostium, resta paper
TRADING_CANARY_MODE=split OSTIUM_CANARY_SYMBOLS=EURUSD

# Pas 3: ostium — tot a ostium (live real)
TRADING_CANARY_MODE=ostium ENABLE_LIVE_TRADING=1
```

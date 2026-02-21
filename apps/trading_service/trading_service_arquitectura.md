# trading_service — Arquitectura

**Servei:** trading_service
**Propòsit:** Execució d'ordres (open/close/sl-tp), balance, positions, trades. Consumeix Data Layer per preu i candles. Sense ingest ni writer propi.

---

## Components

| Component | Funció |
|-----------|--------|
| **IVenueAdapter** | Abstracció de venue (Lighter, gTrade, Ostium) |
| **OrderRouter** | Enruta ordres a l'adapter correcte |
| **Guards / Reconcile** | Idempotència, guardes pre-execució, reconcile |
| **DataLayer client** | Llegeix candles/preu del realtime_datalayer via HTTP |

---

## API Surface

| Ruta | Mètode | Descripció |
|------|--------|------------|
| `/api/v1/broker/health` | GET | Health del servei |
| `/api/v1/broker/pairs` | GET | Parells disponibles (`?venue=`) |
| `/api/v1/broker/balance` | GET | Balance (`?venue=`) |
| `/api/v1/broker/positions` | GET | Posicions obertes (`?venue=`) |
| `/api/v1/broker/trades` | GET | Historial trades (`?venue=`) |
| `/api/v1/broker/orders/open` | POST | Obrir ordre |
| `/api/v1/broker/orders/close` | POST | Tancar ordre |

---

## Dependències externes

| Dependència | Rol |
|-------------|-----|
| `realtime_datalayer` (HTTP) | Preu actual i candles 1m (via `BROKER_URL`) |
| `historical_datalayer` (HTTP, opcional) | Candles històriques per stitching (`HISTORICAL_URL`) |
| Venue API (Lighter/gTrade) | Execució real d'ordres |

---

## Config (Env)

| Env | Default | Descripció |
|-----|---------|------------|
| `MODE` | paper | paper \| live |
| `VENUE` | lighter | lighter \| gtrade \| ostium |
| `ENABLE_LIVE_TRADING` | 0 | Guard live trading |
| `LIGHTER_*` | — | Config Lighter (URL, key, etc.) |
| `BROKER_URL` | http://realtime_datalayer:8001 | URL Data Layer (candles) |
| `HISTORICAL_URL` | — | URL Historical DataLayer (opcional) |

---

## Boundaries

- **NO** ingest propi (NO Ostium polling, NO Dukascopy)
- **NO** escriptura de candles/ticks
- **NO** backfill
- Llegeix candles via `BROKER_URL` (realtime_datalayer) o `HISTORICAL_URL` (historical_datalayer)
- Executa ordres exclusivament via `IVenueAdapter`

---

## TradingCore (Phase E)

| Component | Fitxer |
|-----------|--------|
| `TradingCore` | [`application/trading/trading_core.py`](../../application/trading/trading_core.py) |

Responsabilitat: orquestra open/close d'ordres — quality gate → venue dispatch.
`broker_routes._do_order_open` / `_do_order_close` deleguen a `TradingCore`.

Errors domain-level (sense HTTP):
- `AdapterNotAvailableError` — adapter_factory no configurat → 503
- `VenueNotConfiguredError` — venue no disponible → 422
- `DataQualityGateBadError` — gate=BAD → 422 `DATA_QUALITY_GATE_BAD` (fail-closed)
- `MarketNotFoundError` — símbol no trobat → 404

---

## Venue Selection Policy (Phase F)

| Env | Default | Descripció |
|-----|---------|------------|
| `VENUE` | `""` (paper) | paper \| ostium \| lighter\* \| gtrade\* |
| `ENABLE_LEGACY_VENUES` | `0` | 1 per habilitar venues legacy (lighter, gtrade) |

**Paper-first:** si `VENUE=""` o `VENUE=paper` → `PaperVenueAdapter` (default segur).

**Ostium scaffold:** `VENUE=ostium` → `OstiumExecutionAdapter` (wired, exec = `NotImplementedError` fins Phase G).

**Legacy opt-in:** `VENUE=lighter` o `VENUE=gtrade` requereixen `ENABLE_LEGACY_VENUES=1`.
Sense opt-in, `adapter_factory=None` → `AdapterNotAvailableError` → 503.

| Venue | Adapter | Disponible |
|-------|---------|------------|
| `paper` (default) | `PaperVenueAdapter` | ✅ sempre |
| `ostium` | `OstiumExecutionAdapter` (scaffold) | ✅ wired; exec NotImplementedError |
| `lighter` | `LighterVenueAdapter` | opt-in (`ENABLE_LEGACY_VENUES=1`) |
| `gtrade` | — | opt-in (`ENABLE_LEGACY_VENUES=1`); sense adapter exec |

Adapter: [`infrastructure/venues/ostium/ostium_execution_adapter.py`](../../infrastructure/venues/ostium/ostium_execution_adapter.py)

---

## Deploy

```bash
# Aixecar (split compose)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d trading_service

# Rebuild si hi ha canvis de codi
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build trading_service

# Verificar
curl -s http://localhost:8010/api/v1/broker/health
```

---

## Tests

```bash
./scripts/run_tests.sh trading_service
```

---

## OstiumExecutionAdapter (Phase G)

| Component | Fitxer |
|-----------|--------|
| `IOstiumClient` | [`infrastructure/venues/ostium/ostium_client.py`](../../infrastructure/venues/ostium/ostium_client.py) |
| `OstiumClient` | idem — implementació real (ostium_python_sdk + web3) |
| `FakeOstiumClient` | idem — stub per 0-network tests |
| `OstiumExecutionAdapter` | [`infrastructure/venues/ostium/ostium_execution_adapter.py`](../../infrastructure/venues/ostium/ostium_execution_adapter.py) |

**Position ID**: `ostium:{pair_id}:{trade_index}`

**Open**: `IOstiumClient.open_trade(pair_id, is_long, collateral, leverage, at_price)` → receipt → position_id

**Close**: `IOstiumClient.close_trade(pair_id, trade_index, at_price)` (preu obtingut automàticament)

**SL/TP**: `IOstiumClient.update_sl / update_tp` (no-op MVP — SDK testnet no suporta)

**get_open_positions**: brute-force `getOpenTrade` via Web3 contract call (0..9 per pair)

**Subgraph**: NO disponible en testnet → `get_trade_history` / `get_pairs` retornen `[]`

**Smoke opt-in**: `ENABLE_OSTIUM_LIVE_SMOKE=1 ./scripts/smoke_ostium_exec.sh`

**Tests**: `testing/apps/trading_service/test_ostium_execution_adapter_unit.py` (23 tests, 0-network)

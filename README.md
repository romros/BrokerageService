# BrokerageService — Ostium-first Broker Gateway

API REST per execució i marketdata (`/api/v1/broker/*`, `/api/v1/data/*`). **Venue canònic: Ostium** (testnet → mainnet). Arquitectura **split** (realtime + historical + trading).

**Docs:** [docs/ESTAT.md](docs/ESTAT.md) · [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md)

---

## Prerequisits

- Docker + Docker Compose
- Python 3.11+ (per tests locals)
- `lab/ostium/.env` amb `RPC_URL`, `PRIVATE_KEY` (copia de `lab/ostium/.env.example`)

---

## Quick Start

```bash
# Tests (0-network per defecte)
./test.sh testing/run_all.py

# Ostium LIVE — happy path canònic (up stack + smoke)
./scripts/up_ostium_live.sh

# Smoke only (trading_service ja arrencat)
./scripts/run_ostium_live_smoke.sh --recreate --clean
```

---

## Arquitectura split — dues bases d'accés

### 1. Directe (trading_service sol, debug/smoke)

**Base:** `http://127.0.0.1:8010`

- Broker: `GET /api/v1/broker/health`, `POST /api/v1/broker/orders/open`, etc.
- Data: `GET /api/v1/data/ohlcv/{symbol}`
- Backtests: `POST /api/v1/backtests/run`, `GET /api/v1/backtests/runs/{run_id}`

**Ús:** Smoke E2E (`BASE_URL=http://127.0.0.1:8010` evita timeout nginx).

### 2. Proxy unificat (gateway single-port)

**Base:** `http://127.0.0.1:8081`

| Prefix | Servei | Exemple |
|--------|--------|---------|
| `/trade/*` | trading_service:8010 | `/trade/api/v1/broker/health` |
| `/data/*` | historical_datalayer:8002 | `/data/ohlcv/EURUSD`, `/data/coverage/EURUSD` |
| `/realtime/*` | realtime_datalayer:8082 | `/realtime/health`, `/realtime/ui` |
| `/backtests/*` | trading_service (alias) | `/backtests/run`, `/backtests/runs/{id}` |

---

## Endpoints (via proxy, base `http://127.0.0.1:8081`)

### Broker API — `/trade/api/v1/broker/*`

| Mètode | Path (complet) | Descripció |
|--------|----------------|------------|
| GET | `/trade/api/v1/broker/health` | Health check |
| GET | `/trade/api/v1/broker/mode` | Mode (paper/live), market_data_env |
| GET | `/trade/api/v1/broker/venues` | Venues disponibles |
| GET | `/trade/api/v1/broker/pairs?venue=` | Parells per venue |
| GET | `/trade/api/v1/broker/price/latest?venue=&symbol=` | Preu actual |
| GET | `/trade/api/v1/broker/ohlcv/{symbol}` | Candles OHLCV 1m |
| GET | `/trade/api/v1/broker/coverage?symbol=` | Coverage per símbol |
| GET | `/trade/api/v1/broker/data_status` | Data Layer telemetria |
| GET | `/trade/api/v1/broker/balance?venue=` | Balance per venue |
| GET | `/trade/api/v1/broker/positions?venue=` | Posicions obertes |
| GET | `/trade/api/v1/broker/trades?venue=` | Historial trades |
| GET | `/trade/api/v1/broker/operations/{operation_id}` | Estat operació |
| GET | `/trade/api/v1/broker/preflight?venue=&symbol=` | Preflight per ordre live |
| POST | `/trade/api/v1/broker/orders/open` | Obrir posició (JSON) |
| POST | `/trade/api/v1/broker/orders/close` | Tancar posició (JSON) |

### Data API — `/data/*`

| Mètode | Path (complet) | Descripció |
|--------|----------------|------------|
| GET | `/data/ohlcv/{symbol}` | Candles OHLCV (Parquet/DuckDB) |
| GET | `/data/coverage/{symbol}` | Coverage index per símbol |
| GET | `/data/health` | Health historical |
| GET | `/data/status` | Status + cron metadata |

### Realtime — `/realtime/*`

| Mètode | Path (complet) | Descripció |
|--------|----------------|------------|
| GET | `/realtime/health` | Health realtime |
| GET | `/realtime/status` | Data status per símbol |
| GET | `/realtime/symbols` | Símbols actius |
| GET | `/realtime/ui` | Dashboard web |
| GET | `/realtime/info` | Info servei |

### Backtest API — `/trade/api/v1/backtests/*` o `/backtests/*`

| Mètode | Path (complet) | Descripció |
|--------|----------------|------------|
| POST | `/trade/api/v1/backtests/run` o `/backtests/run` | Executar backtest |
| GET | `/trade/api/v1/backtests/runs/{run_id}` o `/backtests/runs/{run_id}` | Resultat backtest |

Exemple `POST /trade/api/v1/broker/orders/open`:
```json
{"venue": "ostium", "symbol": "EURUSD", "side": "long", "collateral": 5, "leverage": 2}
```

---

## Documentació

- [docs/ESTAT.md](docs/ESTAT.md) — Estat, evidència, comandes canòniques
- [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md) — Arquitectura, contractes, invariants
- [docs/INDEX.md](docs/INDEX.md) — Índex navegació

---

## Contribuir

1. Llegir [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md)
2. Executar `./test.sh testing/run_all.py`
3. Actualitzar [docs/ESTAT.md](docs/ESTAT.md) si cal

---

MIT

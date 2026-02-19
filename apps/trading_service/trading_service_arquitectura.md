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

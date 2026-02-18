# trading_service

**Propòsit:** Broker i execució (orders, balance, positions, trades). Consumeix Data Layer per preu/candles.

---

## Purpose

- Execució d'ordres (open/close/sltp) via IVenueAdapter
- Balance, positions, trades
- Reconcile, guards, idempotència
- Consumeix candles/preu del realtime_datalayer (o historical per backtest)

---

## Run

**Compose profile:** `docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d trading_service`

**Env vars clau:**
- `MODE`, `VENUE`, `ENABLE_LIVE_TRADING`
- `LIGHTER_*` (Lighter exec)
- `BROKER_URL` → `http://realtime_datalayer:8001` (candles)
- `HISTORICAL_URL` → `http://historical_datalayer:8002` (opcional)

---

## API surface (previst)

- `GET /api/v1/broker/pairs?venue=...`
- `GET /api/v1/broker/balance?venue=...`
- `GET /api/v1/broker/positions?venue=...`
- `GET /api/v1/broker/trades?venue=...`
- `POST /api/v1/broker/orders/open`
- `POST /api/v1/broker/orders/close`
- `GET /api/v1/broker/health`

---

## Data

**Escriu:** — (execució via venue API)  
**Llegeix:** realtime_datalayer (candles), historical_datalayer (stitching)  
**Format:** REST JSON; candles via read-through

---

## Health / status

- `GET /api/v1/broker/health` → 200 si OK
- Depèn de Data Layer per health degradat

---

## DoD del servei

- [ ] Ordres open/close funcionen correctament
- [ ] Consumeix candles del realtime_datalayer
- [ ] Reconcile i guards operatius

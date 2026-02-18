# realtime_datalayer

**Propòsit:** Servei de dades en temps real (Ostium recorder 24/7) i servei de candles/ticks recents.

---

## Purpose

- Gravar ticks i candles 1m des d'Ostium (recording 24/7)
- Servir candles recents i ticks via API
- Font primària per trading en temps real

---

## Run

**Compose profile:** `docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d realtime_datalayer`

**Env vars clau:**
- `OSTIUM_ENABLED=1`
- `DATA_LAYER_WRITE_MODE=realtime_plus_backfill`
- `OSTIUM_SYMBOLS`, `OSTIUM_QUARANTINE_SYMBOLS`
- `DATA_LAYER_ENABLED=1`

---

## API surface (previst)

- `GET /candles?symbol=...&timeframe=1m&limit=...&since?&to?`
- `GET /ohlcv/{symbol}?tf=1m&limit=...`
- `GET /data_status`
- `GET /coverage?symbol=...&resolution=1m`
- `GET /health`

---

## Data

**Escriu:** `candle_store` (CSV), tick recorder → `lab/out/ostium_forensics/daily/`  
**Llegeix:** Ostium REST `/latest-price`, Dukascopy (backfill/gaps)  
**Format:** `ts,open,high,low,close,volume` (ts = epoch UTC start-of-minute)

---

## Health / status

- `GET /health` → 200 si OK
- `GET /data_status` → symbol_state, ingest_source, primary_allowed_by_symbol

---

## DoD del servei

- [ ] Ostium recorder actiu i grava candles 1m
- [ ] API candles/data_status respon correctament
- [ ] Gates (stale, missing, dupes) aplicats; data_status coherent

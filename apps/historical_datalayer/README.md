# historical_datalayer

**Propòsit:** Dukascopy, backfill, compat i export. Consumeix dades del realtime per stitching i prehistòria.

---

## Purpose

- Backfill històric (Dukascopy 1m)
- Compat reports (Ostium vs Dukascopy) per graduation gate
- Stitching primary/fallback (gated per compat)
- Export i compatibilitat per backtest

---

## Run

**Compose profile:** `docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d historical_datalayer`

**Env vars clau:**
- `DATA_LAYER_WRITE_MODE=backfill_only` (o consumir de realtime)
- `DATA_LAYER_ENABLED=1`
- `DATAFILES_ROOT`, `CANONICAL_TZ`
- Connexió a `realtime_datalayer` per candles recents (hostname)

---

## API surface (previst)

- `GET /candles?symbol=...&timeframe=1m&since?&to?` (rang històric)
- `GET /coverage?symbol=...&resolution=1m`
- `POST /compat/run` (trigger compat report)
- `GET /data_status` (estat stitching, cutover_ts)

---

## Data

**Escriu:** compat_reports, artifacts backfill  
**Llegeix:** Dukascopy (dukascopy-python), realtime_datalayer (HTTP)  
**Format:** mateix CSV candles; registry `ostium_compat_registry.json`

---

## Health / status

- `GET /health` → 200 si OK
- `GET /data_status` → cutover_ts, mixed_allowed, compat_status

---

## DoD del servei

- [ ] Backfill Dukascopy funcional
- [ ] Compat report genera registry correcte
- [ ] Stitching gated per compat PASS; mixed coherent

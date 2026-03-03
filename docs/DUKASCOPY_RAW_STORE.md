# RAW Dukascopy M1 BI5 BID (BS.T9.07)

Capa **RAW** canònica i immutable per Dukascopy M1 BID (fitxers `.bi5`), per símbol i dia.

## Objectiu

- No dependre del Parquet derivat (que pot canviar d’algorisme).
- Poder re-derivar Parquet quan calgui.
- Sync **incremental** en background, **resumible** i **no-corruptible**.

## Layout (disc)

Arrel configurable via `DATAFILES_ROOT` (default `/datafiles`):

```
{DATAFILES_ROOT}/dukascopy_raw/m1_bi5_bid/
  {SYMBOL}/
    watermark.json
    year=YYYY/
      month=MM/
        day=DD/
          BID_candles_min_1.bi5
          manifest.json
```

### manifest.json (per dia)

```json
{
  "symbol": "EURUSD",
  "date": "2025-03-09",
  "source_url": "https://datafeed.dukascopy.com/datafeed/EURUSD/2025/02/09/BID_candles_min_1.bi5",
  "bytes": 12345,
  "sha256": "...",
  "downloaded_at": "2026-03-03T12:00:00Z"
}
```

### watermark.json (per símbol)

```json
{
  "last_complete_day": "2026-03-02",
  "last_attempt_day": "2026-03-03",
  "last_success_at": "...",
  "last_error": null
}
```

## Guardrails

- **No-delete:** res d’esborrar raw; només afegir.
- **Immutable:** un cop escrit un dia, no es reescriu (només amb `force: true` a la API).
- **Atòmic:** descàrrega a `.tmp` → validar (size>0) → `rename` a `.bi5`; `manifest.json.tmp` → `manifest.json`.

## API

| Mètode | Path | Descripció |
|--------|------|------------|
| POST | `/api/v1/data/raw/dukascopy/sync` | Inicia sync; body: `{"symbols":["EURUSD"],"from_date":"2024-01-01","to_date":"2024-01-07","force":false}`. Retorna `job_id`. |
| GET | `/api/v1/data/raw/dukascopy/status` | Watermarks per símbol, job en curs, últims jobs. |
| GET | `/api/v1/data/raw/dukascopy/jobs/{job_id}` | Progrés del job (days_done, days_total, status, last_error). |

(En historical_datalayer sense prefix: `/raw/dukascopy/sync`, etc.)

## Símbols

Font única: variable d’entorn **`SYMBOLS`** (ex: `EURUSD,XAUUSD`). Default: `EURUSD,XAUUSD`. Documentat a `raw_sync_worker.get_supported_symbols()`.

## Scheduler incremental

- `RAW_SYNC_ENABLED=1` (o `true`/`yes`) activa el loop.
- `RAW_SYNC_INTERVAL_MIN=60`: cada 60 minuts.
- `RAW_SYNC_TAIL_DAYS=7`: sincronitza els últims 7 dies per cada símbol (sense `force`).

## Jobs i lock

- Jobs persistits a `{DATAFILES_ROOT}/jobs/raw_sync/{job_id}.json`.
- Lock: `{DATAFILES_ROOT}/jobs/raw_sync.lock`. Només un job en execució alhora; el segon retorna error.

## Comandes de verificació

```bash
# Status (watermarks, job en curs)
curl -s http://localhost:8081/api/v1/data/raw/dukascopy/status

# Iniciar sync (1 setmana, 1 símbol)
curl -s -X POST http://localhost:8081/api/v1/data/raw/dukascopy/sync \
  -H "Content-Type: application/json" \
  -d '{"symbols":["EURUSD"],"from_date":"2024-01-01","to_date":"2024-01-07"}'

# Progrés d’un job
curl -s http://localhost:8081/api/v1/data/raw/dukascopy/jobs/<job_id>
```

## Codi

- `infrastructure/venues/dukascopy/raw_bi5_store.py` — RawBi5M1Store (path_for_day, exists_day, write_day_atomic, watermark).
- `infrastructure/venues/dukascopy/raw_sync_worker.py` — RawSyncWorker, get_supported_symbols(), jobs, lock.
- Routes: `application/api/data_routes.py` (POST/GET raw/dukascopy/*).
- Inicialització i scheduler: `application/app_factory.py` (lifespan).

## Rollback

Desactivar `RAW_SYNC_ENABLED`. No cal desfer res (raw és additiu).

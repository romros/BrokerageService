# RAW Dukascopy M1 BI5 BID (BS.T9.07)

Capa **RAW** canònica i immutable per Dukascopy M1 BID (fitxers `.bi5`), per símbol i dia.

És una **capa interna** — no té endpoints públics. Forma part del pipeline:

```
RAW store (.bi5/dia)  →  Parquet (mes)  →  DuckDB query
```

## Objectiu

- Tenir les dades brutes al disc, immutables i independents de qualsevol algorisme de processament.
- Poder re-derivar el Parquet amb un algorisme diferent sense re-baixar res.
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

- **No-delete:** res d'esborrar raw; només afegir.
- **Immutable:** un cop escrit un dia, no es reescriu (llevat de `force=True` explícit).
- **Atòmic:** descàrrega a `.tmp` → validar (size>0) → `rename`; `manifest.json.tmp` → `manifest.json`.

## Scheduler incremental (docker-compose.split.yml)

Configurat a `historical_datalayer`:

| Variable | Valor | Significat |
|----------|-------|-----------|
| `RAW_SYNC_ENABLED` | `1` | Activa el cron |
| `RAW_SYNC_INTERVAL_MIN` | `60` | Cada 60 minuts |
| `RAW_SYNC_TAIL_DAYS` | `7` | Últims 7 dies per símbol |
| `SYMBOLS` | `XAUUSD,EURUSD` | Símbols a mantenir al dia |

El cron usa `RawSyncWorker` (intern, sense lock extern) i escriu als mateixos paths del layout.

## Cobertura actual

| Símbol | Estat | Rang |
|--------|-------|------|
| EURUSD | ✅ Complet | 2003-05-04 → present |
| XAUUSD | ✅ Complet | 2003-01-01 → present |

## Jobs i lock

- Jobs persistits a `{DATAFILES_ROOT}/jobs/raw_sync/{job_id}.json`.
- Lock: `{DATAFILES_ROOT}/jobs/raw_sync.lock`. Només un job en execució alhora.

## Verificació des del host

```bash
# Comptar fitxers RAW per símbol
find datafiles/dukascopy_raw/m1_bi5_bid/EURUSD -name "BID_candles_min_1.bi5" | wc -l

# Verificar zero buits (ha de retornar "Dies sense fitxer: 0")
python3 -c "
from datetime import date, timedelta
from pathlib import Path
base = Path('datafiles/dukascopy_raw/m1_bi5_bid/EURUSD')
existing = {
    date(int(f.parts[-4].split('=')[1]), int(f.parts[-3].split('=')[1]), int(f.parts[-2].split('=')[1]))
    for f in base.rglob('BID_candles_min_1.bi5')
}
first = min(existing); last = max(existing)
missing = [d for d in (first + timedelta(i) for i in range((last-first).days+1)) if d not in existing]
print(f'Dies sense fitxer: {len(missing)}')
"
```

## Codi

- `infrastructure/venues/dukascopy/raw_bi5_store.py` — `RawBi5M1Store` (path_for_day, exists_day, write_day_atomic, watermark).
- `infrastructure/venues/dukascopy/raw_sync_worker.py` — `RawSyncWorker`, `get_supported_symbols()`, jobs, lock.
- Inicialització i scheduler: `application/app_factory.py` (lifespan, `RAW_SYNC_ENABLED`).

## Rollback

Desactivar `RAW_SYNC_ENABLED=0` al docker-compose. No cal desfer res (raw és additiu, no-delete).

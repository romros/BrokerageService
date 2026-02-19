# historical_datalayer — Arquitectura

**Servei:** historical_datalayer
**Propòsit:** Backfill Dukascopy, compat reports, stitching gated per compat PASS. Servei autònom, sense ingest realtime.

---

## Components

| Component | Funció |
|-----------|--------|
| **DukascopyProvider** | Descàrrega candles 1m històriques via `dukascopy-python` |
| **BackfillWriter** | Escriu candles Dukascopy al CSV store (format comú) |
| **CompatEngine** | Compara Ostium vs Dukascopy; genera compat registry |
| **StitchingGate** | Permet mixed (Ostium recent + Dukascopy antic) si compat PASS |
| **API** | /health, /candles (rang), /coverage, /compat/run, /data_status |

---

## Storage

- **Candles backfill:** `{DATAFILES_ROOT}/dukascopy/candles/{symbol}/...` (CSV mensual, format comú)
- **Compat registry:** `{DATAFILES_ROOT}/compat_reports/ostium_compat_registry.json`
- **Compat artifacts:** `{DATAFILES_ROOT}/compat_reports/{symbol}_*.json`

---

## API Surface

| Ruta | Mètode | Descripció |
|------|--------|------------|
| `/health` | GET | Health del servei |
| `/candles` | GET | Rang candles 1m (`?symbol=&since=&to=`) |
| `/coverage` | GET | Cobertura per símbol i resolució |
| `/compat/run` | POST | Llançar compat report (Ostium vs Dukascopy) |
| `/data_status` | GET | Estat stitching: cutover_ts, mixed_allowed, compat_status |

---

## Stitching (gated per compat)

- Compat PASS (per symbol) → `ostium_primary_allowed=true` al registry
- Si allowed: resposta stitched = candles Ostium recents + Dukascopy per prehistòria
- Si not allowed: només Dukascopy (o error si no hi ha rang sol·licitat)
- Font de veritat: `get_ostium_primary_allowed(symbol)` del registry

---

## Dependències externes

| Dependència | Rol |
|-------------|-----|
| `dukascopy-python` | Descàrrega candles 1m de Dukascopy |
| `realtime_datalayer` (HTTP, opcional) | Candles recents per stitching |

---

## Config (Env)

| Env | Default | Descripció |
|-----|---------|------------|
| `DATA_LAYER_ENABLED` | 0 | Habilitar data layer |
| `DATA_LAYER_WRITE_MODE` | backfill_only | backfill_only \| full |
| `DATAFILES_ROOT` | /datafiles | Arrel storage |
| `CANONICAL_TZ` | America/New_York | TZ canònica |
| `REALTIME_DATALAYER_BASE_URL` | — | URL realtime per stitching |

---

## Boundaries

- **NO** ingest realtime (NO Ostium polling)
- **NO** escriptura de ticks
- **NO** trading routes
- Dukascopy és la única font externa de dades

---

## Deploy

```bash
# Aixecar (split compose)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d historical_datalayer

# Rebuild si hi ha canvis de codi
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build historical_datalayer

# Verificar
curl -s http://localhost:8082/health
curl -s http://localhost:8082/data_status
```

---

## Tests

```bash
./scripts/run_tests.sh historical_datalayer
```

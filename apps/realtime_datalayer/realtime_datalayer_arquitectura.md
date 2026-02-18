# Realtime DataLayer v1 — Arquitectura

**Servei:** realtime_datalayer  
**Propòsit:** Recollir dades 24/7 (Ostium) i servir candles/ticks recents. Servei autònom, sense dependència de broker/trading.

---

## Components

| Component | Funció |
|-----------|--------|
| **Ostium Ingest** | Polling REST `/latest-price` → ticks → candles 1m |
| **Tick Recorder** | Persistència ticks a JSONL (forense, best-effort) |
| **Candle Store** | CSV candles 1m (ts, O, H, L, C, V) |
| **API** | /health, /status, /api/v1/broker/ohlcv, /api/v1/broker/data_status, /api/v1/broker/coverage |

---

## Storage

- **Candles:** `{REALTIME_DATALAYER_ROOT}/candles/{symbol}/...` (CSV mensual)
- **Ticks:** `{REALTIME_DATALAYER_ROOT}/ticks/daily/YYYYMMDD/{symbol}.jsonl`

**Retenció (ring buffer per hores):**
- `REALTIME_CANDLES_MAX_HOURS` (ex 72 o 168)
- `REALTIME_TICKS_MAX_HOURS` (ex 24 o 72)

---

## Contracte API

### GET /health
- `status`: ok | degraded | initializing
- Resposta <200ms

### GET /status
- `symbols`: per símbol: last_tick_ts, last_candle_ts, counts, duplicates, gaps
- `retention`: candles_max_hours, ticks_max_hours
- `uptime`: segons des d'arrencada
- `ingest_state`: running | stopped | initializing

### GET /api/v1/broker/ohlcv/{symbol}
- Candles del store local (tf=1m)

### GET /api/v1/broker/data_status
- Telemetria Data Layer (symbol_state, ingest_source, etc.)

---

## Config (env)

| Env | Default | Descripció |
|-----|---------|------------|
| REALTIME_DATALAYER_ROOT | /datafiles/realtime_datalayer | Arrel storage |
| REALTIME_CANDLES_MAX_HOURS | 168 | Retenció candles (hores) |
| REALTIME_TICKS_MAX_HOURS | 72 | Retenció ticks (hores) |
| OSTIUM_ENABLED | 1 | Ingest Ostium |
| OSTIUM_SYMBOLS | EURUSD,GBPUSD | Símbols a ingerir |
| OSTIUM_POLL_S | 2 | Interval polling (segons) |

---

## Boundaries

- **NO** adapter, **NO** trading routes
- **NO** compat Dukascopy (historical_datalayer)
- **NO** mixed stitching (fase posterior)

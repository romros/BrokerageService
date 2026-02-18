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
| **API** | /health, /status, /symbols (GET/PUT), /docs, /ui, /api/v1/broker/ohlcv, /api/v1/broker/data_status, /api/v1/broker/coverage |

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
- `effective_tz`: CANONICAL_TZ (ex. America/New_York)
- `now_utc`: timestamp UTC actual
- `now_local`: timestamp a effective_tz

### GET /symbols
- `desired`: llista desitjada (config)
- `active`: símbols actualment en ingest (no stopped)
- `by_symbol`: per cada símbol: ostium_asset, kind (perp|spot|unknown), resolution_source (auto|override), **market_state** (open|closed|unknown), market_open, market_state_reason, **last_price**, ticks_seen, ticks_last_ts, candles_written, candle_last_ts, errors_count, last_error, **state** (running|closed|warming|warning|degraded|stopped)

### PUT /symbols
- Body: `{"symbols": ["EURUSD","USDJPY",...], "apply_mode": "diff"|"replace"}`
- `diff`: afegeix símbols a la llista actual (no treu)
- `replace`: reemplaça la llista total
- Hot-reload: sense restart; config guardada a disc

### Instrument resolution
- Per cada logical_symbol es resol a ostium_asset (Ostium API).
- Si hi ha ambigüitat (spot/perp), es prefereix PERP quan està disponible.
- Override manual a `config/symbols.json` → `instrument_overrides`: `{"XAUUSD": {"ostium_asset": "XAUUSD", "kind": "perp"}}`

### GET /api/v1/broker/ohlcv/{symbol}
- Candles del store local (tf=1m)

### GET /api/v1/broker/data_status
- Telemetria Data Layer (symbol_state, ingest_source, etc.)

---

## Config

### Persistent: `{REALTIME_DATALAYER_ROOT}/config/symbols.json`
```json
{
  "symbols": ["EURUSD", "USDJPY", "XAUUSD", "GBPUSD", "GOOGUSD", "NVDAUSD", "DAXEUR", "SPXUSD"],
  "instrument_overrides": {"XAUUSD": {"ostium_asset": "XAUUSD", "kind": "perp"}}
}
```
- Carregat a l'arrencada; actualitzat via PUT /symbols.
- Llista inicial d'assets: EURUSD, USDJPY, XAUUSD (prefer perp), GBPUSD, GOOGUSD, NVDAUSD, DAXEUR, SPXUSD.

### Env

| Env | Default | Descripció |
|-----|---------|------------|
| REALTIME_DATALAYER_ROOT | /datafiles/realtime_datalayer | Arrel storage |
| REALTIME_CANDLES_MAX_HOURS | 168 | Retenció candles (hores) |
| REALTIME_TICKS_MAX_HOURS | 72 | Retenció ticks (hores) |
| OSTIUM_ENABLED | 1 | Ingest Ostium |
| OSTIUM_POLL_S | 2 | Interval polling (segons) |

---

## Operativa web: /docs i /ui

- **GET /** — Redirigeix a /ui (realtime_datalayer).
- **GET /docs** — Swagger UI (OpenAPI). Permet provar GET/PUT /symbols, GET /status, GET /health des del navegador.
- **GET /openapi.json** — Especificació OpenAPI.
- **GET /info** — Servei info: version, build, port, utc_now (per capçalera UI).
- **GET /ui** — Dashboard v2: badges open/closed/unknown/warning/degraded, taula ordenable amb last_price, filtres (show degraded/warning only, hide closed), clock UTC + CANONICAL_TZ, presets 8 assets / FX-only, PUT /symbols amb banner de resposta.

Via túnel SSH: `ssh -L 8081:localhost:8081 user@host` → obrir http://localhost:8081/ui i http://localhost:8081/docs.

---

## Market hours

- **FX/XAU 24/5:** Diumenge 22:00 UTC – Divendres 22:00 UTC. Fora d'horari → `market_closed`, ingest pausat.
- **Indices/equities (GOOGUSD, NVDAUSD, DAXEUR, SPXUSD):** `market_state_reason=unknown`; no degradar per stale (només per errors reals).
- Quan `market_closed` → open: ingest es repren automàticament.

## Boundaries

- **NO** adapter, **NO** trading routes
- **NO** compat Dukascopy (historical_datalayer)
- **NO** mixed stitching (fase posterior)

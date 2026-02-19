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
- `by_symbol`: per cada símbol: ostium_asset, kind (perp|spot|unknown), resolution_source (auto|override), **market_state** (open|closed|unknown), market_open, market_state_reason, **last_price**, ticks_seen, ticks_last_ts, candles_written, candle_last_ts, errors_count, last_error, **state** (running|closed|warming|warning|degraded|paused_closed|stopped), degrade_reason, next_poll_in_s, **coverage_expected_minutes**, **coverage_missing_minutes**, **coverage_ratio**, **symbol_uptime_s**

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

## Market hours (v2.2 — America/New_York)

Perfils Ostium (timezone: America/New_York):

| Perfil | Símbols | Horari |
|--------|---------|--------|
| ostium_xau_break | XAUUSD | Open 00:00–16:59, break 16:59–18:10, open 18:10–24:00 |
| ostium_indices_break | DAXEUR, SPXUSD | Open 00:00–16:59, break 16:59–18:00, open 18:00–24:00 |
| ostium_rth_equities | NVDAUSD | Open 09:31–15:59 (RTH weekday) |
| us_equities_ny | GOOGUSD | Open 09:30–16:00 (NYSE RTH weekday) |
| fx_24_5 | EURUSD, GBPUSD, USDJPY, AUDUSD | Diumenge 22:00 UTC – Divendres 22:00 UTC |

- **paused_closed:** Quan `market_closed`, `daily_break` o `rth_closed` → ingest pausat (sense borrar dades). `next_open_local` informat.
- **Health:** closed/paused no penalitza; només símbols OPEN degradats compten.
- **Override:** `symbols.json` → `market_hours_overrides: {"SYMBOL": "profile"}`.

## HEALTH vs COVERAGE (v2.2)

**HEALTH** (`state`): basat en `market_open`, `errors_count`, `stale_seconds`. **Prohibit:** `missing_minutes_24h` no pot degradar durant warmup.

**WARMUP:** durant `service_uptime_s < warmup_minutes` (default 120min), `missing_minutes_24h` mai degrada.
- `expected_open_minutes` = `min(1440, service_uptime_s // 60) - closed_mins` (no 1440 fix)
- `in_warmup = observed_open_minutes < warmup_minutes`

**COVERAGE** (informatiu, no governa HEALTH):
- `coverage_expected_minutes`: minuts oberts esperats per l'uptime actual
- `coverage_missing_minutes`: minuts oberts sense candle
- `coverage_ratio`: observed/expected (0..1)
- `symbol_uptime_s`: segons des del primer tick

## Deploy zero-downtime

```bash
# 1. Build (mentre el servei corre — les candles al volum no es toquen)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml build realtime_datalayer

# 2. Restart (solo el contenidor: ~10-15s gap, dades intactes)
docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml up -d --no-deps realtime_datalayer

# 3. Verificar (esperar ~8s)
curl -s http://localhost:8081/health   # esperat: {"status":"ok"}
curl -s http://localhost:8081/symbols  # estats i coverage per símbol
```

**Les candles sobreviuen al restart:** el volum `./datafiles:/datafiles` és persistent. El gap d'ingest durant el restart (~10-15s) és acceptable — el CSV store resumeix des de l'últim candle escrit.

## Boundaries

- **NO** adapter, **NO** trading routes
- **NO** compat Dukascopy (historical_datalayer)
- **NO** mixed stitching (fase posterior)

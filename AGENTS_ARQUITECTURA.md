# AGENTS_ARQUITECTURA.md — BrokerageService (Reference)

**Data:** 2026-02-13  
**Repo/Path:** `/mnt/volume-SQ/dev/BrokerageService`  
**Venue principal:** **Lighter** (paper-ready + live-hardening complet)  
**Altres venues:** gTrade (paper-ready; live-hardening pendent)  
**Modes:** LIVE / PAPER / BACKTEST  
**Timeframe:** 1m only  
**TZ canònica (config):** `CANONICAL_TZ=America/New_York` (NY close style)  
**TZ container (runtime/logs):** `TZ=America/New_York`  
**API canònica:** REST `/api/v1/broker/*` (POST body únic per ordres)  
**Objectiu:** Font única de referència estable. Operativa diària → [docs/ESTAT.md](docs/ESTAT.md).

---

## 0) TL;DR

- ✅ **API Broker canònica** a `broker_routes.py` (prefix `/api/v1/broker`)
- ✅ **Candles**: candle_store (sense venue), 1m only, OHLCV unificat
- ✅ **Lighter**: open/close + SL/TP + balance + reconcile + guards + restart-safety + smoke + e2e → **DONE**
- ✅ **Quality gates**: run_all passa; evidència 3× smoke real + 3× e2e real (paper testnet)
- 🟡 **gTrade**: paper OK; mainnet hardening pendent
- ⛔ **Backtest**: pendent

---

## 1) Decisions tancades (invariants)

1. **Timeframe únic:** `1m`
2. **Candles sense venue:** `GET /candles` i `GET /ohlcv/{symbol}` venen del `candle_store`
3. **TZ canònica:** `America/New_York` (rang/particionat, NY close style)
4. **`ts` canònic:** epoch UTC (start-of-minute); convenció Dukascopy-style — veure §5
5. **API Broker:** prefix `/api/v1/broker`; decorators sense duplicar `/broker`
6. **Ordres:** només POST body (`/orders/open`, `/orders/close`); sense query legacy
7. **Errors:** `{"detail": "...", "code": "..."}` amb 503/422/404
8. **Single-writer** per símbol al storage CSV

---

## 2) Estat implementat

### Lighter (principal)
✅ paper-ready · ✅ live-hardening complet · ⛔ backtest pendent  
Market data, open/close, SL/TP, balance, reconcile, guards, bootstrap, smoke, e2e.

### gTrade (existent)
✅ paper-ready · 🟡 live-hardening pendent · ⛔ backtest pendent  
Nota: `openPrice`/oracle zona sensible (veure §10 AGENTS si cal).

### BACKTEST
Contracte previst, però pipeline no implementada encara.

### 2.2 Mode PAPER amb market data MAINNET (Freqtrade-first)

Freqtrade es provarà primer en **PAPER**, però amb **market data real de MAINNET** perquè:
- testnet no té tots els assets
- testnet pot tenir preus "fake" o desalineats
- volem candles/WS realistes per validar l'edge i el pipeline

**Decisió:** PAPER = **mainnet market data** + **paper execution** (sense transaccions reals).

**Invariants:**
- market data = mainnet (per defecte en PAPER)
- execution = paper (simulada)
- zero tx reals en paper

**Variables de config:**
- `MODE=PAPER` — execució simulada
- `MARKET_DATA_ENV=mainnet` — font de preus (mainnet|testnet; default mainnet)
- `ENABLE_LIVE_TRADING=0` — kill switch (paper sempre 0)

**Nota explícita:** paper ≠ testnet. PAPER pot usar mainnet per market data i paper per execució.

### 2.3 Principis d’arquitectura (SOLID + DI minimalista)

- **SOLID / SRP:** rutes primes (validate → deps → call → map response). Lògica i mapping en helpers/serveis petits.
- **Ports & adapters:** `domain/*` defineix models + interfaces (ports); `infrastructure/*` implementa venue adapters i storage.
- **DI minimalista (estil Java, sense framework):**
  - Injecció per constructor/on-startup (FastAPI lifespan).
  - `set_broker_deps(...)` injecta dependències globals de rutes (candle_store, adapter_factory, mode, venue).
- **Evitar palla:** només abstraure quan hi ha 2 implementacions o un seam clar per testing.

### 2.4 Coding standards (invariants)

#### A) Imports a la capçalera (regla general)
- Tots els imports han d'anar a la capçalera del fitxer.
- Prohibit fer imports dins de funcions per estil.

**Excepcions permeses (documentades):**
- Evitar imports circulars (amb comentari `# local import to avoid circular dependency`).
- Lazy import per evitar càrrega pesada (p.ex. llibreria molt costosa) amb comentari `# lazy import to reduce startup cost`.
- Aquestes excepcions han de ser rares i justificades.

#### B) Zero hardcode (regla general)
- No posar valors màgics (strings, ints, floats, paths, timeouts, limits) dins la lògica.
- Tot valor "policy" o "protocol" ha d'estar en:
  1) Constants de mòdul (p.ex. `DEFAULT_LIMIT`, `MAX_LIMIT`)
  2) Constants de classe (si té sentit)
  3) Config (`foundation/config/...` o `application/config/...`) si pot ser compartit o sobreescrit per env.

**Exemples de què és hardcode no permès:**
- "America/New_York" repetit a mà en 5 fitxers
- "1m" i rangs de limit repetits
- codis d'error repetits
- llistes de venues ("lighter","gtrade") repetides

**Exemples permesos:**
- literals en tests (fixtures)
- strings de log no-crítics
- literals ultra locals (p.ex. `side_lower in ("long","short")`) si no és policy de configuració

**Fonts canòniques:**
- `foundation/config/constants.py` — CANONICAL_TIMEZONE_NAME, SUPPORTED_TIMEFRAME, DEFAULT_*_LIMIT, MAX_*_LIMIT, KNOWN_VENUES
- `application/api/error_codes.py` — codis d'error Broker API

---

## 3) Broker API — Contracte v0 (canònic)

**Base URL:** `http://localhost:8000/api/v1/broker`

### 3.1 Paths

| Mètode | Path | Descripció |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/mode` | Mode actual |
| GET | `/venues` | Llista venues disponibles |
| GET | `/pairs` | Llista pairs (requereix `venue`) |
| GET | `/price/latest` | Preu actual (requereix `venue`, `symbol`) |
| GET | `/candles` | Candles OHLCV (sense venue) |
| GET | `/ohlcv/{symbol}` | Candles OHLCV path style (sense venue) |
| GET | `/balance` | Balance compte (requereix `venue`) |
| GET | `/positions` | Posicions obertes (requereix `venue`) |
| GET | `/trades` | Trade history (fills) — CCXT/Freqtrade compatible |
| POST | `/orders/open` | Obrir posició (JSON body) |
| POST | `/orders/close` | Tancar posició (JSON body) |

### 3.2 Endpoints detallats

**Health i meta**

| Path | Params | Response |
|------|--------|----------|
| `GET /health` | - | status, mode, venue, timestamp |
| `GET /mode` | - | mode, is_live, is_paper, is_backtest, venue, market_data_env |
| `GET /venues` | - | venues: string[] |

**Market data**

| Path | Params | Notes |
|------|--------|-------|
| `GET /pairs` | `venue` (required) | Requereix venue; per aquesta instància, només `lighter` |
| `GET /price/latest` | `venue`, `symbol` | bid, ask, mid, timestamp |
| `GET /candles` | `symbol`, `timeframe=1m`, `limit`, `since?`, `to?` | Sense venue. Només 1m |
| `GET /ohlcv/{symbol}` | `tf=1m`, `since?`, `to?`, `limit` | Sense venue. Només 1m |

**Account / Trading**

| Path | Params/Body | Notes |
|------|-------------|-------|
| `GET /balance` | `venue` | usdc, available_margin, used_margin, total_equity, margin_usage_percent |
| `GET /positions` | `venue` | positions[] |
| `GET /trades` | `venue`, `symbol?`, `since?`, `to?`, `limit` (1–5000) | trades[] (trade_id, symbol, side, price, size, fee, timestamp ISO8601) |
| `POST /orders/open` | JSON body | venue, symbol, side (long\|short), collateral, leverage, sl_price?, tp_price? |
| `POST /orders/close` | JSON body | venue, position_id, percent (0, 100] |

### 3.3 Invariants

- **Candles:** no accepten venue; només `timeframe/tf=1m` → si ≠1m: 422 `TIMEFRAME_NOT_SUPPORTED`
- **Adapter:** `/pairs`, `/price/latest`, `/balance`, `/positions`, `/trades`, `/orders/open`, `/orders/close` requereixen `adapter_factory`; si no wired → 503 `ADAPTER_NOT_AVAILABLE`; venue incorrecte → 422 `VENUE_NOT_CONFIGURED`

### 3.4 Errors

Format: `{"detail": "...", "code": "..."}`

| code | status | Descripció |
|------|--------|-------------|
| `ADAPTER_NOT_AVAILABLE` | 503 | adapter_factory no configurat |
| `CANDLE_STORE_NOT_AVAILABLE` | 503 | candle_store no disponible |
| `VENUE_NOT_CONFIGURED` | 422 | venue no configurat en aquesta instància |
| `TIMEFRAME_NOT_SUPPORTED` | 422 | timeframe != "1m" |
| `INVALID_SIDE` | 422 | side no és long ni short |
| `INVALID_PERCENT` | 422 | percent fora de (0, 100] |
| `POSITION_NOT_FOUND` | 404 | position_id no existeix |
| `SYMBOL_NOT_FOUND` | 404 | symbol no existeix |

### 3.5 Samples

**POST /orders/open**

```json
{
  "venue": "lighter",
  "symbol": "ETH",
  "side": "long",
  "collateral": 100,
  "leverage": 20,
  "sl_price": null,
  "tp_price": null
}
```

Response 200: `{ "success": true, "position_id": "lighter:0", "order_id": "...", "executed_price": 3950.0, "executed_size": 0.506, "tx_hash": "0x..." }`

**POST /orders/close**

```json
{
  "venue": "lighter",
  "position_id": "lighter:0",
  "percent": 100
}
```

Response 200: `{"success": true}`

---

## 4) Wiring (main.py / set_broker_deps / VENUE)

- `set_broker_deps(candle_store, adapter_factory, mode, venue)` s’executa al startup (lifespan)
- `GET /venues` reflecteix wiring: `[]` si no hi ha adapter_factory, `["lighter"]` si wired
- **VENUE=lighter:** crea `LighterVenueAdapter`, `adapter.start()`, injecta `adapter_factory`, `adapter.stop()` al shutdown
- **VENUE=lighter + USE_FAKE_PRICE_FEED=1:** sense adapter (broker arrenca sense xarxa); market data usa fake
- **VENUE≠lighter** (o buit): `adapter_factory=None` → endpoints adapter retornen 503; venue incorrecte en query → 422

---

## 5) Data / Storage (TZ NY + ts epoch UTC + 1m only)

- **TZ canònica:** `America/New_York` (partició, queries, NY close style)
- **Layout CSV:** `datafiles/{broker}/{asset}/{timezone}/{YYYY}/{MM}.csv`
- **Format:** `ts,open,high,low,close,volume`; `volume=0` si no existeix
- **Invariant NO GAPS:** seqüència validada; single-writer + escriptura atòmica

### 5.1 Convenció canònica de candles (Dukascopy-style)

**Timestamp de candle (`ts`) = start-of-minute (inici del període), en epoch UTC.**

Una candle 1m etiquetada amb `ts` representa l'interval:

```
[ts, ts + 60s)
```

El "close" és el darrer preu/tick dins l'interval; la candle queda "tancada" quan comença el minut següent.

**Regla d'or per l'algorisme/backtest:** la candle `ts=10:05:00` és "el minut 10:05", no "el minut que acaba a 10:05".

**Exemple (obligatori):**
- `ts = 2026-02-13 10:05:00Z` → interval `[10:05:00Z, 10:06:00Z)`
- `ts = 1739460300` (epoch) → interval `[1739460300, 1739460360)`

**Implicacions:**
- No usar timestamps de "close time" (evita off-by-one minute).
- `since`/`to` en queries han d'interpretar-se respecte el bar start (rang sobre starts).

---

## 6) Quality Gates

- **Gate A (bloquejador):** `./test.sh testing/run_all.py` passa
- **Gate B (bloquejador):** Integration mock SL/TP + Balance passa
- **Gate C (post-milestone):** 3× smoke real OK; 3× e2e trade real OK (`positions_after=0`)
- **WS preflight integration (real broker):** `test_ws_preflight_integration_real.py` — fake feed, no network

Evidència concreta (logs, timestamps) → [docs/ESTAT.md](docs/ESTAT.md)

### 6.0 Env vars (market data)

| Var | Descripció |
|-----|------------|
| `USE_FAKE_PRICE_FEED=1` | Usa FakeLighterPriceFeedClient (sense xarxa). Per tests d'integració. |

### 6.1 Testing (TDD scripts, sense pytest)

**Filosofia:** tests simples en scripts Python (no pytest). Cada test té `main()`, fa `assert`, imprimeix resum, i retorna exit code.

**On són els tests:**

```
testing/
  unit/           # tests purament en memòria (0 network)
  integration/    # fluxos de components (normalment mock)
  api/            # smoke REST/WS contra localhost
  run_all.py      # runner: executa i falla si hi ha errors
```

**Com executar:**

```bash
# Suite completa (unit + integration mock + alguns api local)
./test.sh testing/run_all.py

# Un test concret
./test.sh testing/unit/test_broker_api.py
./test.sh testing/integration/test_lighter_adapter_sltp.py
```

**"Done" per feature (regla):** Cap feature es considera feta si no inclou: mínim 1 unit/integration test nou, i si toca API: smoke test de l'endpoint.

### 6.2 Plantilla de test (sense pytest)

Exemple de test unitari mínim:

```python
# testing/unit/test_example.py
import sys

def main() -> int:
    x = 2 + 2
    assert x == 4
    print("OK test_example")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Regla: si el test falla, `assert` peta i el runner ho marca com FAILED.

---

## 7) Docker / Runtime (TZ del container)

**Recorda:** Si has canviat codi, reconstruir abans: `docker compose build brokerage`.

Per coherència (logs, display, NY close style):

**docker-compose.yml** — al servei `brokerage`:
```yaml
environment:
  - TZ=America/New_York
  - CANONICAL_TZ=America/New_York
  # ... resta
```

**Dockerfile** (base `python:3.11-slim`):
```dockerfile
RUN apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*
ENV TZ=America/New_York
```

**Verificació:**
```bash
docker compose run --rm brokerage date
docker compose run --rm brokerage python3 -c "import time, datetime; print(datetime.datetime.now()); print(time.tzname)"
```
Hora NY i `('EST','EDT')` quan toca → OK.

> El dataset canònic no depèn del TZ del container: `ts` és epoch UTC. El TZ del container és per display i logs.

---

## 8) Roadmap curt (no canònic)

- ~~Trade history (IVenueAdapter)~~ ✅ P1 DONE
- Maker-first close (opcional)
- Backtest pipeline complet
- gTrade mainnet hardening

---

## 9) Changelog curt

* 2026-02-13 — Unificació API `/api/v1/broker/*`, POST body only, errors consistents, legacy eliminat
* 2026-02-13 — Lighter M1+M2+M3 complet (smoke + e2e evidència a docs/ESTAT.md)
* 2026-02-13 — Docker TZ=America/New_York + tzdata + CANONICAL_TZ

# Runbook: API canònica de Trades (Broker)

**Objectiu:** Referència exacta de rutes, mode (LIVE/PAPER) i models per integrar Ostium (T2) sense inventar endpoints.

**Font verificada:** `application/api/broker_routes.py`, `application/main.py`, `application/config/live_guards_config.py`.

---

## 1. On viu l’API

| Qué | On |
|-----|-----|
| **Router** | `application/api/broker_routes.py` |
| **Prefix** | `/api/v1/broker` |
| **Muntatge** | `application/main.py`: `app.include_router(broker_router)` (el router ja duu prefix) |
| **Handlers trading** | Subrouter `trading_router`; data (health, candles, etc.) a `data_router` |

---

## 2. Rutes canòniques (trades / positions)

Totes són **GET** o **POST**; base URL: `http(s)://<host>:<port>/api/v1/broker`.

| Mètode | Path | Query / Body | Response | Definició (fitxer:decorator) |
|--------|------|--------------|----------|------------------------------|
| GET | `/health` | — | `HealthResponse` (status, mode, venue, timestamp) | broker_routes.py L254 `get_health` |
| GET | `/mode` | — | `ModeResponse` (mode, is_live, is_paper, is_backtest, venue, market_data_env, market_data_source) | broker_routes.py L273 `get_mode` |
| GET | `/venues` | — | `{ "venues": ["paper","lighter",...] }` | broker_routes.py L291 `get_venues` |
| GET | `/balance` | `venue` (required) | `BalanceResponse` | broker_routes.py L468 `get_balance` |
| GET | **`/positions`** | **`venue`** (required) | **`PositionsResponse`** (positions: List[PositionItem]) | broker_routes.py L478 `get_positions` |
| GET | `/trades` | `venue`, `symbol?`, `since?`, `to?`, `limit?` | `TradesResponse` (trades: List[TradeItem]) | broker_routes.py L506 `get_trades` |
| POST | **`/orders/open`** | Body: **OrderOpenRequest** | **OrderOpenResponse** | broker_routes.py L558 `order_open` |
| POST | **`/orders/close`** | Body: **OrderCloseRequest** | **OrderCloseResponse** | broker_routes.py L564 `order_close` |
| GET | `/preflight` | `venue?`, `symbol?` | JSON (ready, checks, risk_caps) | broker_routes.py L569 `get_preflight` |

**Positions (open positions):** endpoint canònic = **GET `/api/v1/broker/positions?venue=<venue>`**. El handler crida `adapter.get_open_positions()` i retorna `PositionsResponse`. **Punt d’integració T2 (Ostium):** fer que el venue `ostium` retorni posicions des de `OstiumClient.get_open_trades` (TradingStorage).

**Open trade:** **POST `/api/v1/broker/orders/open`** amb body JSON. **Close trade:** **POST `/api/v1/broker/orders/close`** amb body JSON.

---

## 3. Mode LIVE / PAPER (com es passa i on es valida)

- **No es passa per request:** no hi ha query param ni header `mode`. El mode és **configuració de servidor** a l’arrencada.
- **Origen:** `application/main.py` → `load_config()` llegeix `MODE` (default `"paper"`). Valors: `paper` | `live` | `backtest` (MVP: només LIVE + PAPER; backtest fora).
- **Injecció:** `set_broker_deps(mode=config["mode"], ...)` al lifespan; la variable global `_mode` a `broker_routes.py` és el que retorna **GET /mode** i el que rep **TradingCore** en crear-lo per open/close.
- **Kill switch LIVE:** `ENABLE_LIVE_TRADING` (env). Si `0` (default), el servidor pot estar en `MODE=live` però les ordres es tracten com a paper (zero TX). Font: `application/main.py` (use_paper_execution, enable_live), `application/config/live_guards_config.py` → `enable_live_trading_from_env()`.
- **Validació:** A `application/trading/trading_core.py`, TradingCore rep `mode` al constructor. Els live guards (risk caps, allowlist) s’apliquen quan `mode == "live"`; si `ENABLE_LIVE_TRADING` no és `1`, es retorna 403 LIVE_TRADING_DISABLED.

**Resum:** Per saber el mode actual → **GET `/api/v1/broker/mode`**. Per operar en LIVE cal `MODE=live` + `ENABLE_LIVE_TRADING=1` + venue amb adapter live.

---

## 4. Models de request/response (trades)

**Request (Pydantic, a `application/api/models.py`):**

- **OrderOpenRequest:** `venue`, `symbol`, `side` (long|short), `collateral`, `leverage`, `sl_price?`, `tp_price?`, `client_order_id?`.
- **OrderCloseRequest:** `venue`, `position_id`, `percent` (default 100, 0–100).

**Response (broker_routes + models):**

- **OrderOpenResponse:** success, position_id, order_id, executed_price, executed_size, tx_hash.
- **OrderCloseResponse:** success.
- **PositionItem (dins PositionsResponse):** position_id, symbol, side, size, notional, open_price, entry_time, mark_price?, unrealized_pnl?, sl_price?, tp_price?, liquidation_price?.
- **PositionsResponse:** positions: List[PositionItem].

Els handlers de open/close delegan a `application/trading/trading_core.py` (`TradingCore.open_order` / `close_order`), que resol l’adapter per `venue` i crida `adapter.open_position` / `adapter.close_position`.

---

## 5. Exemples curl (reals, basats en el codi)

```bash
# Mode actual (LIVE/PAPER)
curl -s "http://localhost:8010/api/v1/broker/mode"

# Posicions obertes (canònic per T2 — positions)
curl -s "http://localhost:8010/api/v1/broker/positions?venue=lighter"
# T2 Ostium: venue=ostium quan hi hagi adapter Ostium

# Obrir posició (POST body)
curl -s -X POST "http://localhost:8010/api/v1/broker/orders/open" \
  -H "Content-Type: application/json" \
  -d '{"venue":"lighter","symbol":"EURUSD","side":"long","collateral":100,"leverage":5}'

# Tancar posició (POST body)
curl -s -X POST "http://localhost:8010/api/v1/broker/orders/close" \
  -H "Content-Type: application/json" \
  -d '{"venue":"lighter","position_id":"lighter:0","percent":100}'
```

---

## 6. Punts d’integració per T2 (positions Ostium)

- **Adapter:** Afegir/wiring d’adapter per `venue=ostium` a `main.py` (lifespan) i fer que `adapter_factory("ostium")` retorni l’adapter Ostium (ex. `OstiumExecutionAdapter` amb `IOstiumClient` que llegeix TradingStorage).
- **Positions:** El mateix endpoint **GET `/api/v1/broker/positions?venue=ostium`** ha de cridar `adapter.get_open_positions()`; l’adapter Ostium ha de delegar a `OstiumClient.get_open_trades` (read-only TradingStorage, sense subgraph).
- **Mode:** No cal canviar com es passa el mode; el mode actual és el de `_mode` (MODE env). Per positions PAPER (stub) es pot retornar llista buida o posicions simulades segons acord T2; per LIVE, posicions reals via TradingStorage.

---

## 7. T2 fet: `venue=ostium` a GET /positions (LIVE + PAPER)

- **Wiring:** Quan `VENUE=ostium`, `application/main.py` crea `OstiumExecutionAdapter` (PAPER = `FakeOstiumClient`, LIVE = `OstiumClient` des de env) i registra `adapter_factory("ostium")`.
- **LIVE:** Posicions llegides del chain via TradingStorage (Trade(9)); requereix `OSTIUM_PRIVATE_KEY` i `OSTIUM_RPC_URL` (opcional).
- **PAPER:** Retorna `[]` sense fer cap crida de xarxa (log: «paper mode → no network»).
- **curl (directe, port per defecte 8000):** `GET http://localhost:8000/api/v1/broker/positions?venue=ostium`  
  **Via proxy split (port 8081):** `GET http://localhost:8081/trade/api/v1/broker/positions?venue=ostium`

---

## 8. Check-list T2 (completat)

- [x] Wiring a `main.py`: quan `VENUE=ostium`, adapter Ostium injectat; PAPER = FakeOstiumClient, LIVE = OstiumClient.
- [x] `get_open_positions()` a l’adapter Ostium delegant a `OstiumClient.get_open_trades` (TradingStorage Trade(9)); position_id tipus `ostium:{pair_id}:{index}`.
- [x] PAPER retorna `[]`; LIVE retorna posicions reals (o `[]` si cap trade obert).

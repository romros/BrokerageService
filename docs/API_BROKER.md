# Broker API — Contracte canònic

**Base URL:** `http://localhost:8000/api/v1/broker`  
**Referència completa:** [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md) §3

---

## Paths

| Mètode | Path | Descripció |
|--------|------|------------|
| GET | `/health` | Health check |
| GET | `/mode` | Mode (inclou `market_data_env`) |
| GET | `/venues` | Venues disponibles |
| GET | `/pairs` | Pairs (requereix `venue`) |
| GET | `/price/latest` | Preu actual |
| GET | `/candles`, `/ohlcv/{symbol}` | Candles OHLCV 1m |
| GET | `/balance`, `/positions` | Balance i posicions |
| POST | `/orders/open` | Obrir posició (JSON body) |
| POST | `/orders/close` | Tancar posició (JSON body) |

---

## Errors

Format: `{"detail": "...", "code": "..."}`

| code | status |
|------|--------|
| `ADAPTER_NOT_AVAILABLE` | 503 |
| `CANDLE_STORE_NOT_AVAILABLE` | 503 |
| `VENUE_NOT_CONFIGURED` | 422 |
| `TIMEFRAME_NOT_SUPPORTED` | 422 |
| `POSITION_NOT_FOUND` | 404 |

---

## Exemples

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

**POST /orders/close**
```json
{
  "venue": "lighter",
  "position_id": "lighter:0",
  "percent": 100
}
```

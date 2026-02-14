# BrokerageService — Lighter (principal)

**Venue principal:** **Lighter** — MVP 100% per Lighter. Altres DEX (p.ex. gTrade) s’incorporaran en el futur.  
**Dissenyat per:** Freqtrade adapter consumption

**Docs:** [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md) · [docs/ESTAT.md](docs/ESTAT.md) · [docs/SAFETY_RUNBOOK.md](docs/SAFETY_RUNBOOK.md)

---

## Overview

Servei de brokerage independent. **MVP 100% Lighter**; altres venues (gTrade, etc.) es podran afegir més endavant.

**3 modes**:

- **LIVE** — Trading real (Lighter principal; gTrade futur)
- **PAPER** — Market data real + execució simulada (sense risc)
- **BACKTEST** — Simulació amb dades històriques (pipeline pendent)

**Scope:**
- Timeframe: **1m only**
- TZ canònica: **America/New_York**
- API: REST `/api/v1/broker/*` + WebSocket
- PAPER Freqtrade: market data mainnet + execució paper (`MARKET_DATA_ENV=mainnet`, `ENABLE_LIVE_TRADING=0`)

---

## Estat actual (2026-02-13)

- ✅ **Lighter M1+M2+M3** DONE: marketdata, SL/TP, balance, reconcile, guards, smoke, e2e
- ✅ **44 tests** passa; smoke 3× + e2e 3× + **soak 10 min** OK
- ✅ **Broker API canònica** POST body únic per ordres
- ✅ **Freqtrade P0** PAPER mainnet-data
- 🟡 **gTrade**: existent (paper OK); no prioritzat per MVP; s’incorporarà en el futur
- ⛔ **Backtest**: pendent

---

## API (prefix `/api/v1/broker`)

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

**Exemple POST /orders/open:**
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

---

## Quick Start

```bash
# Tests
./test.sh testing/run_all.py

# Iniciar servei (Docker)
docker compose up -d brokerage

# Health
curl http://localhost:8000/api/v1/broker/health

# Mode (inclou market_data_env)
curl http://localhost:8000/api/v1/broker/mode

# Candles
curl "http://localhost:8000/api/v1/broker/ohlcv/XAUUSD?limit=10"
```

---

## Configuració (.env)

```bash
MODE=paper
VENUE=lighter                    # lighter | gtrade

# PAPER mainnet-data (Freqtrade)
MARKET_DATA_ENV=mainnet          # mainnet | testnet
ENABLE_LIVE_TRADING=0            # kill switch (paper sempre 0)

# Storage
CANONICAL_TZ=America/New_York
DATAFILES_ROOT=/datafiles
SYMBOLS=XAUUSD,EURUSD
```

---

## Comandes operatives

```bash
# Smoke (mock 5s)
docker compose run --rm brokerage python3 -m application.smoke --venue mock --mode PAPER --seconds 5

# Smoke 3× (lighter, 120s)
docker compose run --rm brokerage python3 -m application.smoke --venue lighter --mode PAPER --seconds 120 --repeat 3 --pause-s 5

# Soak 10 min
./scripts/soak_smoke.sh
# o 15 min: ./scripts/soak_smoke.sh 900

# E2E trade (paper testnet)
docker compose run --rm brokerage python3 -m application.e2e_trade \
  --venue lighter --mode PAPER --symbol ETH --collateral 100 --leverage 20 \
  --settle-timeout-s 120 --poll-s 2
```

---

## Arquitectura

```
BrokerageService/
├── application/         # FastAPI, broker_routes, smoke, e2e
├── domain/              # models, interfaces (IVenueAdapter, ICandleStore)
├── infrastructure/
│   ├── storage/         # CSVCandleStore, GapValidator
│   ├── venues/
│   │   ├── lighter/     # Principal: LighterVenueAdapter, market data, price feed
│   │   └── gtrade/      # Futur: gTrade adapter (paper-ready, no prioritzat MVP)
│   ├── execution/       # PaperExecutionEngine
│   └── ws/              # WebSocketHub
├── foundation/          # logging, lifecycle
├── scripts/             # soak_smoke.sh, etc.
└── testing/             # unit, integration, api
```

---

## Testing

```bash
./test.sh testing/run_all.py
```

- **Unit:** 44 tests (store, lighter, gtrade, broker_api, mode_market_data_env, etc.)
- **Integration:** Lighter adapter, flows, backfill
- **API:** REST smoke, WS smoke

---

## Documentació

- [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md) — Referència d’arquitectura, contracte API, invariants
- [docs/ESTAT.md](docs/ESTAT.md) — Estat del projecte, evidència, backlog
- [docs/SAFETY_RUNBOOK.md](docs/SAFETY_RUNBOOK.md) — Runbook operatiu, soak, E2E
- [testing/README.md](testing/README.md) — Testing

---

## Contribuir

1. Llegir [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md)
2. Implementar seguint principis SOLID + DI minimalista
3. Afegir tests
4. Actualitzar [docs/ESTAT.md](docs/ESTAT.md)
5. Executar `./test.sh testing/run_all.py`

---

## Llicència

MIT

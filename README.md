# BrokerageService — Broker Gateway API

API REST per [Freqtrade](https://www.freqtrade.io/) (`/api/v1/broker/*`). Venue actual: **Ostium** (LIVE testnet → mainnet).

**Docs:** [docs/ESTAT.md](docs/ESTAT.md) · [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md)

---

## Prerequisits

- Docker + Docker Compose
- Python 3.11+ (per tests locals)
- `lab/ostium/.env` amb `RPC_URL`, `PRIVATE_KEY` (copia de `lab/ostium/.env.example`)

---

## Quick Start

```bash
# Tests (0-network per defecte)
./test.sh testing/run_all.py

# Ostium LIVE — happy path canònic (up stack + smoke)
./scripts/up_ostium_live.sh

# Smoke only (trading_service ja arrencat)
./scripts/run_ostium_live_smoke.sh --recreate --clean
```

---

## Arquitectura split

**Gateway unificat:** `datalayer-proxy` port **8081**

| Prefix | Servei | Notes |
|--------|--------|-------|
| `/realtime/*` | realtime_datalayer:8082 | Candles Ostium 24/7 |
| `/data/*` | historical_datalayer:8002 | Backfill, Parquet, coverage |
| `/trade/*` | trading_service:8010 | Broker API, ordres |

**Accés directe (debug):** `http://127.0.0.1:8010` per smoke (evita timeout nginx).

---

## API (prefix `/api/v1/broker`)

| Mètode | Path | Descripció |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/balance`, `/positions` | Balance i posicions |
| POST | `/orders/open` | Obrir posició (JSON) |
| POST | `/orders/close` | Tancar posició (JSON) |

Exemple `POST /orders/open`:
```json
{"venue": "ostium", "symbol": "EURUSD", "side": "long", "collateral": 5, "leverage": 2}
```

---

## Documentació

- [docs/ESTAT.md](docs/ESTAT.md) — Estat, evidència, comandes canòniques
- [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md) — Arquitectura, contractes, invariants
- [docs/INDEX.md](docs/INDEX.md) — Índex navegació

---

## Contribuir

1. Llegir [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md)
2. Executar `./test.sh testing/run_all.py`
3. Actualitzar [docs/ESTAT.md](docs/ESTAT.md) si cal

---

MIT

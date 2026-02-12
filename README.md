# BrokerageService - gTrade Independent Brokerage

**Versió:** 0.5.0 (Fases 1+2+3+4+4.5+5 completades ✅)
**Venue principal:** gTrade (Arbitrum)
**Dissenyat per:** Freqtrade adapter consumption

---

## 🎯 Overview

Servei de brokerage independent amb **3 modes d'operació**:

- **LIVE** - Trading real amb gTrade (blockchain, Arbitrum)
- **PAPER** - Dades live reals però execució simulada (sense risc)
- **BACKTEST** - Simulació amb dades històriques a velocitat accelerada

**Scope inicial:**
- Assets: `XAUUSD`, `EURUSD`
- Timeframe: **1m only**
- Timezone canònica: **America/New_York**
- Storage: CSV amb layout canònic + "NO GAPS" invariant

---

## 📊 Estat Actual (2026-02-08)

✅ **FASE 1** - Storage CSV + Gap Invariant + OHLCV Read
✅ **FASE 2** - Live Ingestion → CandleBuilder → Store
✅ **FASE 3** - Backfill Scheduler + Patch Policy
✅ **FASE 4** - Paper Trading + Positions API + Idempotència
✅ **FASE 4.5** - CostModel amb fees oficials gTrade
✅ **FASE 5** - WebSocket Hub + Real-time Broadcasting

**Tests:** 11/11 passing ✅

**Propera fase recomanada:** 🔜 **FASE 6** - gTrade Live Adapter

---

## 📁 Arquitectura

```
BrokerageService/
├── foundation/          # ✅ Logger singleton, lifecycle, config
├── domain/
│   ├── models/          # ✅ Candle, Position, Order, Balance, etc.
│   └── interfaces/      # ✅ IVenueAdapter, ICandleStore, IExecutionEngine, etc.
├── infrastructure/
│   ├── storage/         # ✅ CSVCandleStore, GapValidator, IdempotencyStore
│   ├── builders/        # ✅ CandleBuilder (tick → 1m candle)
│   ├── execution/       # ✅ PaperExecutionEngine (amb WS events)
│   ├── data/            # ✅ MockBackfillProvider
│   ├── ws/              # ✅ WebSocketHub, WSMessage, broadcast system
│   └── venues/gtrade/   # ⏸️ Pendent (Fase 6)
├── application/
│   ├── services/        # ✅ BackfillService
│   └── api/             # ✅ REST endpoints (ohlcv + trading)
└── testing/             # ✅ 11/11 tests passing
    ├── unit/            # 6 tests (store, validator, builder, provider, idempotency, cost_model)
    ├── integration/     # 3 tests (live_to_store, backfill_patch, paper_positions)
    └── api/             # 2 tests (rest_smoke, ws_smoke)
```

**Docs:**
- [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md) - Pla complet amb roadmap per fases
- [ESTAT.md](ESTAT.md) - Estat detallat del projecte + què falta

---

## 🚀 API Endpoints

### Core
- `GET /health` - Health check
- `GET /mode` - Mode info (live/paper/backtest)

### Market Data
- `GET /ohlcv/{symbol}?tf=1m&since=...&to=...&limit=...` - OHLCV amb gap validation
  - Returns candles amb `is_complete` flag
  - TZ canònica: America/New_York

### Trading (Paper mode)
- `POST /positions` - Open position (idempotent via `client_order_id`)
- `GET /positions` - List open positions amb unrealized PnL
- `DELETE /positions/{position_id}` - Close position (idempotent)
- `PATCH /positions/{position_id}/sl` - Update stop loss
- `PATCH /positions/{position_id}/tp` - Update take profit
- `GET /balance` - Account balance + margin usage

### WebSocket (Real-time streaming)
- `WS /ws` - Real-time streaming with subscribe/unsubscribe
  - Channels: `ticker:SYMBOL`, `candle:SYMBOL:1m`, `positions`, `balance`, `execution`
  - Protocol: subscribe, unsubscribe, resume (with seq/resync)
  - All broadcast messages include sequence numbers
  - Automatic position/balance events on paper trades

---

## 💰 Fee Model (Paper Trading)

**Actual (Fase 4.5) - gTrade Official Fees:**

| Asset  | Spread | Open Fee | Close Fee | Total Cost |
|--------|--------|----------|-----------|------------|
| EURUSD | 0.01%  | 0.012%   | 0.012%    | ~0.034%    |
| XAUUSD | 0.01%  | 0.05%    | 0.05%     | ~0.11%     |

**Fee breakdown API response:**
```json
{
  "fees_breakdown": {
    "spread_cost": 1.00,
    "open_fee": 5.00,
    "price_impact_cost": 0.0,
    "total_entry_cost": 6.00
  }
}
```

**PnL tracking:**
- `pnl_gross`: Price movement only (before fees)
- `pnl_net`: Realized PnL (after all fees)

Fees calculats sobre `position_size = collateral × leverage`

**Borrowing fees & Dynamic Spread:** Placeholder (0.0) - implementació a Fase 6 amb real OI data

**Fonts:**
- https://docs.gains.trade/developer/integrators/guides/calculating-borrowing-fees
- https://docs.gains.trade/developer/integrators/price-feed

---

## 🛠️ Usage

### Quick Start

```bash
# Run tests
./test.sh testing/run_all.py

# Start service (paper mode, backtest data)
docker-compose up -d

# Health check
curl http://localhost:8000/api/v1/health

# Get OHLCV
curl "http://localhost:8000/api/v1/ohlcv/XAUUSD?limit=10"

# Open position (paper)
curl -X POST http://localhost:8000/api/v1/positions \
  -H "Content-Type: application/json" \
  -d '{
    "client_order_id": "test_001",
    "symbol": "XAUUSD",
    "side": "buy",
    "collateral": 1000,
    "leverage": 10,
    "sl_price": 2650,
    "tp_price": 2750
  }'
```

### Configuration (.env)

```bash
# Mode
MODE=paper                        # live | paper | backtest
VENUE=gtrade
SYMBOLS=XAUUSD,EURUSD

# Storage
CANONICAL_TZ=America/New_York
DATAFILES_ROOT=./datafiles

# Backfill
BACKFILL_INTERVAL_SECONDS=600     # 10 minutes
CORRECTIVE_WINDOW_MINUTES=5

# Paper trading
PAPER_INITIAL_BALANCE=10000       # USDC
PAPER_SLIPPAGE_BPS=5              # 5 basis points
PAPER_FEE_BPS=6                   # 0.06%

# Live mode (Fase 6 - future)
# ARBITRUM_RPC_URL=https://arb1.arbitrum.io/rpc
# GTRADE_PRIVATE_KEY=...
```

---

## 🧪 Testing

**Philosophy:** Simple Python scripts (NO pytest)

```bash
# Run all tests
./test.sh testing/run_all.py

# Run specific test
./test.sh testing/unit/test_idempotency.py
./test.sh testing/integration/test_paper_positions_flow.py
```

**Test suites:**
- Unit: 6 tests (store, validator, builder, provider, idempotency, cost_model)
- Integration: 3 tests (live_to_store, backfill_patch, paper_positions)
- API: 2 tests (rest_smoke, ws_smoke)

**Total: 11/11 passing ✅**

---

## 📈 Roadmap

### ✅ Completat
- Fase 1: Storage + Gap validation
- Fase 2: CandleBuilder + Live ingestion
- Fase 3: Backfill scheduler
- Fase 4: Paper trading + Idempotency
- Fase 4.5: CostModel oficial gTrade
- Fase 5: WebSocket Hub + Real-time broadcasting

### 🔜 Pròximes Fases

**Fase 6** - gTrade Live Adapter
- WS price feed integration (`wss://backend-arbitrum.gains.trade`)
- Smart contract execution (Arbitrum)
- Borrowing fees amb real OI data
- SDK integration (`@gainsnetwork/sdk`)
- Esforç: Alt (4-5h)

---

## 📚 Documentation

- [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md) - Complete architecture plan
- [ESTAT.md](ESTAT.md) - Current project state + pending tasks
- [testing/README.md](testing/README.md) - Testing documentation

**External:**
- [gTrade Developer Docs](https://docs.gains.trade/developer/integrators/backend)
- [gTrade Price Feed](https://docs.gains.trade/developer/integrators/price-feed)
- [Calculating Borrowing Fees](https://docs.gains.trade/developer/integrators/guides/calculating-borrowing-fees)

---

## 🤝 Contributing

Per afegir noves features:
1. Llegir [AGENTS_ARQUITECTURA.md](AGENTS_ARQUITECTURA.md) per entendre el pla
2. Implementar feature seguint principis SOLID + DI minimalista
3. Afegir tests (unit + integration si aplica)
4. Actualitzar [ESTAT.md](ESTAT.md) amb canvis
5. Executar `./test.sh testing/run_all.py` per validar

---

## 📄 License

MIT

# Extended Exchange (x10xchange) - Evaluation Lab

## 📋 Platform Overview

**Network:** Starknet (L2 Ethereum scaling)
**Architecture:** Hybrid CLOB (off-chain matching, on-chain settlement)
**Markets:** Crypto + TradFi perpetuals (forex, indices, commodities)
**Collateral:** USDC only
**Leverage:** 5x-100x (market-dependent)
**Trading:** 24/7 including weekends

---

## 🎯 Lab Objective

Validate Extended for BrokerageService integration following same methodology as gTrade/Ostium:

1. ✅ **Setup**: Install SDK, configure testnet
2. ⏳ **Connect**: Initialize SDK, authenticate
3. ⏳ **Query**: Test market data, positions API
4. ⏳ **Execute**: Open position on testnet
5. ⏳ **Monitor**: Track position via REST/WebSocket
6. ⏳ **Close**: Close position programmatically
7. ⏳ **Evaluate**: Compare fees, latency, reliability vs gTrade/Ostium

---

## 🔧 Technical Details

### API Endpoints
- **Mainnet**: `https://api.starknet.extended.exchange/api/v1`
- **Testnet**: `https://api.starknet.sepolia.extended.exchange/api/v1`

### Python SDK
- **Repo**: https://github.com/x10xchange/python_sdk
- **Python**: 3.10+ (supports 3.9-3.12)
- **Auth**: StarkNet keys derived from Ethereum wallet
- **Signing**: Rust-accelerated SNIP12/EIP712

### Key Features
- ✅ Full order lifecycle (place/cancel/query)
- ✅ Position tracking (current + historical)
- ✅ Real-time WebSocket streams
- ✅ Subaccount support
- ✅ TWAP and scaled order types
- ✅ Leverage management per market

---

## 📊 Available Markets

### TradFi (Traditional Finance)
- **Indices**: SPX (S&P 500), NDX (Nasdaq 100)
- **Forex**: EUR/USD and others
- **Commodities**: XAU (Gold), XAG (Silver), XBR (Brent - delisting)

### Crypto
- BTC, ETH, and multiple altcoins
- Organized in 6 liquidity groups

**Unique**: Trade TradFi 24/7 (spreads widen outside standard hours)

---

## 💰 Fee Structure

**Status**: Not documented in public docs
**TODO**: Extract from API during testing

**Comparison baseline**:
- gTrade: ~$10 per round-trip
- Ostium: ~$0.16 per round-trip

---

## ⚡ Position Limits

| Liquidity Group | Max Limit Order | Max Market Order | Max Position Value |
|-----------------|-----------------|------------------|-------------------|
| 1 (BTC, ETH)    | $15M           | $3M             | $30M              |
| 2               | $5M            | $1M             | $10M              |
| 3               | $2M            | $400k           | $4M               |
| 4               | $1M            | $200k           | $2M               |
| 5               | $500k          | $100k           | $1M               |
| 6 (small tokens)| $250k          | $50k            | $500k             |

---

## 🧪 Testing Strategy

### Phase 1: SDK Setup ✅
- [x] Research documentation
- [x] Create Dockerfile for isolated testing
- [x] Create docker-compose.yml
- [x] Configure requirements.txt with correct package
- [x] Create test_connection.py
- [x] Document API credentials setup
- [ ] User: Obtain API credentials from testnet.extended.exchange
- [ ] User: Run initial connection test

### Phase 2: Connection Test
- [ ] Initialize SDK with testnet endpoint
- [ ] Authenticate with Stark keys
- [ ] Query account balances
- [ ] List available markets

### Phase 3: Market Data
- [ ] Fetch market info (EUR/USD, BTC/USD)
- [ ] Test REST API latency
- [ ] Test WebSocket real-time feeds
- [ ] Compare data quality vs gTrade/Ostium

### Phase 4: Trading Cycle
- [ ] Open small position (5 USDC @ 10x leverage)
- [ ] Query position via REST API
- [ ] Monitor P&L updates
- [ ] Close position programmatically
- [ ] Measure end-to-end latency

### Phase 5: Advanced Features
- [ ] Test TWAP order execution
- [ ] Test conditional orders (TP/SL)
- [ ] Test WebSocket position updates
- [ ] Test subaccount isolation

### Phase 6: Comparison
- [ ] Fee structure vs gTrade/Ostium
- [ ] API latency vs competitors
- [ ] SDK reliability and error handling
- [ ] Documentation quality
- [ ] Testnet vs mainnet differences

---

## 🚨 Key Considerations

### ✅ Advantages
- **TradFi markets**: Unique access to indices/forex/commodities
- **24/7 trading**: No weekend gaps
- **Mature SDK**: Rust-accelerated, comprehensive API
- **Testnet available**: Full testing before mainnet
- **Hybrid CLOB**: Better price discovery than pure AMM

### ⚠️ Potential Issues
- **Starknet dependency**: Different L2 than Arbitrum (gTrade/Ostium)
- **USDC-only collateral**: Limited compared to multi-collateral platforms
- **Signature complexity**: All orders need Stark key signatures
- **Order expiration**: Max 90 days, requires renewal
- **No public subgraph**: Must rely on REST API for historical data
- **Liquidity groups**: Smaller tokens have strict limits

---

## 🎯 Success Criteria

For Extended to be viable for BrokerageService:

1. ✅ **Testnet available**: ✅ Confirmed (Sepolia)
2. ✅ **Python SDK exists**: ✅ Confirmed (mature, documented)
3. ⏳ **Open/Close cycle works**: TODO - validate programmatically
4. ⏳ **Position query < 5s**: TODO - test REST API latency
5. ⏳ **Fees competitive**: TODO - measure actual costs
6. ⏳ **SDK reliability**: TODO - error handling, edge cases
7. ⏳ **Documentation adequate**: TODO - validate during implementation

---

## 📝 Test Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| `test_connection.py` | SDK init + auth | ✅ Created |
| `test_markets.py` | Query available markets | TODO |
| `test_prices.py` | REST + WebSocket price feeds | TODO |
| `test_full_cycle.py` | Open → Monitor → Close | TODO |
| `test_websocket.py` | Real-time position updates | TODO |

## 🛠️ Setup Instructions

### 1. Get API Credentials
1. Visit https://testnet.extended.exchange/
2. Connect Ethereum wallet
3. Complete onboarding process
4. Navigate to **API Management**
5. Generate API key
6. Copy: `API key`, `Public key`, `Private key`, `Vault ID`

### 2. Configure Environment
```bash
cd /mnt/volume-SQ/dev/BrokerageService/lab/extended
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run via Docker
```bash
docker-compose build
docker-compose up -d
docker exec -it extended-cli bash
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Run Tests
```bash
python test_connection.py
```

---

## 🔗 Resources

- Docs: https://docs.extended.exchange/
- API Docs: https://api.docs.extended.exchange/
- Python SDK: https://github.com/x10xchange/python_sdk
- Trading Rules: https://docs.extended.exchange/extended-resources/trading/trading-rules
- Order Types: https://docs.extended.exchange/extended-resources/trading/order-types

---

## 📊 Comparison Matrix

| Feature | gTrade | Ostium | Extended |
|---------|--------|--------|----------|
| **Network** | Arbitrum | Arbitrum | Starknet |
| **Markets** | Crypto only | Crypto + Forex | Crypto + TradFi |
| **Testnet** | ✅ Fast subgraph | ❌ Broken subgraph | ⏳ TODO |
| **SDK Quality** | Good | Mixed (bugs) | ⏳ TODO |
| **Fees (RT)** | ~$10 | ~$0.16 | ⏳ TODO |
| **Position Query** | <5s subgraph | Mainnet: 1.90s, Testnet: >120s | ⏳ TODO |
| **24/7 Trading** | Crypto only | Crypto + Forex | All markets |
| **Unique Features** | - | - | TradFi indices/commodities |

---

## ✅ Next Steps

1. Install Extended Python SDK
2. Create Docker environment
3. Write `test_connection.py` to validate testnet access
4. Execute initial tests and document results
5. Update this document with findings
6. Prepare final recommendation for BrokerageService integration

---

**Status**: 🟡 Initial research complete, implementation pending
**Last Updated**: 2026-02-11

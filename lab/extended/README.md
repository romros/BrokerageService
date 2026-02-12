# Extended Exchange Lab

Quick start guide for testing Extended (x10xchange) on Starknet.

## Setup

### 1. Get API Credentials

Visit https://testnet.extended.exchange/ and:
1. Connect your Ethereum wallet
2. Onboard to the platform
3. Navigate to **API Management**
4. Generate API key
5. Copy: API key, Public key, Private key, Vault ID

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Build Docker Container

```bash
docker-compose build
docker-compose up -d
docker exec -it extended-cli bash
```

### 4. Install Dependencies

Inside container:
```bash
pip install -r requirements.txt
```

### 5. Run Tests

```bash
# Test connection and authentication
python test_connection.py

# Test market data (coming soon)
python test_markets.py

# Test full trading cycle (coming soon)
python test_full_cycle.py
```

## Quick Reference

**Network:** Starknet Sepolia (testnet)
**Collateral:** USDC
**Markets:** Crypto + TradFi (EUR-USD, BTC-USD, SPX, etc.)
**Leverage:** 5x-100x

## Documentation

- Main docs: https://docs.extended.exchange/
- API docs: https://api.docs.extended.exchange/
- Python SDK: https://github.com/x10xchange/python_sdk

## Comparison Target

We're evaluating Extended vs:
- **gTrade**: ~$10 fees, fast subgraph (<5s)
- **Ostium**: ~$0.16 fees, mainnet fast (1.90s), testnet broken (>120s)

Goal: Determine if Extended is viable for BrokerageService integration.

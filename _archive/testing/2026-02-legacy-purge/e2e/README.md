# E2E Tests - Real Testnet Transactions

⚠️  **MANUAL/SLOW TESTS - NOT RUN IN CI BY DEFAULT**

## Overview

E2E tests execute **REAL blockchain transactions** on Arbitrum Sepolia testnet to validate:

- RPC connectivity
- Transaction signing and broadcasting
- Backend verification loop
- Market status fallback logic
- Position lifecycle (open → verify → close)
- Balance tracking

## Safety Guards

All E2E tests enforce strict safety checks:

1. **E2E_TESTNET=1** - Confirms intent to run testnet transactions
2. **ENABLE_LIVE_TRADING=1** - Enables transaction execution
3. **Chain ID verification** - Must be 421614 (Sepolia), aborts on mainnet
4. **Collateral limits** - MAX_COLLATERAL_USDC enforced (default: 10 USDC)
5. **Balance checks** - Verifies sufficient ETH + USDC before execution

## Test Execution

### Option 1: Standalone Script (Recommended)

```bash
# Run with small collateral (5 USDC)
E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 ./test.sh _archive/python/2026-02-cleanup/scripts/testnet_e2e_smoke.py

# Run with custom collateral limit
E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 MAX_COLLATERAL_USDC=20 ./test.sh _archive/python/2026-02-cleanup/scripts/testnet_e2e_smoke.py
```

### Option 2: Pytest Wrapper

```bash
# Run all E2E tests
E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 pytest testing/e2e/ -v -s

# Run specific test
E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 pytest testing/e2e/test_testnet_smoke.py -v -s

# With custom config
E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 MAX_COLLATERAL_USDC=20 pytest testing/e2e/ -v -s
```

## Prerequisites

1. **Arbitrum Sepolia RPC** configured in `.env`
2. **Testnet wallet** with:
   - ETH for gas (at least 0.001 ETH)
   - GNS_USDC tokens (at least MAX_COLLATERAL_USDC)
3. **Environment variables** set:
   - `ARBITRUM_RPC_URL`
   - `WALLET_MNEMONIC` or `WALLET_PRIVATE_KEY`
   - `GTRADE_DIAMOND_ADDRESS` (Sepolia: 0xd659a15812064C79E189fd950A189b15c75d3186)

## What Gets Tested

### testnet_e2e_smoke.py

Full position lifecycle:

1. **Health check** - Chain ID, balances (ETH + USDC)
2. **Find tradable symbol** - Uses fallback if primary closed
3. **Open position** - Small collateral (5 USDC @ 2x leverage)
4. **Backend verification** - Polls until position_id resolved
5. **Verify position listed** - Check `get_open_positions()`
6. **Close position** - Exit via market order
7. **Verify position removed** - Confirm backend sync
8. **Final balance check** - Track ETH gas + USDC change

**Expected duration:** 30-60s (depends on network + backend polling)

## CI/CD Integration

E2E tests are **SKIPPED by default** in CI pipelines.

To enable in CI:

```yaml
# .gitlab-ci.yml or .github/workflows/test.yml
e2e-testnet:
  stage: test
  when: manual  # Manual trigger only
  variables:
    E2E_TESTNET: "1"
    ENABLE_LIVE_TRADING: "1"
  script:
    - pytest testing/e2e/ -v -s
```

## Troubleshooting

### Test skipped

```
❌ ABORT: E2E_TESTNET must be set to '1'
```

**Fix:** Set environment variable `E2E_TESTNET=1`

### Insufficient balance

```
❌ ABORT: Insufficient ETH balance (need at least 0.001 ETH for gas)
```

**Fix:** Get testnet ETH from [Arbitrum Bridge](https://bridge.arbitrum.io/)

### Wrong chain

```
❌ ABORT: Detected MAINNET chain_id=42161
```

**Fix:** Verify `ARBITRUM_RPC_URL` points to Sepolia testnet (`https://sepolia-rollup.arbitrum.io/rpc`)

### Market closed

E2E tests use **fallback logic** automatically:
- If XAUUSD closed (weekend) → tries EURUSD → tries BTCUSD
- Test should NOT fail due to market hours

If all symbols closed:
```
❌ No tradable symbols found!
```

**Fix:** Add more fallback symbols in `.env`:
```bash
FALLBACK_SYMBOLS=BTCUSD,ETHUSD
```

## Cost Estimation

Typical costs per E2E run (Sepolia testnet):

- **Gas cost:** ~0.0001-0.0005 ETH (~$0.30-$1.50 mainnet equivalent, FREE on testnet)
- **Trading fees:** ~0.05-0.15 USDC (gTrade fees, deducted from position)
- **Slippage:** Minimal (2-3 bps with 5 USDC position)

**Total testnet cost:** FREE (testnet ETH + GNS_USDC have no real value)

## Validation Checklist

Before marking FASE 6B.1.B.7 complete:

- [ ] E2E script runs 3 times consecutively without errors
- [ ] Position opens successfully (txhash + position_id resolved)
- [ ] Backend verification confirms position appears
- [ ] Position closes successfully
- [ ] Backend verification confirms position removed
- [ ] Balance tracking accurate (ETH gas deducted, USDC change tracked)
- [ ] Fallback logic works (tested on weekend or with unavailable primary symbol)
- [ ] Safety guards enforce (rejects mainnet, enforces collateral limits)

## Next Steps

After E2E validation:

**FASE 6B.2 - Mainnet Integration:**
- Reconcile loop (compare local vs blockchain state)
- Real borrowing fees integration (`/trading-variables`)
- Dynamic spread calculation
- Safety audit + monitoring
- Production deployment checklist

**FASE 7 - Historical Data Integration:**
- Real Dukascopy or gTrade `/charts` backfill
- Replace MockBackfillProvider

**FASE 8 - Backtest Mode:**
- Virtual clock (IClock implementation)
- Historical data playback
- Backtest controls API

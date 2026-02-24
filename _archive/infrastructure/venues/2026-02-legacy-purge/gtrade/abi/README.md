# gTrade ABI - Official Contract Interfaces

This directory contains the official ABI (Application Binary Interface) for the gTrade Diamond contract used for on-chain trading interactions.

---

## 📋 Files

### `GNSMultiCollatDiamond.json`

- **Contract Name:** GNSDiamond
- **Contract Address:** `0xFF162c694eAA571f685030649814282eA457f169` (Arbitrum Mainnet)
- **Source:** [Gains Network SDK](https://github.com/GainsNetwork-org/sdk/blob/main/abi/GNSMultiCollatDiamond.json)
- **Version:** gTrade v8+ (Diamond Pattern)
- **Size:** 528 KB, 21,549 lines

---

## 🔧 Functions Used

### 1. **openTrade**

**Signature:**
```solidity
openTrade(
    (address,uint32,uint16,uint24,bool,bool,uint8,uint8,uint120,uint64,uint64,uint64,bool,uint160,uint24),
    uint16,
    address
)
```

**Selector:** `0x5bfcc4f8`

**Parameters:**
1. **Trade struct** (tuple with 15 fields):
   - `user` (address): Trader wallet address
   - `index` (uint32): Trade index (0 for new trades)
   - `pairIndex` (uint16): Trading pair ID (0=XAUUSD, 1=EURUSD, etc.)
   - `leverage` (uint24): Leverage scaled by 1e3 (10,000 = 10x)
   - `long` (bool): True=LONG, False=SHORT
   - `isOpen` (bool): Always true for new trades
   - `collateralIndex` (uint8): Collateral token index (0=USDC)
   - `tradeType` (uint8): 0=TRADE (market), 1=LIMIT, 2=STOP
   - `collateralAmount` (uint120): Collateral in token wei (USDC=6 decimals)
   - `openPrice` (uint64): Market price scaled by 1e10 (for slippage check)
   - `tp` (uint64): Take profit price scaled by 1e10 (0=no TP)
   - `sl` (uint64): Stop loss price scaled by 1e10 (0=no SL)
   - `isCounterTrade` (bool): False (reserved for future use)
   - `positionSizeToken` (uint160): 0 (calculated by contract)
   - `__placeholder` (uint24): 0 (reserved)

2. **maxSlippageP** (uint16): Max slippage in basis points (300 = 3%)
3. **referrer** (address): Referrer address (0x0 if none)

**Usage:** Opens a new leveraged position (LONG or SHORT) with specified collateral and leverage.

---

### 2. **closeTradeMarket**

**Signature:**
```solidity
closeTradeMarket(uint32,uint64)
```

**Selector:** `0x36ce736b`

**Parameters:**
1. **_index** (uint32): Trade index
2. **_expectedPrice** (uint64): Expected market price scaled by 1e10 (for slippage protection)

**Usage:** Closes an existing trade at market price. Contract looks up the trade by index internally (no need to pass pairIndex).

---

### 3. **updateSl**

**Signature:**
```solidity
updateSl(uint32,uint64)
```

**Selector:** `0xb5d9e9d0`

**Parameters:**
1. **_index** (uint32): Trade index
2. **_newSl** (uint64): New stop loss price scaled by 1e10

**Usage:** Updates the stop loss price for an existing trade.

---

### 4. **updateTp**

**Signature:**
```solidity
updateTp(uint32,uint64)
```

**Selector:** `0xf401f2bb`

**Parameters:**
1. **_index** (uint32): Trade index
2. **_newTp** (uint64): New take profit price scaled by 1e10

**Usage:** Updates the take profit price for an existing trade.

---

## ✅ Selector Verification

To verify that function selectors match the official ABI:

```bash
# Run selector verification script
./test.sh testing/verify_abi_selectors.py
```

Expected output:
```
✅ openTrade: selector matches (0x5bfcc4f8)
✅ closeTradeMarket: selector matches (0x36ce736b)
✅ updateSl: selector matches (0xb5d9e9d0)
✅ updateTp: selector matches (0xf401f2bb)
```

---

## 📚 References

### Official Documentation
- **gTrade Docs:** https://docs.gains.trade/developer/integrators
- **Contract Addresses:** https://docs.gains.trade/what-is-gains-network/contract-addresses
- **Gains Network SDK:** https://github.com/GainsNetwork-org/sdk
- **Diamond Pattern (v8):** https://medium.com/gains-network/introducing-gtrade-v8-diamond-refactor-and-smart-contract-integration-a175b96ccb82

### Blockchain Explorers
- **Arbiscan (Mainnet):** https://arbiscan.io/address/0xFF162c694eAA571f685030649814282eA457f169
- **Testnet:** Arbitrum Sepolia (address TBD)

---

## 🔄 Updating the ABI

If a new gTrade version is released, update the ABI:

```bash
# Download latest ABI from SDK
curl -sL "https://raw.githubusercontent.com/GainsNetwork-org/sdk/main/abi/GNSMultiCollatDiamond.json" \
  -o infrastructure/venues/gtrade/abi/GNSMultiCollatDiamond.json

# Verify selectors still match
./test.sh testing/verify_abi_selectors.py

# Update signatures in abi_encoder.py if changed
# Run full test suite
./test.sh testing/run_all.py
```

---

## ⚠️ Important Notes

1. **Price Scaling:** All prices use 1e10 scaling (10 decimals)
   - Example: 2700.5 XAUUSD → `27005000000000`

2. **Leverage Scaling:** Leverage uses 1e3 scaling (3 decimals)
   - Example: 10x leverage → `10000`

3. **Collateral:** USDC uses 6 decimals (1e6)
   - Example: 1000 USDC → `1000000000`

4. **Trade Index:** Assigned by backend after trade creation
   - Use `index=0` when opening new trades
   - Backend returns real index via `/open-trades/<address>` API

5. **Diamond Pattern:** The contract uses EIP-2535 Diamond pattern
   - Single entry point (`GNSMultiCollatDiamond`)
   - Functions delegated to facets internally
   - ABI aggregates all facet functions

---

**Last Updated:** 2026-02-09
**gTrade Version:** v8+ (Diamond)
**ABI Source:** [GainsNetwork-org/sdk](https://github.com/GainsNetwork-org/sdk)

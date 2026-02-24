# Lab gTrade — Experiments i Validacions

## 🎯 Objectiu

Directori d'experiments específics per gTrade: price feeds, trade execution, validació de paràmetres.

---

## 📁 Scripts Disponibles

### 1. `ws_price_probe.py` — WebSocket Price Monitor

**Què fa:**
- Connecta al price feed de gTrade: `wss://feed-gtrade-arb.gainsnetwork.io/ws`
- Mostra preus en temps real per cada pair
- Valida scaling (1e10) i format
- Útil per debug i validació de fonts de preus

**Com executar:**
```bash
python lab/gtrade/ws_price_probe.py

# O dins Docker:
docker compose run --rm brokerage python lab/gtrade/ws_price_probe.py
```

**Output esperat:**
```
📡 WebSocket Price Feed (wss://feed-gtrade-arb.gainsnetwork.io/ws)
════════════════════════════════════════════════════════════════════

BTCUSD: $70,457.42 (scaled: 704574200000000)
ETHUSD: $3,245.67 (scaled: 32456700000000)
LINKUSD: $25.34 (scaled: 253400000000)

Updated: 2026-02-10 07:15:23 UTC
```

---

### 2. `open_trade_once.py` — Trade Mínim (Testnet)

**Què fa:**
- Executa 1 trade mínim (150 USDC @ 10x = $1,500)
- Usa preu real del WebSocket feed
- **NOMÉS amb safety guards**: `E2E_TESTNET=1` + `ENABLE_LIVE_TRADING=1`
- Documenta TxHash i resultat

**Com executar:**
```bash
E2E_TESTNET=1 \
ENABLE_LIVE_TRADING=1 \
WALLET_PRIVATE_KEY=0x... \
python lab/gtrade/open_trade_once.py
```

**Safety checks:**
- ✅ Chain ID = 421614 (Sepolia only)
- ✅ Balance ETH >= 0.01 (gas)
- ✅ Balance USDC >= 150
- ✅ USDC allowance approved
- ❌ Abort si mainnet detectat

---

### 3. `open_close_cycle.py` — Open & Close Cycle (RECOMANAT!)

**Què fa:**
- Aplica TOTS els descobriments de l'anàlisi SDK oficial
- **maxSlippage com MULTIPLICADOR** (1.10 = 110% = 10% slippage)
- openPrice amb buffer adequat (5% per LONG)
- Obre posició, espera 10s, tanca posició
- Validació completa de balances i health checks

**DESCOBRIMENTS APLICATS:**
```python
# maxSlippage = MULTIPLICADOR, NO percentage!
max_slippage_multiplier = 1.10  # 110% = acepto fins a 10% slippage
max_slippage_scaled = 1100      # × 1e3

# openPrice = LIMIT PRICE (preu màxim per LONG)
open_price = oracle_price * 1.05  # 5% buffer
```

**Com executar:**
```bash
E2E_TESTNET=1 \
ENABLE_LIVE_TRADING=1 \
WALLET_PRIVATE_KEY=0x... \
python lab/gtrade/open_close_cycle.py
```

**Diferències vs open_trade_once.py:**
- ✅ maxSlippage correcte (1100 vs 1000)
- ✅ openPrice amb buffer explícit
- ✅ Crida contracte directament (no adapter)
- ✅ Cicle complet open → wait → close
- ✅ Documentació exhaustiva de cada pas

---

## 🏗️ Components Implementats

### `GTradePriceProviderWS`

**Ubicació:** `infrastructure/venues/gtrade/price_provider.py`

**Interfície:**
```python
class IPriceProvider(Protocol):
    async def get_current_price(self, symbol: str) -> float:
        """Get current market price for symbol"""
        ...

class GTradePriceProviderWS(IPriceProvider):
    """WebSocket-based price provider using gTrade feed"""

    def __init__(self, ws_url: str = DEFAULT_GTRADE_PRICE_WS_URL):
        ...

    async def start(self):
        """Start WebSocket client"""
        ...

    async def stop(self):
        """Stop WebSocket client"""
        ...

    async def get_current_price(self, symbol: str) -> float:
        """Get latest price from cache (non-blocking)"""
        ...
```

**Ús:**
```python
provider = GTradePriceProviderWS()
await provider.start()

# Get current price
btc_price = await provider.get_current_price("BTCUSD")  # 70457.42

# Calculate openPrice for LONG
open_price = btc_price * 1.05  # 5% buffer
open_price_scaled = int(open_price * 1e10)

await provider.stop()
```

---

## 🧪 Validació de Paràmetres

### Scaling Factors (CRÍTIC)

| Paràmetre | Escala | Exemple |
|-----------|--------|---------|
| `openPrice` | **1e10** | 70457.42 → 704574200000000 |
| `leverage` | **1e3** | 10x → 10000 |
| `collateralAmount` | **1e6** (USDC) | 150 USDC → 150000000 |
| `maxSlippageP` | **1e3** | 10% → 1000 |
| `positionSizeToken` | **1e18** | Varies by asset |

**Validar scaling:**
```python
# Correcte
price = 70457.42
scaled = int(price * 1e10)  # 704574200000000 ✅

# Incorrecte
scaled = int(price * 1e18)  # MASSA GRAN ❌
scaled = int(price)         # MASSA PETIT ❌
```

---

## 🚨 Errors Comuns

### Error `0x10906acb`

**Significat:** Validació de preu fallida (openPrice fora de rang acceptable)

**Causes:**
1. `openPrice = 0` → No permès
2. `openPrice` massa alt per LONG (> oracle_price + buffer)
3. `openPrice` massa baix per SHORT (< oracle_price - buffer)
4. `openPrice` no escalat correctament (1e10)

**Solució:**
```python
# LONG: openPrice ha de ser >= oracle_price
# SHORT: openPrice ha de ser <= oracle_price

oracle_price = await provider.get_current_price("BTCUSD")

if is_long:
    open_price = oracle_price * 1.05  # 5% buffer (conservador)
else:
    open_price = oracle_price * 0.95  # 5% buffer (conservador)

open_price_scaled = int(open_price * 1e10)
```

---

### Error `InvalidCollateralIndex`

**Causa:** collateralIndex incorrecte per xarxa

**Solució:**
- **Sepolia:** `collateralIndex = 3` (GNS_USDC: 0x4cC7...)
- **Mainnet:** `collateralIndex = 0` (USDC: 0x75fE...)

---

### Error `InsufficientBalance`

**Causes:**
1. Balance USDC insuficient
2. USDC allowance no aprovada

**Solució:**
```bash
# Aprovar allowance primer
python _archive/python/2026-02-cleanup/scripts/approve_usdc.py
```

---

### Error Position Size Mínim

**Causa:** `collateral × leverage < $1,500 USD` (Sepolia)

**Solució:**
```python
# Mínim Sepolia: $1,500
collateral = 150.0  # USDC
leverage = 10       # 150 × 10 = $1,500 ✅

# Massa petit:
collateral = 50.0
leverage = 10       # 50 × 10 = $500 ❌
```

---

## 📚 Referències

### Documentació Oficial

- [Opening/Closing Trades](https://docs.gains.trade/gtrade-leveraged-trading/opening-closing-trades)
  - Market orders
  - openPrice parameter
  - Max slippage protection

- [Technical Reference - Contracts](https://docs.gains.trade/developer/technical-reference/contracts)
  - Diamond pattern
  - Trade struct (15 camps)
  - Function signatures

- [ITradingInteractionsUtils](https://docs.gains.trade/developer/technical-reference/contracts/interfaces/libraries/itradinginteractionsutils)
  - `openTrade()` signature
  - Parameter types
  - Validation rules

- [Backend Integration](https://docs.gains.trade/developer/integrators/backend)
  - REST endpoints
  - WebSocket price feed
  - Data structures

### Descobriments Lab

**Validat amb txs reals Sepolia:**
- ✅ openPrice NO pot ser 0 (és limit price, no "use oracle")
- ✅ openPrice = oracle_price × buffer (1.05 per LONG funciona)
- ✅ maxSlippageP independent (1000 = 10% OK)
- ✅ collateralIndex=3 per Sepolia (vs 0 mainnet)
- ✅ Position size mínim $1,500 USD

**TX Referència exitosa:**
- [0xced13024...](https://sepolia.arbiscan.io/tx/0xced130245364a21c052cd913a95138dca230356a5c52dd485ffe1cd6b47f1d3c)
- openPrice: 704574168395628 (70457.42 USD)
- collateralIndex: 3
- maxSlippageP: 1000
- leverage: 200x

---

## 🎯 Workflow Recomanat

### 1. Debug Price Feed
```bash
# Veure preus en temps real
python lab/gtrade/ws_price_probe.py

# Validar que preus són correctes
# Comparar amb CoinGecko/Binance
```

### 2. Test Trade Mínim
```bash
# Executar 1 trade testnet
E2E_TESTNET=1 ENABLE_LIVE_TRADING=1 \
python lab/gtrade/open_trade_once.py

# Validar a Arbiscan Sepolia
# Confirmar que apareix a historial
```

### 3. Integració Core
```bash
# Quan validat, integrar a E2E smoke
./test.sh _archive/python/2026-02-cleanup/scripts/testnet_e2e_smoke.py

# Verificar 3 runs consecutius OK
```

---

## ⚠️ Safety Notes

- **SEMPRE testejar primer a Sepolia** (testnet)
- **NEVER skip safety guards** (E2E_TESTNET, ENABLE_LIVE_TRADING)
- **Collateral limits** (MAX_COLLATERAL_USDC per experiment)
- **Chain ID verification** (421614 only, abort on mainnet)
- **Documentar cada experiment** a lab/NOTES.md amb evidència

---

**Última actualització:** 2026-02-10 07:20 UTC

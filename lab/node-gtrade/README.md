# Node.js + Python Bridge Demo

## 🎯 Objectiu

Validar que podem usar la SDK oficial de gTrade (@gainsnetwork/trading-sdk) des de Node.js i cridar-la des de Python.

## 📁 Estructura

```
lab/node-gtrade/
├── package.json         # Dependencies
├── simpleQuote.js       # Node.js CLI: genera quote + calldata
├── bridge_demo.py       # Python: crida Node.js i parseja JSON
└── README.md           # Aquest fitxer
```

## 🚀 Setup

```bash
cd lab/node-gtrade

# Install Node.js dependencies
npm install

# Verify Node.js works
node simpleQuote.js

# Test Python bridge
python3 bridge_demo.py
```

## 📊 Output Esperat

**Node.js CLI (simpleQuote.js):**
```json
{
  "success": true,
  "config": {
    "pair": "BTCUSD",
    "direction": "LONG",
    "collateral": 150,
    "leverage": 10
  },
  "quote": {
    "oraclePrice": 70000,
    "openPrice": 73500,
    "maxSlippage": 1.1,
    "buffer": 1.05,
    "positionSize": 1500
  },
  "transaction": {
    "to": "0x4E796d9c5ca682fD37912D01d09EBed394f1B2d4",
    "data": "0x5bfcc4f8..."
  },
  "parameters": {
    "openPriceScaled": 735000000000000,
    "maxSlippageScaled": 1100,
    "leverageScaled": 10000,
    "collateralScaled": "150000000"
  }
}
```

**Python Bridge (bridge_demo.py):**
```
🧪 DEMO: Node.js + Python Bridge
================================================================================

🔧 Calling Node.js CLI...

✅ Quote received from Node.js!

📊 Quote details:
   Pair: BTCUSD
   Direction: LONG
   Collateral: $150.0 USDC
   Leverage: 10x

   Oracle Price: $70,000.00
   Open Price: $73,500.00
   Max Slippage: 1.1 (10%)
   Position Size: $1,500

🔧 Scaled parameters:
   openPrice: 735000000000000
   maxSlippage: 1100
   leverage: 10000
   collateral: 150000000

📝 Transaction:
   to: 0x4E796d9c5ca682fD37912D01d09EBed394f1B2d4
   data: 0x5bfcc4f8...

================================================================================
✅ DEMO SUCCESS: Node.js CLI → Python bridge works!
================================================================================
```

## 🔍 Descobriments Aplicats

### 1. maxSlippage com MULTIPLICADOR
```javascript
const maxSlippage = isLong ? 1.10 : 0.90;  // 1.10 = 110% = 10% slippage
```

**NO** percentage (1000), sinó multiplicador (1.10).

### 2. openPrice amb buffer
```javascript
const buffer = isLong ? 1.05 : 0.95;       // 5% buffer
const openPrice = oraclePrice * buffer;
```

Per LONG: acceptem pagar fins a 5% més de l'oracle.

### 3. SDK fa scaling automàtic
```javascript
const tx = await sdk.build.openTrade({
  openPrice: 73500,        // Float normal
  maxSlippage: 1.10,       // Multiplicador
  leverage: 10             // Integer
});
```

SDK converteix a:
- `openPrice`: × 1e10 → 735000000000000
- `maxSlippage`: × 1e3 → 1100
- `leverage`: × 1e3 → 10000

## ✅ Avantatges Approach

1. **SDK Oficial:** Usa @gainsnetwork/trading-sdk (TypeScript)
2. **Python Compatible:** subprocess + JSON communication
3. **Type Safety:** Node.js amb imports ES6
4. **Testable:** Separació clara CLI ↔ Bridge
5. **Descobriments Aplicats:** Tots els learnings integrats

## 🔬 Next Steps

Si aquesta demo funciona:

1. Afegir `estimateGas` validation
2. Crear `executeOpenTrade.js` per trades reals
3. Integrar a `gtrade_adapter.py` via bridge
4. Tests E2E amb Sepolia

## 📝 Notes

- Node.js version: >= 18.x (per ESM support)
- Dependencies: @gainsnetwork/trading-sdk, ethers v6
- Output: stdout = JSON, stderr = logs

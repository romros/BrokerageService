# Ostium - Resultats de Validació

**Data**: 2026-02-11
**Network**: Arbitrum Sepolia (testnet)
**Status**: ✅ **VIABLE amb workaround**

---

## 📊 Resultat Final

### ✅ Trade Validat
- **TX**: [0xb7021ec9e63979f740036301d407d17170a3996be823281369eb0c84ea9c89e9](https://sepolia.arbiscan.io/tx/0xb7021ec9e63979f740036301d407d17170a3996be823281369eb0c84ea9c89e9)
- **Pair**: EUR/USD
- **Direction**: LONG 10x
- **Collateral**: 99.20 USDC
- **Entry**: $1.18553
- **Exit**: $1.18588
- **PNL**: **+$0.29 (+0.30%)** ✅
- **Duration**: ~8 minuts

### 💰 Fees (Market Orders)
- **Open gas**: ~475k (475,086 | 474,033 | 474,794 avg)
- **Close gas**: ~460k (from previous tests)
- **Total gas**: ~935k per round-trip
- **Cost**: **~$0.22** per RT @ 0.1 gwei, ETH $2,300
- **vs gTrade**: ~$10 per RT
- **Estalvi**: **45x més barat!** 🎯

**Nota**: Fees validades amb 3 trades independents ([detalls](MARKET_FEES_RESULTS.md))

---

## ⚠️ Problema: Subgraph Testnet

### Diagnòstic
- ✅ API respon ràpid (0.26s)
- ❌ NO indexa noves transaccions
- **Workaround**: Brute force trade_index (0-255)

### Solució Implementada

**Flow sense subgraph**:
1. Obrir posició amb SDK → obtenir receipt
2. Extreure `pair_id` dels events (topic[3] de OrderOpened)
3. Trobar `trade_index` via contract query (0-255)
4. Tancar posició amb SDK

**Cost**: Màxim 256 RPC calls (~1s amb RPC ràpid)

---

## 🧪 Scripts Disponibles

### 1. Health Check
**File**: `test_subgraph_quick.py`

Verifica si el subgraph respon (testnet i mainnet).

```bash
python3 test_subgraph_quick.py
```

---

### 2. Full Cycle (Original)
**File**: `test_full_cycle.py`

Cicle complet amb subgraph (trencat en testnet).

```bash
python3 test_full_cycle.py
```

⚠️ Requereix subgraph funcionant

---

### 3. Full Cycle NO Subgraph ✅ (RECOMANAT)
**File**: `test_full_cycle_no_subgraph.py`

Cicle complet SENSE subgraph. **Approach robust per producció**.

```bash
python3 test_full_cycle_no_subgraph.py
```

**Avantatges**:
- ✅ No depèn del subgraph
- ✅ Usa SDK (codi net)
- ✅ Ràpid (no espera 120s)
- ✅ Fiable (llegeix de blockchain directament)

---

### 4. Market Fees Analysis
**File**: `test_market_fees.py`

Analitza gas i fees de Market orders (3 trades).

```bash
python3 test_market_fees.py
```

**Resultat**: ~$0.22 per round-trip ([veure detalls](MARKET_FEES_RESULTS.md))

---

## 🐳 Docker

Tots els scripts corren dins del container:

```bash
docker exec -it ostium_lab bash
python3 test_full_cycle_no_subgraph.py
```

---

## 🎯 Recomanació per Producció

### Testnet
✅ **Usar `test_full_cycle_no_subgraph.py`**
- Workaround funciona perfectament
- No depèn del subgraph trencat

### Mainnet
⚠️ **Validar primer abans de desplegar**:

1. Test petit en mainnet (5-10 USDC)
2. Verificar si subgraph mainnet indexa correctament
3. Si subgraph mainnet funciona → **EXCEL·LENT** (fees molt barates)
4. Si subgraph mainnet també falla → Usar mateix workaround

---

## 📈 Comparativa

| Criteri | gTrade | Ostium |
|---------|--------|--------|
| **Fees RT (Market)** | ~$10 | ~$0.22 ✅ |
| **Fees RT (Limit)** | ~$10 | ❌ NO suportades testnet |
| **Testnet subgraph** | ✅ <5s | ❌ NO indexa |
| **Mainnet subgraph** | ✅ <5s | ⚠️ Per validar |
| **SDK qualitat** | ✅ Madur | ⚠️ Bugs menors |
| **Workaround disponible** | N/A | ✅ Funciona |
| **Producció ready** | ✅ Sí | ⚠️ Validar mainnet |

**Conclusió**: Ostium **45x més barat** (Market orders) però cal validar mainnet abans de producció.

---

## 📁 Fitxers

**Scripts**:
- `test_subgraph_quick.py` - Health check
- `test_full_cycle.py` - Cicle amb subgraph
- `test_full_cycle_no_subgraph.py` - Cicle sense subgraph ✅
- `test_market_fees.py` - Anàlisi fees Market orders
- `test_limit_with_abi.py` - Test LIMIT amb ABI directe

**Documentació**:
- `MARKET_FEES_RESULTS.md` - Resultats detallats fees Market
- `LIMIT_ORDERS_INVESTIGATION.md` - Investigació LIMIT orders
- `FEES_THEORETICAL.md` - Fees teòrics (maker/taker/spread) ✅

**Config**:
- `Dockerfile` - Container setup
- `requirements.txt` - Dependencies
- `.env.example` - Config template

---

**Última actualització**: 2026-02-11
**Status**: ✅ Testnet validat, mainnet pendent

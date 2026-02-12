# Lab — Experimental Area

## 🎯 Propòsit

El directori `lab/` és un espai d'experimentació per **descobrir com funcionen sistemes externs** (testnet, APIs, oracles) **sense modificar el codi core** del projecte.

### Regles d'Or

1. **NO TOCAR CORE**: Cap experiment modifica `infrastructure/`, `domain/`, `application/` o `testing/`
2. **Evidència documentada**: Tots els descobriments van a `lab/NOTES.md` amb:
   - Data, objectiu, paràmetres
   - Resultat (txhash, error, output)
   - Conclusions
3. **Promoció controlada**: Quan trobem solució → escriure proposta a `NOTES.md` → llavors sí, PR petit amb tests
4. **No CI**: Scripts de lab NO entren a CI ni a `testing/run_all.py`

## 📁 Estructura

```
lab/
  README.md              # Aquest fitxer
  NOTES.md               # Diari d'experimentació

  gtrade/                # gTrade integration (validated ✅)
  ostium/                # Ostium integration (testnet ❌, mainnet ⚠️)
  extended/              # Extended (x10xchange) evaluation (🟡 in progress)

  sepolia/               # Experiments Arbitrum Sepolia testnet
    decode_reference_tx.py        # Decodificar tx exitosa de referència
    reproduce_revert_open_trade.py # Reproduir revert 0x10906acb
    brute_open_price_window.py    # Trobar rang acceptable d'openPrice
    price_sources_probe.py        # Provar fonts de preus
    artifacts/
      reference_tx.json   # Dades tx exitosa
      last_run.json       # Últim experiment
```

## 🚀 Com Executar

```bash
# Scripts lab s'executen amb test.sh per usar Docker env
./test.sh lab/sepolia/decode_reference_tx.py

# O directament amb docker compose
docker compose run --rm \
  -e ARBITRUM_RPC_URL="..." \
  -e WALLET_PRIVATE_KEY="..." \
  brokerage python lab/sepolia/reproduce_revert_open_trade.py
```

## ⚠️ Safety

- Scripts lab poden enviar tx reals (amb `LAB_CONFIRM=1`)
- Sempre usar testnet (chain_id=421614)
- Collateral mínim per experiments (1500 notional = 150 USDC @ 10x)
- Cada script documenta params abans d'executar

## 🎓 Workflow Típic

1. **Descoberta**: Executar scripts lab per entendre comportament
2. **Documentació**: Escriure descobriments a `NOTES.md` amb evidència
3. **Proposta**: Quan clar, escriure disseny de solució (sense codi)
4. **Promoció**: PR petit al core amb tests, basat en evidència lab
5. **Cleanup**: Mantenir lab net, archivar experiments antics

---

## 📊 Platform Evaluations

### Lighter (✅ VALIDATED - CHEAPEST)
- **Network**: Lighter L3 ZK-rollup (Arbitrum testnet)
- **Cost/RT**: **$0.16** (0% protocol fees + $0.08 gas each way)
- **Status**: ✅ COMPLETE - Market, Limit, SL/TP, Cancel validated
- **Report**: [lighter/LIGHTER_COMPLETE_VALIDATION.md](lighter/LIGHTER_COMPLETE_VALIDATION.md)
- **EUR/USD**: ❌ Not available on testnet (needs mainnet validation)
- **Key Discovery**: Decimal scaling varies by order type (×1e6 vs ×100/×10k)

### gTrade (✅ Validated)
- **Network**: Arbitrum (Sepolia testnet validated)
- **Cost/RT**: ~$10 per round-trip (high min fees: $5/trade)
- **Status**: ✅ Production-ready via Node.js SDK bridge
- **EUR/USD**: ✅ Available (mainnet)
- **Key Discovery**: openPrice = limit price (not "use oracle"), maxSlippage = multiplicador × 1e3

### Ostium (⚠️ Partially Viable)
- **Network**: Arbitrum
- **Cost/RT**: ~$0.56 per round-trip
- **Status**: ⚠️ Testnet subgraph broken (>120s), mainnet functional
- **EUR/USD**: ✅ Available
- **Key Discovery**: Testnet ≠ mainnet reliability

### Extended (🟡 In Progress)
- **Network**: Starknet
- **Markets**: Crypto + TradFi (indices, forex, commodities)
- **SDK**: Python 3.10+, Rust-accelerated
- **Status**: Initial lab setup complete, awaiting API credentials

---

## 🏆 Decision Matrix (Current)

| Broker | Cost/RT | EUR/USD | Validation | Mainnet | Recommendation |
|--------|---------|---------|------------|---------|----------------|
| **Lighter** | **$0.16** 🏆 | ❌ Testnet | ✅ Complete | ⏳ Pending | **Best for crypto** (if EUR/USD confirmed mainnet) |
| **Ostium** | $0.56 | ✅ | ⚠️ Partial | ⚠️ | **Backup/Forex** |
| **gTrade** | $10.00 | ✅ | ✅ Complete | ✅ | **High-volume only** (fees prohibitive <$10k positions) |

**Next Step**: Validate Lighter EUR/USD availability on mainnet → Final decision

See [NOTES.md](NOTES.md) for chronological experiment journal.

---

**Status actual:** Lighter validation COMPLETE (testnet), awaiting mainnet EUR/USD confirmation

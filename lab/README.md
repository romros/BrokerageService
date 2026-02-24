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

## 📁 Estructura (T5.32 Ostium-first)

```
lab/
  README.md              # Aquest fitxer
  NOTES.md               # Diari d'experimentació
  ostium/                # Ostium LIVE (canònic)
  extended/              # Extended (x10xchange) evaluation (🟡 in progress)
  out/                   # Artifacts

  _archive/2026-02-legacy-purge/  # lighter, gtrade, sepolia, node-gtrade (T5.32)
```

## 🚀 Com Executar

```bash
# Ostium LIVE (canònic)
./scripts/up_ostium_live.sh

# Scripts lab ostium
./test.sh lab/ostium/scripts/close_open_position.py --symbol EURUSD --dry-run
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

## Ostium LIVE (canònic)

- **Venue**: Ostium (testnet → mainnet)
- **Happy path**: `./scripts/up_ostium_live.sh`
- **Docs**: [lab/ostium/README.md](ostium/README.md), [docs/ESTAT.md](../docs/ESTAT.md)

---

**Legacy (T5.32 arxivat):** Lighter, gTrade → `_archive/lab/2026-02-legacy-purge/`

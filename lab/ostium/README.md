# Ostium Lab

Lab per validar integració d'Ostium amb BrokerageService.

## Quick Start

```bash
# 1. Setup
cp .env.example .env
# Editar .env amb PRIVATE_KEY

# 2. Build & run
docker build -t ostium_lab .
docker run -it --name ostium_lab -v $(pwd):/app ostium_lab bash

# 3. Test (dins container)
python3 test_full_cycle_no_subgraph.py
```

## Scripts

| Script | Descripció | Status |
|--------|------------|--------|
| `test_subgraph_quick.py` | Health check subgraph | ✅ |
| `test_full_cycle.py` | Cicle amb subgraph | ⚠️ Testnet broken |
| `test_full_cycle_no_subgraph.py` | Cicle sense subgraph | ✅ **Recomanat** |

## Resultats

**Veure**: [RESULTS.md](RESULTS.md)

- ✅ Testnet validat (+$0.29 profit)
- ✅ Fees: ~$0.16 (62x més barat que gTrade)
- ✅ Workaround disponible per subgraph trencat
- ⚠️ Mainnet pendent de validar

## Next Steps

1. Integrar approach a `main` (net)
2. Validar mainnet abans de producció
3. Implementar a BrokerageService

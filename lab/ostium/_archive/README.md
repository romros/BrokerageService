# Arxius legacy (Ostium LAB)

Scripts arxivats per dependència de subgraph testnet o per ser substituïts per alternatives més robustes.

- **scripts/test_full_cycle.py** — Full cycle Open → Subgraph → Close. Depèn del subgraph testnet (sovint lent o desalineat). Test canònic actual: `scripts/test_full_cycle_multicall.py` (multicall + tradingStorage, sense subgraph).

# Archive venues legacy (T5.35)

| Original | Arxivat | Replacement |
|----------|---------|-------------|
| `infrastructure/venues/lighter/` | `_archive/infrastructure/venues/2026-02-legacy-purge/lighter/` | Paper: `infrastructure/paper_market_data/` |
| `infrastructure/venues/gtrade/` | `_archive/infrastructure/venues/2026-02-legacy-purge/gtrade/` | Ostium: `infrastructure/venues/ostium/` |
| `infrastructure/builders/lighter_di.py` | `_archive/infrastructure/builders/lighter_di.py` | `infrastructure/paper_market_data/builder.py` |
| `application/services/backend_trade_verifier.py` | `_archive/application/services/backend_trade_verifier.py` | gTrade-specific, només per archived tests |

**Paper market data:** `get_symbols_from_env`, `build_paper_market_data_provider` → `infrastructure/paper_market_data/`

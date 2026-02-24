# Archive — BrokerageService

**T5.32 (2026-02):** Purga legacy Ostium-first. Tot Lighter/gTrade fora del tree principal.

## Llista de moviments (git mv)

### Lab
| Original | Destí |
|----------|-------|
| `lab/lighter/*` | `lab/2026-02-legacy-purge/lighter/` |
| `lab/gtrade/*` | `lab/2026-02-legacy-purge/gtrade/` |
| `lab/sepolia/*` | `lab/2026-02-legacy-purge/sepolia/` |
| `lab/node-gtrade/*` | `lab/2026-02-legacy-purge/node-gtrade/` |

### Testing
| Original | Destí |
|----------|-------|
| `testing/unit/test_*lighter*`, `test_*gtrade*`, `test_smoke_*`, `test_sltp_*`, etc. | `testing/2026-02-legacy-purge/unit/` |
| `testing/integration/test_lighter_*`, `test_gtrade_*`, `test_gap_repair_*`, etc. | `testing/2026-02-legacy-purge/integration/` |
| `testing/api/test_ws_smoke.py` | `testing/2026-02-legacy-purge/api/` |
| `testing/apps/trading_service/test_soak_e2e.py` | `testing/2026-02-legacy-purge/apps/` |
| `testing/e2e/*` | `testing/2026-02-legacy-purge/e2e/` |
| `testing/verify_abi_selectors.py` | `testing/2026-02-legacy-purge/` |

### Infrastructure venues (T5.35)
| Original | Destí |
|----------|-------|
| `infrastructure/venues/lighter/` | `infrastructure/venues/2026-02-legacy-purge/lighter/` |
| `infrastructure/venues/gtrade/` | `infrastructure/venues/2026-02-legacy-purge/gtrade/` |
| `infrastructure/builders/lighter_di.py` | `infrastructure/builders/lighter_di.py` |
| `application/services/backend_trade_verifier.py` | `application/services/backend_trade_verifier.py` |

**Replacement:** Paper market data → `infrastructure/paper_market_data/` (get_symbols_from_env, build_paper_market_data_provider).

### Altres
| Directori | Contingut |
|-----------|------------|
| `python/2026-02-cleanup/` | Scripts gTrade (T5.30) |
| `compose/2026-02/` | Compose legacy |
| `scripts/2026-02-ostium-legacy/` | Ostium smokes antics (LOT SANEJAMENT) |

## Canonical Ostium LIVE

- **Run:** `./scripts/up_ostium_live.sh`
- **Smoke:** `./scripts/run_ostium_live_smoke.sh --recreate --clean`

Source of truth: [docs/ESTAT.md](../docs/ESTAT.md) § Ostium LIVE.

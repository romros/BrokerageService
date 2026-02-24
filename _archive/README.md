# Archive — BrokerageService

**T5.32 (2026-02):** Purga legacy Ostium-first. Tot Lighter/gTrade fora del tree principal.

## Estructura

| Directori | Contingut |
|-----------|------------|
| `lab/2026-02-legacy-purge/` | lighter, gtrade, sepolia, node-gtrade (originals lab/lighter, lab/gtrade, etc.) |
| `testing/2026-02-legacy-purge/` | Tests Lighter/gTrade (unit, integration, api, apps, e2e) |
| `python/2026-02-cleanup/` | Scripts gTrade (T5.30) |
| `compose/2026-02/` | Compose legacy |
| `scripts/2026-02-ostium-legacy/` | Ostium smokes antics (LOT SANEJAMENT) |

## Canonical Ostium LIVE

- **Run:** `./scripts/up_ostium_live.sh`
- **Smoke:** `./scripts/run_ostium_live_smoke.sh --recreate --clean`

Source of truth: [docs/ESTAT.md](../docs/ESTAT.md) § Ostium LIVE.

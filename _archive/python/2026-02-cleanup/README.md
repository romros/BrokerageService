# Archive 2026-02-cleanup — Legacy scripts (gTrade/Lighter)

**Data:** 2026-02-24  
**Tasca:** T5.30 — Repo cleanup (safe mirror, no deletions)

## Mapping

| Original | Archive | Reason | Replacement |
|----------|---------|--------|-------------|
| `scripts/testnet_e2e_smoke.py` | `_archive/python/2026-02-cleanup/scripts/testnet_e2e_smoke.py` | gTrade E2E Arbitrum Sepolia; no Ostium LIVE | `testing/e2e/test_testnet_smoke.py` (pytest) o manual |
| `scripts/testnet_trade_anytime.py` | `_archive/python/2026-02-cleanup/scripts/testnet_trade_anytime.py` | gTrade manual E2E; no Ostium | — |
| `scripts/test_market_status_sepolia.py` | `_archive/python/2026-02-cleanup/scripts/test_market_status_sepolia.py` | gTrade market status probe; no Ostium | — |
| `scripts/approve_usdc.py` | `_archive/python/2026-02-cleanup/scripts/approve_usdc.py` | gTrade USDC allowance; lab/gtrade | `_archive/.../scripts/approve_usdc.py` |
| `scripts/soak_freqtrade_paper_real.sh` | `_archive/python/2026-02-cleanup/scripts/soak_freqtrade_paper_real.sh` | Lighter paper soak; no Ostium | `./scripts/run_ostium_live_smoke.sh` (Ostium) |
| `scripts/run_freqtrade_live_testnet.sh` | `_archive/python/2026-02-cleanup/scripts/run_freqtrade_live_testnet.sh` | Lighter live testnet | — |
| `scripts/run_freqtrade_paper.sh` | `_archive/python/2026-02-cleanup/scripts/run_freqtrade_paper.sh` | Lighter paper runner | `application.tools.freqtrade_runner` (via tests) |

## Canonical Ostium LIVE

- **Run:** `./scripts/up_ostium_live.sh`
- **Smoke only:** `./scripts/run_ostium_live_smoke.sh --recreate --clean`

Source of truth: [docs/ESTAT.md](../../docs/ESTAT.md) § Ostium LIVE.

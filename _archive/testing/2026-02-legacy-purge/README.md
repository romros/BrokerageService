# Archive testing legacy (T5.32)

Tests Lighter i gTrade arxivats. Repo Ostium-first.

| Categoria | Tests |
|-----------|-------|
| Unit | test_lighter_*, test_gtrade_*, test_smoke_runner, test_sltp_*, test_ws_*, etc. |
| Integration | test_lighter_*, test_gtrade_*, test_freqtrade_runner_*, test_gap_repair_flow, etc. |
| API | test_ws_smoke |
| Apps | test_soak_e2e |
| E2E | test_testnet_smoke (gTrade) |

Per executar des de l'arrel: `./test.sh _archive/testing/2026-02-legacy-purge/unit/test_xxx.py` (requereix infrastructure/venues/lighter i gtrade al tree principal).

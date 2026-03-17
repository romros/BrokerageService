# Scripts — BrokerageService

**Propòsit:** Capa operativa. Scripts per executar, no un calaix de sastre.

---

## Operatius (usar normalment)

| Script | Funció |
|--------|--------|
| `run_ostium_rollover.sh` | Rollover CSV→Parquet (1 símbol) |
| `run_ostium_rollover_all.sh` | Rollover tots (cron diari) |
| `run_smoke.sh` | Smoke per profile |
| `run_tests.sh` | Suites tests |
| `live_on.sh` / `live_off.sh` | Kill-switch LIVE↔PAPER |
| `up_ostium_live.sh` | Up stack + smoke LIVE |
| `run_ostium_live_smoke.sh` | Smoke LIVE (trading_service) |
| `run_compat.sh` | Compat Ostium vs Dukascopy |
| `sync_symbol.sh` | Sync Dukascopy per símbol |
| `sync_xauusd_full.sh` | Sync XAUUSD llarg |
| `run_lab.sh` | Monitors LAB |
| `run_lab_backtest.sh` | LAB backtest |
| `run_full_pipeline.sh` | Backfill pipeline |
| `run_historical_cron.sh` | Cron daily/retry/gap-repair |
| `run_backtest_offline.sh` | Backtest offline |
| `run_backtest_parquet.sh` | Backtest Parquet |
| `smoke_gateway.sh` | Verifica gateway |
| `run_soak.sh` | Soak genèric |
| `run_soak_e2e.sh` | Soak e2e |
| `run_soak_ostium_validation.sh` | Soak Ostium |
| `check_soak_status.sh` | Estat soak |
| `fix_datafiles_permissions.sh` | Permisos datafiles/logs |
| `parity_check.sh` | Parity M1 + auto-retry |
| `run_t825_evidence_pack.sh` | Evidence pack post-BI5 |
| `run_t849_gold_smoke.sh` | Gold parity suite |
| `run_t850_lab_cleanup.sh` | Lab cleanup |
| `run_t915_sq_bs_m1_parity_gate.sh` | Gate SQ↔BS M1 |
| `run_t9152_export_sq_complete.sh` | Export SQ |
| `run_t916_gap_audit.sh` | Gap audit |
| `run_t918_certify_sq_range.sh` | Certificar rang SQ |
| `run_t919_archive_legacy_parquet.sh` | Arxivar legacy Parquet |

---

## One-shot (puntuals)

Veure [scripts/oneshot/](oneshot/) — scripts LAB, migracions, validacions puntuals. No formen part del flux operatiu.

---

## Arxiu

Veure [scripts/_archive/](_archive/) — scripts obsolets (RAW deprecated, etc.).

---

## Subprojectes

- [scripts/network_smokes/](network_smokes/) — smokes de xarxa (gateway, Ostium)

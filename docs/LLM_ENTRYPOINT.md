# LLM Entrypoint — BrokerageService

**Propòsit:** Punt d'entrada oficial per agents (Cursor, ChatGPT, etc.). Llegeix primer. Defineix el model mental i les regles operatives.

---

## 1. Overview (10 línies)

**BrokerageService** és un API REST multi-venue per execució i marketdata. **Venue canònic:** Ostium (testnet→mainnet). Arquitectura **split** en 3 serveis: `realtime_datalayer` (Ostium ingest 24/7), `historical_datalayer` (Dukascopy backfill, Parquet), `trading_service` (ordres, balance, positions). Pipeline: Ostium → CSV (veritat immediata); Dukascopy → Parquet (històric); merge `/data` amb preferència CSV en overlap. **Filosofia:** No inventar dades; fonts explícites (`source=dukascopy|ostium`); playbooks obligatoris per canvis d'assets.

---

## 2. Ordre de lectura (OBLIGATORI)

1. [README.md](../README.md) — Quick start, arquitectura split, endpoints
2. [docs/ESTAT.md](ESTAT.md) — Estat operatiu, comandes canòniques, evidència
3. [AGENTS_ARQUITECTURA.md](../AGENTS_ARQUITECTURA.md) — Invariants, Data Layer, contractes

**Baseline:** Aquest ordre defineix el model mental mínim. Sense llegir-los, no implementis.

---

## 3. Problema → què fer (índex ràpid)

| Problema | Acció / Doc |
|----------|-------------|
| Afegir asset Ostium (MSFT, NVDA, NDXUSD...) | [PLAYBOOK_ADD_ASSET_OSTIUM.md](playbooks/PLAYBOOK_ADD_ASSET_OSTIUM.md) — SYMBOLS, OSTIUM_SYMBOLS, mapping, MARKET_HOURS_UNKNOWN |
| Afegir asset Dukascopy (històric FX) | [PLAYBOOK_ADD_ASSET_DUKASCOPY.md](playbooks/PLAYBOOK_ADD_ASSET_DUKASCOPY.md) |
| Delta Parquet vs SQ, gaps, integritat | [DATA_PARITY_GATES.md](DATA_PARITY_GATES.md) — gates A/B/C/D; `run_t825_evidence_pack.sh`, `run_t915_sq_bs_m1_parity_gate.sh` |
| Rollover Ostium CSV→Parquet | `./scripts/run_ostium_rollover.sh` (1 símbol) o `run_ostium_rollover_all.sh` (cron) |
| Incident, aturar servei | [SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md) — **MAI** aturar realtime_datalayer |
| Tests, smoke, validació | [scripts/README.md](../scripts/README.md) — `run_tests.sh`, `run_smoke.sh`, `run_soak_ostium_validation.sh` |
| Navegació completa | [docs/INDEX.md](INDEX.md) — Hub centralitzat |

---

## 4. Segons la tasca

| Tipus | Docs |
|-------|------|
| **Data layer** | [docs/DATA_PARITY_GATES.md](DATA_PARITY_GATES.md), [docs/DUKASCOPY_RAW_STORE.md](DUKASCOPY_RAW_STORE.md), [docs/INDICATOR_PARITY_SPEC.md](INDICATOR_PARITY_SPEC.md) |
| **Afegir assets** | [docs/playbooks/PLAYBOOK_ADD_ASSET_OSTIUM.md](playbooks/PLAYBOOK_ADD_ASSET_OSTIUM.md), [docs/playbooks/PLAYBOOK_ADD_ASSET_DUKASCOPY.md](playbooks/PLAYBOOK_ADD_ASSET_DUKASCOPY.md), [docs/playbooks/PLAYBOOK_ADD_ASSET_FULL.md](playbooks/PLAYBOOK_ADD_ASSET_FULL.md) |
| **Trading / execució** | [docs/runbook_trades_api.md](runbook_trades_api.md), [docs/SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md) |
| **Scripts operatius** | [scripts/README.md](../scripts/README.md) — operatius, oneshot, arxiu |
| **Validació / recerca** | [lab/gold/](../lab/gold/), [lab/runner/](../lab/runner/), [lab/ostium/](../lab/ostium/) |
| **Incidents** | [docs/SAFETY_RUNBOOK.md](SAFETY_RUNBOOK.md) — MAI aturar realtime_datalayer |
| **Navegació** | [docs/INDEX.md](INDEX.md) — Hub centralitzat |

---

## 5. Guardrails (CRÍTIC)

### ❌ Prohibit

- **No inventar dades** — Mai generar candles, preus o timestamps ficticis
- **No omplir gaps silenciosament** — Gaps han de ser explícits (headers X-Data-Missing-Minutes, etc.)
- **No barrejar fonts sense `source=...`** — Sempre indicar font (dukascopy, ostium)
- **No saltar-se playbooks** — Afegir assets → seguir PLAYBOOK_ADD_ASSET_*
- **No assumir que Ostium té històric** — Ostium és live-only; històric = Dukascopy
- **No aturar realtime_datalayer** — És el gold; perd ingest irreparablement

### ✅ Obligatori

- **Respectar separació realtime vs historical** — realtime_datalayer ≠ historical_datalayer
- **CSV = veritat immediata** — En overlap, CSV guanya sobre Parquet
- **Parquet = consolidació** — Rollover diari CSV→Parquet; merge idempotent
- **Llegir entrypoint + baseline** abans d'implementar
- **Definition of Done clar** — No codificar sense DoD verificable

---

## 6. Conceptes clau

| Concepte | Definició |
|----------|-----------|
| **Ostium** | Live-only. Ingest 24/7 via REST; candles a CSV; rollover diari a Parquet |
| **Dukascopy** | Històric profund (2003→avui). RAW bi5 → Parquet → DuckDB |
| **CSV vs Parquet** | CSV = veritat immediata (realtime); Parquet = consolidació durable |
| **`/data` merge** | `source=ostium` llegeix Parquet + CSV; en overlap, CSV prioritat |
| **cutover_ts** | Primer `ts` al primary; stitching gated per compat |
| **TZ canònica** | `America/New_York` (config i display); `ts` sempre UTC epoch |
| **Assets Ostium** | EURUSD, GBPUSD, XAUUSD, MSFT, NVDA, NDXUSD (allowlist); XAU quarantine |

---

## 7. Com treballar correctament

1. Llegir aquest entrypoint
2. Llegir baseline (README → ESTAT → AGENTS)
3. Consultar **§3 Problema → què fer** si cal orientació ràpida
4. Identificar playbook si la tasca toca assets
5. No implementar sense DoD clar
6. Validar amb integritat si toca Data Layer (gaps, duplicates, ts_step)
7. Actualitzar [docs/ESTAT.md](ESTAT.md) si cal evidència nova

---

## 8. Documentació completa (raw URLs)

**Base:** `https://raw.githubusercontent.com/romros/BrokerageService/main/`

Per agents externs (ChatGPT, etc.): afegir el path al base per obtenir el contingut.

### Docs principals
```
README.md
AGENTS_ARQUITECTURA.md
docs/LLM_ENTRYPOINT.md
docs/ESTAT.md
docs/INDEX.md
docs/plantilla_tasca.md
docs/SAFETY_RUNBOOK.md
docs/DATA_PARITY_GATES.md
docs/DUKASCOPY_RAW_STORE.md
docs/INDICATOR_PARITY_SPEC.md
docs/DIAGNOSI_PROJECTE_2026-02.md
docs/DEUTE_ARQUITECTURA_FISICA.md
docs/runbook_trades_api.md
docs/LAB_OSTIUM_PRICE_MONITORING.md
```

### Playbooks
```
docs/playbooks/README.md
docs/playbooks/PLAYBOOK_ADD_ASSET_FULL.md
docs/playbooks/PLAYBOOK_ADD_ASSET_DUKASCOPY.md
docs/playbooks/PLAYBOOK_ADD_ASSET_OSTIUM.md
```

### Apps (per servei)
```
apps/trading_service/README.md
apps/trading_service/trading_service_estat.md
apps/trading_service/trading_service_arquitectura.md
apps/historical_datalayer/README.md
apps/historical_datalayer/historical_datalayer_estat.md
apps/historical_datalayer/historical_datalayer_arquitectura.md
apps/realtime_datalayer/README.md
apps/realtime_datalayer/realtime_datalayer_estat.md
apps/realtime_datalayer/realtime_datalayer_arquitectura.md
```

### Lab
```
lab/README.md
lab/NOTES.md
lab/OSTIUM_COMPLETE.md
lab/datalayer/README.md
lab/bi5_vs_sqcli/README.md
lab/ostium/README.md
lab/ostium/COMANDES_DEMA.md
lab/ostium/RESUM_VISUAL.md
lab/ostium/RESULTS.md
lab/extended/README.md
lab/extended/EXTENDED.md
lab/gold/README.md
lab/gold/state_machine.md
lab/gold/cases/rsi35_exit60_m1_oracle/spec.md
lab/gold/execution/spec_exit_after_bars.md
lab/gold/indicators/spec_rsi_sq_exact.md
lab/runner/README.md
lab/runner/out_compare/README.md
lab/runner/out_compare/compare_notes.md
lab/runner/out_compare/mt4_oracle_tools/README.md
```

### Deploy, scripts, testing
```
deploy/compose/overrides/README.md
deploy/compose/lab/README.md
scripts/README.md
scripts/oneshot/README.md
scripts/_archive/2026-03-raw-deprecated/README.md
scripts/network_smokes/ESTAT.md
scripts/network_smokes/PLAYBOOK.md
testing/README.md
testing/DETERMINISM_PROOF.md
packages/shared/README.md
```

### Artifacts
```
lab/datalayer/artifacts/BS.T9.08/README.md
lab/datalayer/artifacts/BS.T9.08/final_report.md
lab/datalayer/artifacts/BS.T9.10/final_report.md
```

---

**Índex complet:** [docs/INDEX.md](INDEX.md)

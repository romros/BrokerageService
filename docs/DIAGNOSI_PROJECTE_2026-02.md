# Diagnòsi del projecte — BrokerageService (2026-02-24)

**Objectiu:** Revisió general de l'arquitectura, objectius, operativa i grau de polit.

**Actualitzat:** P0 (docs) executat — ESTAT i AGENTS coherents amb l'estat real.

---

## 1) Objectiu del projecte (resum)

**BrokerageService** és un servei multi-venue amb:
- **Data Layer canònic** (candles 1m fiables, Ostium + Dukascopy)
- **Execució desacoblada** (paper, Ostium LIVE)
- **Arquitectura split** (realtime + historical + trading)

**Venue canònic:** Ostium (Lighter/gTrade arxivats T5.32).

---

## 2) Grau de polit de l'arquitectura

### 2.1 Forts ✅

| Àrea | Grau | Notes |
|------|------|-------|
| **Ports + Wiring (T5.41)** | 8/10 | `application/ports/` (ExecutionPort, MarketDataPort, OperationStorePort); `wiring.py` centralitzat; serveis amb DI explícit |
| **Boundaries de serveis** | 8/10 | realtime/historical/trading ben delimitats; role wiring; nginx single-port |
| **Data Layer** | 9/10 | Parquet, DuckDB, stitching, coverage, mixed; headers X-Data-*; quality gate fail-closed |
| **Broker API** | 8/10 | REST estable; POST body; error codes; fast-ack 202 |
| **Testing** | 8/10 | 74 tests 0-network; run_all; suites per servei; sense pytest |
| **Docs** | 8/10 | ESTAT, AGENTS, INDEX; runbooks; subprojectes documentats; **coherents** (P0 executat) |
| **Normes de codi** | 8/10 | Imports a capçalera; zero hardcode; constants centralitzades |

### 2.2 Punts febles (restants)

| Àrea | Grau | Notes |
|------|------|-------|
| **Separació física** | 5/10 | 3 serveis comparteixen mateixa imatge/codi. **No és un problema ara:** ja hi ha split runtime + boundaries. Prioritat baixa fins que calgui releases independents. |
| **INDEX.md ports** | 7/10 | "realtime_datalayer (port 8081)" — correcte des de POV usuari (gateway); 8082 és intern. |

**Risc real per "producte":** No és arquitectura; és **operativa + observabilitat** (alerts, runbook, rotació).

---

## 3) Operativa / funcionalitat que falta o és incompleta

### 3.1 Backlog explícit (ESTAT § Backlog)

| Item | Estat | Necessari per objectiu? |
|------|-------|-------------------------|
| Prefetch recent (N hores/dies) a prod | ❌ | Sí per prod Data Layer |
| Scheduler (cron/loop) + idempotència | 🟡 Parcial (run_historical_cron) | Parcialment cobert |
| Alert mínim: stale/missing/duplicates | ❌ | Sí per operar amb confiança |
| Rotació artifacts/logs | ❌ | Sí per prod |
| Soak 6–12h amb prefetch actiu | 🟡 Soak existeix | Validació |
| Cutover policy primary/fallback per símbol | 🟡 Registry existeix | Cobert |
| Doc "operar data layer" (runbook) | 🟡 SAFETY_RUNBOOK parcial | Ampliable |

### 3.2 Limitacions que afecten Freqtrade

| Item | Impacte | Política recomanada |
|------|---------|---------------------|
| **SL/TP** via `update_sl`/`update_tp` | no-op al venue (SDK testnet no exposa) | Freqtrade: close client-side o SL/TP virtual al broker |
| **trade_history / pairs** | buits (subgraph no funciona) | Reporting limitat; per Hisenda cal **ledger propi** (operations existeix; falta ledger de trades) |
| **percent** en `close_position` | ignorat MVP (sempre 100%) | Documentar; acceptable per MVP |

### 3.3 Què no cal (per objectiu actual)

| Item | Observació |
|------|------------|
| Migració `foundation/` → `packages/shared/` | Futur Phase 2; no bloqueja |
| Separació física (paquets per servei) | Prioritat baixa; només quan calgui releases independents |
| Subgraph Ostium | No disponible; get_trade_history/get_pairs retornen [] |

---

## 4) Recomanacions prioritàries

### P0 — Docs ✅ **Fet (2026-02-24)**

- [x] Corregir ESTAT.md: "Exec Ostium pendent Phase E" → "Ostium exec Phase G/H implementat"
- [x] Corregir taula Backtest: "Pipeline pendent" → "API + runner implementats"
- [x] Actualitzar AGENTS §14: Lighter/gTrade arxivat; Ostium venue canònic.

### P1 — Abans de "real money" (producció)

4. **Alert mínim + observabilitat:**
   - stale/missing/duplicates per símbol
   - latència open/close + % 202 pending
   - error-rate per codi
5. **Prefetch/cron idempotent** (si aplica al Data Layer prod)
6. **Rotació logs/artifacts**
7. **Runbook curt:** start / continue / rollback

### P2 — Arquitectura (llarg termini)

8. **Separació física:** Només quan calgui releases independents.

---

## 5) Resum executiu

| Criteri | Valoració |
|---------|-----------|
| **Arquitectura** | Sòlida; ports + wiring; boundaries clars; separació física no prioritària |
| **Objectiu** | Complert al 85%: Data Layer + Ostium exec + split operatius |
| **Risc producte** | **Operativa + observabilitat** (no arquitectura) |
| **Operativa** | Falta: alerts, prefetch prod, runbook complet; scheduler parcial |
| **Freqtrade** | SL/TP virtual o client-side; ledger trades per Hisenda; percent close documentat |
| **Docs** | **Coherents** (P0 executat) |
| **Grau de polit** | **8/10** — Producció per Ostium LIVE; refinament per observabilitat i ops |

---

## 6) Accions executades (2026-02-24)

1. **T5.41 Ports + Wiring:** `application/ports/` (ExecutionPort, MarketDataPort, OperationStorePort); `wiring.py` centralitzat; serveis amb DI explícit; broker_routes delega a wiring.
2. **Arxiu root:** `run_smoke.sh`, `refactor_imports.py`, `SETUP_TESTNET.md`, `plantilla_tasca.md` → `_archive/root/2026-02-legacy-purge/`.
3. **Fix smoke backtests:** `GET /api/v1/backtests/runs` afegit (retorna `{"runs": []}` o llista); smoke gateway passa amb contenidor reconstruït.
4. **ESTAT.md:** Corregides 3 frases "Exec Ostium pendent Phase E" → "Ostium exec Phase G/H implementat"; taula Backtest actualitzada.
5. **AGENTS_ARQUITECTURA.md:** §14 i TL;DR actualitzats (Lighter/gTrade arxivat; Ostium execution-ready); §3.1 Data Layer fonts.
6. **Changelog AGENTS:** Entrada 2026-02-24 docs coherents.

---

## 7) Annex: Proves Ostium vs Dukascopy (compat backtest)

**Objectiu:** Validar que les candles Ostium (REST polling) són compatibles amb Dukascopy per backtesting (Dukascopy = històric, Ostium = realtime).

**Resultats (2026-02-18/20, dades reals):**

| Símbol | Candles | Corr | Dir agree 1m | Dir agree filtrat | Verdict |
|--------|---------|------|--------------|-------------------|---------|
| **EURUSD** | ~650 | 0.968 | 89.9% | **96.7%** (eligible=427) | PASS_BACKTEST |
| **XAUUSD** | ~650 | 0.977 | 91.1% | **95.9%** (eligible=468) | PASS_BACKTEST |

**Mètriques:** `dir_agree_filtered` exclou minuts "flat" (moviment < 0.5pip FX / $0.5 XAU) per evitar soroll. Llindar PASS_BACKTEST: corr ≥ 0.90 i dir_agree_filtered ≥ 95%.

**Fitxers clau (GitHub raw, branch main):**

| Fitxer | URL |
|--------|-----|
| Compat script (v2) | `https://raw.githubusercontent.com/romros/BrokerageService/main/lab/ostium/scripts/ostium_vs_dukascopy_compat_v2.py` |
| Compat engine | `https://raw.githubusercontent.com/romros/BrokerageService/main/application/services/compat_report_service.py` |
| Ostium compat tool | `https://raw.githubusercontent.com/romros/BrokerageService/main/application/tools/ostium_compat_report.py` |
| Unit tests | `https://raw.githubusercontent.com/romros/BrokerageService/main/testing/unit/test_ostium_compat_report_service.py` |
| Timeline compat | `https://raw.githubusercontent.com/romros/BrokerageService/main/lab/out/ostium_prices/TIMELINE_COMPAT.md` |
| Lab README | `https://raw.githubusercontent.com/romros/BrokerageService/main/lab/ostium/README.md` |
| Backtest provider (registry) | `https://raw.githubusercontent.com/romros/BrokerageService/main/application/data/backtest_market_data.py` |
| Doc price monitoring | `https://raw.githubusercontent.com/romros/BrokerageService/main/docs/LAB_OSTIUM_PRICE_MONITORING.md` |

---

## 8) Tasques pendents (apuntades, no executades)

### T6.1 — CompatReport canònic (reproducible + documentat + thresholds)

**Objectiu:** Convertir la prova compat que "un dia va funcionar" en un comandament canònic amb:
- thresholds explícits (corr ≥ X, dir_agree_filtered ≥ Y, max_gap ≤ Z…)
- output artifact (JSON) a `artifacts/compat/…`
- 1 línia a docs/ESTAT.md de "com executar-ho"

No cal canviar l'algoritme; només:
- consolidar `dir_agree_filtered` (excloure minuts flat) com a mètrica oficial
- normalitzar paths (perquè `lab/out/...` és molt "lab")

**DoD T6.1:**
- `python3 -m application.tools.ostium_compat_report --symbol EURUSD --minutes 1440` genera JSON report + verdict PASS_BACKTEST|PARTIAL|INCOMPATIBLE
- el doc diu: "si PASS_BACKTEST → acceptable portar estratègia a paper-live"

**Thresholds formals:**
- PASS_BACKTEST si: corr ≥ 0.90, dir_agree_filtered ≥ 95%, missing/dup dins llindars
- PARTIAL si passa corr però dir_agree_filtered baixa
- INCOMPATIBLE si corr baixa o best_lag ≠ 0 massa sovint

*(Base ja existeix: SIS-2 correlació + part SIS-1 missing/dup + part SIS-3 direction agree dins `build_compat_report` i probe v2.)*

### T6.2 — Quarantine harness Freqtrade (EURUSD+XAUUSD 1h)

Després de T6.1.

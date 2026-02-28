# DATA PARITY GATES — BrokerageService Historical Data

**Data:** 2026-02-28
**Principi:** No es passa al gate següent si l'anterior no és PASS o PARTIAL-acceptat.

---

## Resum de gates

| Gate | Descripció | Estat | Data |
|------|-----------|-------|------|
| **Gate A** | Dukascopy M1 parity vs SQ (EURUSD) | **PARTIAL** | 2026-02-28 |
| **Gate B** | Aggregation parity M1→D1/H4/H1 | PENDENT | — |
| **Gate C** | Dukascopy↔Ostium candle compatibility | PASS (T8.9) | 2026-02-28 |
| **Gate D** | Runner backtest parity + paper/live | PASS (T8.11) | 2026-02-28 |

---

## Gate A: Dukascopy M1 parity vs SQ (EURUSD)

**Estat: PARTIAL (acceptat)**

### SQ baseline
- Dataset: `EURUSD_M1_dukas_M1_UTCMinus05`
- Total records: **8,499,508**
- Coverage: 2003-05-05 → 2026-02-28

### Nostra cobertura (2026-02-28)
- Total rows: **5,756,530**
- Coverage: **2007-01 → 2026-02** (175 mesos)
- Delta vs SQ: **-32.3%** (2,742,978 rows menys)

### Diagnòstic Fase A (2026-02-28)

Sync test `2003-05 → 2006-12` amb `QUALITY_MODE=ingest`:
- Resultat: `done=1, empty=43, failed=0`
- La "1 done" (2006-12) contenia 1 sola candle amb timestamp **2007-01-01 00:00 UTC** (artefacte off-by-one de rang mensual). Eliminat.
- Earliest candle real: `ts=1167609600` = **2007-01-01 00:00:00 UTC**

**Conclusió:** La Dukascopy M1 pública per EURUSD comença el **2007-01-01**. No hi ha dades M1 anteriors via API pública. SQ disposa de 2003-2006 probablement via:
- Agregació de ticks (diferent qualitat)
- Font alternativa (no pública)

### Per què PARTIAL és acceptable

1. **No-delete policy activa** (T8.16): mai s'eliminen dades per baix threshold
2. **QUALITY_MODE=ingest**: baixem tot el que Dukascopy retorna
3. La diferència (32%) reflecteix una limitació de la font, no un error de baixada
4. Per a backtesting des de 2007 (rang disponible), la paritat és verificable

### Criteris per a PASS complet

- `coverage_from <= 2003-05-05` i `total_rows >= 8,000,000`
- Requereix: font alternativa de ticks 2003-2006 + agregació M1

### Mesos missing (2007-2011, confirmats buits Dukascopy)

Els 55 mesos `2007-06 → 2011-12` estan confirmats com a buits per l'API Dukascopy. No es reintentar.

**Report complet:** `lab/runner/out_compare/parity_EURUSD_M1_vs_SQ.json`

---

## Gate B: Aggregation parity M1→D1/H4/H1

**Estat: PENDENT**

Verificar que l'agregació M1→D1/H4/H1 produeix els mateixos totals i KPIs que SQ.

**Prerequisit:** Gate A PARTIAL acceptat. ✅

**Criteris:**
- Recounts D1/H4/H1 coincideixen amb M1 agregat (sense gaps)
- OHLCV consistent entre timeframes
- El runner (lab) usa la mateixa agregació que els engines de backtesting

---

## Gate C: Dukascopy↔Ostium candle compatibility

**Estat: PASS (T8.9)**

Completat el 2026-02-28. EURUSD i XAUUSD superen PASS_BACKTEST:
- EURUSD: corr=0.968, dir_agree_filtered=96.7%
- XAUUSD: corr=0.977, dir_agree_filtered=95.9%

---

## Gate D: Runner backtest parity + paper/live

**Estat: PASS (T8.11)**

Entry match-rate vs MT4: 50.0% (18pp de millora amb ATR Wilder + warmup + D1 offset).

---

## Política de qualitat de dades

### QUALITY_MODE

| Mode | Quan usar | Comportament |
|------|-----------|-------------|
| `ingest` (default) | Sempre en producció/sync | Accepta qualsevol rows>0. Mai falla per cobertura baixa. |
| `integrity` | Diagnòstic manual post-sync | Aplica MIN_ROWS/MIN_COMPLETENESS/MAX_FLAT_RATIO. |

### No-delete policy (T8.16)

`sync_manager._process_month()` **mai fa `unlink()`** sobre parquets amb rows>0.
L'única eliminació possible és via `repair_empty_parquets.py --fix` (explícit, manual).

### Thresholds (mode integrity)

| Variable | Default | Descripció |
|----------|---------|-----------|
| `MIN_ROWS_MONTH_1M` | 10,000 | Mínim rows per mes M1 |
| `MAX_FLAT_RATIO_GATE` | 0.05 | Màxim ratio barres O=H=L=C |
| `MIN_COMPLETENESS_1M` | 0.50 | Mínim completeness (rows/expected_minutes) |

### Camps observabilitat (SyncJob)

- `done`: mesos escrits correctament
- `empty`: mesos confirmats buits per Dukascopy (retorna [])
- `suspect`: mesos escrits però amb cobertura baixa (informatiu)
- `failed`: mesos que han fallat després de tots els retries

---

## Historial de canvis

| Data | Tasca | Canvi |
|------|-------|-------|
| 2026-02-28 | T8.16 | QUALITY_MODE ingest/integrity + no-delete + empty/suspect counters |
| 2026-02-28 | T8.17 | Fase A diagnòstic: confirmat EURUSD M1 comença 2007-01 via Dukascopy públic |
| 2026-02-28 | T8.14 | Quality gate mensual al sync |
| 2026-02-28 | T8.13 | Fix parquets buits perpetus |
| 2026-02-28 | T8.12 | Parity checker + report EURUSD M1 |
